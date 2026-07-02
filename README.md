# Moth

Moth is a JSON-first cross-repo snapshot tool for architecture, governance,
complexity, and startup risk. It is closer to CodeGraph than to a document
generator: the output is a machine-readable snapshot that other models or
controllers can consume quickly.

## What it owns

- repo profiles
- structured snapshots and health summaries
- adapters around existing tools like CodeGraph and complexity-optimizer
- repo-local evidence paths and risk flags

## What it does not own

- project business rules or thresholds
- live writers / ETL / trading logic
- project-specific truth sources beyond identifying them in a profile
- long prose reports unless explicitly requested

Profiles are intentionally lightweight: they point at evidence paths,
codegraph roots, and optional complexity commands. The snapshot is the
derived artifact; the source repos remain the truth source.

If a repo keeps a complexity baseline JSON, profiles may also point at
`complexity_baseline_path`. In that case Moth compares the current analyzer
findings against the baseline and exposes the diff in the snapshot.

The complexity diff excludes findings whose path contains any of the default
ignored parts (`.claude/worktrees/`, `node_modules/`, `.venv`, `.git/`) so
agent-worktree copies and vendored trees cannot fake `new_high` regressions;
the excluded total is reported as `ignored_count` in the diff (never silently
dropped). Profiles can override the list with `complexity_ignored_path_parts`
(set `[]` to disable filtering).

## Local install

Use a Python 3.11+ interpreter for the virtualenv. If your default `python3`
is older, point the venv at an explicit 3.11+ binary and upgrade
`pip`/`setuptools`/`wheel` inside the venv before installing editable.

```bash
cd /Users/dp/Documents/M/moth
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Then:

```bash
moth snapshot --repo /Users/dp/Documents/M/stock/chunkymonkey --profile chunkymonkey --format json
moth profiles --format json
moth profiles --workspace /Users/dp/Documents/M --format json
moth workspace --workspace /Users/dp/Documents/M --format json
moth init --repo /Users/dp/Documents/M/stock/chunkymonkey --output /Users/dp/Documents/M/stock/chunkymonkey/.moth/profile.yaml
moth sync --repo /Users/dp/Documents/M/stock/chunkymonkey --profile chunkymonkey --format json
moth affected --repo /Users/dp/Documents/M/stock/chunkymonkey --profile chunkymonkey backend/foo.py --format json
moth coupling --repo /Users/dp/Documents/M/stock/chunkymonkey --impact config/schema_registry.json --format markdown
moth cycles --repo /Users/dp/Documents/M/lifehack --format markdown
moth takeover --repo /Users/dp/Documents/M/lifehack
moth gates --repo /Users/dp/Documents/M/lifehack my_experiment
```

Moth expects the current CodeGraph CLI surface (`status --json`,
`affected --json`, `query --path`, `explore --path`). For complexity scanning,
install or refresh the upstream skill with:

```bash
npm install -g codex-complexity-optimizer
```

The official installer writes the analyzer under
`${CODEX_HOME:-~/.codex}/skills/complexity-optimizer`; profile command entries
may use `~` or environment variables, and Moth expands them before execution.

`doctor` is kept as a compatibility alias, but `snapshot` is the primary
machine-readable entrypoint.

Snapshots include a stable `schema_version` and `generated_at` timestamp so
other models can consume them without guessing the payload shape.

`sync` refreshes the repo's CodeGraph index first and then emits a payload with
both the sync result and the latest snapshot.

`affected` combines CodeGraph `affected --json` with the profile's
complexity command run against only the supplied changed files. It is intended
for pre-review scoping: which tests are likely affected, and whether the files
being changed introduce high-confidence complexity hotspots.

`coupling` is the pre-delete/pre-rename safety rail. Plain `moth coupling`
checks for orphan references, and the same orphan check is included in every
`snapshot` / `doctor` / `report`. Use `moth coupling --impact <name-or-path>`
before deleting or renaming tables, scripts, config keys, evidence paths, docs,
or shared symbols; it reports fan-in by code/config/doc/test/CI/Moth/shell
surface so callers can be migrated before removal.

`cycles` detects import cycles (AST import graph + Tarjan SCC) inside a
package. Configure it per profile; unconfigured repos are unaffected (SKIP):

```yaml
# .moth/profile.yaml
import_cycles:
  scan_paths: [backend/services, backend/api]
  package_prefix: backend
  allowlist_path: config/architecture_known_cycles.json  # optional
```

A detected cycle whose members are a subset of an allowlist entry is `known`;
anything else is `new` and fails the check (and the overall `doctor` /
`snapshot` report). A configured-but-missing/invalid allowlist is a FAIL, not
a silent empty list.

`takeover` is the first command of a new session: it runs the repo-owned
takeover checklist (one read-only command + optional verdict regexes per
section, fail-closed — non-zero exit / timeout / missing required pattern all
FAIL) and prints a one-page verdict. `gates` runs an experiment's
pre-registered go/no-go assertion pack (same schema as Moth assertion packs);
any fail/error means NO-GO and exit 1. Both commands read the legacy
`.sherpa/` layout first (`.sherpa/takeover.yaml`, `.sherpa/gates/<exp>.yaml`)
and fall back to `.moth/`; existing sherpa-initialized repos need no
migration. `moth init` scaffolds a starter `.moth/takeover.yaml` template
alongside the profile. (Merged from the retired sibling tool `sherpa`,
2026-07-02.)

All report-style commands accept `--output <path>` to persist the rendered
payload to disk while still writing the same content to stdout:
`snapshot`, `doctor`, `report`, `profile`, `profiles`, `workspace`, `sync`,
and `affected`.

`profiles` lists the installed profile registry, and `--workspace` can scan a
workspace tree for repo-local `.moth/profile.yaml` files so a fresh session can
discover what Moth can inspect without opening YAML files by hand.

`workspace` emits a workspace-level inventory plus per-repo snapshots for all
repo-local profiles under the given root.

`init` writes a repo-local scaffold at `.moth/profile.yaml` by default so
Moth can auto-discover new repos without editing the bundled registry by hand.

Exit codes are intentionally soft: `PASS` and `WARN` both exit `0`, and only
`FAIL` exits non-zero. Warnings are carried in the JSON payload.

## Credits

Moth credits the workflow and tooling foundations of:

- CodeGraph
- complexity-optimizer
- ChunkyMonkey
- LifeHack governance patterns

See `NOTICE.md` for the maintained attribution list.

## Assertion packs (claims vs reality)

Profiles may list `assertion_packs` — YAML files owned by the target repo that
pin its load-bearing claims (doc numbers, schema counts, data-shape contracts)
to executable read-only observations:

```yaml
# .moth/profile.yaml
assertion_packs:
  - .moth/assertions/claims.yaml
```

Every `moth doctor` / `snapshot` / `report` run executes the packs and folds
failures into `issues` (overall status goes `FAIL`). Supported assertion
types: `duckdb_sql` (always `read_only=True`; requires the `assertions`
extra), `shell` (argv list, no shell, hard timeout), `file_size`,
`file_exists`. Expectation ops: `==,!=,>=,<=,>,<,between,regex`.

Design intent: codegraph/complexity audit the *shape* of code; assertion
packs audit the seam where most real incidents live — drift between what the
docs claim and what the data actually is (stale sizes, schema regressions,
silent truncation, calendar clamps). The engine is generic and fail-closed
(execution errors are failures, never skips); thresholds stay in the target
repo per the operating rules.
