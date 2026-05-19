# Agent Comparison

## Quick Reference

| File | Purpose | Best For |
|---|---|---|
| `agent.py` | Single agent, 12 tools, streaming | Quick queries, coding, system checks |
| `crew.py` | Multi-agent teams, 3 crews | Complex multi-step tasks with specialists |
| `agent_graph.py` | Graph workflow, approval, test loop | Coding tasks, sensitive ops, verification |

---

## Feature Matrix

| Feature | agent.py | crew.py | agent_graph.py |
|---|---|---|---|
| **Tools** | 12 | 7 | 7 |
| **Streaming** | ✅ (Ollama) / simulated (CF) | ✅ | ❌ |
| **Human approval** | ❌ | ❌ | ✅ |
| **Error recovery** | ✅ retry + backoff | ❌ | ✅ retry |
| **Test → fix loop** | ❌ | ❌ | ✅ |
| **Multi-file planning** | ❌ | ❌ | ✅ `--plan` |
| **Git writes** | ❌ | ❌ | ✅ with approval |
| **Validation loop** | ❌ | ❌ | ✅ |
| **Checkpointing** | ❌ | ❌ | ✅ |
| **Multi-agent** | ❌ | ✅ 9 specialists | ❌ |
| **RAG memory** | ✅ | ❌ | ❌ |
| **Session memory** | ✅ session.json | ❌ | ❌ |
| **Token tracking** | ✅ | ❌ | ❌ |
| **Project context** | ✅ auto-loads README | ❌ | ❌ |
| **Cloudflare support** | ✅ | ✅ | ✅ |
| **Speed** | ⚡ Fast | 🐌 Slow | ⚡ Medium |

---

## Use Case Examples

### "Check disk usage"
```bash
python agent.py "check disk usage"          # ✅ Best — fast, simple
python agent_graph.py "check disk usage" --no-tests --no-approval  # works too
python crew.py devops "check disk usage"    # ⚠️ overkill
```
**Winner:** `agent.py`

---

### "Add a docstring to the run_task function in agent.py"
```bash
python agent.py "add a docstring to run_task in agent.py"
# ✅ Uses extract_symbol → edit_file workflow
# ✅ Token-efficient (extracts only the function, not whole file)

python agent_graph.py "add docstring to run_task in agent.py" --plan
# ✅ Shows plan first, then edits, then runs tests
```
**Winner:** `agent_graph.py --plan` for safety, `agent.py` for speed

---

### "Review agent.py, fix bugs, write tests"
```bash
python crew.py code "review agent.py and fix bugs"
# ✅ Reviewer → Fixer → Tester pipeline
# ✅ Each agent focused on one job

python agent_graph.py "review agent.py" --plan
# ✅ Plans first, edits surgically, runs tests automatically
```
**Winner:** `crew.py` for structured review, `agent_graph.py` for automated test verification

---

### "Research Python 3.13 and write a report"
```bash
python crew.py research "Python 3.13 new features"
# ✅ Researcher → Analyst → Writer pipeline
# ✅ Structured markdown report saved to disk
```
**Winner:** `crew.py research`

---

### "Fix the failing test in rag.py"
```bash
python agent_graph.py "fix the failing test in rag.py" --plan
# ✅ Shows plan before touching files
# ✅ Edits file surgically
# ✅ Runs pytest automatically after edit
# ✅ If tests still fail, loops back to fix again (up to 3 attempts)
```
**Winner:** `agent_graph.py`

---

### "Fetch the LangChain docs and summarize tool calling"
```bash
python agent.py "fetch https://python.langchain.com/docs/concepts/tools/ and summarize tool calling"
# ✅ Uses fetch_url tool to get full page content
# ✅ Summarizes and answers
```
**Winner:** `agent.py`

---

## Decision Tree

```
What do you need?
│
├─ Quick query (disk, date, RAM, list files)
│  → agent.py
│
├─ Coding task (add feature, fix bug, add docstring)
│  ├─ Need test verification → agent_graph.py --plan
│  └─ Quick edit → agent.py
│
├─ Multi-step with specialists (review→fix→test, research→analyze→write)
│  → crew.py
│
├─ Sensitive file write (need approval + preview)
│  → agent_graph.py
│
├─ Command that might fail (need retry)
│  → agent_graph.py
│
├─ Long task you might pause and resume
│  → agent_graph.py --no-checkpoints removed
│
└─ Fetch and read a full webpage
   → agent.py (fetch_url tool)
```

---

## Performance

**Speed (fastest to slowest):**
1. `agent.py` — 1-2 LLM calls, streaming
2. `agent_graph.py` — 2-4 LLM calls (graph overhead)
3. `crew.py` — 3+ LLM calls (one per agent)

**Safety (safest to riskiest):**
1. `agent_graph.py` — approval + retry + test loop + validation
2. `crew.py` — specialists reduce errors
3. `agent.py` — error recovery but no approval

**Tools available:**
1. `agent.py` — 12 tools (most complete)
2. `agent_graph.py` — 7 tools
3. `crew.py` — 7 tools

---

## Summary

- **agent.py** = Daily driver (fast, 12 tools, memory, session continuity)
- **crew.py** = Specialist team (slow but thorough, multi-agent pipeline)
- **agent_graph.py** = Safety-first coding agent (approval, test loop, planning)

All three support Ollama, Cloudflare, OpenAI, and Groq via `LLM_PROVIDER` in `.env`.
