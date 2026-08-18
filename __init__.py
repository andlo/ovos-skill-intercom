"""
skill OVOS Intercom
Copyright (C) 2026  Andreas Lorensen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

---

LAN intercom for OVOS - "send a message to the bedroom" delivers a
spoken message to a named peer OVOS device on the same local network,
with an optional spoken reply sent back. See README.md and
DEVELOPMENT.md for the full design reasoning; the single sentence
that matters most: THIS SKILL SPEAKS MESSAGES, IT NEVER EXECUTES
COMMANDS. A received message is only ever passed to self.speak() -
never routed through the intent pipeline. That boundary is the entire
reason this can be a small, self-contained skill instead of a much
bigger, much more dangerous piece of infrastructure - see
DEVELOPMENT.md "Why not just relay to the target's messagebus" and
"Why this isn't a smaller HiveMind".

Household-wide shared secret, not pairwise pairing: every device that
should be able to send/receive intercom messages has the SAME code
spoken to it once (`"set intercom code to ..."`), rather than each
PAIR of devices needing its own separate secret - scales linearly
(N devices = N spoken setup commands) instead of quadratically
(N devices = N*(N-1)/2 pairwise setups). Proportionate to "keep
casual LAN presence out", the same security level as a household
WiFi password, not "defend against a targeted attacker" - seeDEVELOPMENT.md
"Threat model: a WiFi-password-equivalent, not HiveMind-grade".
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from ovos_workshop.skills import OVOSSkill
from ovos_workshop.decorators import intent_handler
from ovos_bus_client.message import Message
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceListener

SERVICE_TYPE = "_ovosintercom._tcp.local."
INCOMING_MESSAGE_BUS_EVENT = "ovos.intercom.message.received"

# Response statuses the receiver's HTTP endpoint can return - see
# DEVELOPMENT.md "Wire protocol" for the full request/response shape.
STATUS_OK = "ok"
STATUS_NO_CODE_SET = "no_code_set"
STATUS_WRONG_CODE = "wrong_code"


def normalize_code(raw):
    """The shared code is just a STRING comparison, not a parsed
    number - "4 7 2 9" and "fire syv to ni" are both valid as long as
    the same words are spoken consistently every time (both when
    configuring a device and when sending from another one). Avoids
    needing any number-parsing at all: lowercase, collapse internal
    whitespace to single spaces, strip. Returns None for empty/blank
    input rather than an empty string, so callers can use a plain
    truthy check for "is a code actually set"."""
    if not raw:
        return None
    normalized = " ".join(raw.strip().lower().split())
    return normalized or None


def normalize_name(raw):
    """Same normalization as normalize_code() - device names are
    matched case-insensitively and whitespace-insensitively too
    ("Soveværelset" and "soveværelset" must be the same target)."""
    return normalize_code(raw)


def get_local_ip():
    """Best-effort local IP detection via a UDP 'connect' that never
    actually sends any data - just asks the OS which local address
    and interface it would use for that destination. Works even with
    no real internet access, as long as a route exists. A small,
    independent reimplementation of the same idea
    ovos-skill-network-scanner uses - not imported from there, since
    that package registers its own 'ovos.plugin.skill' entry point;
    depending on it would silently register network-scanner as an
    available skill on every device that installs this one, an
    unwanted side effect, not a reason to duplicate code lightly. See
    DEVELOPMENT.md "Why not depend on ovos-skill-network-scanner"."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


# ---------------------------------------------------------------
# mDNS - advertise this device (once it has a configured name) so
# other intercom-capable devices can find its current IP/port by
# name, and browse for other devices doing the same. Deliberately
# carries NO secret in the advertised data (mDNS TXT records are
# broadcast in cleartext on the LAN) - the code is only ever sent
# inside the actual HTTP message payload, see DEVELOPMENT.md "Wire
# protocol". A device with a name set but no code yet still
# advertises - see DEVELOPMENT.md "Advertising without a code set"
# for why that's needed to give a specific, helpful error rather than
# a bare 'device not found'.
# ---------------------------------------------------------------

def build_service_info(name, ip, port):
    instance_name = f"{name}.{SERVICE_TYPE}"
    return ServiceInfo(
        SERVICE_TYPE,
        instance_name,
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={},
    )


class _PeerCollectingListener(ServiceListener):
    """Collects every currently-advertised intercom peer's name and
    address as plain data - no OVOSSkill/bus access here, so this
    stays independently testable without a running skill instance."""

    def __init__(self):
        self.found = {}

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info is None:
            return
        addresses = info.parsed_addresses()
        if not addresses:
            return
        peer_name = name[: -(len(SERVICE_TYPE) + 1)] if name.endswith(SERVICE_TYPE) else name
        self.found[normalize_name(peer_name)] = {"ip": addresses[0], "port": info.port}

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)


