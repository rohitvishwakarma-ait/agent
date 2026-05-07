# LangGraph Integration Guide

## What Was Added

`agent_graph.py` — A LangGraph-powered agent with advanced features that `agent.py` doesn't have.

---

## Key Features

### 1. **Human-in-the-Loop Approval**

**Problem in `agent.py`:** When you ask it to create a file, it writes immediately. If it misunderstands, the wrong content is already on disk.

**Solution in `agent_graph.py`:**
```bash
python agent_graph.py "create a config.json file"
```

The agent will:
1. Generate the file content
2. **PAUSE** and show you a preview
3. Ask: "Approve this write? (y/n)"
4. Only write if you say 'y'

**How it works:**
- `check_approval_needed` node detects `write_file` tool calls
- Routes to `human_approval_node` which pauses execution
- User reviews and approves/rejects
- Only then does `tools` node execute the write

---

### 2. **Automatic Retry Logic**

**Problem in `agent.py`:** If a command fails (network timeout, wrong path), the agent just returns the error and moves on.

**Solution in `agent_graph.py`:**
```bash
python agent_graph.py "curl https://api.example.com/data"
```

If the curl fails:
1. `retry_node` detects the `ERROR[...]` in the tool result
2. Automatically retries up to 2 times
3. Asks the agent to try a different approach
4. If still fails after 2 retries, explains the issue to the user

**How it works:**
- All tools return errors in format: `ERROR[TYPE]: message`
- `route_after_tools` checks for `ERROR[` in tool results
- Routes to `retry_node` which increments retry counter
- Loops back to `agent` with feedback

---

### 3. **Conditional Branching**

**Problem in `agent.py`:** Linear flow only — every step runs even if unnecessary.

**Solution in `agent_graph.py`:**

The graph has multiple paths:

```
agent
  ├─ No tools needed? → END (skip everything)
  └─ Tools needed?
       ├─ write_file? → approval → tools → agent
       └─ other tool? → tools → agent
```

**How it works:**
- `route_after_agent` checks if tools were called
- `route_after_approval_check` decides if approval is needed
- Each routing function returns a string that determines the next node

---

### 4. **Iterative Refinement Loop**

**Problem in `agent.py`:** Agent responds once and stops. If the response is bad, you have to manually ask it to improve.

**Solution in `agent_graph.py`:**

The `validator_node` checks the agent's response:
- Too short? Loop back with feedback
- Contains errors but no explanation? Loop back
- Passes validation? Continue

Maximum 3 iterations to prevent infinite loops.

**How it works:**
- `validator_node` runs validation rules
- Sets `validation_passed` to True/False
- `route_after_validation` loops back to `agent` if validation failed

---

### 5. **Persistent State (Checkpointing)**

**Problem in `agent.py`:** If you close the terminal mid-task, all progress is lost.

**Solution in `agent_graph.py`:**

```bash
# Start a task
python agent_graph.py "review all Python files and write a report"
# [agent is working...]
# [you close the terminal]

# Next day, resume exactly where you left off
python agent_graph.py --resume
```

**How it works:**
- `MemorySaver` checkpointer saves the entire graph state after each node
- State includes: messages, retry count, approval status, iteration count
- `--resume` flag loads the last checkpoint and continues

---

## Usage Examples

### Basic Usage (No Approval)
```bash
venv/bin/python agent_graph.py "check disk usage" --no-approval
```

### With Approval (Default)
```bash
venv/bin/python agent_graph.py "create a hello.py file"
# Agent generates content
# Shows preview
# Waits for your approval
```

### Disable Checkpoints (Faster)
```bash
venv/bin/python agent_graph.py "list files" --no-approval --no-checkpoints
```

### Resume After Restart
```bash
venv/bin/python agent_graph.py --resume
```

---

## Architecture Comparison

| Feature | `agent.py` | `agent_graph.py` |
|---|---|---|
| Tool execution | Immediate | Can pause for approval |
| Error handling | Returns error, moves on | Automatic retry (up to 2x) |
| Flow control | Linear only | Conditional branching |
| Validation | None | Iterative refinement loop |
| State persistence | None | Checkpointing (resume later) |
| Complexity | Simple | More complex but more powerful |

---

## The Graph Structure

```
START
  │
  ▼
agent (decides what to do)
  │
  ├─ No tools? → END
  │
  └─ Tools needed?
       │
       ▼
     check_approval (is it write_file?)
       │
       ├─ Yes → approval (human reviews) → tools
       │
       └─ No → tools (execute immediately)
              │
              ▼
            retry (did tool fail?)
              │
              ├─ Yes → agent (try again)
              │
              └─ No → agent (continue)
                     │
                     ▼
                   validator (check response quality)
                     │
                     ├─ Failed → agent (refine)
                     │
                     └─ Passed → END
```

---

## When to Use Which Agent

**Use `agent.py` when:**
- Simple, straightforward tasks
- You trust the agent completely
- Speed is more important than safety
- No need to resume later

**Use `agent_graph.py` when:**
- File writes need approval
- Tools might fail and need retries
- Complex multi-step tasks
- You might need to pause and resume
- Response quality matters (validation loop)

---

## Configuration

### Disable Approval Globally
Edit `agent_graph.py` line 393:
```python
enable_approval = "--no-approval" not in flags
# Change to:
enable_approval = False  # always disabled
```

### Change Retry Limit
Edit `agent_graph.py` line 177:
```python
if retry_count < 2:  # max 2 retries
# Change to:
if retry_count < 5:  # max 5 retries
```

### Change Validation Rules
Edit `validator_node` function (line 195) to add your own rules.

---

## Troubleshooting

**"Cannot resume without checkpoints"**
- Remove `--no-checkpoints` flag
- Checkpoints are required for `--resume`

**Agent is slow**
- Use `--no-checkpoints` for faster execution
- Checkpointing adds overhead

**Approval prompt doesn't appear**
- Make sure you didn't use `--no-approval` flag
- Only `write_file` tool triggers approval

---

## Next Steps

1. **Try it:** Run a simple task with approval enabled
2. **Test retry:** Run a command that will fail (e.g., `curl https://invalid-url`)
3. **Test resume:** Start a long task, kill it, then `--resume`
4. **Customize:** Add your own validation rules or routing logic

The graph is fully extensible — you can add new nodes, new routing logic, or new validation rules without changing the core structure.
