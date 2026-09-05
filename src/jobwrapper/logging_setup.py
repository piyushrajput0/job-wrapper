"""Rich console + rotating file log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from rich.console import Console
from rich.logging import RichHandler

from . import paths

console = Console()
_configured = False


def setup(verbose: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger("jobwrapper")
    if _configured:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    rich_handler = RichHandler(console=console, rich_tracebacks=True, show_path=False, markup=False)
    rich_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(rich_handler)

    log_dir = paths.ensure_layout()["logs"]
    file_handler = RotatingFileHandler(log_dir / "jobwrapper.log", maxBytes=4_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    logger.propagate = False
    _configured = True
    return logger


def get(name: str = "jobwrapper") -> logging.Logger:
    setup()
    return logging.getLogger(name if name.startswith("jobwrapper") else f"jobwrapper.{name}")
