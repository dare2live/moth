"""Dependency-free HTML projection of ``moth.visual-document.v1``."""

from __future__ import annotations

from html import escape
from typing import Any


def _text(value: Any) -> str:
    return escape(str(value or "").replace("—", "-").replace("–", "-"))


def _status_class(value: Any) -> str:
    normalized = str(value or "UNKNOWN").upper()
    if normalized in {"PASS", "READY", "COMPLETE", "OBSERVED", "DECLARED", "AVAILABLE"}:
        return "good"
    if normalized in {"FAIL", "BLOCKED", "INVALID"}:
        return "bad"
    return "warn"


def _render_entity(entity: dict[str, Any]) -> str:
    attributes = entity.get("attributes") or {}
    details = "".join(
        f"<dt>{_text(key)}</dt><dd>{_text(value)}</dd>"
        for key, value in sorted(attributes.items())
        if value is not None
    )
    return (
        '<article class="entity">'
        '<div class="entity-heading">'
        f"<h4>{_text(entity.get('name'))}</h4>"
        f'<span class="state {_status_class(entity.get("status"))}">{_text(entity.get("status"))}</span>'
        "</div>"
        f'<p class="kind">{_text(entity.get("kind"))}</p>'
        f"<p>{_text(entity.get('summary'))}</p>"
        + (f'<dl class="attributes">{details}</dl>' if details else "")
        + "</article>"
    )


