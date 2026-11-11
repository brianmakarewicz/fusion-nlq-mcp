"""Usage log: one JSON line per tool call, metadata only.

Each line records which tool ran, when, how long it took, how big the result was
and the outcome. It records no SQL, no parameter values and no results, so Fusion
data never lands here; each input is reduced to its length.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any


def _log_path() -> str:
    """FUSION_MCP_METER_LOG, or metering.jsonl next to the saved connections."""
    from .credentials import config_path
    return os.environ.get("FUSION_MCP_METER_LOG") or str(config_path().parent / "metering.jsonl")


def _shape(value: Any) -> dict:
    """Reduce an input to its length."""
    return {"len": len(str(value))}


class Meter:
    """Context manager that times a tool call and appends one log line."""

    def __init__(self, tool: str, inputs: dict | None = None):
        self.tool = tool
        self.inputs = {k: _shape(v) for k, v in (inputs or {}).items()}
        self.outcome = "ok"
        self.detail = ""
        self.out_size = 0
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def result_size(self, n: int):
        self.out_size = n

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.outcome = "error"
            # Error text can quote table, column or literal values, so keep only
            # the exception type and any ORA- code.
            code = re.search(r"ORA-\d{5}", str(exc))
            self.detail = exc_type.__name__ + (f" {code.group(0)}" if code else "")
        rec = {
            "ts": int(time.time()),
            "tool": self.tool,
            "inputs": self.inputs,
            "ms": round((time.monotonic() - self._start) * 1000, 1),
            "out_size": self.out_size,
            "outcome": self.outcome,
            "detail": self.detail,
        }
        try:
            path = _log_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass  # never let metering failure break a tool call
        return False  # do not suppress exceptions
