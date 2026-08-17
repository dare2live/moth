from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from socketserver import ThreadingMixIn
from threading import BoundedSemaphore
from wsgiref.util import setup_testing_defaults

import json
import os
import subprocess
import pytest
import yaml
from jsonschema import Draft202012Validator

from moth.profiles.loader import RepoProfile
from moth.report import build_report
from moth.cli import main
from moth.inspection import sanitize_public_text
from moth.web_app import create_web_application
from moth.web_config import load_web_console_config
from moth.web_registry import register_web_project
from moth.web_server import BoundedWSGIServer, serve_web_console


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_web_project_view_v1_keeps_profile_state_optional() -> None:
    schema = json.loads(
        (
            PROJECT_ROOT
            / "src"
            / "moth"
            / "schemas"
            / "moth.web-project-view.schema.json"
        ).read_text(encoding="utf-8")
    )
    payload = {
        "schema_version": "moth.web-project-view.v1",
        "project": {"id": "repo", "name": "Repo", "description": ""},
        "execution_policy": "safe_view",
        "inspection": {},
        "visual_document": {},
    }

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def _call_wsgi(
    app,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    host: str = "127.0.0.1:8765",
    origin: str | None = None,
    payload: dict | None = None,
) -> tuple[str, dict, bytes]:
    environ: dict = {}
    setup_testing_defaults(environ)
    route, _, query = path.partition("?")
    environ["PATH_INFO"] = route
    environ["QUERY_STRING"] = query
    environ["REQUEST_METHOD"] = method
    environ["HTTP_HOST"] = host
    if token is not None:
        environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    if payload is not None:
        raw = json.dumps(payload).encode()
        environ["CONTENT_TYPE"] = "application/json"
        environ["CONTENT_LENGTH"] = str(len(raw))
        environ["wsgi.input"] = __import__("io").BytesIO(raw)
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def test_web_config_resolves_only_declared_projects(tmp_path) -> None:
    repo = tmp_path / "project-a"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / ".moth" / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [
                {
                    "id": "project-a",
                    "name": "Project A",
                    "repo": "../project-a",
                    "description": "Primary fixture",
                }
            ],
        },
    )

    config = load_web_console_config(config_path)

    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert [project.id for project in config.projects] == ["project-a"]
    assert config.projects[0].repo_path == repo.resolve()
    assert config.projects[0].public_metadata() == {
        "id": "project-a",
        "name": "Project A",
        "description": "Primary fixture",
        "profile_state": "ephemeral",
    }


def test_web_config_uses_valid_local_profile_and_marks_invalid_profile(tmp_path) -> None:
    configured = tmp_path / "configured"
    invalid = tmp_path / "invalid"
    configured_profile = configured / ".moth" / "profile.yaml"
    invalid_profile = invalid / ".moth" / "profile.yaml"
    configured_profile.parent.mkdir(parents=True)
    invalid_profile.parent.mkdir(parents=True)
    configured_profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: configured",
                "repo_path: .",
                "codegraph_root: .",
                "instruction_sources:",
                "  sources: []",
            ]
        ),
        encoding="utf-8",
    )
    invalid_profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: invalid",
                "repo_path: .",
                "codegraph_root: .",
                "evidence_paths:",
                "  escaped: /tmp/outside.md",
                "instruction_sources:",
                "  sources: []",
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(
        tmp_path / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [
                {"id": "configured", "name": "Configured", "repo": "configured"},
                {"id": "invalid", "name": "Invalid", "repo": "invalid"},
            ],
        },
    )

    config = load_web_console_config(config_path)

    assert config.projects[0].profile.kind == "profile"
    assert config.projects[0].profile_state == "configured"
    assert config.projects[1].profile.kind == "ephemeral_profile"
    assert config.projects[1].profile_state == "partial"


