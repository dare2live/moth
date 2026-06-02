# Operating model

Moth is a derived control plane. It does not define business rules. It reads
repo-local evidence and turns it into onboarding and audit summaries.

## Ownership

- **Profiles**: repo-specific paths, gate commands, and report locations
- **Adapters**: wrappers around existing tooling such as CodeGraph and
  complexity analysis
- **Checks**: startup, docs, worktree, and governance readiness checks
- **Reports**: markdown and JSON outputs for controllers and new sessions

## Non-goals

- no new strategy logic
- no market-data writers
- no per-repo threshold ownership
- no replacement for the source repos
