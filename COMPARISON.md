# Agent Comparison: agent.py vs crew.py vs agent_graph.py

## Quick Reference

| File | Purpose | Best For |
|---|---|---|
| `agent.py` | Single agent, simple tasks | Quick queries, system checks |
| `crew.py` | Multi-agent teams | Complex multi-step tasks |
| `agent_graph.py` | Single agent with advanced control | Tasks needing approval/retry/validation |

---

## Feature Matrix

| Feature | agent.py | crew.py | agent_graph.py |
|---|---|---|---|
| **Execution Model** | Single agent | 3 specialized agents per crew | Single agent with graph workflow |
| **Tools** | 7 tools | Same 7 tools | Same 7 tools |
| **Memory** | RAG (rag.store.json) | RAG + optional CrewAI memory | RAG (rag.store.json) |
| **Streaming** | ✅ Yes | ✅ Yes | ❌ No (graph-based) |
| **Human Approval** | ❌ No | ❌ No | ✅ Yes (for file writes) |
| **Retry Logic** | ❌ No | ❌ No | ✅ Yes (automatic, up to 2x) |
| **Conditional Branching** | ❌ No | ⚠️ Sequential only | ✅ Yes (dynamic routing) |
| **Validation Loop** | ❌ No | ❌ No | ✅ Yes (iterative refinement) |
| **Checkpointing** | ❌ No | ❌ No | ✅ Yes (resume after restart) |
| **Complexity** | Low | Medium | High |
| **Speed** | Fast | Slow (3 LLM calls) | Medium |

---

## Use Case Examples

### Example 1: "Check disk usage"

**agent.py:**
```bash
python agent.py "check disk usage"
# ✅ Fast, simple, one LLM call
# ⚠️  No retry if command fails
```

**crew.py:**
```bash
python crew.py devops "check disk usage"
# ⚠️  Overkill — uses 3 agents for a simple task
# ⚠️  Slow — 3 separate LLM calls
```

**agent_graph.py:**
```bash
python agent_graph.py "check disk usage" --no-approval
# ✅ Automatic retry if command fails
# ⚠️  Slightly slower due to graph overhead
```

**Winner:** `agent.py` — simplest and fastest for this task.

---

### Example 2: "Create a config.json file"

**agent.py:**
```bash
python agent.py "create a config.json file"
# ⚠️  Writes immediately, no preview
# ⚠️  If agent misunderstands, wrong content is on disk
```

**crew.py:**
```bash
python crew.py code "create a config.json file"
# ⚠️  Overkill — reviewer, fixer, tester for one file
# ⚠️  No approval step
```

**agent_graph.py:**
```bash
python agent_graph.py "create a config.json file"
# ✅ Shows preview before writing
# ✅ You approve/reject
# ✅ Safe
```

**Winner:** `agent_graph.py` — only one with human approval.

---

### Example 3: "Review agent.py, fix bugs, write tests"

**agent.py:**
```bash
python agent.py "review agent.py, fix bugs, write tests"
# ⚠️  Single agent tries to do 3 different jobs
# ⚠️  Gets confused juggling multiple concerns
# ⚠️  Output is messy
```

**crew.py:**
```bash
python crew.py code "review agent.py"
# ✅ Reviewer finds bugs
# ✅ Fixer fixes them
# ✅ Tester writes tests
# ✅ Each agent focused on one job
# ✅ Structured output
```

**agent_graph.py:**
```bash
python agent_graph.py "review agent.py, fix bugs, write tests"
# ⚠️  Single agent, same confusion as agent.py
# ✅ But has approval for file writes
# ✅ And retry if tools fail
```

**Winner:** `crew.py` — designed for multi-step tasks with specialists.

---

### Example 4: "Research Python 3.13 and write a report"

**agent.py:**
```bash
python agent.py "research Python 3.13 and write a report"
# ⚠️  Returns raw search results
# ⚠️  No analysis or structure
```

**crew.py:**
```bash
python crew.py research "Python 3.13 new features"
# ✅ Researcher gathers info
# ✅ Analyst structures it
# ✅ Writer produces clean markdown report
# ✅ Saved to disk automatically
```

**agent_graph.py:**
```bash
python agent_graph.py "research Python 3.13 and write a report"
# ⚠️  Single agent, same as agent.py
# ✅ But has approval before writing report
```

**Winner:** `crew.py` — research crew is purpose-built for this.

---

### Example 5: "curl https://api.example.com (might fail)"

**agent.py:**
```bash
python agent.py "curl https://api.example.com"
# ⚠️  If it fails, just returns error
# ⚠️  No retry
```

**crew.py:**
```bash
python crew.py devops "curl https://api.example.com"
# ⚠️  No retry logic
# ⚠️  Overkill for one command
```

**agent_graph.py:**
```bash
python agent_graph.py "curl https://api.example.com" --no-approval
# ✅ If it fails, automatically retries
# ✅ Tries different approach
# ✅ Up to 2 retries
```

**Winner:** `agent_graph.py` — only one with automatic retry.

---

## Decision Tree

```
What do you need?
│
├─ Simple query (disk usage, date, list files)
│  → Use agent.py
│
├─ Multi-step task with specialists (review→fix→test, research→analyze→write)
│  → Use crew.py
│
├─ File write that needs approval
│  → Use agent_graph.py
│
├─ Command that might fail and needs retry
│  → Use agent_graph.py
│
├─ Long task you might need to pause and resume
│  → Use agent_graph.py
│
└─ Complex task with validation loop
   → Use agent_graph.py
```

---

## Performance Comparison

**Speed (fastest to slowest):**
1. `agent.py` — 1 LLM call, no overhead
2. `agent_graph.py` — 1-3 LLM calls (depends on retries/validation)
3. `crew.py` — 3+ LLM calls (one per agent)

**Safety (safest to riskiest):**
1. `agent_graph.py` — approval + retry + validation
2. `crew.py` — specialists reduce errors
3. `agent.py` — no safety features

**Complexity (simplest to most complex):**
1. `agent.py` — ~300 lines, straightforward
2. `crew.py` — ~650 lines, multi-agent orchestration
3. `agent_graph.py` — ~450 lines, graph workflow

---

## Combining Them

You can use all three in the same project:

```bash
# Quick system check
python agent.py "check RAM usage"

# Complex code review
python crew.py code "review and improve agent.py"

# Sensitive file operation
python agent_graph.py "create production config" 
```

Each tool has its place. Choose based on the task requirements.

---

## Summary

- **agent.py** = Swiss Army knife (fast, simple, good for most things)
- **crew.py** = Specialist team (slow but thorough for complex tasks)
- **agent_graph.py** = Safety-first (approval, retry, validation)

All three share the same tools and RAG memory, so they're complementary, not competing.
