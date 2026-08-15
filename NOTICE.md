# Notices and attribution

This project is a derived tool that orchestrates audits and reports.

## Attributions

- **CodeGraph** (<https://github.com/colbymchenry/codegraph>, npm
  `@colbymchenry/codegraph`): structural graphing and dependency visibility.
  Moth calls its CLI; no source is vendored here.
  Version check 2026-08-14: upstream newest tag `v1.5.0`, `main` package.json
  `1.5.0`, npm dist-tag latest `1.5.0`, locally installed `1.5.0` —— 四处一致,
  当前无可升版本。
- **Omen (`panbanda/omen`)**: multi-language hotspot, change-risk, and diff
  analysis. Moth currently treats its CLI as an optional external capability;
  no Omen source code is vendored here.
- **complexity-optimizer** (<https://github.com/Kappaemme-git/codex-complexity-optimizer>):
  complexity hotspot analysis and review patterns. Moth's built-in
  `moth.analyzers.complexity` is a **derived and extended** implementation, not a copy.
  Divergence check 2026-08-14 (**该方向的"升级"是破坏性的, 勿照上游覆盖**):
  upstream `main` 只有一个 commit, `analyze_complexity.py` 377 行, package.json `0.1.1`;
  本机 skill 511 行 / 自称 `1.0.1`, 且其 `.upstream-commit` 指向的 sha 在上游**不存在**
  (GitHub API 422) —— 即本地不是落后而是已分叉领先。
  实测 8 项能力 (ListComp/SetComp/DictComp/GeneratorExp 推导式嵌套、`_track_assignment`
  赋值追踪、`_constant_time_lookup` 常数时间查找、`_is_query_call` N+1 查询、`receiver_name`)
  在上游 **全无**、本机 skill 与 Moth 内建 **全有**; Moth 内建 639 行 > skill 511 行 > 上游 377 行。
  照上游覆盖会删掉 N+1 检测与推导式分析并把版本从 1.0.1 降到 0.1.1。
- **ChunkyMonkey**: controller-led audit workflow, profile-driven startup
  contracts, and evidence-first reporting conventions
- **LifeHack**: cross-repo governance and truth-source discipline

These projects are credited as sources of workflow and tooling ideas. Their
respective licenses and upstream policies continue to apply to their own code
and documentation.
