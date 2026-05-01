# vmware-pilot Architecture Audit — 2026-04-30

Audit triggered by Enterprise Harness Engineering article series (Linkloud × addxai). Question: is pilot using the v1 (persistent agent + SendMessage) or v2 (Dispatcher + one-shot subagent) pattern?

## Verdict

**Pilot is already v2-aligned.** No refactor needed. The core architecture is sound.

## Evidence

### v2 properties present

| v2 property | Where it lives in pilot |
|---|---|
| Stateless MCP surface | All MCP tools (`plan_workflow`, `run_workflow`, `approve`, `rollback`) return immediately |
| State externalized | `vmware_pilot/models.py::WorkflowStore` — SQLite-backed |
| Dispatcher tracks status only | `vmware_pilot/executor.py::WorkflowExecutor.run_until_checkpoint` exits on checkpoint, failure, or completion |
| One-shot subagent semantics | The AI agent is the subagent — pilot returns the plan, the agent executes per-step by calling other skills' MCP tools |
| Approval gates as state transitions | `WorkflowState.AWAITING_APPROVAL` |
| Reasoning centralized, not per-step | Templates encode the full plan up front; per-step dispatch is mechanical |

### v1 anti-patterns NOT present

- No `asyncio` / background loops / long-running agent processes
- No `SendMessage` / inter-agent message passing
- No persistent agent threads
- No shared mutable agent state outside SQLite

## Gaps vs the article's full v2 model

These are **additive** gaps, not refactor blockers. The core dispatcher pattern is correct.

### G1. No Investigation Subagent equivalent

The article's v2 has an Investigation Subagent with internal state machine (rapid-assessment → gather → causal-chain → completeness-check → optional-deepen → report).

Pilot's existing templates are hardcoded recipes (clone_and_test, incident_response, etc.) — none do open-ended investigation against the four root-cause criteria.

**Proposal**: add an `investigate_alert` template that:

1. Parallel gather: aria_metrics + monitor_alarms + monitor_events
2. Form causal chain hypothesis (delegated to AI agent)
3. Validate against the four criteria from `investigation-protocol.md`
4. If incomplete → auto-deepen up to 3 rounds
5. Output structured report

This effectively codifies the investigation protocol as a workflow.

### G2. No Review Subagent

The article's v2 has a Review Subagent with 23 checkpoints between plan and run.

Pilot relies on the human to review the plan. For agent-only autonomous flows, no automated quality gate exists.

**Proposal**: add an optional `review_workflow(workflow_id)` MCP tool that runs sanity checks before execution:

- Targets in `params` exist (resolve via skill MCP `*_list` calls)
- No conflicting steps (e.g., delete X then operate on X)
- Risk/cost rollup (sum of step risks)
- Estimated duration
- Returns `verdict: approved | needs_revision` with itemized findings

### G3. Sequential steps only — no parallel gather

`executor.py::run_until_checkpoint` iterates steps one-by-one. Investigation workflows benefit from parallel data gathering across skills.

**Proposal**: add a `parallel_group` step type that dispatches N steps concurrently and waits for all before continuing. Failures inside a group halt the workflow same as a single step.

### G4. No L5 pattern extraction

Tracked as separate task (B2 — iSCSI rescan PoC). Pattern Extraction Subagent would observe successful executions in audit.db and propose auto-remediation candidates.

### G5. Implicit dispatch contract

`executor.py::WorkflowExecutor.__init__` defaults `dispatch=_noop_dispatch`. In production, the AI agent is the de-facto dispatcher: it reads the plan from `run_workflow`'s response, calls per-step MCP tools itself, and the user observes the orchestration via the chat history.

This works but isn't documented anywhere. New users (and new agents) cannot tell from the code that they need to "drive" pilot.

**Proposal**: add a docstring + a section in `references/integration-patterns.md` clarifying the dispatch contract: "pilot returns plans; the calling AI agent executes them; pilot tracks state via approve/rollback."

## Recommendations — Priority Order

1. **G5 (docs only)** — 30 minutes. No risk. Clarifies the contract for users and agents.
2. **G1 (investigate_alert template)** — 1-2 days. Codifies investigation-protocol.md as a workflow. High value for diagnostic use cases.
3. **G2 (review_workflow tool)** — 2-3 days. Adds a safety gate; useful but not blocking.
4. **G3 (parallel_group step)** — 2-3 days. Performance optimization; only valuable if G1 ships first.
5. **G4 (L5 pattern extraction)** — Tracked as B2.

## Conclusion

No urgent refactor. Pilot's foundation is correct. The article's "v1 → v2" migration was about getting OUT of the persistent-agent + SendMessage trap; pilot was never in that trap. The remaining gaps are additive features, not architectural debt.
