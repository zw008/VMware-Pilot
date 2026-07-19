"""Read-only mode must remove write tools from the real FastMCP registry.

Regression source: VMware-AIops issue #31 (juanpf-ha). An operator driving the
family with a local Llama 3.3 70B had to hand-write the prompt instruction
"work exclusively in read-only mode and never modify alerts, definitions,
reports or configuration", because read-only was only ever a documented
intent. A weak model can ignore a prompt; it cannot call a tool that is not in
list_tools().

vmware_policy/tests/test_readonly.py pins the gate's *semantics* against a
stand-in registry. This file pins the other half: that the real FastMCP API the
gate reaches for still behaves as assumed, and that this skill's actual tool
inventory splits the way its docs claim.

vmware-pilot orchestrates multi-step workflows, so most of its surface mutates
state: plan/run/approve/rollback/cancel and the whole authoring flow. The write
set is *derived* from the live registry's [READ]/[WRITE] docstring markers
rather than hard-coded, so adding a tool cannot silently escape the gate.
"""

import asyncio
import importlib
import sys

import pytest


def _load_server(monkeypatch, read_only):
    """Import vmware_pilot.mcp_server.server fresh under the given read-only env."""
    monkeypatch.delenv("VMWARE_READ_ONLY", raising=False)
    monkeypatch.delenv("VMWARE_PILOT_READ_ONLY", raising=False)
    if read_only is not None:
        monkeypatch.setenv("VMWARE_READ_ONLY", read_only)

    for name in [m for m in sys.modules if m.startswith("vmware_pilot.mcp_server")]:
        del sys.modules[name]
    return importlib.import_module("vmware_pilot.mcp_server.server")


def _tools(server):
    return asyncio.run(server.mcp.list_tools())


def _tool_names(server):
    return {t.name for t in _tools(server)}


def _split_by_marker(server):
    """Derive (read, write) tool names from the live [READ]/[WRITE] markers."""
    read, write = set(), set()
    for tool in _tools(server):
        description = (tool.description or "").lstrip()
        if description.startswith("[WRITE]"):
            write.add(tool.name)
        elif description.startswith("[READ]"):
            read.add(tool.name)
        else:  # pragma: no cover — a marker-less tool is a docs bug
            pytest.fail(f"tool {tool.name} has no [READ]/[WRITE] marker")
    return read, write


@pytest.fixture(autouse=True)
def _restore_modules():
    """Put back the exact module objects other test files already hold.

    Deleting them is not enough here: ``vmware_pilot.mcp_server._shared`` re-imports
    ``vmware_pilot.mcp_server.server`` lazily on every tool call so that
    ``monkeypatch.setattr(server, "_store", ...)`` is honoured. If this file
    leaves the modules purged, tests/test_server.py patches its stale module
    object while the tools resolve a freshly imported one, and its store
    patches silently stop taking effect.
    """
    saved = {n: m for n, m in sys.modules.items() if n.startswith("vmware_pilot.mcp_server")}
    yield
    for name in [m for m in sys.modules if m.startswith("vmware_pilot.mcp_server")]:
        del sys.modules[name]
    sys.modules.update(saved)


def test_default_mode_exposes_write_tools(monkeypatch):
    """Baseline: without the switch every tool is present."""
    server = _load_server(monkeypatch, None)
    _, write_tools = _split_by_marker(server)
    assert write_tools, "expected vmware-pilot to have write tools"
    assert write_tools <= _tool_names(server)
    assert server.WITHHELD_WRITE_TOOLS == []


def test_read_only_removes_every_write_tool(monkeypatch):
    _, write_tools = _split_by_marker(_load_server(monkeypatch, None))
    server = _load_server(monkeypatch, "true")
    survivors = _tool_names(server)
    assert not (write_tools & survivors), (
        f"write tools survived: {sorted(write_tools & survivors)}"
    )


def test_read_only_keeps_read_tools(monkeypatch):
    """The gate must not be a blunt instrument — reads still work."""
    read_tools, _ = _split_by_marker(_load_server(monkeypatch, None))
    server = _load_server(monkeypatch, "true")
    assert read_tools <= _tool_names(server)
    for tool in ("list_workflows", "get_workflow_status", "get_skill_catalog"):
        assert tool in _tool_names(server)


def test_withheld_list_is_reported(monkeypatch):
    """Startup must be able to tell the operator what was withheld."""
    _, write_tools = _split_by_marker(_load_server(monkeypatch, None))
    server = _load_server(monkeypatch, "true")
    assert set(server.WITHHELD_WRITE_TOOLS) == write_tools


def test_every_surviving_tool_is_marked_read(monkeypatch):
    """End-to-end contract against the live registry."""
    server = _load_server(monkeypatch, "true")
    for tool in _tools(server):
        assert (tool.description or "").lstrip().startswith("[READ]"), tool.name


def test_skill_env_var_also_works(monkeypatch):
    _, write_tools = _split_by_marker(_load_server(monkeypatch, None))

    monkeypatch.delenv("VMWARE_READ_ONLY", raising=False)
    monkeypatch.setenv("VMWARE_PILOT_READ_ONLY", "true")
    for name in [m for m in sys.modules if m.startswith("vmware_pilot.mcp_server")]:
        del sys.modules[name]
    server = importlib.import_module("vmware_pilot.mcp_server.server")
    assert not (write_tools & _tool_names(server))


def test_fastmcp_registry_api_still_present(monkeypatch):
    """The gate reaches into _tool_manager.list_tools(); pin that it exists.

    If an mcp upgrade moves this, we want a red test here rather than a gate
    that silently stops removing anything.
    """
    server = _load_server(monkeypatch, None)
    assert callable(getattr(server.mcp, "remove_tool", None))
    assert callable(getattr(server.mcp._tool_manager, "list_tools", None))
    assert server.mcp._tool_manager.list_tools()
