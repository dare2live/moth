# Moth Next migration

This release changes contracts, not the ownership boundary: target
repositories still own business rules, architecture intent, tests, and gates.
Moth owns bounded discovery, normalization, evidence linking, and verdict
composition.

## Project model

`moth.project-model.v2` adds canonical `entities`, `relations`, `flows`, and
`state_machines`. The v1-shaped `project`, `applications`, `runtimes`, and
`modules` fields remain as a compatibility projection for existing consumers.
New consumers should use the canonical topology fields.

Repositories may add `.moth/architecture.yaml`, validated by
`moth.architecture-intent.v1`. Free-form documents can be cited as provenance,
but Moth does not parse prose into To-Be facts. Missing declarations remain
`NOT_DECLARED`; invalid references, escaping paths, stale/missing evidence, or
unknown vocabulary fail closed.

Desired items use explicit `REQUIRED` or `FORBIDDEN` expectations. Absence is
only a confirmed result when current coverage is explicitly complete.
Otherwise drift is `UNVERIFIABLE`, never silently conformant.

## Change safety

The same `moth inspect` entry accepts:

```bash
moth inspect --repo <repo> --task-kind high_risk_change \
  --change-phase pre --file src/example.py --plan-only --format json

moth inspect --repo <repo> --task-kind high_risk_change \
  --change-phase post --file src/example.py --format json
```

Target repositories declare mandatory gates in
`.moth/change-safety.yaml`. CLI `--gate` values are additive; they never
replace mandatory gates. `--plan-only` never executes a gate. CodeGraph
`affectedTests` is always a planned set, not proof that tests ran.

Change-safety exits are `GO=0`, `NO_GO=1`, and `CAUTION=2`. The legacy
`moth affected` command remains available, but an empty test set without
provider completeness evidence now returns `WARN` and exit `2` instead of a
false-green exit `0`.

## External tools and Skills

There are no exact-version ceilings for CodeGraph, Omen, Mio,
architect-controller, or other registered upstreams. Versions are observed
evidence. Compatibility is decided by the configured runtime capability and
normalized output contracts in `docs/compatibility-matrix.yaml`.

When the user says “更新 Moth 相关工具和 Skill” or equivalent, the Moth Skill
must inventory authoritative upstreams, update to the selected latest stable
releases, run capability/output probes, refresh observed evidence, update the
plugin cachebuster, reinstall the plugin, and forward-test from a fresh task.

Guidance discovery and activation-receipt state are independent contracts (see
`src/moth/guidance.py` and `src/moth/decision_context.py`). A third layer,
Guidance application evidence, previously let a controller pass
`--application-reports` accepting `moth.guidance-application.v1` evidence
bound to the original run, current Skill digest, and matching activation
receipt, recording bounded decision summaries and structured conflict
resolutions. That layer was retired 2026-09-08 and deleted
(`src/moth/guidance_application.py` and its schema/policy/tests): an
independent review found no host ever produced application reports. The
receipt/application loop was wired only for the Codex host — the sole receipt
writer in the repo is
`plugins/moth/skills/moth/scripts/make_activation_receipts.py`, which stamps a
fixed `codex-moth-skill` executor — and other hosts have no matching Skill
install, so the layer validated nothing beyond its own tests, never a real
consumer.

For the record, the layer was *not* retired because it required a
`PLATFORM_VERIFIED` receipt. Its policy accepted
`activation_states: [SELF_ATTESTED, PLATFORM_VERIFIED]`, and a `SELF_ATTESTED`
receipt was enough to drive a report all the way to `report_state: VALID`,
`application_state: APPLIED_WITH_EVIDENCE`, and
`application_readiness: COMPLETE`. `PLATFORM_VERIFIED` is separately
unreachable in this codebase (`_receipt_state` in `decision_context.py` only
ever returns `NONE`, `INVALID`, `STALE`, or `SELF_ATTESTED`), which is why
`context_readiness` can never reach `READY` while a required source is active
— but that is a fact about the receipt layer, not a dependency of the retired
application layer. The reason for retirement is the absence of a producer,
full stop.

Retiring it does narrow one specific path: a caller could previously hand a
required source a `SELF_ATTESTED` activation receipt and *also* pass a
non-empty `--application-reports` array that failed to claim that source, which
forced `context_readiness` to `BLOCKED` (via `missing_application_sources`)
instead of the usual `SELF_ATTESTED`. That path no longer exists — such a
source now resolves to `SELF_ATTESTED` like any other. No shipped caller
(`moth.cli`, `moth.orchestration`, `moth.inspection`) ever populated
`application_reports` with anything, so this does not change the behavior of
any pipeline that has run to date; it only removes a lever a caller could have
used by hand-crafting a report file. Every other `context_readiness` path —
`BLOCKED` from a missing, invalid, or stale activation receipt, and `READY`/
`SELF_ATTESTED` from receipt state alone — is unchanged.

Before an external update, retain the previously observed version and plugin
cache entry. If the new runtime fails a required capability/output probe,
restore that prior package or plugin entry, keep the compatibility result
failed, and do not weaken the contract or pin a permanent ceiling. A later
compatible stable release may be adopted normally.
