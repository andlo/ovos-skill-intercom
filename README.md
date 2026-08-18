# Intercom — a design document, not a working skill yet

**Status: idea and architecture-decision stage.** This repo exists to
document the concept and, critically, the security boundary it must
respect - before writing any skill code.

## The idea

"Send besked til soveværelset" → recording starts → the message is
delivered to a peer OVOS device on the same LAN, which speaks it
aloud with the sender's name attached, and can optionally record and
send a spoken reply back.

```
Afsender:  "send besked til soveværelset"
Assistent: "hvad skal jeg sige?"
Afsender:  [optager ytring]
Assistent: "besked sendt"

Modtager:  "besked fra stuen" → [læser beskeden højt]
Assistent: "ønsker du at svare?"
Bruger:    "ja"
Assistent: "sig din besked"
Bruger:    [optager svar]
Assistent: "svar sendt"

Afsender:  "svar fra soveværelset: [besked]"
```

## The one non-negotiable design boundary

**This skill speaks messages. It never executes commands.** A
received message can only ever be passed to `self.speak()` - it is
never routed through the intent pipeline, never treated as an
utterance to act on. This is not a simplification to add later; it is
the entire reason this can be a small, safe, self-contained skill
instead of a much bigger, much more dangerous piece of infrastructure.

### Why "just relay it to the target's messagebus" was rejected

The obvious-looking shortcut - connect to the target device's OVOS
messagebus and emit a message there - was investigated and rejected.
Per OVOS's own `ovos-bus-client` documentation:

> The bus is private. It has no authentication - every connected
> client can issue any natural-language command, speak through the
> speakers, take over any subsystem, and read every other client's
> traffic. Keep it bound to 127.0.0.1 (the default), never expose it
> on a network interface... For remote access, use HiveMind.

Opening the bus to the LAN doesn't grant "the ability to make the
target speak a message" - it grants **full remote control of that
device**, exactly as if someone were sitting in front of it saying
anything they wanted. That is a categorically different (and far
larger) capability than "deliver this one message," and OVOS's own
maintainers explicitly warn against it.

### Why this isn't "build a smaller HiveMind"

`HiveMind` already exists specifically to do authenticated,
authorized, encrypted remote *command* execution across OVOS
devices (see `JarbasHiveMind/HiveMind-core`) - with per-client
permissions, identity, and policy enforcement built up over years.
If/when there's a real want for "set an alarm in the bedroom from the
living room," the correct path is to actually adopt HiveMind for that
specific purpose, not to reinvent a thinner, less-audited version of
it inside a skill meant to be a doorbell chime. Scope creep from
"speak a message" to "execute a command on another device" is exactly
the line this skill must not cross.

## Proposed architecture (not yet built)

1. **Discovery**: reuse `ovos-skill-network-scanner`'s mDNS pattern
   to find peer devices running this skill on the LAN, rather than
   requiring hand-entered IP addresses.
2. **Delivery**: each device runs its own small, narrowly-scoped
   listener (owned entirely by this skill, not the OVOS core
   messagebus) that accepts exactly one thing: a text payload plus a
   shared secret configured via skill settings. On receipt, it calls
   `self.speak()` on its own local (127.0.0.1) bus connection - it
   never touches another device's bus, and no other device can touch
   its own bus through this mechanism either.
3. **Reply flow**: a reply is just a message sent back the same way,
   tagged as a reply to the original sender - not a different
   mechanism.
4. **Auth**: shared secret per device pair, configured via skill
   settings (same pattern as `ovos-skill-sound-like`'s optional API
   key). Not full HiveMind-grade identity/crypto - proportionate to
   "don't let a random device on the LAN spam my speakers with
   arbitrary text," not "defend against a hostile network."

## Open questions (resolve before implementing)

- Exact transport for the narrow listener - lightweight HTTP endpoint
  vs. a raw socket. Either is fine as long as it stays scoped to
  "accept text + secret, call self.speak()" and nothing more.
- What happens if the target device is offline/unreachable - silent
  failure, retry, or tell the sender immediately?
- Multi-room broadcast ("send besked til alle") vs. single-target
  only for v1 - probably single-target first, broadcast is a bigger
  discovery/addressing problem worth deferring.
- Should devices need to be paired/introduced once (exchange secrets)
  before showing up as discoverable targets, or is LAN presence alone
  enough for v1? Leaning toward requiring pairing - discoverability
  alone is a weaker bar than "someone deliberately configured this."

## Category
**Utility**

## Tags
#intercom #multi-device #messaging #idea #design-doc
