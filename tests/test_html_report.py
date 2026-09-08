import re
from pathlib import Path

from moth.html_report import _text, render_html_report
from moth.visual_model import build_visual_model
from moth.visual_policy import load_visual_policy

from test_visual_model import inspection_fixture

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_html_report_is_self_contained_accessible_and_escapes_content() -> None:
    inspection = inspection_fixture()
    inspection["snapshot"]["issues"] = [
        "unsafe <script>alert(1)</script>",
        "see https://example.test/reference",
    ]
    inspection["snapshot"]["project_model"]["project"]["name"] = "<Unsafe>"

    html = render_html_report(build_visual_model(inspection))

    assert html.startswith("<!doctype html>")
    assert '<html lang="zh-CN">' in html
    assert "<title>&lt;Unsafe&gt; - Moth</title>" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "https://example.test/reference" in html
    assert 'Content-Security-Policy' in html
    assert 'src="http' not in html
    assert 'href="http' not in html
    assert "@media (prefers-color-scheme: dark)" in html
    assert "@media (max-width: 767px)" in html
    assert "overflow-wrap: anywhere" in html
    assert "max-width: 100%; min-width: 0; overflow-x: auto" in html
    assert 'href="#main-content"' in html
    assert 'aria-label="项目视图"' in html


def test_html_report_allows_honest_empty_home_sections() -> None:
    inspection = inspection_fixture()
    inspection["status"] = "PASS"
    inspection["project_health"] = "PASS"
    inspection["context_readiness"] = "READY"
    inspection["snapshot"]["issues"] = []
    inspection["snapshot"]["warnings"] = []
    inspection["snapshot"]["dirty_worktree_count"] = 0
    inspection["snapshot"]["codegraph"]["index_up_to_date"] = True
    inspection["snapshot"]["complexity"]["summary"]["high_count"] = 0
    inspection["snapshot"]["project_model"]["coverage"]["warnings"] = []
    inspection["orchestration"]["decision_context"]["context_readiness"] = "READY"

    html = render_html_report(build_visual_model(inspection))

    assert "暂无有证据支持的优先动作" in html
    assert "暂无有证据支持的禁止项" in html


def test_html_report_contains_all_six_layer_anchors_and_is_deterministic() -> None:
    model = build_visual_model(inspection_fixture())

    first = render_html_report(model)
    second = render_html_report(model)

    assert first == second
    assert first.count('id="finding-guidance-context"') == 1
    for layer_id in (
        "overview",
        "architecture",
        "stack",
        "flows",
        "code",
        "evidence",
    ):
        assert f'id="layer-{layer_id}"' in first


def test_html_report_bounds_relations_and_evidence_for_adversarial_project() -> None:
    inspection = inspection_fixture()
    project_model = inspection["snapshot"]["project_model"]
    template = project_model["applications"][0]
    project_model["applications"] = []
    project_model["evidence"] = []
    for index in range(10_000):
        evidence_id = f"manifest:app-{index}.json"
        project_model["applications"].append(
            {
                **template,
                "id": f"application:{index}",
                "name": f"application-{index}",
                "evidence_ids": [evidence_id],
            }
        )
        project_model["evidence"].append(
            {
                "id": evidence_id,
                "kind": "manifest",
                "locator": f"app-{index}.json",
                "sha256": "sha256:" + f"{index:064x}"[-64:],
            }
        )

    model = build_visual_model(inspection)
    html = render_html_report(model)
    evidence_layer = next(
        layer for layer in model["layers"] if layer["id"] == "evidence"
    )

    assert evidence_layer["omitted"]["evidence"] >= 9_000
    assert html.count('class="evidence"') <= 500
    assert html.count("<li>") <= 500
    assert len(html.encode("utf-8")) < 500_000
    evidence_targets = set(re.findall(r'href="#(evidence-[^"]+)"', html))
    evidence_anchors = set(re.findall(r'id="(evidence-[^"]+)"', html))
    assert evidence_targets <= evidence_anchors


# J1: as_is.provenance 的来源拆分必须显式渲染, confirmed=0 也要写出来 —— 那恰恰是
# 最该让人警醒的数字, 不能因为是 0 就被 `if provenance.get("confirmed")` 这类写法悄悄吞掉。


def test_html_report_shows_zero_confirmed_provenance_explicitly() -> None:
    model = build_visual_model(inspection_fixture())
    as_is = model["architecture"]["as_is"]
    assert as_is["provenance"] == {"detected": 0, "declared": 1, "confirmed": 0}

    html = render_html_report(model)

    assert "0 个被独立证实" in html
    assert "扫描到" in html
    assert "只来自声明文件" in html


