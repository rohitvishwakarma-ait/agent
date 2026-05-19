# LangGraph Implementation Notes

## What Was Built

`agent_graph.py` — A LangGraph-powered coding agent built in two phases.

---

## Phase 1 (Original)

### Features Added
1. Human-in-the-loop approval for file writes
2. Automatic retry logic (up to 2x on tool failure)
3. Conditional branching (dynamic routing)
4. Validation loop (iterative refinement, max 3 iterations)
5. Checkpointing via `MemorySaver`

### Verified Working
- File write approval: shows preview, waits for y/n
- Retry: detects `ERROR[...]` in tool results, loops back
- Branching: skips approval for non-write tools
- Checkpointing: `--resume` flag loads last state

---

## Phase 2 (New)

### Features Added
6. **Test → Fix loop** — runs pytest after code edits, auto-fixes failures
7. **Multi-file planning** — `--plan` flag shows structured plan before acting
8. **Git write operations** — `git_write` tool (stage/commit/branch with approval)

### New Tools
- `edit_file` — surgical str_replace (safer than write_file for edits)
- `run_tests` — runs pytest, returns pass/fail + details
- `git_write` — git stage/commit/branch with human approval

### New Nodes
- `planner_node` — generates implementation plan, asks user to approve
- `test_runner_node` — runs pytest, feeds failures back to agent

---

## Cloudflare Compatibility

**Problem:** Cloudflare Workers AI rejects OpenAI-style tool schemas (`array` content type).

**Solution:** In Cloudflare mode (`USE_TEXT_TOOLS=True`):
- Tools described as plain text in system prompt
- Model responds with `TOOL_CALL: name` / `INPUT: {...}` format
- `agent_node` parses and executes tools directly (no LangGraph ToolNode)
- Multi-turn loop (up to 6 turns) handles `read_file → edit_file → run_tests` sequences

---

## Flags Reference

```
--no-approval     skip human approval for write_file and git_write
--no-checkpoints  disable MemorySaver (faster, no resume)
--plan            show implementation plan before acting
--no-tests        skip pytest verification after code edits
--resume          resume last checkpointed task
```

---

## Performance

| Scenario | Nodes visited | Approx time |
|---|---|---|
| Simple query (no tools) | agent | 3-5s |
| Shell command | agent → check_approval → tools → agent | 8-12s |
| Code edit with tests | agent → tools → run_tests → agent | 20-40s |
| Code edit with plan | planner → agent → tools → run_tests | 30-60s |

---

## Known Limitations

- Checkpointing is in-memory only (`MemorySaver`) — lost on process exit
  - For persistence: switch to `SqliteSaver`
- Cloudflare approval is skipped (tools execute directly in agent_node)
- `run_tests` requires pytest installed in venv (`venv/bin/pip install pytest`)
