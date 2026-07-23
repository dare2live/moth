"""Loopback transport for the Moth Web Console."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from moth.web_app import create_web_application
from moth.web_config import load_web_console_config, load_web_policy


class QuietRequestHandler(WSGIRequestHandler):
    """Avoid logging authorization-bearing request metadata."""

    def log_message(self, format: str, *args: object) -> None:
        return


class BoundedWSGIServer(WSGIServer):
    def get_request(self):
        socket, address = super().get_request()
        socket.settimeout(float(load_web_policy()["network"]["read_timeout_seconds"]))
        return socket, address


def serve_web_console(config_path: str | Path) -> int:
    config = load_web_console_config(config_path)
    token = secrets.token_urlsafe(32)
    app = create_web_application(config, token=token)
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
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            sys.stdout.write("\nMoth Web Console stopped.\n")
    return 0