def test_web_config_rejects_duplicate_ids_and_non_loopback_bind(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base = {
        "schema_version": "moth.web-console.v1",
        "server": {"host": "127.0.0.1", "port": 8765},
        "projects": [
            {"id": "same", "name": "One", "repo": "../repo"},
            {"id": "same", "name": "Two", "repo": "../repo"},
        ],
    }
    duplicate = _write_config(tmp_path / ".moth" / "duplicate.yaml", base)
    with pytest.raises(ValueError, match="unique"):
        load_web_console_config(duplicate)

    base["server"]["host"] = "0.0.0.0"
    base["projects"] = [{"id": "repo", "name": "Repo", "repo": "../repo"}]
    exposed = _write_config(tmp_path / ".moth" / "exposed.yaml", base)
    with pytest.raises(ValueError, match="loopback"):
        load_web_console_config(exposed)


def test_web_config_rejects_symlink_and_profile_repo_redirect(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    other = tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    profile = allowed / "custom.yaml"
    profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: redirected",
                "repo_path: ../other",
                "codegraph_root: .",
                "instruction_sources:",
                "  sources: []",
            ]
        ),
        encoding="utf-8",
    )
    config_path = _write_config(
        tmp_path / ".moth" / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [
                {
                    "id": "allowed",
                    "name": "Allowed",
                    "repo": "../allowed",
                    "profile": "custom.yaml",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="must describe its declared repo"):
        load_web_console_config(config_path)

    profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: allowed",
                "repo_path: .",
                "codegraph_root: .",
                "instruction_sources:",
                "  sources: []",
            ]
        ),
        encoding="utf-8",
    )
    link = tmp_path / ".moth" / "linked.yaml"
    link.symlink_to(config_path)
    with pytest.raises(ValueError, match="symlink"):
        load_web_console_config(link)


def test_safe_view_skips_repo_configured_executables(tmp_path) -> None:
    marker = tmp_path / "marker-created"
    pack = tmp_path / "assertions.yaml"
    pack.write_text(
        yaml.safe_dump(
            {
                "kind": "assertion_pack",
                "name": "unsafe",
                "assertions": [
                    {
                        "id": "write-marker",
                        "type": "shell",
                        "command": ["/usr/bin/touch", str(marker)],
                        "expect": {"op": "==", "value": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = RepoProfile(
        kind="profile",
        name="safe-view",
        repo_path=tmp_path,
        codegraph_root=tmp_path,
        complexity_command=["/usr/bin/touch", str(marker)],
        assertion_packs=[pack],
        instruction_sources={"sources": []},
        tools={
            "unsafe": {
                "adapter": "command",
                "command": ["/usr/bin/touch", str(marker)],
            }
        },
    )

    report = build_report(profile, execution_policy="safe_view")

    assert not marker.exists()
    assert report["execution_policy"] == "safe_view"
    assert report["assertions"]["verdict"] == "NONE"
    assert "disabled repository-configured executables" in " ".join(report["warnings"])


def test_projects_api_lists_public_metadata_without_filesystem_paths(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / ".moth" / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [
                {
                    "id": "repo",
                    "name": "Repository",
                    "repo": "../repo",
                    "description": "Read-only target",
                }
            ],
        },
    )
    app = create_web_application(load_web_console_config(config_path), token="secret")

    status, headers, body = _call_wsgi(app, "/api/v1/projects", token="secret")
    payload = yaml.safe_load(body)

    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert payload == {
        "schema_version": "moth.web-project-list.v1",
        "capabilities": {"project_selection": False},
        "projects": [
            {
                "id": "repo",
                "name": "Repository",
                "description": "Read-only target",
                "profile_state": "ephemeral",
            }
        ],
    }
    assert str(tmp_path) not in body.decode()


def test_project_selection_api_registers_and_reloads_allowlist(tmp_path) -> None:
    repo_a = tmp_path / "project-a"
    repo_b = tmp_path / "project-b"
    repo_a.mkdir()
    repo_b.mkdir()
    config_path = _write_config(
        tmp_path / ".moth" / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "project-a", "name": "Project A", "repo": "../project-a"}],
        },
    )

    def register_selected():
        result = register_web_project(repo_b, config_path=config_path)
        return load_web_console_config(config_path), result["project_id"], result["created"]

    app = create_web_application(
        load_web_console_config(config_path),
        token="secret",
        config_loader=lambda: load_web_console_config(config_path),
        project_registration=register_selected,
        project_view_builder=lambda project: {
            "schema_version": "moth.web-project-view.v1",
            "project": project.public_metadata(),
            "inspection": {"status": "WARN"},
            "visual_document": {"schema_version": "moth.visual-document.v1"},
        },
    )

    initial = json.loads(_call_wsgi(app, "/api/v1/projects", token="secret")[2])
    assert initial["capabilities"] == {"project_selection": True}

    status, _, body = _call_wsgi(
        app,
        "/api/v1/projects/select",
        method="POST",
        token="secret",
    )
    registration = json.loads(body)
    assert status == "200 OK"
    assert registration["selected"] is True
    assert registration["created"] is True
    assert registration["project"]["name"] == "project-b"
    assert str(tmp_path) not in body.decode()

    project_id = registration["project"]["id"]
    projects = json.loads(_call_wsgi(app, "/api/v1/projects", token="secret")[2])
    assert [project["id"] for project in projects["projects"]] == ["project-a", project_id]
    inspected = _call_wsgi(
        app,
        "/api/v1/inspections",
        method="POST",
        token="secret",
        payload={"project_id": project_id},
    )
    assert inspected[0] == "200 OK"


def test_projects_and_inspections_reload_external_registry_changes(tmp_path) -> None:
    repo_a = tmp_path / "project-a"
    repo_b = tmp_path / "project-b"
    repo_a.mkdir()
    repo_b.mkdir()
    config_path = _write_config(
        tmp_path / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "project-a", "name": "Project A", "repo": "project-a"}],
        },
    )
    app = create_web_application(
        load_web_console_config(config_path),
        token="secret",
        config_loader=lambda: load_web_console_config(config_path),
        project_view_builder=lambda project: {
            "schema_version": "moth.web-project-view.v1",
            "project": project.public_metadata(),
            "inspection": {"status": "WARN"},
            "visual_document": {"schema_version": "moth.visual-document.v1"},
        },
    )

    registration = register_web_project(repo_b, config_path=config_path)
    projects = json.loads(_call_wsgi(app, "/api/v1/projects", token="secret")[2])
    inspected = _call_wsgi(
        app,
        "/api/v1/inspections",
        method="POST",
        token="secret",
        payload={"project_id": registration["project_id"]},
    )

    assert len(projects["projects"]) == 2
    assert inspected[0] == "200 OK"


