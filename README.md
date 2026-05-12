# Custom AI Agent Project

A complete AI agent system built from scratch in Python, featuring three agent architectures, Claude Code-like editing capabilities, multi-provider LLM support, and persistent memory.

---

## 🚀 Quick Start

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pull required Ollama models (for local inference)
ollama pull qwen2:7b
ollama pull nomic-embed-text

# Configure environment
cp .env.example .env
# Edit .env — set LLM_PROVIDER and add API keys

# Run agents
python agent.py "check disk usage"
python crew.py devops "system health report"
python agent_graph.py "fix the bug in rag.py" --plan
```

---

## 📁 Project Structure

```
.
├── agent.py              # LangChain agent — fast, streaming, 12 tools
├── agent_graph.py        # LangGraph agent — approval, retry, test loop, planning
├── crew.py               # CrewAI multi-agent — 3 crews, 9 specialists
├── rag.py                # RAG memory — vector + keyword fallback
├── llm_config.py         # Unified LLM provider config
│
├── rag.store.json        # Vector store (persistent memory)
├── session.json          # Short-term session memory (last 20 messages)
├── .env                  # API keys and provider config (not committed)
├── .env.example          # Config template
├── requirements.txt      # Python dependencies
│
├── README.md             # This file
├── COMPARISON.md         # Which agent to use when
├── PROJECT_OVERVIEW.md   # Complete architecture
├── LANGGRAPH_GUIDE.md    # LangGraph features deep dive
└── LANGGRAPH_ADDED.md    # LangGraph implementation notes
```

---

## 🤖 Three Agents

### 1. **agent.py** — Fast & Feature-Rich

**Best for:** Quick queries, coding tasks, system checks, web research

**Tools (12 total):**

| Tool | Purpose |
|---|---|
| `run_shell` | Shell commands (ps, df, free, uptime) |
| `read_file` | Read any file |
| `write_file` | Create new files |
| `list_directory` | List files/folders |
| `web_search` | DuckDuckGo / Brave search |
| `http_request` | Call any REST API |
| `git_tool` | Read-only git (log, status, diff) |
| `index_codebase` | Scan project — extract all symbols |
| `edit_file` | Surgical str_replace edits (Phase 1) |
| `preview_diff` | Show diff before applying (Phase 1) |
| `extract_symbol` | Extract one function/class via AST (Phase 3) |
| `fetch_url` | Fetch full webpage content (Phase 3) |

**Features:**
- Streaming responses (Ollama) / word-by-word simulation (Cloudflare)
- RAG memory with vector + keyword fallback
- Session continuity via `session.json`
- Project-aware startup (auto-loads README + file structure)
- Session change tracker (`/session` command)
- Token/cost tracking
- Error recovery with exponential backoff retry

```bash
python agent.py "what is my CPU usage"
python agent.py "add a docstring to the run_task function in agent.py"
python agent.py "fetch https://docs.python.org/3/ and summarize"
python agent.py  # interactive mode — type /session, /clear, /exit
```

---

### 2. **crew.py** — Multi-Agent Teams

**Best for:** Complex multi-step tasks requiring specialists

**Crews:**
- **CodeCrew:** Reviewer → Fixer → Tester
- **ResearchCrew:** Researcher → Analyst → Writer
- **DevOpsCrew:** SysAdmin → GitInspector → ReportWriter

**Providers supported:** Ollama, Cloudflare, OpenAI, Groq (set `LLM_PROVIDER` in `.env`)

```bash
python crew.py code "review agent.py and fix bugs"
python crew.py research "latest Python 3.13 features"
python crew.py devops "full system health report"
```

---

### 3. **agent_graph.py** — Advanced Control

**Best for:** Coding tasks, sensitive operations, tasks needing verification

**Phase 1 features:**
- Human-in-the-loop approval (file writes, git operations)
- Automatic retry logic (up to 2x on tool failure)
- Conditional branching
- Validation loop (iterative refinement)
- Checkpointing (resume after restart)

**Phase 2 features:**
- Test → Fix loop (runs pytest after edits, auto-fixes failures)
- Multi-file planning (`--plan` flag shows plan before acting)
- Git write operations (commit, branch, stage — with approval)

```bash
python agent_graph.py "fix the bug in rag.py" --plan
python agent_graph.py "check disk usage" --no-tests --no-approval
python agent_graph.py "add feature X" --plan --no-checkpoints
python agent_graph.py --resume
```

**Flags:**
```
--no-approval     skip human approval for writes
--no-checkpoints  disable state persistence
--plan            show implementation plan before acting
--no-tests        skip test verification loop
--resume          resume last checkpointed task
```

---

## 🧠 Memory System

### Long-term Memory — `rag.store.json`
- Stores factual statements as 768-dim vectors
- Semantic search via cosine similarity
- Falls back to keyword search if Ollama is down
- Auto-cleanup: removes entries older than 30 days, caps at 200 entries
- Deduplication: never stores the same fact twice
- Only stores facts, not questions

### Short-term Memory — `session.json`
- Stores last 20 messages between runs
- Loaded on startup as `chat_history`
- Gives the agent context from your previous conversation

```bash
# Session 1
python agent.py "my name is Rohit and I work at AIT Global India"

