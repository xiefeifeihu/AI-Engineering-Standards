# AI Engineering Standards

Canonical engineering standards shared across local AI / Vibe Coding projects.

## Network Standard

Current pre-release version:

```text
NETWORK_SPEC_VERSION=V0.2
NETWORK_SPEC_STATUS=PRE_RELEASE
V0_2_COLD_START_ACCEPTANCE=PASS
FINAL_RELEASE_PENDING=true
```

Documents:

- `network/AI-NETWORK-STANDARD.md` — canonical network architecture, Network Gate, Project Network Module, logging/Web/Agent rules.
- `network/AI-NETWORK-HANDOFF.md` — current verified machine/project state and cross-session handoff.

## Project integration

Each Project keeps a synchronized local snapshot plus a project-owned profile and gate:

```text
docs/AI-NETWORK-STANDARD.md
docs/AI-NETWORK-PROFILE.md
scripts/network/network-gate.cmd
scripts/network/network-gate.sh
```

The Canonical repository defines shared contracts. Each Project owns its real endpoints, runtime/build/provider dependencies and Network Self-Test.

## Version governance

Do not publish `V1.0` until the user explicitly approves the formal release. Pre-release refinements remain on `V0.2` and are tracked by Git commits and dates.
