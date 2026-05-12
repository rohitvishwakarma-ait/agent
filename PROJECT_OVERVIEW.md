# Project Overview — Complete Architecture

## What You Built

A complete AI agent system with **3 architectures**, **12 tools**, **multi-provider LLM support**, **persistent memory**, and **Claude Code-like editing capabilities**.

---

## The Complete Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    CUSTOM AI AGENT PROJECT                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  agent.py    │  │  crew.py     │  │   agent_graph.py     │  │
│  │              │  │              │  │                      │  │
│  │ 12 tools     │  │ 3 crews      │  │ Phase 1+2 features   │  │
│  │ Streaming    │  │ 9 agents     │  │ Test→fix loop        │  │
│  │ RAG + session│  │ Multi-step   │  │ Planning + approval  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                  │                      │              │
│         └──────────────────┴──────────────────────┘              │
│                            │                                     │
│                            ▼                                     │
│         ┌──────────────────────────────────────────┐            │
│         │           SHARED COMPONENTS               │            │
│         ├──────────────────────────────────────────┤            │
│         │                                           │            │
│         │  llm_config.py — Unified LLM provider    │            │
│         │  ├─ Ollama (local, free)                  │            │
│         │  ├─ Cloudflare Workers AI                 │            │
│         │  ├─ OpenAI GPT                            │            │
│         │  ├─ Anthropic Claude                      │            │
│         │  ├─ Google Gemini                         │            │
│         │  └─ Groq                                  │            │
│         │                                           │            │
│         │  rag.py — Memory System                   │            │
│         │  ├─ rag.store.json (vector store)         │            │
│         │  ├─ Vector search (cosine similarity)     │            │
│         │  ├─ Keyword fallback (Ollama down)        │            │
│         │  └─ Auto-cleanup (30 day expiry)          │            │
│         │                                           │            │
│         │  session.json — Short-term memory         │            │
│         │  └─ Last 20 messages across runs          │            │
│         └───────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## agent.py — The Daily Driver

```
Architecture: Single ReAct Agent (LangChain)
Tools: 12
Memory: RAG (long-term) + session.json (short-term)
Providers: All 6 (Ollama, Cloudflare, OpenAI, Anthropic, Gemini, Groq)

Tools:
  Standard:       run_shell, read_file, write_file, list_directory,
                  web_search, http_request, git_tool
  Phase 1 (code): index_codebase, edit_file, preview_diff
  Phase 3 (polish): extract_symbol, fetch_url

Phase 3 features:
  ✅ extract_symbol — AST-based function extraction (90% token savings)
  ✅ Project-aware startup (auto-loads README + file structure)
  ✅ Session tracker (/session command)
  ✅ Token/cost tracking
  ✅ Error recovery (retry with exponential backoff)
  ✅ RAG fallback to keyword search when Ollama is down
  ✅ Session continuity (session.json persists between runs)

Cloudflare mode:
  ✅ Text-based tool calling (no OpenAI schema)
  ✅ Word-by-word streaming simulation
  ✅ Multi-turn tool loop (up to 6 turns)
```

---

## crew.py — The Specialist Team

```
Architecture: Multi-Agent (CrewAI)
Crews: 3 × 3 agents = 9 specialists
Providers: Ollama, Cloudflare, OpenAI, Groq

CodeCrew:
  Reviewer  → reads code, lists issues (tools: read_file, list_directory)
  Fixer     → fixes issues (tools: read_file, write_file)
  Tester    → writes pytest tests (tools: read_file, write_file)

ResearchCrew:
  Researcher → web search (tools: web_search)
  Analyst    → structures findings (no tools — pure reasoning)
  Writer     → writes markdown report (tools: write_file)

DevOpsCrew:
  SysAdmin      → system health (tools: run_shell)
  GitInspector  → repo status (tools: git_tool, list_directory)
  ReportWriter  → combined report (tools: write_file)

Provider config (reads LLM_PROVIDER from .env):
  ollama     → LLM(model="ollama/qwen2:7b", ...)
  cloudflare → LLM(model="openai/@cf/...", base_url=gateway_url, ...)
  openai     → LLM(model="openai/gpt-4o-mini", ...)
  groq       → LLM(model="groq/llama-3.3-70b-versatile", ...)
```

---

## agent_graph.py — The Safety-First Coding Agent

