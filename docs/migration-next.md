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

Guidance discovery, activation, and application are independent contracts.
`--application-reports` accepts `moth.guidance-application.v1` evidence bound
to the original run, current Skill digest, and matching activation receipt. It
records bounded decision summaries and structured conflict resolutions; every
reference must resolve in the current project-model evidence registry. Moth
does not parse prose or claim host-native verification.

Before an external update, retain the previously observed version and plugin
cache entry. If the new runtime fails a required capability/output probe,
restore that prior package or plugin entry, keep the compatibility result
failed, and do not weaken the contract or pin a permanent ceiling. A later
compatible stable release may be adopted normally.