def _render_relation(
    relation: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> str:
    source = entities.get(str(relation.get("source_id"))) or {}
    target = entities.get(str(relation.get("target_id"))) or {}
    return (
        "<li>"
        f"<strong>{_text(source.get('name') or relation.get('source_id'))}</strong>"
        f" <span>{_text(relation.get('label'))}</span> "
        f"<strong>{_text(target.get('name') or relation.get('target_id'))}</strong>"
        "</li>"
    )


def _render_finding(finding: dict[str, Any]) -> str:
    impacts = "".join(f"<li>{_text(item)}</li>" for item in finding.get("impact") or [])
    avoid = "".join(f"<li>{_text(item)}</li>" for item in finding.get("avoid") or [])
    evidence_links = ", ".join(
        f'<a href="#evidence-{_text(evidence_id)}">{_text(evidence_id)}</a>'
        for evidence_id in finding.get("evidence_ids") or []
    )
    return (
        '<details class="finding">'
        "<summary>"
        f'<span class="severity {_status_class(finding.get("severity"))}">{_text(finding.get("severity"))}</span>'
        f"{_text(finding.get('title'))}</summary>"
        '<dl class="finding-grid">'
        f"<div><dt>它在哪里</dt><dd>{_text(finding.get('location'))}</dd></div>"
        f"<div><dt>它负责什么</dt><dd>{_text(finding.get('responsibility'))}</dd></div>"
        f"<div><dt>为什么值得注意</dt><dd>{_text(finding.get('why'))}</dd></div>"
        f"<div><dt>证据是什么</dt><dd>{evidence_links}</dd></div>"
        f"<div><dt>可能造成什么</dt><dd><ul>{impacts}</ul></dd></div>"
        f"<div><dt>最安全的第一步</dt><dd>{_text(finding.get('safest_step'))}</dd></div>"
        f"<div><dt>暂时不要做什么</dt><dd><ul>{avoid}</ul></dd></div>"
        "</dl></details>"
    )


def _render_home_findings(
    ids: list[str],
    findings: dict[str, dict[str, Any]],
) -> str:
    if not ids:
        return '<p class="empty">暂无有证据支持的优先动作。</p>'
    return "".join(
        '<article class="home-item">'
        f"<h3>{_text(findings[finding_id].get('title'))}</h3>"
        f"<p>{_text(findings[finding_id].get('safest_step'))}</p>"
        f'<a href="#finding-{_text(finding_id)}">查看证据</a>'
        "</article>"
        for finding_id in ids
        if finding_id in findings
    )


def _render_home_actions(
    ids: list[str],
    actions: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
) -> str:
    if not ids:
        return '<p class="empty">暂无有证据支持的禁止项。</p>'
    chunks = []
    for action_id in ids:
        action = actions.get(action_id)
        if not action:
            continue
        finding_id = str(action.get("basis_finding_id") or "")
        finding = findings.get(finding_id) or {}
        chunks.append(
            '<article class="home-item">'
            f"<h3>{_text(action.get('title'))}</h3>"
            f"<p>依据: {_text(finding.get('why'))}</p>"
            f'<a href="#finding-{_text(finding_id)}">查看证据</a>'
            "</article>"
        )
    return "".join(chunks)


def _render_architecture(
    architecture: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    relations: dict[str, dict[str, Any]],
) -> str:
    def side(title: str, payload: dict[str, Any]) -> str:
        entity_html = "".join(
            _render_entity(entities[entity_id])
            for entity_id in payload.get("entity_ids") or []
            if entity_id in entities
        )
        relation_html = "".join(
            _render_relation(relations[relation_id], entities)
            for relation_id in payload.get("relation_ids") or []
            if relation_id in relations
        )
        content = entity_html or '<p class="empty">暂无已声明内容。</p>'
        omitted = payload.get("omitted") or {}
        omitted_text = (
            f'<p class="omitted">已聚合隐藏实体 {int(omitted.get("entities") or 0)}，'
            f'关系 {int(omitted.get("relations") or 0)}。</p>'
            if omitted.get("entities") or omitted.get("relations")
            else ""
        )
        return (
            '<section class="truth-panel">'
            '<div class="panel-heading">'
            f"<h3>{_text(title)}</h3>"
            f'<span class="state {_status_class(payload.get("state"))}">{_text(payload.get("state"))}</span>'
            "</div>"
            f'<div class="entity-list">{content}</div>'
            + (f'<ul class="relations">{relation_html}</ul>' if relation_html else "")
            + omitted_text
            + "</section>"
        )

    return (
        '<div class="truth-columns">'
        f"{side('当前架构 As-Is', architecture.get('as_is') or {})}"
        f"{side('期望架构 To-Be', architecture.get('to_be') or {})}"
        "</div>"
    )


def _render_evidence(
    evidence: dict[str, dict[str, Any]],
    evidence_ids: list[str],
) -> str:
    visible = [
        (evidence_id, evidence[evidence_id])
        for evidence_id in evidence_ids
        if evidence_id in evidence
    ]
    if not visible:
        return '<p class="empty">暂无可公开证据。</p>'
    return '<div class="evidence-list">' + "".join(
        '<article class="evidence" '
        f'id="evidence-{_text(evidence_id)}">'
        f"<h4>{_text(item.get('locator'))}</h4>"
        f"<p>{_text(item.get('summary'))}</p>"
        f"<code>{_text(evidence_id)}</code>"
        "</article>"
        for evidence_id, item in visible
    ) + "</div>"


def _render_layers(model: dict[str, Any]) -> str:
    entities = model.get("entities") or {}
    relations = model.get("relations") or {}
    findings = model.get("findings") or {}
    chunks = []
    rendered_finding_ids: set[str] = set()
    for layer in model.get("layers") or []:
        layer_id = str(layer.get("id") or "")
        entity_html = "".join(
            _render_entity(entities[entity_id])
            for entity_id in layer.get("entity_ids") or []
            if entity_id in entities
        )
        relation_html = "".join(
            _render_relation(relations[relation_id], entities)
            for relation_id in layer.get("relation_ids") or []
            if relation_id in relations
        )
        finding_chunks = []
        for finding_id in layer.get("finding_ids") or []:
            if finding_id not in findings:
                continue
            if finding_id in rendered_finding_ids:
                finding_chunks.append(
                    f'<p><a href="#finding-{_text(finding_id)}">'
                    f"查看关联问题: {_text(findings[finding_id].get('title'))}</a></p>"
                )
                continue
            rendered_finding_ids.add(finding_id)
            finding_chunks.append(
                f'<div id="finding-{_text(finding_id)}">'
                f"{_render_finding(findings[finding_id])}</div>"
            )
        finding_html = "".join(finding_chunks)
        omitted = layer.get("omitted") or {}
        omitted_text = (
            f'<p class="omitted">已聚合隐藏实体 {int(omitted.get("entities") or 0)}，'
            f'关系 {int(omitted.get("relations") or 0)}，'
            f'问题 {int(omitted.get("findings") or 0)}，'
            f'证据 {int(omitted.get("evidence") or 0)}。</p>'
            if (
                omitted.get("entities")
                or omitted.get("relations")
                or omitted.get("findings")
                or omitted.get("evidence")
            )
            else ""
        )
        special = ""
        if layer_id == "architecture":
            special = _render_architecture(
                model.get("architecture") or {},
                entities,
                relations,
            )
            entity_html = ""
            relation_html = ""
        if layer_id == "evidence":
            special += _render_evidence(
                model.get("evidence") or {},
                layer.get("evidence_ids") or [],
            )
        content = (
            special
            + (f'<div class="entity-list">{entity_html}</div>' if entity_html else "")
            + (f'<ul class="relations">{relation_html}</ul>' if relation_html else "")
            + finding_html
            + omitted_text
        )
        if not content:
            content = '<p class="empty">本层尚无可验证内容，不能据此判断为空。</p>'
        chunks.append(
            f'<section class="layer" id="layer-{_text(layer_id)}">'
            '<div class="layer-heading">'
            f"<h2>{_text(layer.get('label'))}</h2>"
            f'<span class="state {_status_class(layer.get("availability"))}">{_text(layer.get("availability"))}</span>'
            f"<p>{_text(layer.get('summary'))}</p>"
            "</div>"
            f"{content}</section>"
        )
    return "".join(chunks)


def render_html_report(model: dict[str, Any]) -> str:
    identity = model.get("identity") or {}
    status = model.get("status") or {}
    home = model.get("home") or {}
    navigation = model.get("navigation") or {}
    findings = model.get("findings") or {}
    actions = model.get("actions") or {}
    layer_nav = "".join(
        f'<a href="#layer-{_text(item.get("id"))}">{_text(item.get("label"))}</a>'
        for item in navigation.get("layers") or []
    )
    viewpoint_nav = "".join(
        f'<a href="#layer-{_text((item.get("layer_ids") or ["overview"])[0])}">'
        f"{_text(item.get('label'))}</a>"
        for item in navigation.get("viewpoints") or []
    )
    status_rows = "".join(
        f'<div><span>{label}</span><strong class="{_status_class(value)}">{_text(value)}</strong></div>'
        for label, value in (
            ("整体状态", status.get("value")),
            ("项目健康", status.get("project_health")),
            ("协作上下文", status.get("context_readiness")),
        )
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_text(identity.get("name"))} - Moth</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #f4f6f8; --surface: #fbfcfd; --surface-2: #edf1f4;
  --text: #18202a; --muted: #596575; --line: #cbd2da;
  --accent: #176b57; --bad: #a33a32; --warn: #8b5b12;
  --radius: 12px; --shadow: 0 12px 34px rgba(40,56,72,.08);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #11161d; --surface: #171e27; --surface-2: #202a35;
    --text: #e5eaf0; --muted: #aab4c0; --line: #394554;
    --accent: #65c2a7; --bad: #f09288; --warn: #e7b45e; --shadow: none;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.55; overflow-wrap: anywhere;
}}
a {{ color: var(--accent); }}
.skip {{ position: absolute; left: -999px; top: 8px; }}
.skip:focus {{ left: 12px; z-index: 4; padding: 8px 12px; background: var(--surface); }}
.shell {{ width: min(1440px, 100%); margin: 0 auto; padding: 24px; }}
.topbar {{
  display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 24px;
  align-items: end; padding: 28px 0 24px; border-bottom: 1px solid var(--line);
}}
.brand {{ color: var(--accent); font-weight: 750; letter-spacing: -.02em; }}
h1 {{ margin: 8px 0 6px; font-size: clamp(2rem,5vw,4.7rem); line-height: .98; letter-spacing: -.055em; }}
.lede {{ margin: 0; max-width: 68ch; color: var(--muted); }}
.status-grid {{ min-width: 280px; display: grid; gap: 8px; }}
.status-grid div {{ display: flex; justify-content: space-between; gap: 28px; }}
.status-grid span, .kind, .empty, .omitted {{ color: var(--muted); }}
.good {{ color: var(--accent); }} .warn {{ color: var(--warn); }} .bad {{ color: var(--bad); }}
.view-nav, .layer-nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.view-nav {{ padding: 18px 0 8px; }}
.layer-nav {{ position: sticky; top: 0; z-index: 2; padding: 10px 0 18px; background: var(--bg); }}
.view-nav a, .layer-nav a {{
  color: var(--text); text-decoration: none; border: 1px solid var(--line);
  border-radius: 999px; padding: 9px 12px; background: var(--surface);
}}
.view-nav a:hover, .layer-nav a:hover, .view-nav a:focus, .layer-nav a:focus {{
  border-color: var(--accent); outline: 2px solid transparent;
}}
.home-grid {{ display: grid; grid-template-columns: 1.25fr .75fr; gap: 18px; margin: 26px 0 36px; }}
.section-block, .truth-panel {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 22px;
}}
.section-block h2, .layer h2 {{ margin: 0 0 6px; letter-spacing: -.025em; }}
.home-item {{ padding: 15px 0; border-bottom: 1px solid var(--line); }}
.home-item:last-child {{ border-bottom: 0; }}
.home-item h3, .home-item p {{ margin: 0 0 6px; }}
.layer {{ scroll-margin-top: 72px; padding: 54px 0; border-top: 1px solid var(--line); }}
.layer-heading {{ max-width: 68ch; margin-bottom: 22px; }}
.layer-heading p {{ color: var(--muted); margin: 4px 0 0; }}
.state, .severity {{ font: 700 .72rem ui-monospace, monospace; text-transform: uppercase; }}
.entity-list, .evidence-list {{ display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }}
.entity, .evidence {{
  min-width: 0; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 15px; box-shadow: var(--shadow);
}}
.entity-heading, .panel-heading {{ display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }}
.entity h4, .evidence h4, .panel-heading h3 {{ margin: 0; }}
.entity p, .evidence p {{ margin: 6px 0; }}
.attributes, .finding-grid {{ display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }}
.attributes dt, .finding-grid dt {{ color: var(--muted); font-size: .78rem; }}
.attributes dd, .finding-grid dd {{ margin: 0; overflow-wrap: anywhere; }}
.relations {{ padding: 14px 18px 0 34px; }}
.relations span {{ color: var(--muted); margin: 0 6px; }}
.finding {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); margin: 10px 0;
}}
.finding summary {{ cursor: pointer; padding: 14px 16px; font-weight: 700; }}
.severity {{ margin-right: 10px; }}
.finding-grid {{ padding: 0 16px 16px; }}
.finding-grid ul {{ margin: 0; padding-left: 18px; }}
.truth-columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
.truth-panel {{ box-shadow: var(--shadow); }}
code {{ overflow-wrap: anywhere; color: var(--accent); }}
footer {{ padding: 30px 0 48px; color: var(--muted); border-top: 1px solid var(--line); }}
@media (max-width: 767px) {{
  .shell {{ padding: 16px; }}
  .topbar, .home-grid, .truth-columns, .entity-list, .evidence-list,
  .attributes, .finding-grid {{ grid-template-columns: 1fr; }}
  .status-grid {{ min-width: 0; }}
  .layer-nav {{ max-width: 100%; min-width: 0; overflow-x: auto; flex-wrap: nowrap; }}
  .layer-nav a {{ white-space: nowrap; }}
  .layer {{ padding: 38px 0; }}
}}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
</style>
</head>
<body>
<a class="skip" href="#main-content">跳到主要内容</a>
<div class="shell">
  <header class="topbar">
    <div>
      <div class="brand">Moth project atlas</div>
      <h1>{_text(identity.get("name"))}</h1>
      <p class="lede">{_text(identity.get("description") or "暂无可验证的项目说明。")}</p>
    </div>
    <div class="status-grid" aria-label="当前状态">{status_rows}</div>
  </header>
  <nav class="view-nav" aria-label="项目视图">{viewpoint_nav}</nav>
  <nav class="layer-nav" aria-label="理解层级">{layer_nav}</nav>
  <main id="main-content">
    <div class="home-grid">
      <section class="section-block">
        <h2>当前最重要的事</h2>
        {_render_home_findings(home.get("priority_finding_ids") or [], findings)}
      </section>
      <section class="section-block">
        <h2>暂时不要做</h2>
        {_render_home_actions(home.get("avoid_action_ids") or [], actions, findings)}
      </section>
    </div>
    {_render_layers(model)}
  </main>
  <footer>所有结论都应回到证据。未声明不等于不存在。</footer>
</div>
</body>
</html>
"""