def test_html_report_omits_provenance_line_when_key_is_absent() -> None:
    """to_be 从不带 provenance 键 (未声明目标架构) —— 这一行不该被臆造出来。"""
    model = build_visual_model(inspection_fixture())
    assert "provenance" not in model["architecture"]["to_be"]

    html = render_html_report(model)

    # 基线 fixture 只有 as_is 会产出来源拆分, to_be 没有 provenance 键就不该渲染这一行。
    # (用带 class 的完整前缀匹配, 避免撞上术语表里 OBSERVED 词条本身也提到"来源拆分"。)
    assert html.count('<p class="meta-note">来源拆分') == 1


# J2: complete=false 要显式露面, key 不存在不能被当成 false, complete=true 也不该
# 被误显示成"不完整"。三种状态要分开验。


def test_html_report_shows_incomplete_architecture_note_when_complete_is_false() -> None:
    inspection = inspection_fixture()
    inspection["snapshot"]["project_model"]["architecture"] = {
        "current": {
            "state": "OBSERVED",
            "complete": False,
            "entity_ids": ["python-console:sample"],
            "relation_ids": [],
            "evidence_ids": ["manifest:pyproject.toml"],
        },
    }
    model = build_visual_model(inspection)
    assert model["architecture"]["as_is"]["complete"] is False

    html = render_html_report(model)

    assert "这份架构声明自称不完整，未画出的组件不等于不存在。" in html


def test_html_report_omits_incomplete_note_when_complete_is_true() -> None:
    inspection = inspection_fixture()
    inspection["snapshot"]["project_model"]["architecture"] = {
        "current": {
            "state": "OBSERVED",
            "complete": True,
            "entity_ids": ["python-console:sample"],
            "relation_ids": [],
            "evidence_ids": ["manifest:pyproject.toml"],
        },
    }
    model = build_visual_model(inspection)
    assert model["architecture"]["as_is"]["complete"] is True

    html = render_html_report(model)

    assert "这份架构声明自称不完整，未画出的组件不等于不存在。" not in html


def test_html_report_omits_incomplete_note_when_complete_key_is_absent() -> None:
    model = build_visual_model(inspection_fixture())
    assert "complete" not in model["architecture"]["as_is"]

    html = render_html_report(model)

    assert "这份架构声明自称不完整，未画出的组件不等于不存在。" not in html


# J3: 显示 source.generated_at, 且渲染器保持纯函数 —— 不执行 git 去找 commit。
# document 本身不携带任何 commit/版本字段 (source 的 schema 是
# additionalProperties: false, 只有 inspection_digest 和 generated_at), 所以报告里
# 该老实说"这份 document 没有这个字段", 而不是假装去查。


def test_html_report_shows_generated_at_and_says_document_has_no_commit_field() -> None:
    inspection = inspection_fixture()
    inspection["snapshot"]["generated_at"] = "2026-09-07T01:02:03Z"
    model = build_visual_model(inspection)
    assert model["source"]["generated_at"] == "2026-09-07T01:02:03Z"

    html = render_html_report(model)

    assert "2026-09-07T01:02:03Z" in html
    assert "commit" in html
    assert "未携带" in html


def test_html_report_generated_at_note_survives_missing_value() -> None:
    model = build_visual_model(inspection_fixture())
    assert model["source"]["generated_at"] is None

    html = render_html_report(model)

    assert "commit" in html
    assert "未携带" in html


# J4: 术语表常驻 (单一真相源) —— 从 visual_policy.yaml 的 terms 段渲染成 <dl>,
# 不是 title 属性, 也不是 hover。防漂移: app.js 的 TERMS 键集合必须和
# visual_policy.yaml 的 terms 键集合完全一致。


def test_html_report_renders_terms_as_a_permanent_dl_not_hover_only() -> None:
    model = build_visual_model(inspection_fixture())
    terms = load_visual_policy()["terms"]
    assert terms, "visual policy 里没有 terms —— 先在 yaml 里加这一段"

    html = render_html_report(model)

    assert '<dl class="glossary-list">' in html
    assert ' title="' not in html
    for key, value in terms.items():
        assert f"<dt>{key}</dt>" in html
        assert _text(value) in html


def test_terms_glossary_matches_app_js_terms_key_for_key() -> None:
    """防漂移: 术语表现在有两份 (app.js 的 TERMS, visual_policy.yaml 的 terms),
    任何一边加了词而另一边没加, 这个用例必须报红。"""
    app_js = (PROJECT_ROOT / "src" / "moth" / "web_assets" / "app.js").read_text(
        encoding="utf-8"
    )
    body = app_js.split("const TERMS = {", 1)[1].split("};", 1)[0]
    explained = set(re.findall(r"^\s*([A-Z][A-Z_]+)\s*:", body, flags=re.MULTILINE))
    assert explained, "app.js 的术语表没解析出任何词 —— 先修这个用例, 别让它假绿"

    policy_terms = set(load_visual_policy()["terms"].keys())

    assert policy_terms == explained


