# Operating model

Moth is a derived control plane. It does not define business rules. It reads
repo-local evidence and turns it into onboarding and audit summaries.

## Ownership

- **Profiles**: repo-specific evidence paths, codegraph roots, and adapter commands
- **Adapters**: wrappers around existing tooling such as CodeGraph and
  complexity analysis
- **Checks**: startup, docs, worktree, DuckDB free-block scan, and governance readiness
- **Reports**: markdown and JSON outputs for controllers and new sessions

DuckDB file-size claims are a ratchet. The engine scans `data/*.duckdb` for
`free_blocks` and warns; project packs still own blocking thresholds. Compact
is a writer-side duty.

## Non-goals

- no new strategy logic
- no market-data writers
- no per-repo threshold ownership
- no replacement for the source repos