```
Architecture: State Graph (LangGraph)
Tools: 7 (run_shell, read_file, write_file, edit_file,
           list_directory, run_tests, git_write)
Providers: All 6 (with Cloudflare text-mode multi-tool loop)

Phase 1 (original):
  ✅ Human approval (write_file, git_write)
  ✅ Retry logic (up to 2x on tool failure)
  ✅ Conditional branching
  ✅ Validation loop (max 3 iterations)
  ✅ Checkpointing (MemorySaver)

Phase 2 (new):
  ✅ Test → fix loop (pytest after edits, auto-fix failures, max 3 attempts)
  ✅ Multi-file planning (--plan flag, user approves before execution)
  ✅ Git write operations (stage, commit, branch — all with approval)

Cloudflare multi-tool loop:
  ✅ Loops up to 6 turns (read_file → edit_file → run_tests in sequence)
  ✅ Feeds tool results back into conversation
  ✅ Breaks on FINAL_ANSWER or max_turns

Graph nodes:
  planner → agent → check_approval → approval → tools → retry → run_tests → validator
```

---

## Memory Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MEMORY LAYERS                         │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Layer 1: In-context (chat_history)                     │
│  ├─ Last 4 messages in current run                      │
│  └─ Cleared when process exits                          │
│                                                          │
│  Layer 2: Session (session.json)                        │
│  ├─ Last 20 messages across runs                        │
│  ├─ Loaded on startup as chat_history                   │
│  └─ Saved after every interaction                       │
│                                                          │
│  Layer 3: Long-term (rag.store.json)                    │
│  ├─ Factual statements as 768-dim vectors               │
│  ├─ Semantic search (cosine similarity)                 │
│  ├─ Keyword fallback when Ollama is down                │
│  ├─ Auto-cleanup: 30 day expiry, max 200 entries        │
│  └─ Deduplication: never stores same fact twice         │
│                                                          │
│  What gets stored in RAG:                               │
│  ✅ "my name is Rohit"                                  │
│  ✅ "I work at AIT Global India"                        │
│  ✅ "I prefer dark mode"                                │
│                                                          │
│  What doesn't get stored:                               │
│  ❌ Questions ("what is my name?")                      │
│  ❌ System data (disk usage, ports)                     │
│  ❌ Duplicates                                          │
└─────────────────────────────────────────────────────────┘
```

---

## Tool Ecosystem

```
agent.py tools (12):
  run_shell       — shell commands (ps, df, free, uptime)
  read_file       — read any file
  write_file      — create new files
  list_directory  — list files/folders
  web_search      — DuckDuckGo / Brave search
  http_request    — call any REST API
  git_tool        — read-only git (log, status, diff)
  index_codebase  — scan project, extract all symbols via AST
  edit_file       — surgical str_replace (Phase 1)
  preview_diff    — show diff before applying (Phase 1)
  extract_symbol  — extract one function/class via AST (Phase 3)
  fetch_url       — fetch full webpage content (Phase 3)

agent_graph.py tools (7):
  run_shell, read_file, write_file, edit_file,
  list_directory, run_tests, git_write

crew.py tools (7 as BaseTool classes):
  RunShellTool, ReadFileTool, WriteFileTool, ListDirectoryTool,
  WebSearchTool, GitTool + HttpTool
```

---

## LLM Provider Support

```
Provider      | agent.py | crew.py | agent_graph.py | Notes
─────────────────────────────────────────────────────────────
Ollama        |    ✅    |   ✅    |      ✅        | Local, free
Cloudflare    |    ✅    |   ✅    |      ✅        | AI Gateway
OpenAI        |    ✅    |   ✅    |      ✅        | GPT-4o-mini
Anthropic     |    ✅    |   ❌    |      ✅        | Claude
Gemini        |    ✅    |   ❌    |      ✅        | Flash
Groq          |    ✅    |   ✅    |      ✅        | Fast inference

Configure via LLM_PROVIDER in .env
Test with: python llm_config.py test <provider>
```

---

## Improvements Implemented

| # | Improvement | File |
|---|---|---|
| 1 | Error recovery + retry with backoff | agent.py |
| 2 | RAG fallback to keyword search | rag.py |
| 3 | Cloudflare multi-tool loop | agent_graph.py |
| 4 | Streaming simulation (Cloudflare) | agent.py |
| 5 | crew.py multi-provider support | crew.py |
| 6 | RAG store expiry + auto-cleanup | rag.py |
| 7 | Session continuity (session.json) | agent.py |
| 8 | fetch_url tool | agent.py |
| 10 | Token/cost tracking | agent.py |

---

## What You Learned

1. **ReAct Pattern** — think → act → observe loop
2. **Tool Calling** — how LLMs decide which tools to use
3. **RAG** — vector embeddings + cosine similarity for memory
4. **Multi-Agent Systems** — specialist collaboration
5. **State Graphs** — LangGraph conditional routing
6. **AST Parsing** — token-efficient code extraction
7. **Provider Abstraction** — unified LLM config across 6 providers
8. **Cloudflare Compatibility** — text-mode tool calling workaround
9. **Session Persistence** — short-term vs long-term memory
10. **Error Recovery** — retry logic, fallbacks, graceful degradation