def test_concurrent_project_registration_keeps_every_project(tmp_path) -> None:
    config_path = tmp_path / "web.yaml"
    repos = [tmp_path / f"project-{index}" for index in range(4)]
    for repo in repos:
        repo.mkdir()

    with ThreadPoolExecutor(max_workers=len(repos)) as executor:
        results = list(
            executor.map(
                lambda repo: register_web_project(repo, config_path=config_path),
                repos,
            )
        )

    config = load_web_console_config(config_path)
    assert len(config.projects) == len(repos)
    assert {project.id for project in config.projects} == {
        result["project_id"] for result in results
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "401 Unauthorized"),
        ({"token": "secret", "host": "localhost:8765"}, "403 Forbidden"),
        (
            {"token": "secret", "origin": "http://attacker.invalid"},
            "403 Forbidden",
        ),
        ({"token": "secret", "payload": {"path": "/tmp"}}, "422 Unprocessable Entity"),
    ],
)
def test_project_selection_route_enforces_request_boundary(tmp_path, kwargs, expected) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "repo", "name": "Repo", "repo": "repo"}],
        },
    )
    app = create_web_application(
        load_web_console_config(config_path),
        token="secret",
        project_registration=lambda: None,
    )

    status, _, _ = _call_wsgi(
        app,
        "/api/v1/projects/select",
        method="POST",
        **kwargs,
    )

    assert status == expected


def test_project_selection_api_cancels_without_mutating_registry(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "repo", "name": "Repo", "repo": "repo"}],
        },
    )
    app = create_web_application(
        load_web_console_config(config_path),
        token="secret",
        project_registration=lambda: None,
    )

    status, _, body = _call_wsgi(
        app,
        "/api/v1/projects/select",
        method="POST",
        token="secret",
    )

    assert status == "200 OK"
    assert json.loads(body) == {
        "schema_version": "moth.web-project-registration.v1",
        "selected": False,
        "created": False,
        "project": None,
    }


