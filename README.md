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

## Built-in complexity analyzer

Moth ships the complexity-optimizer hotspot scanner as a vendored module
(`moth.analyzers.complexity`, schema-frozen 2026-07-02). Profiles without a
`complexity_command` use it automatically, in-process — no external skill
path or `npm install` required. The snapshot marks builtin runs with the
command value `<builtin:moth.analyzers.complexity>`; the findings JSON schema
(`path/line/severity/kind/message/suggestion/confidence`) and output are
byte-compatible with the upstream script, so existing complexity baseline
JSONs keep working unchanged.

Run it standalone with:

```bash
moth complexity <path> [--exclude NAME ...] [--format json|markdown] [--max-findings N]
```

`--exclude` is repeatable and matches directory names (same semantics as the
original script). In builtin mode a profile can express excludes directly:

```yaml
# .moth/profile.yaml
complexity_excludes:
  - .venv_scrape
```

`complexity_excludes` is consumed only in builtin mode; if the profile sets an
explicit `complexity_command`, the option is ignored and `doctor` emits a
warning note (put the excludes into the command's own `--exclude` flags
instead). To keep using an external analyzer script, set `complexity_command`
as before — explicit commands still run as subprocesses and win over the
builtin.

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
moth complexity /Users/dp/Documents/M/stock/chunkymonkey --exclude .venv_scrape --format json
moth coupling --repo /Users/dp/Documents/M/stock/chunkymonkey --impact config/schema_registry.json --format markdown
moth cycles --repo /Users/dp/Documents/M/lifehack --format markdown
moth takeover --repo /Users/dp/Documents/M/lifehack
moth gates --repo /Users/dp/Documents/M/lifehack my_experiment
moth inspect --repo /Users/dp/Documents/M/lifehack --task-kind architecture_orchestration --plan-only --format json
moth inspect --repo /Users/dp/Documents/M/lifehack --task-kind architecture_orchestration --plan-only --format html --output /tmp/moth-lifehack.html
moth inspect --repo /Users/dp/Documents/M/lifehack --task-kind high_risk_change --change-phase pre --file backend/foo.py --plan-only --format json
moth inspect --repo /Users/dp/Documents/M/lifehack --task-kind high_risk_change --change-phase post --file backend/foo.py --format json
```

Moth expects the current CodeGraph CLI surface (`status --json`,
`affected --json`, `query --path`, `explore --path`). Complexity scanning is
built in (see above); installing the upstream skill is only needed if a
profile pins an external `complexity_command`:

```bash
npm install -g codex-complexity-optimizer
```

Omen is an optional external evidence provider. The verified upstream is
`panbanda/omen`; install its CLI with:

```bash
brew install panbanda/brews/omen
omen --version
omen --path . --format json --compact hotspot --top 10
```

Moth's thin Omen adapter consumes bounded `hotspot`, `changes`, and `diff`
JSON. Compatibility is decided by runtime capability and output-contract
probes, not by an exact version ceiling; the observed version remains evidence.
Moth does not make `omen all` a release gate: individual analyzer failures
retain explicit, per-capability verdicts instead of being hidden behind an
aggregate exit status.

The official installer writes the analyzer under
`${CODEX_HOME:-~/.codex}/skills/complexity-optimizer`; profile command entries
may use `~` or environment variables, and Moth expands them before execution.

`doctor` is kept as a compatibility alias, but `snapshot` is the primary
machine-readable entrypoint.

Snapshots include a stable `schema_version` and `generated_at` timestamp so
other models can consume them without guessing the payload shape.

Profiles may also declare typed guidance sources by logical ID:

```yaml
instruction_sources:
  sources:
    - id: mio
      kind: collaboration_lens
      provider: codex_skill
      ref: skill:mio
      activation: substantive_judgment
      requirement: required_when_active
      scope: user
      owner: user
      sensitivity: personal
      egress_policy: metadata_only
