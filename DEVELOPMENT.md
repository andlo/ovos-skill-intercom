# Development

## Why fixed intents, and the non-negotiable speak-only boundary

See README.md and the module docstring in `__init__.py` for the full
reasoning - the single sentence that matters most: **this skill
speaks messages, it never executes commands**. A received message is
only ever passed to `self.speak()`, never routed through the intent
pipeline. That boundary is why this can be a small, self-contained
skill instead of a much bigger, much more dangerous piece of
infrastructure - see "Why not just relay to the target's messagebus"
and "Why this isn't a smaller HiveMind" in the README.

## Article-stripping via substring match, not per-locale article lists

Caught via live testing on real hardware (two devices on the actual
LAN), not a unit test guess: `"send a message to the bedroom"`
resolves to `send_message.intent`'s `{target}` slot as `"the
bedroom"` - Padatious captures whatever follows "to " literally, it
doesn't know "the" is a droppable article. Meanwhile a device only
ever advertises its bare configured name (`"bedroom"`) via mDNS.
`normalize_name()` lowercases and collapses whitespace but never
stripped articles, so an exact-match lookup failed on completely
ordinary phrasing - `discover_peer("the bedroom")` couldn't find a
device advertised as `"bedroom"`, and the user was correctly, if
misleadingly, told "I can't find a device called the bedroom".

Fixed by checking substring containment as a fallback after an exact
match fails: if a known device's normalized name is CONTAINED in the
normalized spoken target, treat it as a match. This generalizes
across "the"/"a"/"an" and equivalent leading articles in other
languages without needing a maintained per-locale article list -
`"the bedroom"` contains `"bedroom"`; `"det soveværelse"` would
contain `"soveværelse"` the same way, no da-dk-specific code needed.
The check is deliberately one-directional (device name found IN the
spoken target, not the reverse) - a device named just `"a"` matching
every utterance containing the letter "a" would be a much worse
failure mode than the one this fixes.

## Threat model: a WiFi-password-equivalent, not HiveMind-grade

The shared household code is proportionate to "keep casual LAN
presence out," not "defend against a targeted attacker." Concretely,
and disclosed rather than glossed over:
- The code is sent in **cleartext** inside the HTTP POST body on
  every message - anyone passively sniffing LAN traffic could
  capture it. Acceptable for a trusted home LAN, the same trust
  boundary a WiFi password itself already assumes.
- The receiver **tells the sender** whether a code mismatch or a
  missing code was the reason a message wasn't delivered
  (`STATUS_WRONG_CODE` / `STATUS_NO_CODE_SET`), rather than staying
  silent either way. This is a deliberate trade-off, not an
  oversight: knowing "the code's wrong" vs. "nothing's configured
  yet" is far more useful for a household member fixing a real setup
  problem than it is dangerous as an oracle for guessing a 4-digit-
  or-passphrase-strength secret in a household-trust setting - but it
  IS marginally more information than staying completely silent on
  every rejection would leak. Worth being explicit that this was a
  deliberate choice, not something overlooked.
- No encryption on the wire at all (plain HTTP, not HTTPS) - same
  trust boundary as above; adding TLS would need certificate
  management this project has no infrastructure for yet.

## Why not depend on ovos-skill-network-scanner

Investigated and rejected. `ovos-skill-network-scanner` registers its
own `ovos.plugin.skill` entry point
(confirmed in its `setup.py`) - declaring it as a pip dependency of
this skill would cause OVOS's plugin manager to discover and
potentially load network-scanner as an active skill on every device
that installs this one, whether or not that was wanted, plus pull in
its `mac-vendor-lookup` dependency for a device that may not want
network scanning at all. On top of that side effect, the actual code
overlap turned out smaller than it first looked: network-scanner
*passively browses* for already-existing, standard service types
(Chromecast, printers, ...); this skill needs to both *advertise* its
own custom service type and browse specifically for that type - a
different task, not the same function reused. `get_local_ip()` is
duplicated here (a small, well-known UDP-connect trick, not a
meaningful chunk of unique logic) rather than imported.

## Household-wide shared code, not pairwise pairing

Every device that should participate says the SAME code once
(`"set intercom code to ..."`) rather than each PAIR of devices
needing its own separate secret - scales linearly (N devices = N
spoken setup commands) instead of quadratically (N devices =
N*(N-1)/2 pairwise setups), which matters a lot once a household has
more than 2-3 intercom-capable devices. The code is just a normalized
STRING comparison (see `normalize_code()`), not a parsed number - a
passphrase and a digit PIN are equally valid, whichever a household
prefers.

## Advertising without a code set

A device advertises itself via mDNS as soon as it has a NAME
configured, independent of whether a CODE is also set yet. This is
deliberate: it lets a sender's `discover_peer()` call actually FIND a
partially-configured device and get a specific, useful error
(`target_no_code_set`) rather than a bare "device not found" that
would be indistinguishable from "that device doesn't exist / isn't
on the network at all." The code itself is never included in the
advertised mDNS data (see "Wire protocol" below) regardless of
whether it's set.

## Wire protocol

A single HTTP POST endpoint (`/message`) on a dynamically-chosen
port (`HTTPServer(("0.0.0.0", 0), ...)` - the OS picks a free port,
advertised via mDNS, so there's no fixed-port collision risk across
devices or other services).

Request body:
```json
{"sender_name": "...", "code": "...", "message": "...", "reply_port": 1234}
```

Response body:
```json
{"status": "ok" | "no_code_set" | "wrong_code"}
```

Including the sender's own `reply_port` in the request means a
reply can be sent directly back to the request's source IP (captured
from the HTTP connection itself) + that port - no second mDNS lookup
needed to send a reply, and it's inherently addressed back to the
exact device that sent the original message, not a fresh
name-based lookup that could resolve differently if IPs changed
in between.

