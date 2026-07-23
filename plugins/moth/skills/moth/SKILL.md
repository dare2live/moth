---
name: moth
description: One-call project understanding and controller orchestration. Use when Codex starts or resumes substantive repository work, architecture or refactoring, audits and research, high-risk changes, when the user explicitly asks for Moth, or says to update/升级 Moth 相关工具和 Skill. It makes Moth discover project evidence and the user's registered Guidance sources, loads Mio and architect/controller Skills in the declared order, records honest executor self-attestation separately from host verification, and carries work through repo-owned gates so the user does not need to remember separate tools or Skills.
---

# Moth

Use Moth as the single user-facing entry. Treat CodeGraph, Omen, complexity
analysis, Mio, and controller Skills as internal capabilities selected by the
Moth contract.

## 1. Classify the task

Choose exactly one task kind:

- `mechanical`: low-risk literal edits with no judgment.
- `substantive_judgment`: normal implementation, diagnosis, or tradeoffs.
- `architecture_orchestration`: architecture, broad refactors, ambiguous
  decomposition, or multi-step controller work.
- `high_risk_change`: deployment, migration, security, destructive, paid, or
  data-integrity-sensitive work.
- `audit_research`: audit, review, research, or evidence-first familiarization.

When uncertain, choose the more demanding applicable kind.

## 2. Ask Moth for one activation plan

Resolve the target repository from the user request and current workspace. Run:

```bash
moth inspect --repo <repo> --task-kind <kind> --plan-only \
  --format json --output <temporary-plan.json>
```

Use `mktemp -d` for temporary artifacts when the sandbox permits writes. In a
strict read-only sandbox, keep the plan and receipts in memory and use the
helper's `--inspection - --output -` stdin/stdout transport. If the installed
`moth` command is unavailable while working in the Moth source repository, use
`PYTHONPATH=<moth-repo>/src python3 -m moth.cli` for that checkout.

Do not continue when the inspection status is `FAIL`; diagnose the reported
contract or project-health failure first. `NEEDS_EXECUTOR` is the expected
pre-load state, not a project failure.

When the user needs a readable local project atlas, use the same Moth entry
instead of invoking a separate renderer:

```bash
moth inspect --repo <repo> --task-kind <kind> --plan-only \
  --format html --output <report.html>
```

The HTML is a self-contained rendering of `moth.visual-document.v1`. It must
not run collectors, know platform/tool-specific schemas, or invent priorities,
To-Be architecture, flows, or risk claims that are absent from the inspection
evidence.

When the user wants to browse several configured projects or inspect the
portable contracts through a local API, keep the same Moth entry:

```bash
moth init --repo <repo> --register-web
moth serve
```

Open the complete loopback URL printed by Moth. The browser project selector
can request only allowlisted project IDs. Web requests always use
`safe_view`: they never run repository assertion packs, profile-selected
external complexity commands, configurable tool adapters, change gates, or
arbitrary paths. Do not weaken this boundary to make a project appear greener.
The API must return only the portable inspection and validated
`moth.visual-document.v1`; use the in-page API JSON action when the user wants
the raw contract.

## 3. Load every planned Guidance source

Read `orchestration.decision_context.ordered_guidance_sources` in order. For
each source:

1. Match its `skill:<id>` reference against the current session's Available
   Skills catalog.
2. Read that Skill's `SKILL.md` completely using its catalog path.
3. Follow referenced resources required for this task.
4. Do not substitute a similarly named Skill, copy its body into Moth, or claim
   it loaded when the catalog entry is absent.

This normally loads the Mio collaboration lens before architect-controller.
Project-specific controllers may follow them when registered.

## 4. Self-attest loading without overstating proof

Only after every planned Skill has been read, run the bundled helper with one
`--loaded-source` per source in the exact activation order:

```bash
python3 <this-skill-dir>/scripts/make_activation_receipts.py \
  --inspection <temporary-plan.json> \
  --output <temporary-receipts.json> \
  --loaded-source <first-id> \
  --loaded-source <next-id>
```