def test_api_requires_token_exact_host_and_same_origin(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = load_web_console_config(
        _write_config(
            tmp_path / ".moth" / "web.yaml",
            {
                "schema_version": "moth.web-console.v1",
                "server": {"host": "127.0.0.1", "port": 8765},
                "projects": [{"id": "repo", "name": "Repo", "repo": "../repo"}],
            },
        )
    )
    app = create_web_application(config, token="secret")

    assert _call_wsgi(app, "/api/v1/projects")[0] == "401 Unauthorized"
    assert (
        _call_wsgi(
            app,
            "/api/v1/projects",
            token="secret",
            host="attacker.example",
        )[0]
        == "403 Forbidden"
    )
    assert (
        _call_wsgi(
            app,
            "/api/v1/projects",
            token="secret",
            origin="https://attacker.example",
        )[0]
        == "403 Forbidden"
    )
    status, headers, _ = _call_wsgi(
        app,
        "/api/v1/projects",
        token="secret",
        origin="http://127.0.0.1:8765",
    )
    assert status == "200 OK"
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert _call_wsgi(app, "/api/v1/health")[0] == "401 Unauthorized"
    assert _call_wsgi(app, "/api/v1/health", token="secret")[0] == "200 OK"


def test_inspection_api_accepts_only_project_id_and_limits_concurrency(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = load_web_console_config(
        _write_config(
            tmp_path / ".moth" / "web.yaml",
            {
                "schema_version": "moth.web-console.v1",
                "server": {"host": "127.0.0.1", "port": 8765},
                "projects": [{"id": "repo", "name": "Repo", "repo": "../repo"}],
            },
        )
    )
    gate = BoundedSemaphore(1)
    app = create_web_application(
        config,
        token="secret",
        project_view_builder=lambda project: {
            "schema_version": "moth.web-project-view.v1",
            "project": project.public_metadata(),
            "inspection": {"status": "WARN"},
            "visual_document": {"schema_version": "moth.visual-document.v1"},
        },
        inspection_gate=gate,
    )

    status, _, body = _call_wsgi(
        app,
        "/api/v1/inspections",
        method="POST",
        token="secret",
        payload={"project_id": "repo"},
    )
    result = json.loads(body)
    assert status == "200 OK"
    assert result["project"]["id"] == "repo"
    assert result["inspection"]["status"] == "WARN"

    rejected, _, _ = _call_wsgi(
        app,
        "/api/v1/inspections",
        method="POST",
        token="secret",
        payload={"project_id": "repo", "task_kind": "architecture_orchestration"},
    )
    assert rejected == "422 Unprocessable Entity"

    gate.acquire()
    try:
        busy, _, _ = _call_wsgi(
            app,
            "/api/v1/inspections",
            method="POST",
            token="secret",
            payload={"project_id": "repo"},
        )
    finally:
        gate.release()
    assert busy == "429 Too Many Requests"


def test_web_assets_are_exact_packaged_routes_and_use_safe_dom(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = load_web_console_config(
        _write_config(
            tmp_path / ".moth" / "web.yaml",
            {
                "schema_version": "moth.web-console.v1",
                "server": {"host": "127.0.0.1", "port": 8765},
                "projects": [{"id": "repo", "name": "Repo", "repo": "../repo"}],
            },
        )
    )
    app = create_web_application(config, token="secret")

    index_status, index_headers, index = _call_wsgi(app, "/")
    script_status, _, script = _call_wsgi(app, "/assets/app.js")
    traversal_status, _, _ = _call_wsgi(app, "/assets/../web_config.py")

    assert index_status == "200 OK"
    assert index_headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"Moth Web Console" in index
    assert script_status == "200 OK"
    assert b"textContent" in script
    assert b"innerHTML" not in script
    assert b"Authorization" in script
    assert b"add-project-button" in index
    assert b"/api/v1/projects/select" in script
    assert b"drift?.state" not in script
    assert traversal_status == "404 Not Found"


def test_cli_serve_delegates_to_web_server(monkeypatch) -> None:
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "moth.cli.serve_web_console",
        lambda config_path, *, open_browser=False: seen.append(
            (config_path, open_browser)
        )
        or 0,
    )

    assert main(
        ["serve", "--config", "custom-web.yaml", "--open-browser"]
    ) == 0
    assert seen == [("custom-web.yaml", True)]


def test_serve_can_open_authenticated_url_after_binding(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "repo", "name": "Repo", "repo": "repo"}],
        },
    )
    events: list[tuple[str, str]] = []

    class FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def serve_forever(self):
            raise KeyboardInterrupt

    def fake_make_server(host, port, _app, **_kwargs):
        events.append(("bound", f"{host}:{port}"))
        return FakeServer()

    def fake_open(url):
        events.append(("opened", url))
        return True

    monkeypatch.setattr("moth.web_server.make_server", fake_make_server)
    monkeypatch.setattr("moth.web_server.open_capability_url", fake_open)

    assert serve_web_console(config_path, open_browser=True) == 0
    assert events[0] == ("bound", "127.0.0.1:8765")
    assert events[1][0] == "opened"
    assert events[1][1].startswith("http://127.0.0.1:8765/#token=")