# Session 2 (next day)
python agent.py "where do I work?"
# → "You work at AIT Global India" (from RAG)
# → Also remembers recent conversation context (from session.json)
```

---

## 🔧 LLM Provider Configuration

Set `LLM_PROVIDER` in `.env` to switch providers:

```bash
LLM_PROVIDER=ollama       # local, free, default
LLM_PROVIDER=cloudflare   # fast, cheap
LLM_PROVIDER=openai       # powerful
LLM_PROVIDER=groq         # extremely fast
LLM_PROVIDER=anthropic    # excellent reasoning
LLM_PROVIDER=gemini       # large context
```

Test a provider:
```bash
python llm_config.py list              # show all providers + status
python llm_config.py test ollama       # test Ollama
python llm_config.py test cloudflare   # test Cloudflare
```

---

## 📊 Agent Comparison

| Feature | agent.py | crew.py | agent_graph.py |
|---|---|---|---|
| Speed | ⚡ Fast | 🐌 Slow | ⚡ Medium |
| Tools | 12 | 7 | 7 |
| Streaming | ✅ | ✅ | ❌ |
| Human approval | ❌ | ❌ | ✅ |
| Retry logic | ✅ (error recovery) | ❌ | ✅ |
| Test → fix loop | ❌ | ❌ | ✅ |
| Multi-file planning | ❌ | ❌ | ✅ |
| Git writes | ❌ | ❌ | ✅ |
| Multi-agent | ❌ | ✅ | ❌ |
| Cloudflare support | ✅ | ✅ | ✅ |
| Session memory | ✅ | ❌ | ❌ |
| Token tracking | ✅ | ❌ | ❌ |

---

## 🚧 Troubleshooting

**"Ollama connection refused"**
```bash
ollama serve
```

**RAG works without Ollama**
- If Ollama is down, RAG automatically falls back to keyword search
- You'll see: `⚠️ RAG: Ollama unavailable — using keyword search fallback`

**Cloudflare tool-calling errors**
- Cloudflare uses text-mode tool calling (not OpenAI schema format)
- This is handled automatically — no action needed

**Agent is slow**
- Use `--no-checkpoints` for agent_graph.py
- Switch to Cloudflare or Groq for faster inference

---

## 📚 Documentation

- **[COMPARISON.md](COMPARISON.md)** — Which agent to use when
- **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** — Complete architecture
- **[LANGGRAPH_GUIDE.md](LANGGRAPH_GUIDE.md)** — LangGraph features deep dive

---

## 🔮 What's Next

- Web UI (Gradio or Streamlit)
- MCP server (expose tools to other IDEs)
- ChromaDB integration (when RAG exceeds 500 entries)
- Voice interface (Whisper + TTS)
- Image/file attachment support (multimodal)
