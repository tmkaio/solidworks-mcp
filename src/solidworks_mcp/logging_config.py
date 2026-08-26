"""
Logging configuration for SolidWorks MCP server.

CRITICAL: This server runs on STDIO transport. Any writes to stdout
will corrupt the JSON-RPC framing. All logging MUST go to stderr
and/or a rotating file — never to stdout.

Call configure_logging() before importing any other project module.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


def configure_logging(
    level: str | None = None,
    log_file: str | None = None,
) -> None:
    """
    Configure application logging.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR). Defaults to
               the LOG_LEVEL environment variable, falling back to INFO.
        log_file: Path to a rotating log file. Defaults to
                  ~/.solidworks-mcp/logs/server.log when LOG_FILE env var is
                  not set and no explicit path is given.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    numeric_level = getattr(logging, level, logging.INFO)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
    ]

    # Resolve log file path
    if log_file is None:
        log_file = os.environ.get("LOG_FILE")
    if log_file is None:
        log_dir = Path.home() / ".solidworks-mcp" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = str(log_dir / "server.log")
        except OSError:
            log_file = None  # Fall back to stderr-only if dir creation fails

    if log_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8",
            )
            handlers.append(file_handler)
        except OSError as exc:
            print(f"[solidworks-mcp] Warning: Could not open log file: {exc}", file=sys.stderr)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=handlers,
        force=True,
    )

    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
