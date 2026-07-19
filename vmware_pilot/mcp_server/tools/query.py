"""Read-only query/discovery tools: review, status, list, skill catalog."""

from __future__ import annotations

from vmware_policy import vmware_tool

from vmware_pilot.mcp_server._catalog import SKILL_CATALOG
from vmware_pilot.mcp_server._shared import _get_store, mcp
from vmware_pilot.review import review as _review_workflow_impl


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="low")
def review_workflow(workflow_id: str) -> dict:
    """[READ] Sanity-check a planned workflow before execution.

    Performs structural validation only — does NOT call into other skills.
    Catches the common authoring errors before they hit production:

      - Delete-then-use: a step deletes resource X, a later step references X
      - Missing required params: a step has empty params or placeholder values
      - Cross-skill order issues: surfacing the cross-skill dispatch sequence
      - Risk profile: count of destructive vs. read-only steps
      - Approval coverage: are all destructive ops gated behind a require_approval?

    Args:
        workflow_id: The workflow ID returned by ``plan_workflow``.

    Returns:
        Dict with keys:
          - ``verdict``: ``"approved"`` if no structural issues, otherwise ``"needs_revision"``
          - ``findings``: list of {severity, kind, message, step_index}
          - ``summary``: counts (steps, gather/destructive/approval), groups, est_duration_min
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}
        return _review_workflow_impl(wf)
    except Exception as e:
        return {
            "error": str(e),
            "hint": f"Review failed for '{workflow_id}'. "
            f"Use get_workflow_status() to inspect raw state.",
        }


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="low")
def get_workflow_status(workflow_id: str) -> dict:
    """[READ] Get current workflow state, diff report, and audit log.

    Args:
        workflow_id: The workflow ID to query.

    Returns:
        Full workflow state including steps, audit log, and diff report.
    """
    try:
        wf = _get_store().load(workflow_id)
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}
        return wf.to_dict()
    except Exception as e:
        return {"error": str(e), "hint": "Use list_workflows() to see active workflow IDs."}


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="low")
def list_workflows() -> dict:
    """[READ] List all available workflow templates (built-in + custom).

    Built-in templates are always available. Custom templates are loaded
    from ~/.vmware/workflows/*.yaml — drop a YAML file there to add
    your own workflows.

    Returns:
        dict with builtin and custom workflow lists, each with name, description, steps count.
    """
    try:
        from vmware_pilot.custom_loader import list_custom_workflows
        from vmware_pilot.templates import BUILTIN_TEMPLATES

        builtin = [
            {
                "name": name,
                "type": "builtin",
                "description": (fn.__doc__ or "").split("\n")[0].strip(),
            }
            for name, fn in BUILTIN_TEMPLATES.items()
        ]
        custom = [{**c, "type": "custom"} for c in list_custom_workflows()]

        active = _get_store().list_active()

        return {
            "templates": builtin + custom,
            "active_workflows": active,
        }
    except Exception as e:
        return {"error": str(e), "hint": "Failed to list workflows."}


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@vmware_tool(risk_level="low")
def get_skill_catalog() -> dict:
    """[READ] Get the complete catalog of available skills and tools for workflow design.

    Use this to understand what building blocks are available when designing
    a custom workflow. Each skill lists its key tools with risk level and description.

    Returns:
        dict mapping skill name → {description, tools: {tool_name: {risk, desc}}}.
    """
    return SKILL_CATALOG
