# Moth Operating Rules

Moth is a cross-repo audit and onboarding tool. It owns derived reports and
repo profiles, not project business rules.

## Core rules

- Keep repository-specific thresholds, gates, and truth sources in the target
  repo, not in Moth.
- Moth may read goal/handoff/docs/codegraph/complexity outputs and turn them
  into a consolidated snapshot.
- Prefer machine-readable output. Do not add doc-heavy generated reports unless
  a caller explicitly asks for prose.
- Use controller-led work for multi-step changes.
- Prefer small, inspectable slices and keep adapters thin.
- Credits for CodeGraph, complexity-optimizer, and any other sourced tooling
  must stay visible in repo docs and release materials.