`send_message()` returns `None` (not a `STATUS_*` string) when the
peer couldn't be reached at all (timeout, connection refused,
malformed response) - callers must distinguish "unreachable" from
"reachable but rejected", they are not the same case.

## Bridging a background thread into OVOS's bus

The HTTP listener runs in its own background thread
(`threading.Thread(target=httpd.serve_forever)`), entirely outside
OVOS's own event/bus thread. Calling `self.speak_dialog()` or
`self.get_response()` directly from that thread would not be safe -
those are designed to be called from the skill's normal, bus-driven
execution context. The request handler therefore does ONLY the
minimum safe work itself (parse the JSON body, validate the code,
write the HTTP response) and hands off everything interactive to
`self.bus.emit(Message(INCOMING_MESSAGE_BUS_EVENT, {...}))` - the
skill registers a handler for that event via `self.add_event(...)` in
`initialize()`, which runs on the normal thread and is where
`speak_dialog`/`ask_yesno`/`get_response` actually get called. This
is the first skill in this project family that needed to bridge a
raw background thread into OVOS's bus - worth flagging as a new
pattern, not an established one, since it hasn't been used or
reviewed anywhere else yet.

The HTTP response (`{"status": "ok"}`) is written and sent BEFORE
the bus event is emitted and the interactive speak/reply flow begins
- so the sender's "message sent" confirmation is decoupled from
whether the recipient actually engages with it, matching how a real
doorbell/intercom buzzer works: you know it rang, independent of
whether anyone answers.

## Self-healing against duplicate instantiation

Discovered during live cross-device testing, not anticipated in the
original design: **every plugin skill on an OVOS device can be
instantiated TWICE at startup** if network/internet are already
connected when `SkillManager` starts (the common case) - a genuine
platform-level race condition, filed as
[OpenVoiceOS/ovos-core#887](https://github.com/OpenVoiceOS/ovos-core/issues/887)
after confirming it affects official skills (e.g.
`ovos-skill-ddg.openvoiceos`) equally, not something specific to this
project's skills or their entry-point declarations. Root cause, as
far as traced: `SkillManager.run()` calls `_load_on_startup()`
synchronously on its own thread, while `handle_network_connected`/
`handle_internet_connected` (bus-message handlers dispatched on a
*different* thread) can fire almost immediately if the network is
already up, both ultimately reaching `load_plugin_skills()`'s
`if skill_id not in self.plugin_skills` check on a plain,
unsynchronized dict - a classic time-of-check-to-time-of-use race
that lets both threads pass the check for the same `skill_id` before
either has finished loading it.

For most skills this "only" means a harmlessly doubled spoken
response. For this skill it's a real functional problem: two live
instances means two competing background HTTP listeners and two
competing mDNS advertisements for the same device name, with no
guarantee which one a peer's `discover_peer()` ends up talking to on
any given send.

Rather than wait on an upstream fix, `Intercom` self-heals via a
module-level (not per-instance) singleton guard: `_active_server` and
`_active_server_lock` track whichever `IntercomServer` is currently
running *across* however many `Intercom` instances the platform bug
produces. Each `initialize()` call stops any previously-active
server before starting its own and claiming the singleton slot - so
regardless of how many duplicate instances get created, only the
most-recently-initialized one's HTTP listener and mDNS advertisement
stay live. `shutdown()` is defensive both ways: safe to call on an
already-stopped server (the stale instance being torn down later),
and only clears `_active_server` if it's still pointing at that
specific instance's server (so a stale instance's shutdown can't
accidentally clear the CURRENT active instance's state).

Verified with real `HTTPServer` instances in
`tests/test_duplicate_instantiation_guard.py`, not mocked stand-ins -
including confirming the stopped instance's port genuinely stops
accepting connections, not just that a mock's `.stop()` was called.

## Known limitations

- **No encryption, no code-guessing rate limiting.** See "Threat
  model" above.
- **A stale/renamed device can't be un-advertised remotely** - if a
  device's name is changed, its OLD advertisement is explicitly
  unregistered first (see `_update_advertisement()`), but if a device
  goes offline uncleanly (power loss rather than a graceful shutdown
  calling `shutdown()`), its mDNS advertisement can linger in other
  devices' local zeroconf caches until it naturally expires - a real,
  if minor and self-healing, rough edge.
- **Discovery is a fresh, timed scan per send (~3 seconds), not a
  cached/persistent browser** - a deliberate trade-off (see
  `discover_peer()`'s docstring): simpler, and avoids keeping a
  zeroconf browser running indefinitely for a feature used
  infrequently, at the cost of a few seconds' latency on every send.
- **A reply attempt that fails is reported generically** - the
  receiver doesn't distinguish "the original sender is now
  unreachable" from other failure modes on the reply path in v1; see
  `reply_failed.dialog`.

## Setup
```bash
git clone https://github.com/andlo/ovos-skill-intercom.git
cd ovos-skill-intercom
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -r requirements-test.txt
```

## Running tests
```bash
pytest tests/ -v
```

Note: `tests/test_wire_protocol.py` starts real `HTTPServer` instances
bound to `127.0.0.1` on ephemeral ports - no network access beyond
loopback, but not pure unit tests either; this is deliberate, see
that file's module docstring.

## Versioning

`version.py` follows `VERSION_MAJOR.VERSION_MINOR.VERSION_BUILD[aVERSION_ALPHA]`,
same convention as the rest of this project family.

## Style / conventions

- License: GPL-3.0-or-later
- `locale/<lang-code>/` layout, `skill.json` inside each locale folder
- 5 locales: en-us, da-dk, de-de, fr-fr, es-es (project baseline)