def test_macos_browser_launcher_keeps_capability_out_of_process_args(
    monkeypatch,
) -> None:
    from moth.browser_launcher import open_capability_url

    capability_url = "http://127.0.0.1:8765/#token=super-secret"
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "darwin")
    monkeypatch.setattr("moth.browser_launcher.subprocess.run", fake_run)

    assert open_capability_url(capability_url) is True
    command, kwargs = calls[0]
    assert command == ["/usr/bin/osascript"]
    assert "super-secret" not in " ".join(command)
    assert capability_url in kwargs["input"]


def test_macos_project_selector_returns_only_existing_directory(
    tmp_path,
    monkeypatch,
) -> None:
    from moth.browser_launcher import select_project_directory

    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=f"SELECTED\n{tmp_path}\n")

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "darwin")
    monkeypatch.setattr("moth.browser_launcher.subprocess.run", fake_run)

    assert select_project_directory() == tmp_path.resolve()
    command, kwargs = calls[0]
    assert command == ["/usr/bin/osascript"]
    assert str(tmp_path) not in " ".join(command)
    assert "choose folder" in kwargs["input"]
    assert kwargs["stdout"] is subprocess.PIPE


def test_macos_project_selector_distinguishes_cancel_from_failure(monkeypatch) -> None:
    from moth.browser_launcher import ProjectSelectionError, select_project_directory

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "darwin")
    monkeypatch.setattr(
        "moth.browser_launcher.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="CANCELLED\n"),
    )
    assert select_project_directory() is None

    monkeypatch.setattr(
        "moth.browser_launcher.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout=""),
    )
    with pytest.raises(ProjectSelectionError, match="failed"):
        select_project_directory()


def test_web_server_uses_threaded_request_handling() -> None:
    assert issubclass(BoundedWSGIServer, ThreadingMixIn)


def test_project_selection_capability_is_hidden_without_native_adapter(
    monkeypatch,
) -> None:
    from moth.browser_launcher import project_selection_available

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "linux")

    assert project_selection_available() is False


def test_browser_launcher_fails_soft_without_a_safe_platform_adapter(
    monkeypatch,
) -> None:
    from moth.browser_launcher import open_capability_url

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "linux")

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("unsupported platforms must not launch a process")

    monkeypatch.setattr("moth.browser_launcher.subprocess.run", unexpected_run)

    assert (
        open_capability_url("http://127.0.0.1:8765/#token=super-secret")
        is False
    )
    assert open_capability_url("https://example.com/#token=super-secret") is False


def test_browser_launcher_process_failure_is_nonfatal(monkeypatch) -> None:
    from moth.browser_launcher import open_capability_url

    monkeypatch.setattr("moth.browser_launcher.sys.platform", "darwin")

    def failed_run(*_args, **_kwargs):
        raise OSError("browser unavailable")

    monkeypatch.setattr("moth.browser_launcher.subprocess.run", failed_run)

    assert (
        open_capability_url("http://127.0.0.1:8765/#token=super-secret")
        is False
    )


def test_cli_serve_reports_port_occupied(monkeypatch, capsys) -> None:
    def occupied(_config_path, *, open_browser=False):
        raise OSError("Address already in use")

    monkeypatch.setattr("moth.cli.serve_web_console", occupied)

    assert main(["serve", "--open-browser"]) == 1
    assert "Address already in use" in capsys.readouterr().err


