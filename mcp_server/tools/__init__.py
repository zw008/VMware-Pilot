"""Pilot MCP tool definitions, grouped by concern.

Importing this package registers every tool onto the shared ``mcp`` instance
in ``mcp_server._shared`` via the module-level ``@mcp.tool`` decorators.
"""

from __future__ import annotations

from mcp_server.tools import authoring, lifecycle, query

__all__ = ["authoring", "lifecycle", "query"]
