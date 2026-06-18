from moth.checks.coupling import impact
from moth.checks.coupling import orphans


def test_impact_explicit_file_path_avoids_broad_short_stem(tmp_path) -> None:
    repo = tmp_path
    (repo / "backend").mkdir()
    (repo / "backend/main.py").write_text("# self file should not count\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs/usage.md").write_text("Entrypoint: backend/main.py\n", encoding="utf-8")
    (repo / "README.md").write_text("The main idea is unrelated.\n", encoding="utf-8")

    result = impact(repo, "backend/main.py")

    assert result["query_terms"] == ["backend/main.py", "main.py"]
    assert result["total_files"] == 1
    assert result["categories"]["doc"][0][0] == "docs/usage.md"


def test_orphans_reports_missing_repo_local_moth_profile_paths(tmp_path) -> None:
    repo = tmp_path
    (repo / ".moth").mkdir()
    (repo / ".moth/profile.yaml").write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
                "complexity_baseline_path: missing/baseline.json",
                "evidence_paths:",
                "  agents: AGENTS.md",
                "assertion_packs:",
                "  - .moth/assertions/claims.yaml",
            ]
        ),
        encoding="utf-8",
    )

    result = orphans(repo)

    assert result["verdict"] == "FAIL"
    assert any("complexity_baseline_path" in item for item in result["fails"])
    assert any("evidence_paths.agents" in item for item in result["fails"])
    assert any("assertion_packs" in item for item in result["fails"])
