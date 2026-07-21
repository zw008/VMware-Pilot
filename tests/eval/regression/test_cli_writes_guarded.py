"""Every Pilot write routes through vmware_policy — guard() + audit_call() (HLD I-1, I-8).

The family rollout wires @guarded onto CLI write commands so a write run through
Bash is authorized and audited to ~/.vmware/audit.db exactly like its MCP twin.
Pilot's shape makes this a two-part invariant with a twist worth stating up front:

  * Pilot has NO CLI write surface. ``vmware_pilot/cli.py`` is launch-only by
    design (``version`` + ``mcp``); it holds no vCenter connection and mutates
    nothing. There is therefore no CLI command to carry @guarded — and putting it
    on a non-write command would be wrong. So this file instead asserts the CLI
    stays launch-only: if a state-changing command is ever added it MUST be
    @guarded (``test_cli_has_no_unguarded_write_command``).

  * Pilot's real write surface is its MCP tools. The nine tools annotated
    ``readOnlyHint=False`` (plan / run / approve / rollback / cancel + the four
    authoring tools) each route through policy via ``@vmware_tool`` — the same
    guard() + audit_call() core @guarded gives the CLI on the vSphere skills.
    That is the actual I-1 enforcement for Pilot and the primary assertion here
    (``test_every_write_tool_routes_through_policy``).

The write set is DERIVED from the live server, never hand-listed (踩坑 #43): a
tool annotated ``readOnlyHint=False`` is a write. A derivation that silently
returns empty is worse than none (error-shape #1), so both tests floor the
derived count and pin real names before asserting the guard is present.

Unlike the vSphere skills, Pilot has no ``ops/`` layer — its write tools call the
workflow executor/store directly — so the MCP→ops→CLI mapping the sibling I-1
tests use does not apply here and is deliberately omitted.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[3]
PKG_DIR = _REPO / "vmware_pilot"
CLI_FILE = PKG_DIR / "cli.py"
TOOLS_DIR = PKG_DIR / "mcp_server" / "tools"
assert CLI_FILE.is_file(), f"CLI module not found at {CLI_FILE} — the scan would find nothing"
assert TOOLS_DIR.is_dir(), f"MCP tools not found at {TOOLS_DIR} — the derivation would be empty"

#: Executor/store method calls that mutate workflow state (write to
#: ~/.vmware/workflows.db). A CLI command that invokes one of these — or a write
#: MCP tool by name — is performing a workflow write and must carry @guarded.
_WRITE_METHODS = frozenset(
    {"run_until_checkpoint", "resume_after_approval", "rollback", "cancel", "save"}
)


def _write_tool_names() -> frozenset[str]:
    """Write MCP tools, derived live from the server (``readOnlyHint=False``).

    Same mechanism the suite already uses to enumerate tools
    (``test_server.test_expected_tools_exposed``): ``asyncio.run(mcp.list_tools())``.
    """
    from vmware_pilot.mcp_server.server import mcp

    return frozenset(
        t.name
        for t in asyncio.run(mcp.list_tools())
        if getattr(getattr(t, "annotations", None), "readOnlyHint", None) is False
    )


def _decorator_names(node: ast.FunctionDef) -> set[str]:
    """Names of every decorator on ``node`` (``@name`` and ``@obj.name(...)``)."""
    names: set[str] = set()
    for d in node.decorator_list:
        t = d.func if isinstance(d, ast.Call) else d
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, ast.Attribute):
            names.add(t.attr)
    return names


def _referenced_names(node: ast.AST) -> set[str]:
    """Every bare name and attribute tail referenced anywhere under ``node``."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _command_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    """FunctionDefs decorated with ``@<app>.command(...)`` (Typer commands)."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(d, ast.Call)
            and isinstance(getattr(d, "func", None), ast.Attribute)
            and d.func.attr == "command"
            for d in node.decorator_list
        )
    ]


def _write_tools_missing_guard(write: frozenset[str]) -> list[str]:
    """Write MCP tool functions in ``tools/*.py`` that lack ``@vmware_tool``."""
    missing: list[str] = []
    seen: set[str] = set()
    for path in sorted(TOOLS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in write:
                seen.add(node.name)
                if "vmware_tool" not in _decorator_names(node):
                    missing.append(node.name)
    # A scan that never located the tool functions is a broken check, not a clean
    # bill of health (error-shape #1) — fail loudly if the AST and the live
    # server disagree on the write set instead of reporting green on nothing.
    assert seen == set(write), (
        f"AST scan of {TOOLS_DIR} found write tools {sorted(seen)} but the live "
        f"server derived {sorted(write)} — the paths are out of sync"
    )
    return missing


def _cli_write_commands(write: frozenset[str]) -> tuple[list[str], list[str]]:
    """(all CLI command names, those that perform a write but lack @guarded)."""
    vocab = set(write) | set(_WRITE_METHODS)
    tree = ast.parse(CLI_FILE.read_text(encoding="utf-8"))
    commands = _command_functions(tree)
    all_names = [c.name for c in commands]
    unguarded = [
        c.name
        for c in commands
        if (_referenced_names(c) & vocab) and "guarded" not in _decorator_names(c)
    ]
    return all_names, unguarded


def test_every_write_tool_routes_through_policy():
    """The write MCP tools each carry ``@vmware_tool`` (guard + audit) — HLD I-1.

    This is Pilot's real write-enforcement surface. Removing @vmware_tool from a
    write tool, or adding a write tool without it, turns this red.
    """
    write = _write_tool_names()
    assert len(write) >= 8, (
        f"only {len(write)} write MCP tools derived ({sorted(write)}) — the "
        f"readOnlyHint derivation is likely stale; a check matching almost "
        f"nothing is worse than none (踩坑 #43)."
    )
    for must in ("approve", "rollback"):
        assert must in write, (
            f"{must} is no longer derived as a write tool — the readOnlyHint "
            f"derivation stopped resolving it"
        )
    missing = _write_tools_missing_guard(write)
    assert not missing, (
        f"these write MCP tools are not wrapped by @vmware_tool, so they bypass "
        f"policy guard + audit (HLD I-1): {missing}"
    )


def test_cli_has_no_unguarded_write_command():
    """Pilot's CLI is launch-only; any future state-changing command needs @guarded.

    Derived, never hand-listed: a CLI command that calls a write MCP tool or a
    workflow store/executor mutator is a write and must carry @guarded (the CLI
    twin of the @vmware_tool guard on the MCP surface). Today the CLI holds only
    ``version`` + ``mcp`` and derives zero writes — this exists so a write CLI
    command added later cannot ship ungated.
    """
    write = _write_tool_names()
    commands, unguarded = _cli_write_commands(write)
    # Prove the scan actually parsed the CLI (error-shape #1: an empty result
    # from a broken path must not read as "all clear").
    assert {"version_cmd", "mcp_cmd"} <= set(commands), (
        f"CLI command scan found {commands} — expected at least version_cmd and "
        f"mcp_cmd; the parse or path is broken"
    )
    assert not unguarded, (
        f"these CLI commands perform a workflow write but are not @guarded, so "
        f"they bypass policy + audit (HLD I-1): {unguarded}"
    )