def test_start_command_uses_project_environment_and_opens_browser(tmp_path) -> None:
    source = PROJECT_ROOT / "start.command"
    assert source.is_file()
    assert os.access(source, os.X_OK)

    sandbox = tmp_path / "moth"
    binary = sandbox / ".venv" / "bin" / "moth"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)
    launcher = sandbox / "start.command"
    launcher.write_bytes(source.read_bytes())
    launcher.chmod(0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    completed = subprocess.run(
        [str(launcher)],
        cwd=elsewhere,
        check=True,
        text=True,
        capture_output=True,
    )

    assert completed.stdout.splitlines() == ["serve", "--open-browser"]


def test_init_registers_project_for_web_selector_by_default(tmp_path, capsys) -> None:
    repo = tmp_path / "new-project"
    repo.mkdir()
    registry = tmp_path / "user-config" / "web.yaml"
    argv = [
        "init",
        "--repo",
        str(repo),
        "--web-config",
        str(registry),
        "--format",
        "json",
    ]

    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["profile_created"] is True
    assert first["web_registration"]["created"] is True

    assert main(argv) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["profile_created"] is False
    assert second["web_registration"]["created"] is False
    config = load_web_console_config(registry)
    assert [project.repo_path for project in config.projects] == [repo.resolve()]


def test_init_can_explicitly_skip_web_registration(tmp_path, capsys) -> None:
    repo = tmp_path / "local-only"
    repo.mkdir()
    registry = tmp_path / "user-config" / "web.yaml"

    assert (
        main(
            [
                "init",
                "--repo",
                str(repo),
                "--no-register-web",
                "--web-config",
                str(registry),
                "--format",
                "json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["profile_created"] is True
    assert result["web_registration"] is None
    assert not registry.exists()


def test_public_sanitizer_redacts_local_resource_uris() -> None:
    assert sanitize_public_text("https://example.com/docs") == "https://example.com/docs"
    assert sanitize_public_text("file:///Users/dp/secret.txt") == "<private-url>"
    assert sanitize_public_text("vscode://file/Users/dp/secret.txt") == "<private-url>"


def test_safe_view_disables_repo_git_fsmonitor_execution(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(
        f"#!/bin/sh\n/usr/bin/touch {marker}\nprintf '\\0'\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "core.fsmonitor", str(hook)],
        check=True,
    )
    profile = RepoProfile(
        kind="profile",
        name="fsmonitor-safe-view",
        repo_path=tmp_path,
        codegraph_root=tmp_path,
        instruction_sources={"sources": []},
    )

    build_report(profile, execution_policy="safe_view")

    assert not marker.exists()


def test_failed_inspection_leaves_a_traceback_on_the_server(tmp_path, capsys) -> None:
    """500 不能是黑盒: 浏览器只看到中性文案, 服务端必须留下栈。

    2026-08-17 实际付过代价 —— 给 flow_step 加字段撞上视觉文档 schema, 控制台弹
    "这次检查没有完成", 服务端日志一片空白, 只能人肉在 Python 里把整条链重跑一遍
    才知道是哪一行。一个帮人看问题的工具, 自己出问题时得说得出哪里坏了。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(
        tmp_path / ".moth" / "web.yaml",
        {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [{"id": "repo", "name": "Repository", "repo": "../repo"}],
        },
    )

    def explode(project):
        raise ValueError("visual document failed validation")

    app = create_web_application(
        load_web_console_config(config_path),
        token="secret",
        project_view_builder=explode,
    )

    status, _, body = _call_wsgi(
        app,
        "/api/v1/inspections",
        method="POST",
        token="secret",
        payload={"project_id": "repo"},
    )
    captured = capsys.readouterr()

    assert status == "500 Internal Server Error"
    # 响应体仍然中性: 栈是本地控制台的运维信息, 不是给页面的内容。
    assert b"visual document failed validation" not in body
    assert json.loads(body)["error"]["code"] == "INSPECTION_FAILED"
    # 服务端 stderr 上说得出是哪里坏了。
    assert "INSPECTION_FAILED failed" in captured.err
    assert "visual document failed validation" in captured.err
    assert "Traceback" in captured.err