def discover_peer(target_name, timeout=3):
    """Browses for SERVICE_TYPE for `timeout` seconds and returns
    {"ip": ..., "port": ...} for the peer matching target_name
    (normalized comparison), or None if no match was found in time.
    A fresh, short scan per call rather than a long-running cached
    browser - intercom messages are infrequent enough that a few
    seconds' discovery latency per send is an acceptable trade for
    not keeping a background zeroconf browser running indefinitely."""
    target = normalize_name(target_name)
    if target is None:
        return None
    zc = Zeroconf()
    listener = _PeerCollectingListener()
    try:
        ServiceBrowser(zc, SERVICE_TYPE, listener)
        import time
        time.sleep(timeout)
        return listener.found.get(target)
    except Exception:
        return None
    finally:
        zc.close()


# ---------------------------------------------------------------
# Wire protocol - a single HTTP POST endpoint, deliberately as narrow
# as possible: it accepts exactly {sender_name, code, message,
# reply_port} and can only ever result in a call to self.speak() on
# the receiving end, never anything else. Requests are handled in a
# background thread OUTSIDE OVOS's own event/bus thread - the handler
# below does ONLY the minimum safe work itself (parse, validate the
# code, respond) and hands off everything interactive (speaking,
# asking for a reply) to the skill's normal bus-driven event handling
# via self.bus.emit(), rather than calling self.speak_dialog()/
# self.get_response() directly from this thread. See DEVELOPMENT.md
# "Bridging a background thread into OVOS's bus" for why.
# ---------------------------------------------------------------

