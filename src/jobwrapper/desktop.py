"""Job Wrapper as a desktop application.

The web UI already exists and already runs locally; this wraps it in a native window so the
thing behaves like an application - double-click it, a window opens, close it and everything
stops. No terminal, no browser tab, no localhost URL to remember.

The server runs in-process on a free port and is only ever reachable from this machine.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import httpx

from .logging_setup import get
from .models import Profile
from .paths import ensure_layout

log = get("desktop")

WINDOW_TITLE = "Job Wrapper"
STARTUP_TIMEOUT = 25.0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int) -> threading.Thread:
    """uvicorn in a daemon thread, so closing the window ends the process."""
    import uvicorn

    from .server.app import create_app

    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="jobwrapper-server")
    thread.start()
    return thread


def wait_until_ready(port: int, timeout: float = STARTUP_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=2).status_code == 200:
                return True
        except Exception:
            time.sleep(0.25)
    return False


def landing_route() -> str:
    """First run lands on the profile; after that, on the thing you came to do."""
    profile = Profile.load(ensure_layout()["profile"])
    return "#/profile" if profile.missing_required() else "#/autopilot"


def run(port: int | None = None, fullscreen: bool = False) -> int:
    port = port or free_port()
    start_server(port)
    if not wait_until_ready(port):
        log.error("the local server did not start within %ss", STARTUP_TIMEOUT)
        return 1

    url = f"http://127.0.0.1:{port}/{landing_route()}"
    try:
        import webview
    except ImportError:
        log.warning("pywebview is not installed - opening your browser instead "
                    "(install with: uv sync --extra desktop)")
        import webbrowser

        webbrowser.open(url)
        try:
            while True:                      # keep the server alive for the browser tab
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    window: Any = webview.create_window(
        WINDOW_TITLE, url,
        width=1320, height=900, min_size=(900, 640),
        text_select=True, confirm_close=False,
    )
    _install_shutdown_guard(window)
    webview.start()                          # blocks until the window is closed
    return 0


def _install_shutdown_guard(window: Any) -> None:
    """Warn instead of vanishing if a run is still in flight when the window closes."""
    def on_closing() -> bool:
        try:
            import webview

            running = window.evaluate_js(
                "(async () => { const r = await fetch('/api/autopilot/current');"
                " const t = await r.json(); return t.status === 'running'; })()")
            if running:
                return bool(webview.windows and window.create_confirmation_dialog(
                    WINDOW_TITLE, "A run is still in progress. Quit anyway?"))
        except Exception:
            pass
        return True

    try:
        window.events.closing += on_closing
    except Exception:                        # older pywebview builds
        pass


def main() -> None:
    """Entry point for the packaged application."""
    import sys

    from .logging_setup import setup

    setup()
    sys.exit(run())
