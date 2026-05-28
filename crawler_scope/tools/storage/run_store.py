from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel

from crawler_scope.schemas.task_spec import TaskSpec


class RunStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.runs_dir = self.project_root / "runs"

    def create_run(self, task_spec: TaskSpec, task_input: str | None = None) -> str:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        run_id: str | None = None
        run_dir: Path | None = None
        for _ in range(10):
            candidate = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:4]}"
            candidate_dir = self.get_run_dir(candidate)
            try:
                candidate_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                continue

            run_id = candidate
            run_dir = candidate_dir
            break

        if run_id is None or run_dir is None:
            raise RuntimeError("Unable to create a unique run directory.")

        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        (run_dir / "task_input.txt").write_text(
            task_input if task_input is not None else task_spec.user_request,
            encoding="utf-8",
        )
        (run_dir / "task.yaml").write_text(
            yaml.safe_dump(
                task_spec.model_dump(mode="json"),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (run_dir / "trace.jsonl").write_text("", encoding="utf-8")

        now = _iso_now()
        self.save_json(
            run_id,
            "status.json",
            {
                "run_id": run_id,
                "task_id": task_spec.task_id,
                "task_type": task_spec.task_type,
                "status": "initialized",
                "created_at": now,
                "updated_at": now,
            },
        )
        self.append_trace(
            run_id,
            {
                "event": "run_created",
                "timestamp": now,
                "task_id": task_spec.task_id,
                "task_type": task_spec.task_type,
            },
        )
        return run_id

    def append_trace(self, run_id: str, payload: Any) -> Path:
        target = self.get_run_dir(run_id) / "trace.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = _to_serializable(payload)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialized, ensure_ascii=False) + "\n")
        return target

    def save_json(self, run_id: str, relative_path: str | Path, payload: Any) -> Path:
        target = self.get_run_dir(run_id) / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = _to_serializable(payload)
        target.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def save_text(self, run_id: str, relative_path: str | Path, text: str) -> Path:
        target = self.get_run_dir(run_id) / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def load_json(self, run_id: str, relative_path: str | Path) -> Any:
        target = self.get_run_dir(run_id) / Path(relative_path)
        return json.loads(target.read_text(encoding="utf-8"))

    def mark_status(self, run_id: str, status: str, **extra_fields: Any) -> dict[str, Any]:
        status_payload = self.load_json(run_id, "status.json")
        status_payload["status"] = status
        status_payload["updated_at"] = _iso_now()
        status_payload.update(_to_serializable(extra_fields))
        self.save_json(run_id, "status.json", status_payload)
        return status_payload

    def get_run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id


def _to_serializable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {key: _to_serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_serializable(item) for item in value]
    return value


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