For strict read-only execution, pipe the plan JSON to `--inspection -` and
capture `--output -`; pass the captured receipt JSON to Moth through a
read-only process-substitution path. Do not fall back to repository files.

Then rerun the same Moth inspection with:

```bash
moth inspect --repo <repo> --task-kind <kind> \
  --run-id <run-id-from-first-plan> \
  --receipts <temporary-receipts.json> \
  --format json
```

The bundled helper produces an executor self-attestation, not host-native or
cryptographic proof. Never describe it as verified loading. Continue only when
the rerun reports `context_readiness=SELF_ATTESTED` or `READY`; a release gate
that requires machine verification must still require `READY`.

For a task with an empty activation order, skip receipt generation and require
the first inspection to be `READY`.

## 5. Record application evidence

During substantive work, keep bounded, portable IDs for decisions influenced
by each loaded Guidance source and evidence references that support the
influence. Record conflicts explicitly with the other source IDs, the selected
resolution, and evidence. Every reference must resolve to an ID in the current
inspection's `snapshot.project_model.evidence`; never invent a receipt or
evidence ID. Copy `contract_id` and `loaded_at` from that source's matching
activation receipt, and include a bounded overall decision summary plus a
summary for each influenced decision. Before the final inspection, write a
temporary JSON array conforming to `moth.guidance-application.v1` and pass it
through the same entry:

```bash
moth inspect --repo <repo> --task-kind <kind> \
  --run-id <run-id-from-first-plan> \
  --receipts <temporary-receipts.json> \
  --application-reports <temporary-application-reports.json> \
  --format json
```

Require every claimed source to report `APPLIED_WITH_EVIDENCE`. A missing,
invalid, stale, duplicate, or evidence-free report remains `NOT_CLAIMED`.
Application evidence is an explicit executor claim about decision influence;
it does not upgrade `SELF_ATTESTED` loading to host verification and does not
prove that the decision itself was correct. Never infer application by parsing
chat text or Skill prose.

## 6. Execute through evidence gates

Use the loaded Mio lens for judgment and the loaded controller protocol for
truth sources, boundaries, falsification gates, reversible sequencing, and
completion. Let Moth select CodeGraph, Omen, complexity, platform detectors,
and repo-owned checks through its profile; do not make the user invoke them
separately.

Before completion:

- Run the repository's required tests and gates.
- Rerun Moth inspection or the narrow Moth command required by the profile.
- Keep project health separate from task-context readiness.
- Report partial or blocked states honestly; do not convert missing evidence to
  PASS.
- Remove temporary plan, receipt, and application-report files.

For a scoped code change, keep using the same Moth entry:

```bash
moth inspect --repo <repo> --task-kind <kind> \
  --change-phase pre --file <repo-relative-path> --plan-only --format json

moth inspect --repo <repo> --task-kind <kind> \
  --change-phase post --file <repo-relative-path> --format json
```

Do not treat `affectedTests` as executed tests. Repository mandatory gates come
from `.moth/change-safety.yaml`; explicit `--gate` values are additive.
`--plan-only` never executes them. Respect `GO=0`, `NO_GO=1`, and `CAUTION=2`.
Use `.moth/architecture.yaml` as the structured As-Is/To-Be authority; cited
prose is provenance only, and `UNVERIFIABLE` is not a drift pass.

Never export Skill bodies, private paths, task text, amend trails, raw Omen
output, or receipt working files in public artifacts.

## Maintenance requests

When the user asks to update or upgrade Moth-related tools and Skills:

1. Inventory installed and upstream versions from authoritative sources.
2. Update the selected tools and Skills without assuming an old exact-version
   ceiling.
3. Use runtime capability and output-contract probes as the compatibility
   authority; record the observed versions as evidence.
4. Update fixtures and adapters only when the new contract requires it.
5. Revalidate this Skill and plugin, update the plugin cachebuster, reinstall
   it from the configured local marketplace, and forward-test in a fresh task.
6. Refresh `docs/compatibility-matrix.yaml` observed evidence without adding a
   version ceiling.
