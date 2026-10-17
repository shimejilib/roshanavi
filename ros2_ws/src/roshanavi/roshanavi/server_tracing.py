"""詳細計測モード routes (docs/design/measurement.md): status, and turning it on / off.

Turning it on is an operator action (the target nodes pay a small cost per
message), so it is a mutating JSON request behind the security middleware
like every other change; the UI explains the cost before sending it.
"""

from typing import Any, Dict

from fastapi import FastAPI

from .lab import Lab
from .pydantic_compat import StrictModel


class TracingRequest(StrictModel):
    enabled: bool


def register(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/tracing')
    def get_tracing() -> Dict[str, Any]:
        return lab.tracing_status()

    @app.put('/api/tracing')
    def put_tracing(req: TracingRequest) -> Dict[str, Any]:
        return lab.set_tracing(req.enabled)
