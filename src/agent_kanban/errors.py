"""业务错误（PRD 4.3 九码）。"""

from __future__ import annotations

from typing import Any


class BusinessError(Exception):
    """带 PRD 4.3 错误码的业务失败。task_id = 涉及的 requirement id（可为空）。"""

    def __init__(self, code: str, message: str, task_id: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.task_id = task_id

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "task_id": self.task_id}
