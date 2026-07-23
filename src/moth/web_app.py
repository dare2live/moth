"""Authenticated read-only HTTP contract for the local Moth Web Console."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Iterable
from importlib.resources import files
from threading import BoundedSemaphore
from typing import Any

from moth.web_config import WebConsoleConfig, WebProject, load_web_policy


StartResponse = Callable[[str, list[tuple[str, str]]], Any]
ProjectViewBuilder = Callable[[WebProject], dict[str, Any]]


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _headers(content_type: str, content_length: int) -> list[tuple[str, str]]:
    return [
        ("Content-Type", content_type),
        ("Content-Length", str(content_length)),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("X-Frame-Options", "DENY"),
        (
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        ),
    ]


class WebConsoleApplication:
    def __init__(
        self,
        config: WebConsoleConfig,
        *,
        token: str,
        project_view_builder: ProjectViewBuilder,
        inspection_gate: BoundedSemaphore,
    ) -> None:
        if not token:
            raise ValueError("web console token cannot be empty")
        self._config = config
        self._token = token
        self._project_view_builder = project_view_builder
        self._inspection_gate = inspection_gate
        self._authority = f"{config.host}:{config.port}"
        self._origin = f"http://{self._authority}"
        api_policy = load_web_policy()["api"]
        self._max_body = int(api_policy["max_body_bytes"])
        self._max_authorization = int(api_policy["max_authorization_bytes"])

    def _respond_json(
        self,
        start_response: StartResponse,
        status: str,
        payload: Any,
    ) -> Iterable[bytes]:
        body = _json_bytes(payload)
        start_response(status, _headers("application/json; charset=utf-8", len(body)))
        return [body]

    def _respond_asset(
        self,
        start_response: StartResponse,
        resource_name: str,
        content_type: str,
    ) -> Iterable[bytes]:
        body = files("moth.web_assets").joinpath(resource_name).read_bytes()
        start_response("200 OK", _headers(content_type, len(body)))
        return [body]

    def _error(
        self,
        start_response: StartResponse,
        status: str,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> Iterable[bytes]:
        return self._respond_json(
            start_response,
            status,
            {
                "schema_version": "moth.web-error.v1",
                "request_id": secrets.token_hex(8),
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                },
            },
        )

    def _authorized(self, environ: dict[str, Any]) -> bool:
        supplied = str(environ.get("HTTP_AUTHORIZATION") or "")
        if len(supplied.encode("utf-8")) > self._max_authorization:
            return False
        prefix = "Bearer "
        return supplied.startswith(prefix) and secrets.compare_digest(
            supplied[len(prefix) :],
            self._token,
        )

    def _read_payload(
        self,
        environ: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, tuple[str, str, str] | None]:
        if str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0] != "application/json":
            return None, (
                "415 Unsupported Media Type",
                "UNSUPPORTED_MEDIA_TYPE",
                "Inspection requests must use application/json.",
            )
        try:
            size = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            return None, ("400 Bad Request", "MALFORMED_REQUEST", "Invalid content length.")
        if size <= 0:
            return None, ("400 Bad Request", "MALFORMED_JSON", "A JSON body is required.")
        if size > self._max_body:
            return None, (
                "413 Content Too Large",
                "REQUEST_TOO_LARGE",
                "Inspection request exceeds the configured bound.",
            )
        raw = environ["wsgi.input"].read(size)
        try:
            payload = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            return None, ("400 Bad Request", "MALFORMED_JSON", "Request body is not valid JSON.")
        if not isinstance(payload, dict):
            return None, (
                "422 Unprocessable Entity",
                "INVALID_REQUEST",
                "Request body must be an object.",
            )
        if set(payload) != {"project_id"} or not isinstance(payload.get("project_id"), str):
            return None, (
                "422 Unprocessable Entity",
                "INVALID_REQUEST",
                "Only a string project_id is accepted.",
            )
        return payload, None

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        path = str(environ.get("PATH_INFO") or "/")
        method = str(environ.get("REQUEST_METHOD") or "GET")
        static_routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
            "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if path in static_routes and method == "GET":
            resource_name, content_type = static_routes[path]
            return self._respond_asset(start_response, resource_name, content_type)
        if not path.startswith("/api/"):
            return self._error(
                start_response,
                "404 Not Found",
                "NOT_FOUND",
                "The requested Moth Web Console resource was not found.",
            )
        if str(environ.get("HTTP_HOST") or "") != self._authority:
            return self._error(
                start_response,
                "403 Forbidden",
                "HOST_REJECTED",
                "Request host is not allowed.",
            )
        origin = str(environ.get("HTTP_ORIGIN") or "")
        if origin and origin != self._origin:
            return self._error(
                start_response,
                "403 Forbidden",
                "ORIGIN_REJECTED",
                "Request origin is not allowed.",
            )
        if not self._authorized(environ):
            return self._error(
                start_response,
                "401 Unauthorized",
                "UNAUTHORIZED",
                "A valid Web Console capability token is required.",
            )
        if environ.get("QUERY_STRING"):
            return self._error(
                start_response,
                "400 Bad Request",
                "QUERY_REJECTED",
                "The Web Console API does not accept query parameters.",
            )
        if path == "/api/v1/health":
            if method != "GET":
                return self._error(
                    start_response,
                    "405 Method Not Allowed",
                    "METHOD_NOT_ALLOWED",
                    "Use GET for Web Console health.",
                )
            return self._respond_json(
                start_response,
                "200 OK",
                {"schema_version": "moth.web-health.v1", "status": "PASS"},
            )
        if path == "/api/v1/projects":
            if method != "GET":
                return self._error(
                    start_response,
                    "405 Method Not Allowed",
                    "METHOD_NOT_ALLOWED",
                    "Use GET for the project registry.",
                )
            return self._respond_json(
                start_response,
                "200 OK",
                {
                    "schema_version": "moth.web-project-list.v1",
                    "projects": [
                        project.public_metadata() for project in self._config.projects
                    ],
                },
            )
        if path == "/api/v1/inspections":
            if method != "POST":
                return self._error(
                    start_response,
                    "405 Method Not Allowed",
                    "METHOD_NOT_ALLOWED",
                    "Use POST to request a fresh safe-view inspection.",
                )
            payload, error = self._read_payload(environ)
            if error is not None:
                return self._error(start_response, *error)
            assert payload is not None
            try:
                project = self._config.project(payload["project_id"])
            except KeyError:
                return self._error(
                    start_response,
                    "404 Not Found",
                    "PROJECT_NOT_FOUND",
                    "Configured project was not found.",
                )
            if not self._inspection_gate.acquire(blocking=False):
                return self._error(
                    start_response,
                    "429 Too Many Requests",
                    "INSPECTION_BUSY",
                    "Another inspection is already running.",
                    retryable=True,
                )
            try:
                result = self._project_view_builder(project)
            except Exception:
                return self._error(
                    start_response,
                    "500 Internal Server Error",
                    "INSPECTION_FAILED",
                    "The inspection could not be completed.",
                    retryable=True,
                )
            finally:
                self._inspection_gate.release()
            return self._respond_json(start_response, "200 OK", result)
        return self._error(
            start_response,
            "404 Not Found",
            "NOT_FOUND",
            "The requested Moth Web Console resource was not found.",
        )


def create_web_application(
    config: WebConsoleConfig,
    *,
    token: str,
    project_view_builder: ProjectViewBuilder | None = None,
    inspection_gate: BoundedSemaphore | None = None,
) -> WebConsoleApplication:
    if project_view_builder is None:
        from moth.web_service import build_project_view

        project_view_builder = build_project_view
    return WebConsoleApplication(
        config,
        token=token,
        project_view_builder=project_view_builder,
        inspection_gate=inspection_gate or BoundedSemaphore(1),
    )