# J5: 关系列表标注来源 —— CONFIRMED/DETECTED/DECLARED 各自的大白话, 没有 source
# 字段的关系不标注 (不要默认成 DECLARED)。


def _fixture_with_relation_sources() -> dict:
    inspection = inspection_fixture()
    project_model = inspection["snapshot"]["project_model"]
    project_model["modules"] = [
        {
            "id": f"module:{name}",
            "kind": "module",
            "name": f"Module {name.upper()}",
            "responsibility": f"Does {name}.",
            "evidence_ids": ["manifest:pyproject.toml"],
        }
        for name in ("a", "b", "c", "d")
    ]
    project_model["relations"] = [
        {
            "id": "relation:a-b",
            "kind": "calls",
            "source_id": "module:a",
            "target_id": "module:b",
            "label": "调用",
            "evidence_ids": ["manifest:pyproject.toml"],
            "source": "DETECTED",
        },
        {
            "id": "relation:b-c",
            "kind": "calls",
            "source_id": "module:b",
            "target_id": "module:c",
            "label": "调用",
            "evidence_ids": ["manifest:pyproject.toml"],
            "source": "CONFIRMED",
        },
        {
            "id": "relation:c-d",
            "kind": "calls",
            "source_id": "module:c",
            "target_id": "module:d",
            "label": "调用",
            "evidence_ids": ["manifest:pyproject.toml"],
            "source": "DECLARED",
        },
        {
            "id": "relation:d-a",
            "kind": "calls",
            "source_id": "module:d",
            "target_id": "module:a",
            "label": "调用",
            "evidence_ids": ["manifest:pyproject.toml"],
        },
    ]
    return inspection


def test_html_report_labels_relation_source_confirmed_detected_declared() -> None:
    model = build_visual_model(_fixture_with_relation_sources())
    assert model["relations"]["relation:a-b"]["source"] == "DETECTED"
    assert model["relations"]["relation:b-c"]["source"] == "CONFIRMED"
    assert model["relations"]["relation:c-d"]["source"] == "DECLARED"
    assert "source" not in model["relations"]["relation:d-a"]

    html = render_html_report(model)

    assert "DETECTED · 代码里扫描到" in html
    assert "CONFIRMED · 声明且被代码证实" in html
    assert "DECLARED · 仅来自声明文件" in html
    # relation:d-a 没有 source 字段, 不该被标注 —— 只应该出现 3 个标注, 不是 4 个。
    assert html.count('class="relation-source"') == 3


# N4: CONFIRMED/DETECTED 的关系后面附证据位置(path:line), 预算与 N2 相同 —— 已经
# 在 visual_model 里截断, html_report 只负责把截断后的坐标显示出来, 连同截断计数,
# 不能悄悄少显示。DECLARED 关系没有坐标可给, 不该出现这个后缀。


def test_html_report_shows_evidence_locations_for_confirmed_and_detected_relations() -> None:
    from moth.visual_policy import load_visual_policy

    inspection = _fixture_with_relation_sources()
    project_model = inspection["snapshot"]["project_model"]
    limit = int(load_visual_policy()["limits"]["verification_locations_per_relation"])
    project_model["relations"][0]["verification"] = {  # relation:a-b, source=DETECTED
        "status": "CONFIRMED_BY_IMPORT",
        "reason": "confirmed_by_import_edge",
        "locations": [
            {"path": f"src/moth/f{i}.py", "line": i + 1} for i in range(limit + 1)
        ],
    }
    project_model["relations"][1]["verification"] = {  # relation:b-c, source=CONFIRMED
        "status": "CONFIRMED_BY_IMPORT",
        "reason": "confirmed_by_import_edge",
        "locations": [{"path": "src/moth/cli.py", "line": 19}],
    }
    project_model["relations"][2]["verification"] = {  # relation:c-d, source=DECLARED
        "status": "NOT_OBSERVED",
        "reason": "not_observed_in_static_imports",
    }

    model = build_visual_model(inspection)
    html = render_html_report(model)

    assert "src/moth/cli.py:19" in html
    assert "src/moth/f0.py:1" in html
    # limit+1 条位置只留下 limit 条, 剩下 1 条必须显式说出来。
    assert "还有 1 处未显示" in html
    # 只有 relation:a-b / relation:b-c 有坐标; relation:c-d 是 DECLARED + NOT_OBSERVED,
    # 没有坐标可给, 不该出现这个 span。
    assert html.count('class="relation-evidence"') == 2
