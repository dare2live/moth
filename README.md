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
moth sync --repo /Users/dp/Documents/M/stock/chunkymonkey --profile chunkymonkey --format json
```

`doctor` is kept as a compatibility alias, but `snapshot` is the primary
machine-readable entrypoint.

Snapshots include a stable `schema_version` and `generated_at` timestamp so
other models can consume them without guessing the payload shape.

`sync` refreshes the repo's CodeGraph index first and then emits a payload with
both the sync result and the latest snapshot.

`profiles` lists the installed profile registry so a fresh session can discover
what Moth can inspect without opening YAML files by hand.

Exit codes are intentionally soft: `PASS` and `WARN` both exit `0`, and only
`FAIL` exits non-zero. Warnings are carried in the JSON payload.

## Credits

Moth credits the workflow and tooling foundations of:

- CodeGraph
- complexity-optimizer
- ChunkyMonkey
- LifeHack governance patterns

See `NOTICE.md` for the maintained attribution list.
