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

Use `mktemp -d` for temporary artifacts. If the installed `moth` command is
unavailable while working in the Moth source repository, use
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

## 5. Execute through evidence gates

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
- Remove temporary plan and receipt files.

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
