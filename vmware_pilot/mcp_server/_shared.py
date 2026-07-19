"""Shared MCP instance + helpers for VMware Pilot tools.

Holds the single FastMCP instance every tool module registers onto and small
helpers (template-name validation, YAML persistence). The store/executor
accessors live in ``vmware_pilot.mcp_server.server`` (the patch target the test-suite uses);
the ``_get_store``/``_get_executor`` wrappers here defer to them at call time so
that ``monkeypatch.setattr(server, "_store", ...)`` is observed.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from vmware_pilot.executor import WorkflowExecutor
from vmware_pilot.models import WorkflowStore

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "vmware-pilot",
    instructions=(
        "VMware workflow orchestration. Plan and execute multi-step operations "
        "(clone-test-approve-commit, incident response) with state persistence, "
        "approval gates, and automatic rollback. "
        "Use plan_workflow to create a plan, run_workflow to execute, "
        "approve to continue past gates, rollback to abort."
    ),
)


def _get_store() -> WorkflowStore:
    # Defer to the canonical accessor in vmware_pilot.mcp_server.server so test patches of
    # server._store are honoured. Imported lazily to avoid a circular import.
    from vmware_pilot.mcp_server import server

    return server._get_store()


def _get_executor() -> WorkflowExecutor:
    from vmware_pilot.mcp_server import server

    return server._get_executor()


def _validate_template_name(name: str) -> str | None:
    """Return an error message if ``name`` is unsafe as a template filename.

    ``name`` is user-supplied and becomes a filename — reject traversal so a
    template cannot be written outside the workflows dir.
    """
    if not name or "/" in name or "\\" in name or name.startswith(".") or "\x00" in name:
        return (
            f"Invalid workflow name {name!r}: must be non-empty with no path "
            "separators, leading dots, or null bytes"
        )
    return None


def _save_as_yaml(name: str, description: str, steps: list[dict[str, Any]]) -> None:
    """Save a dynamic workflow as YAML for future reuse."""
    import os
    from pathlib import Path

    import yaml

    name_error = _validate_template_name(name)
    if name_error:
        raise ValueError(name_error)

    workflows_dir = Path("~/.vmware/workflows").expanduser()
    workflows_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(workflows_dir, 0o700)
    except OSError:
        pass

    spec = {
        "name": name,
        "description": description,
        "steps": [
            {k: v for k, v in s.items() if v}  # strip empty values
            for s in steps
        ],
    }

    path = workflows_dir / f"{name}.yaml"
    with open(path, "w") as fh:
        yaml.dump(spec, fh, default_flow_style=False, allow_unicode=True)

    logger.info("Saved custom workflow template: %s", path)
