"""Structured logging configuration for the orchestrator."""

from __future__ import annotations

import logging
import os
import sys

import structlog


_HANDLER_NAME = "engine-json-stdout"


def setup_logging() -> None:
    """Configure JSON logging to stdout for structlog and stdlib loggers. Safe to call repeatedly.

    Log level comes from LOG_LEVEL (default INFO). Only this module's own handler is
    replaced on re-run; handlers added by others (e.g. pytest's caplog) are kept.
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    shared_processors: list[structlog.typing.Processor] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            # Rendering happens once, in the handler's formatter below.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    ))

    root_logger = logging.getLogger()
    for existing in [h for h in root_logger.handlers if h.get_name() == _HANDLER_NAME]:
        root_logger.removeHandler(existing)
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Reduce noise from third-party libs
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger bound to the given name."""
    return structlog.get_logger(name)
