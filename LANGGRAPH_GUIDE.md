# LangGraph Agent Guide

## What agent_graph.py Does

`agent_graph.py` is a LangGraph-powered coding agent with two phases of features:

- **Phase 1** — Human approval, retry logic, validation, checkpointing
- **Phase 2** — Test→fix loop, multi-file planning, git write operations

---

## Phase 1 Features

### 1. Human-in-the-Loop Approval

Pauses before any `write_file` or `git_write` operation and shows a preview:

```
🚨 FILE WRITE APPROVAL REQUIRED
Path: config.json
Content preview:
------------------------------------------------------------
{"debug": true, "port": 8080}
------------------------------------------------------------

Approve? (y/n): _
```

Disable with `--no-approval` for non-sensitive tasks.

---

### 2. Automatic Retry Logic

If a tool returns `ERROR[...]`, the retry node:
1. Detects the error
2. Feeds it back to the agent with "try a different approach"
3. Retries up to 2 times
4. After max retries, explains the issue to the user

---

### 3. Conditional Branching

The graph routes dynamically based on what the agent does:

```
agent
  ├─ No tools called? → END
  └─ Tools called?
       ├─ write_file or git_write? → approval → tools
       └─ other tool? → tools directly
              ↓
           retry (if error)
              ↓
           agent (continue)
```

---

### 4. Validation Loop

After the agent responds, `validator_node` checks:
- Response too short (< 10 chars)? → loop back with feedback
- Mentions ERROR but doesn't explain? → loop back
- Passes? → end

Maximum 3 iterations.

---

### 5. Checkpointing

```bash
# Start a task
python agent_graph.py "complex task"
# [Ctrl+C to interrupt]

# Resume exactly where you left off
python agent_graph.py --resume
```

Uses `MemorySaver` (in-memory). For persistence across restarts, switch to `SqliteSaver`.

---

## Phase 2 Features

### 6. Test → Fix Loop

After any code edit, the agent automatically:
1. Runs `pytest` on the project
2. If tests fail → feeds failure details back to agent
3. Agent fixes the code using `edit_file`
4. Runs tests again
5. Repeats up to 3 times

```bash
python agent_graph.py "fix the bug in rag.py"
# → edits rag.py
# → runs pytest
# → if tests fail, fixes and retries
# → stops when tests pass or max attempts reached
```

Disable with `--no-tests`.

---

### 7. Multi-File Planning

Before touching any code, the agent produces a structured plan:

```
📋 IMPLEMENTATION PLAN
============================================================
PLAN:
1. File: rag.py    Action: edit    Reason: add cleanup method
2. File: agent.py  Action: edit    Reason: call cleanup on load

SUMMARY: Add RAG store cleanup to prevent unbounded growth

Approve this plan? (y/n/edit): _
```

You can approve, reject, or edit the plan before execution begins.

Enable with `--plan` flag.

---

### 8. Git Write Operations

The `git_write` tool supports:
- `git_write(action="branch", branch="feature-x")` — create branch
- `git_write(action="stage", files="rag.py")` — stage files
- `git_write(action="commit", message="fix: add cleanup")` — commit

All git writes require human approval (same approval flow as file writes).

---

## Cloudflare Multi-Tool Support

In Cloudflare mode, `agent_node` runs a multi-turn loop (up to 6 turns):

```
Turn 1: model says TOOL_CALL: read_file → execute → feed result back
Turn 2: model says TOOL_CALL: edit_file → execute → feed result back
Turn 3: model says TOOL_CALL: run_tests → execute → feed result back
Turn 4: model says FINAL_ANSWER: done → break loop
```

This enables multi-step coding workflows on Cloudflare without native tool-calling support.

---

## Usage

```bash
# Basic — with tests, with approval
python agent_graph.py "fix the bug in rag.py"

# With planning
python agent_graph.py "add error handling to agent.py" --plan

# Skip tests (for non-code tasks)
python agent_graph.py "check disk usage" --no-tests --no-approval

# Skip approval (for trusted tasks)
python agent_graph.py "list files" --no-approval --no-checkpoints

# Resume last task
python agent_graph.py --resume

# All flags
python agent_graph.py "task" --plan --no-approval --no-tests --no-checkpoints
```

---

## Graph Structure

```
START
  │
  ▼
[planner] (if --plan)
  │
  ▼
[agent] ← LLM decides what to do
  │
  ├─ No tools? → END
  │
  └─ Tools needed?
       │
       ▼
  [check_approval]
       │
       ├─ write_file/git_write? → [approval] → [tools]
       └─ other? → [tools]
              │
              ▼
           [retry] (if ERROR[...])
              │
              └─ → [agent] (try again)
              │
              ▼ (no error)
           [agent]
              │
              ├─ code changed? → [run_tests]
              │       │
              │       ├─ tests failed? → [agent] (fix)
              │       └─ tests passed? → END
              │
              └─ no code change? → END
```

---

## Tools Available

| Tool | Purpose |
|---|---|
| `run_shell` | Shell commands |
| `read_file` | Read files |
| `write_file` | Create new files (requires approval) |
| `edit_file` | Surgical str_replace edits |
| `list_directory` | List files/folders |
| `run_tests` | Run pytest and return results |
| `git_write` | Stage/commit/branch (requires approval) |

---

## Configuration

### Change retry limit
```python
# In retry_node:
if retry_count < 2:  # change to 5 for more retries
```

### Change test fix attempts
```python
# In route_after_tests:
if state.get("fix_attempts", 0) >= 3:  # change limit
```

### Add custom validation rules
```python
# In validator_node, add your own checks:
if "TODO" in content:
    return {"validation_passed": False, "messages": [...]}
```
