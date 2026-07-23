import re

from moth.html_report import render_html_report
from moth.visual_model import build_visual_model

from test_visual_model import inspection_fixture


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