```

`moth inspect` resolves the registered Guidance DAG, normally Mio before
architect-controller, and returns one activation plan. Discovery,
applicability, receipt, and application remain separate states:
`UNAVAILABLE`, `INVALID`, or `DISCOVERED` never claim that an agent loaded the
Skill. The bundled execution bridge may return honest `SELF_ATTESTED` receipts
after the host reads each Skill; only host-native trusted telemetry may produce
`READY`. Absolute paths, Skill bodies, task text, amend trails, and raw receipt
working files are removed from public inspection output.

After executing the plan, a controller may pass a bounded
`moth.guidance-application.v1` JSON array with `--application-reports`.
Reports are bound to the run and current Skill digest and must name influenced
decisions, evidence, and any structured conflict resolution. Missing, stale,
invalid, or evidence-free reports remain `NOT_CLAIMED`; application evidence
does not turn executor self-attestation into host verification. The report's
`contract_id` and `loaded_at` must match its activation receipt, and every
evidence reference must resolve in the current project-model evidence registry.

The same `inspect` entry can render `moth.visual-document.v1` as a self-contained
HTML project atlas. The renderer consumes only that normalized document; it
does not call detectors or understand Omen, CodeGraph, Mio, Apple, Web, or any
other platform-specific contract. Missing To-Be architecture or business-flow
evidence is shown as undeclared/partial rather than invented.
Entity, relation, finding, and evidence rendering budgets live in
`visual_policy.yaml`; truncated views publish omitted counts instead of
silently expanding the DOM.

To initialize a repository and add it to the user-level project selector in
one idempotent Moth call, run inside that repository:

```bash
moth init --repo . --register-web
moth serve
```

Open the complete loopback URL printed by the command. Its fragment contains a
short-lived capability token; the browser removes the fragment immediately and
sends the token only in the `Authorization` header. The console lists only
projects declared in the YAML registry and requests a fresh inspection with:

```http
GET  /api/v1/projects
POST /api/v1/inspections
Content-Type: application/json

{"project_id":"moth"}
```

Web inspections always use `safe_view`: Moth runs its internal read-only
evidence collectors but disables repository assertion packs, profile-selected
external complexity commands, and configurable tool adapters. The response is
the portable `moth.inspection.v1` plus a validated
`moth.visual-document.v1`; raw repository paths, command streams, and private
Skill bodies are not API fields. The server binds only to `127.0.0.1`, requires
the capability token, validates Host and Origin, exposes no CORS permission,
and accepts only one inspection at a time.

The default user registry is `${MOTH_WEB_CONFIG}`, then
`${XDG_CONFIG_HOME}/moth/web.yaml`, then `~/.config/moth/web.yaml`.
`--web-config` and `moth serve --config` provide explicit overrides. The
committed `.moth/web.yaml` remains a portable example for this workspace.
Registration stores project metadata only; it never grants the browser extra
execution authority. An explicit project `profile` must stay inside that
repository and resolve back to the same canonical repository. Omitting
`profile` uses an ephemeral safe-view profile, which is useful when an external
repository's full profile contains executable or machine-private integrations.

Repositories may declare current and desired architecture in
`.moth/architecture.yaml`. The validated v2 project model owns canonical
entities, relations, business flows, and state machines; the HTML renderer
only projects that contract. Free-form documents are provenance, not an
automatic source of To-Be facts. Explicit `REQUIRED`/`FORBIDDEN` constraints
produce `CONFORMANT`, `DRIFT_DETECTED`, or `UNVERIFIABLE` according to the
declared As-Is coverage.

`inspect --change-phase pre|during|post --file <repo-relative-path>` attaches
`moth.change-safety.v1` to the same result. Repo-owned mandatory gates live in
`.moth/change-safety.yaml`; optional `--gate` flags are additive.
`--plan-only` runs read-only discovery but never executes gates. Affected tests
remain `PLANNED` until a repository gate provides execution evidence, and
Omen/complexity signals remain non-causal heuristics.

`sync` refreshes the repo's CodeGraph index first and then emits a payload with
both the sync result and the latest snapshot.

`affected` combines CodeGraph `affected --json` with the profile's
complexity command run against only the supplied changed files. It is intended
for pre-review scoping: which tests are likely affected, and whether the files
being changed introduce high-confidence complexity hotspots. An empty
`affectedTests` result without explicit provider completeness is
`UNKNOWN_EMPTY`, returns `WARN`, and exits `2`; it is not a green test result.

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

Most snapshot-style compatibility commands keep the legacy soft behavior:
`PASS` and `WARN` exit `0`, while `FAIL` exits non-zero. Change-safety results
use `GO=0`, `NO_GO=1`, and `CAUTION=2`. The legacy `affected` command also
returns `2` for `WARN` so unknown test coverage cannot appear green.

The maintained upstream policy and observed evidence live in
`docs/compatibility-matrix.yaml`; versions are observations, never exact
compatibility ceilings. Migration details are in `docs/migration-next.md`.

## Credits

Moth credits the workflow and tooling foundations of:

- CodeGraph
- Omen
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
