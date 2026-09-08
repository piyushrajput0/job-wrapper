"""Tiny in-process background-task registry, so the UI can kick off a search and watch it."""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Task:
    id: str
    kind: str
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str = ""
    progress: str = ""
    result: Any = None
    error: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    controller: Any = None            # set for tasks that can be asked to stop

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.progress = event.get("message", self.progress)
        del self.events[:-200]

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "progress": self.progress, "result": self.result, "error": self.error,
                "events": self.events[-40:],
                "stoppable": self.controller is not None}


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[Task], Any]) -> Task:
        task = Task(id=uuid.uuid4().hex[:10], kind=kind)
        with self._lock:
            self._tasks[task.id] = task

        def run() -> None:
            try:
                task.result = fn(task)
                task.status = "done"
            except Exception as exc:
                task.status = "failed"
                task.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
            finally:
                task.finished_at = datetime.now(UTC).isoformat()

        threading.Thread(target=run, daemon=True, name=f"jobwrapper-{kind}").start()
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def running(self, kind: str | None = None) -> list[Task]:
        return [t for t in self._tasks.values()
                if t.status == "running" and (kind is None or t.kind == kind)]

    def stop(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.controller is not None and hasattr(task.controller, "stop"):
            task.controller.stop()
            task.progress = "stopping after the job in flight..."
            return True
        return False

    def all(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.started_at, reverse=True)[:25]


registry = TaskRegistry()
