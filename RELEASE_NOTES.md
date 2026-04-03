# VMware Pilot — Release Notes

## v1.4.5 — 2026-04-03

- **Security**: bump pygments 2.19.2 → 2.20.0 (fix ReDoS CVE in GUID matching regex)
- **Infrastructure**: add uv.lock for reproducible builds and Dependabot security tracking

## v1.4.0 — 2026-03-29

Initial release. Multi-step workflow orchestration with approval gates for VMware MCP skills.

- 11 MCP tools: design/plan/create/run/approve/rollback/status + discovery
- 4 built-in workflow templates: clone_and_test, incident_response, plan_and_approve, compliance_scan
- Interactive design mode: natural language → draft → edit → confirm → execute
- Custom YAML templates: drop in ~/.vmware/workflows/, hot-reload without restart
- State persistence: SQLite at ~/.vmware/workflows.db, survives restarts
- Approval gates: pause execution for human review before destructive operations
- Rollback: reverse completed steps in order on failure
- Skill catalog: 7 skills, 162 tools available for workflow composition
- blocked_by_policy state: mid-workflow policy denial without auto-rollback
- 32 unit tests