def send_message(ip, port, sender_name, code, message, reply_port, timeout=5):
    """POSTs a message to a peer's intercom endpoint. Returns the
    peer's status string (STATUS_OK/STATUS_NO_CODE_SET/
    STATUS_WRONG_CODE), or None if the peer couldn't be reached at
    all (timeout, connection refused, malformed response) - None is
    a DIFFERENT case from any STATUS_* value and callers must
    distinguish "unreachable" from "reachable but rejected"."""
    import http.client
    body = json.dumps({
        "sender_name": sender_name,
        "code": code,
        "message": message,
        "reply_port": reply_port,
    }).encode("utf-8")
    conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.request("POST", "/message", body=body,
                      headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("status")
    except Exception:
        return None
    finally:
        conn.close()


def _make_handler(skill):
    """Returns a BaseHTTPRequestHandler subclass bound to this skill
    instance - a closure rather than a module-level class, since the
    handler needs access to the skill's settings and bus, and
    http.server.HTTPServer expects a handler CLASS (instantiated per
    request), not an object, so state must be captured via closure
    rather than __init__ arguments."""

    class IntercomRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # don't spam OVOS's logs with routine HTTP access lines

        def do_POST(self):
            if self.path != "/message":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self.send_response(400)
                self.end_headers()
                return

            own_code = normalize_code(skill.settings.get("intercom_code"))
            sender_code = normalize_code(payload.get("code"))

            if own_code is None:
                status = STATUS_NO_CODE_SET
            elif sender_code != own_code:
                status = STATUS_WRONG_CODE
            else:
                status = STATUS_OK

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": status}).encode("utf-8"))

            if status == STATUS_OK:
                # Hand off to the skill's own bus thread - see the
                # module docstring above this section for why this
                # thread must not call self.speak_dialog()/
                # self.get_response() itself.
                skill.bus.emit(Message(INCOMING_MESSAGE_BUS_EVENT, {
                    "sender_name": payload.get("sender_name") or "",
                    "message": payload.get("message") or "",
                    "sender_ip": self.client_address[0],
                    "reply_port": payload.get("reply_port"),
                }))

    return IntercomRequestHandler


class IntercomServer:
    """Owns the background HTTPServer thread's lifecycle - started in
    Intercom.initialize(), stopped in Intercom.shutdown(). Binds to
    port 0 (OS picks a free port) rather than a fixed port, since a
    fixed port could collide with something else already running on
    a given device, and the chosen port is advertised via mDNS anyway
    so nothing needs to know it in advance."""

    def __init__(self, skill):
        self.skill = skill
        self.httpd = HTTPServer(("0.0.0.0", 0), _make_handler(skill))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self):
        return self.httpd.server_address[1]

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Intercom(OVOSSkill):
    """LAN-only speak-only messaging - see the module docstring for
    the non-negotiable "speaks messages, never executes commands"
    boundary, and DEVELOPMENT.md for the fuller architecture
    reasoning."""

    def initialize(self):
        self._server = IntercomServer(self)
        self._server.start()
        self.add_event(INCOMING_MESSAGE_BUS_EVENT, self._handle_incoming_message)
        self._update_advertisement()

    def shutdown(self):
        self._unadvertise()
        self._server.stop()

    # -----------------------------------------------------------
    # Advertising this device - re-registered whenever the name
    # setting changes, so renaming takes effect without a restart.
    # -----------------------------------------------------------
    def _update_advertisement(self):
        self._unadvertise()
        name = normalize_name(self.settings.get("intercom_name"))
        if name is None:
            return  # can't be addressed by voice without a name - don't advertise
        ip = get_local_ip()
        if ip is None:
            return
        self._zc = Zeroconf()
        self._service_info = build_service_info(name, ip, self._server.port)
        try:
            self._zc.register_service(self._service_info)
        except Exception:
            self.log.exception("Failed to register intercom mDNS service")

    def _unadvertise(self):
        zc = getattr(self, "_zc", None)
        info = getattr(self, "_service_info", None)
        if zc is not None and info is not None:
            try:
                zc.unregister_service(info)
            except Exception:
                pass
            zc.close()
        self._zc = None
        self._service_info = None

    # -----------------------------------------------------------
    # Receiving - runs on the skill's normal bus thread, handed off
    # from the HTTP background thread via self.bus.emit(). Safe to
    # call self.speak_dialog()/self.get_response() here.
    # -----------------------------------------------------------
    def _handle_incoming_message(self, message):
        sender_name = message.data.get("sender_name") or ""
        text = message.data.get("message") or ""
        sender_ip = message.data.get("sender_ip")
        reply_port = message.data.get("reply_port")

        self.speak_dialog("message_from", {"sender": sender_name})
        self.speak(text)

        if not sender_ip or not reply_port:
            return  # no way to send a reply even if they wanted to

        wants_reply = self.ask_yesno("want_to_reply") == "yes"
        if not wants_reply:
            return

        self.speak_dialog("say_your_reply")
        reply_text = self.get_response()
        if not reply_text:
            return

        own_name = normalize_name(self.settings.get("intercom_name")) or ""
        own_code = normalize_code(self.settings.get("intercom_code")) or ""
        status = send_message(sender_ip, reply_port, own_name, own_code,
                               reply_text, self._server.port)
        if status == STATUS_OK:
            self.speak_dialog("reply_sent")
        else:
            self.speak_dialog("reply_failed")

    # -----------------------------------------------------------
    # Sending
    # -----------------------------------------------------------
    @intent_handler("set_intercom_code.intent")
    def handle_set_intercom_code(self, message):
        raw = message.data.get("code")
        code = normalize_code(raw)
        if code is None:
            self.speak_dialog("code_not_understood")
            return
        self.settings["intercom_code"] = code
        self.speak_dialog("code_set")

    @intent_handler("set_intercom_name.intent")
    def handle_set_intercom_name(self, message):
        raw = message.data.get("name")
        name = normalize_name(raw)
        if name is None:
            self.speak_dialog("name_not_understood")
            return
        self.settings["intercom_name"] = name
        self._update_advertisement()
        self.speak_dialog("name_set", {"name": name})

    @intent_handler("send_message.intent")
    def handle_send_message(self, message):
        own_name = normalize_name(self.settings.get("intercom_name"))
        own_code = normalize_code(self.settings.get("intercom_code"))
        if own_name is None:
            self.speak_dialog("own_name_not_set")
            return
        if own_code is None:
            self.speak_dialog("own_code_not_set")
            return

        target_raw = message.data.get("target")
        target = normalize_name(target_raw)
        if target is None:
            self.speak_dialog("target_not_understood")
            return

        peer = discover_peer(target)
        if peer is None:
            self.speak_dialog("target_not_found", {"target": target_raw})
            return

        self.speak_dialog("what_to_say")
        text = self.get_response()
        if not text:
            return

        status = send_message(peer["ip"], peer["port"], own_name, own_code,
                               text, self._server.port)
        if status == STATUS_OK:
            self.speak_dialog("message_sent")
        elif status == STATUS_NO_CODE_SET:
            self.speak_dialog("target_no_code_set", {"target": target_raw})
        elif status == STATUS_WRONG_CODE:
            self.speak_dialog("target_code_mismatch", {"target": target_raw})
        else:
            self.speak_dialog("target_unreachable", {"target": target_raw})
