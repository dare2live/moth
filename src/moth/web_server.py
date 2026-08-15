"""Loopback transport for the Moth Web Console."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from moth.browser_launcher import (
    open_capability_url,
    project_selection_available,
    select_project_directory,
)
from moth.web_app import create_web_application
from moth.web_config import load_web_console_config, load_web_policy
from moth.web_registry import register_web_project


class QuietRequestHandler(WSGIRequestHandler):
    """Avoid logging authorization-bearing request metadata."""

    def log_message(self, format: str, *args: object) -> None:
        return


class BoundedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True

    def get_request(self):
        socket, address = super().get_request()
        socket.settimeout(float(load_web_policy()["network"]["read_timeout_seconds"]))
        return socket, address


def serve_web_console(
    config_path: str | Path,
    *,
    open_browser: bool = False,
) -> int:
    registry_path = Path(config_path).expanduser()
    config = load_web_console_config(registry_path)
    token = secrets.token_urlsafe(32)

    def register_selected_project():
        selected = select_project_directory()
        if selected is None:
            return None
        registration = register_web_project(selected, config_path=registry_path)
        refreshed = load_web_console_config(registry_path)
        return refreshed, str(registration["project_id"]), bool(registration["created"])

    app = create_web_application(
        config,
        token=token,
        config_loader=lambda: load_web_console_config(registry_path),
        project_registration=(
            register_selected_project if project_selection_available() else None
        ),
    )
    url = f"http://{config.host}:{config.port}/#token={token}"
    with make_server(
        config.host,
        config.port,
        app,
        server_class=BoundedWSGIServer,
        handler_class=QuietRequestHandler,
    ) as server:
        sys.stdout.write("Moth Web Console is running locally.\n")
        sys.stdout.write(f"{url}\n")
        sys.stdout.write("Press Ctrl-C to stop.\n")
        sys.stdout.flush()
        if open_browser:
            opened = open_capability_url(url)
            if not opened:
                sys.stderr.write(
                    "Moth could not open a browser automatically; "
                    "open the URL printed above.\n"
                )
                sys.stderr.flush()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            sys.stdout.write("\nMoth Web Console stopped.\n")
    return 0
