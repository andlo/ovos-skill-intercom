# <img src='icon.png' card_color='#C45A28' width='50' height='50' style='vertical-align:bottom'/> Intercom

LAN intercom for OVOS - "send a message to the bedroom" delivers a
spoken message to a named peer OVOS device on the same local
network, with an optional spoken reply sent back. Fully offline,
available in English, Danish, German, French, and Spanish.

[![Tests](https://github.com/andlo/ovos-skill-intercom/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-skill-intercom/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-skill-intercom.svg)](https://pypi.org/project/ovos-skill-intercom/)

- [The one non-negotiable boundary](#the-one-non-negotiable-boundary)
- [Setup](#setup)
- [Usage](#usage)
- [How discovery and delivery work](#how-discovery-and-delivery-work)
- [Known limitations](#known-limitations)
- [Install](#install)
- [Development](#development)

## The one non-negotiable boundary

**This skill speaks messages. It never executes commands.** A
received message is only ever passed to `self.speak()` - it is never
routed through the intent pipeline. "Set an alarm in the bedroom
from the living room" is explicitly out of scope; that would be
remote *command execution*, a categorically different (and far more
dangerous) capability than delivering a spoken message. See
[DEVELOPMENT.md](DEVELOPMENT.md) for why relaying to the target's
own OVOS messagebus was investigated and rejected, and why this
isn't "a smaller HiveMind."

## Setup

Each device needs a **name** and a shared household **code**, set by
voice on that specific device:
```
"set intercom name to living room"
"set intercom code to four seven two nine"
```

Every device that should participate says the **same code** - not a
separate secret per pair of devices. Say it once per device; any two
devices with matching codes can message each other.

## Usage
```
"send a message to the bedroom"
  -> "what should I say?"
  -> [you speak the message]
  -> "message sent"

[on the bedroom device]
  "message from living room"
  [message is spoken]
  "do you want to reply?"
  -> "yes" -> "go ahead, say your reply" -> [you speak it] -> "reply sent"
```
```
"send en besked til soveværelset"                  (Danish)
"sende eine nachricht an schlafzimmer"             (German)
"envoie un message à chambre"                      (French)
"envía un mensaje a dormitorio"                    (Spanish)
```

## How discovery and delivery work

Peer devices are found by name via mDNS - no IP addresses to type or
remember. A device advertises itself as soon as it has a **name**
set, even before a code is configured, so a sender gets a specific,
useful error (`"soveværelset har ikke en intercom-kode sat"`) rather
than a bare "device not found" when the target exists but isn't
fully set up yet.

Delivery is a single HTTP request over the LAN to the discovered
peer, carrying the sender's name, the shared code, and the message.
The code is never included in the mDNS advertisement itself - it
only ever travels inside the actual message request. See
[DEVELOPMENT.md](DEVELOPMENT.md) "Wire protocol" for the exact
request/response shape.

## Known limitations

- **Threat model: a WiFi-password-equivalent, not HiveMind-grade.**
  No encryption on the wire, and the receiver does report back
  *which* kind of rejection happened (wrong code vs. no code set at
  all) rather than staying silent - useful for fixing a real setup
  problem, at the cost of leaking slightly more than a flat "message
  not delivered" would. Proportionate to keeping casual LAN presence
  out, not to defending against a targeted attacker.
- **Discovery is a fresh ~3-second scan per send**, not a persistent
  cached browser - simpler, at the cost of a few seconds' latency
  each time.
- **A device that goes offline uncleanly** (power loss, not a
  graceful shutdown) can leave a stale mDNS advertisement lingering
  in peers' local caches until it naturally expires.

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full reasoning behind
each of these, plus why `ovos-skill-network-scanner` was deliberately
**not** made a dependency despite similar-looking mDNS code.

## Install
```bash
pip install ovos-skill-intercom
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md).

## Category
**Utility**

## Tags
#intercom #multi-device #messaging #lan
