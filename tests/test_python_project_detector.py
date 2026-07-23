from moth.detectors.python_project import detect_python_project


def test_missing_pyproject_reports_unknown_coverage_without_guessing(tmp_path) -> None:
    result = detect_python_project(tmp_path)

    assert result["detector"] == {"id": "python-project", "state": "NOT_DETECTED"}
    assert result["project"] is None
    assert result["applications"] == []
    assert result["runtimes"] == []
    assert result["modules"] == []
    assert result["issues"] == []
    assert result["warnings"] == [
        "python project coverage unavailable: pyproject.toml not found"
    ]
    assert str(tmp_path) not in repr(result)


def test_malformed_pyproject_is_explicitly_invalid_without_guessing_modules(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project\nname = 'broken'", encoding="utf-8")

    result = detect_python_project(tmp_path)

    assert result["detector"] == {"id": "python-project", "state": "INVALID"}
    assert result["project"] is None
    assert result["applications"] == []
    assert result["runtimes"] == []
    assert result["modules"] == []
    assert result["evidence"] == []
    assert result["warnings"] == []
    assert result["issues"] == ["python project manifest invalid: pyproject.toml is malformed"]
    assert str(tmp_path) not in repr(result)


def test_pyproject_without_project_identity_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['setuptools']\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"] == {"id": "python-project", "state": "INVALID"}
    assert result["project"] is None
    assert result["modules"] == []
    assert result["issues"] == [
        "python project manifest invalid: pyproject.toml requires project.name"
    ]


def test_non_mapping_console_scripts_are_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nscripts = ['not-a-mapping']\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["applications"] == []
    assert result["modules"] == []
    assert result["issues"] == [
        "python project manifest invalid: project.scripts must be a mapping"
    ]


def test_non_list_dependencies_are_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\ndependencies = 'requests'\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["runtimes"] == []
    assert result["modules"] == []
    assert result["issues"] == [
        "python project manifest invalid: project.dependencies must be a list"
    ]


def test_missing_python_constraint_is_reported_as_partial_coverage(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\ndependencies = []\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "DETECTED"
    assert result["runtimes"][0]["constraint"] is None
    assert result["issues"] == []
    assert result["warnings"] == [
        "python runtime coverage partial: project.requires-python is missing"
    ]


def test_non_string_console_entrypoint_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\n[project.scripts]\nsample = 7\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["applications"] == []
    assert result["issues"] == [
        "python project manifest invalid: project.scripts values must be strings"
    ]


def test_non_string_python_constraint_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nrequires-python = 311\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["runtimes"] == []
    assert result["issues"] == [
        "python project manifest invalid: project.requires-python must be a string"
    ]


def test_non_string_project_version_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\nversion = 1\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["project"] is None
    assert result["issues"] == [
        "python project manifest invalid: project.version must be a string"
    ]


def test_non_string_project_description_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\ndescription = ['not', 'text']\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["project"] is None
    assert result["issues"] == [
        "python project manifest invalid: project.description must be a string"
    ]


def test_empty_project_name_is_invalid(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = ''\n",
        encoding="utf-8",
    )

    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "INVALID"
    assert result["project"] is None
    assert result["issues"] == [
        "python project manifest invalid: pyproject.toml requires project.name"
    ]
