"""Workflow data models — state machine, steps, and persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path("~/.vmware/workflows.db").expanduser()


class WorkflowState(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    MONITORING = "monitoring"
    AWAITING_APPROVAL = "awaiting_approval"
    COMMITTING = "committing"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED_BY_POLICY = "blocked_by_policy"


@dataclass
class WorkflowStep:
    index: int
    action: str
    skill: str
    tool: str
    params: dict[str, Any]
    status: str = "pending"  # pending | running | success | failed | skipped | rolled_back
    result: Any = None
    started_at: str = ""
    completed_at: str = ""
    rollback_tool: str = ""
    rollback_params: dict[str, Any] = field(default_factory=dict)
    group_id: str = ""  # non-empty = parallel-group sibling; agent may dispatch concurrently with peers


@dataclass
class Workflow:
    id: str
    workflow_type: str
    state: WorkflowState
    steps: list[WorkflowStep]
    params: dict[str, Any]
    created_at: str
    updated_at: str
    approved_by: str = ""
    diff_report: dict[str, Any] = field(default_factory=dict)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    blocked_reason: str = ""

    def log(self, action: str, detail: str = "") -> None:
        self.audit_log.append({
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "action": action,
            "detail": detail,
        })
        self.updated_at = datetime.now(tz=timezone.utc).isoformat()

    def current_step(self) -> WorkflowStep | None:
        for step in self.steps:
            if step.status in ("pending", "running"):
                return step
        return None

    def completed_steps(self) -> list[WorkflowStep]:
        return [s for s in self.steps if s.status == "success"]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


def new_workflow_id() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"wf-{ts}-{short}"


# ── SQLite Persistence ────────────────────────────────────────────────

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS workflows (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    state      TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


# Parameter keys whose values must never be written to the state DB.
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
    "authorization", "bearer", "private_key", "credential", "credentials",
})


def _redact_for_persistence(obj: Any) -> Any:
    """Deep-copy ``obj`` with sensitive dict keys masked to '***'.

    Recurses through dicts and lists so secrets nested in step params are
    caught too. Non-container values are returned unchanged.
    """
    if isinstance(obj, dict):
        return {
            k: ("***" if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS
                else _redact_for_persistence(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_for_persistence(item) for item in obj]
    return obj


class WorkflowStore:
    """Persist workflows to SQLite (separate from audit.db)."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path).expanduser() if db_path else _DEFAULT_DB
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = self._connect()
        conn.execute(_CREATE_TABLE)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
        conn.close()
        self._harden_permissions()

    def _harden_permissions(self) -> None:
        """Restrict the state dir to 0700 and DB files (incl. WAL/SHM) to 0600.

        Workflow params are persisted here and can contain sensitive values, so
        keep them owner-only. Best-effort: never raises."""
        try:
            os.chmod(self._path.parent, 0o700)
        except OSError:
            pass
        for suffix in ("", "-wal", "-shm"):
            candidate = self._path.with_name(self._path.name + suffix)
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path), timeout=5)

    def save(self, wf: Workflow) -> None:
        conn = self._connect()
        # Redact secrets BEFORE persisting: workflow/step params may carry
        # passwords/tokens that a caller passed in. They stay in the in-memory
        # Workflow object (downstream steps still work this run); the DB never
        # stores them. After a crash, secrets are re-sourced from env/secret
        # store, not recovered from disk.
        data = json.dumps(_redact_for_persistence(wf.to_dict()), default=str)
        conn.execute(
            "INSERT OR REPLACE INTO workflows (id, type, state, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (wf.id, wf.workflow_type, wf.state.value, data,
             wf.created_at, wf.updated_at),
        )
        conn.commit()
        conn.close()

    def load(self, workflow_id: str) -> Workflow | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT data FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return _from_dict(json.loads(row[0]))

    def list_active(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, type, state, created_at, updated_at FROM workflows "
            "WHERE state NOT IN ('completed', 'failed') ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "type": r[1], "state": r[2], "created_at": r[3], "updated_at": r[4]}
            for r in rows
        ]

    def list_all(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, type, state, created_at, updated_at FROM workflows "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "type": r[1], "state": r[2], "created_at": r[3], "updated_at": r[4]}
            for r in rows
        ]

    def delete(self, workflow_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        conn.commit()
        conn.close()


def _from_dict(d: dict[str, Any]) -> Workflow:
    # Backward compat: older workflows persisted before group_id was added
    steps = []
    for s in d.get("steps", []):
        s.setdefault("group_id", "")
        steps.append(WorkflowStep(**s))
    return Workflow(
        id=d["id"],
        workflow_type=d["workflow_type"],
        state=WorkflowState(d["state"]),
        steps=steps,
        params=d.get("params", {}),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        approved_by=d.get("approved_by", ""),
        diff_report=d.get("diff_report", {}),
        audit_log=d.get("audit_log", []),
        blocked_reason=d.get("blocked_reason", ""),
    )
