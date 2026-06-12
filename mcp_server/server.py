"""MCP server for VMware Pilot — workflow orchestration.

Thin entrypoint. The shared FastMCP instance and helpers live in
``mcp_server._shared``; the 13 tools are defined across ``mcp_server.tools``
(lifecycle / query / authoring) and register themselves on import. The
store/executor singletons + accessors live here because the test-suite patches
``server._store`` / ``server._executor``; ``_shared`` defers to these accessors
so those patches are honoured.

Exposes 13 tools for AI agents to manage multi-step VMware workflows:
  plan_workflow / run_workflow / approve / rollback / cancel_workflow
  review_workflow / get_workflow_status / list_workflows / get_skill_catalog
  create_workflow / design_workflow / update_draft / confirm_draft
"""

from __future__ import annotations

import logging

from mcp_server._catalog import SKILL_CATALOG
from mcp_server._shared import _save_as_yaml, _validate_template_name, mcp
from vmware_pilot.executor import WorkflowExecutor
from vmware_pilot.models import WorkflowStore

logger = logging.getLogger(__name__)

_store: WorkflowStore | None = None
_executor: WorkflowExecutor | None = None


def _get_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store


def _get_executor() -> WorkflowExecutor:
    global _executor
    if _executor is None:
        _executor = WorkflowExecutor(_get_store())
    return _executor


# Importing the tool modules registers every @mcp.tool onto ``mcp`` and gives
# this module the tool functions to re-export (test-suite calls server.<tool>).
from mcp_server.tools.authoring import (  # noqa: E402
    confirm_draft,
    create_workflow,
    design_workflow,
    update_draft,
)
from mcp_server.tools.lifecycle import (  # noqa: E402
    approve,
    cancel_workflow,
    plan_workflow,
    rollback,
    run_workflow,
)
from mcp_server.tools.query import (  # noqa: E402
    get_skill_catalog,
    get_workflow_status,
    list_workflows,
    review_workflow,
)

__all__ = [
    "mcp",
    "main",
    "SKILL_CATALOG",
    "_get_store",
    "_get_executor",
    "_validate_template_name",
    "_save_as_yaml",
    "plan_workflow",
    "run_workflow",
    "approve",
    "rollback",
    "cancel_workflow",
    "review_workflow",
    "get_workflow_status",
    "list_workflows",
    "get_skill_catalog",
    "create_workflow",
    "design_workflow",
    "update_draft",
    "confirm_draft",
]


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")
