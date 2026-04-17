import json
import logging
import sys
import io
import time
import traceback
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional


request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
job_id_var: ContextVar[Optional[str]] = ContextVar("job_id", default=None)
step_var: ContextVar[Optional[str]] = ContextVar("step", default=None)


def set_request_id(v: Optional[str]):
    request_id_var.set(v)


def set_session_id(v: Optional[str]):
    session_id_var.set(v)


def set_job_id(v: Optional[str]):
    job_id_var.set(v)


def set_step(v: Optional[str]):
    step_var.set(v)


def new_request_id() -> str:
    return str(uuid.uuid4())


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.session_id = session_id_var.get()
        record.job_id = job_id_var.get()
        record.step = step_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "session_id": getattr(record, "session_id", None),
            "job_id": getattr(record, "job_id", None),
            "step": getattr(record, "step", None),
        }

        extras: Dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k.startswith("_"):
                continue
            if k in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "request_id",
                "session_id",
                "job_id",
                "step",
            }:
                continue
            extras[k] = v
        if extras:
            base["extra"] = extras

        if record.exc_info:
            base["exception"] = "".join(traceback.format_exception(*record.exc_info)).strip()

        return json.dumps(base, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: str = "INFO"):
    global _configured
    if _configured:
        return
    _configured = True

    root_level = getattr(logging, (level or "INFO").upper(), logging.INFO)
    logger = logging.getLogger("rag")
    logger.setLevel(root_level)
    logger.propagate = False

    h = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8'))
    h.setLevel(root_level)
    h.setFormatter(_JsonFormatter())
    h.addFilter(_ContextFilter())
    logger.addHandler(h)


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    base = "rag"
    if name:
        if name.startswith("backend."):
            name = name[len("backend.") :]
        base = f"{base}.{name}"
    return logging.getLogger(base)

