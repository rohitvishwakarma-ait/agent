# Custom AI Agent Project

A complete AI agent system built from scratch in Python, featuring three different agent architectures for different use cases.

---

## 🚀 Quick Start

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Pull required Ollama models
ollama pull qwen2:7b
ollama pull nomic-embed-text

# Configure environment
cp .env.example .env
# Edit .env and add your API keys (optional)

# Run agents
python agent.py "check disk usage"
python crew.py devops "system health report"
python agent_graph.py "create a hello.py file"
```

---

## 📁 Project Structure

```
.
├── agent.py              # Simple single agent (fast, straightforward)
├── agent_graph.py        # LangGraph agent (approval, retry, validation)
├── crew.py               # Multi-agent crews (specialists for complex tasks)
├── rag.py                # RAG memory system (shared across all agents)
│
├── rag.store.json        # Vector store (persistent memory)
├── .env                  # API keys (not committed)
├── requirements.txt      # Python dependencies
│
├── LANGGRAPH_GUIDE.md    # LangGraph features explained
├── COMPARISON.md         # Which agent to use when
└── README.md             # This file
```

---

## 🤖 Three Agents, Three Purposes

### 1. **agent.py** — Simple & Fast

**Best for:** Quick queries, system checks, simple tasks

**Features:**
- 7 tools (shell, files, web search, git, HTTP)
- RAG memory (remembers facts across sessions)
- Streaming responses
- Interactive mode

**Example:**
```bash
python agent.py "what is my CPU usage"
python agent.py "read package.json and list dependencies"
python agent.py  # interactive mode
```

---

### 2. **crew.py** — Multi-Agent Teams

**Best for:** Complex multi-step tasks requiring specialists

**Features:**
- 3 crews with 9 specialized agents total
- Each agent has one focused job
- Sequential workflow (output flows between agents)
- Structured results

**Crews:**
- **CodeCrew:** Reviewer → Fixer → Tester
- **ResearchCrew:** Researcher → Analyst → Writer
- **DevOpsCrew:** SysAdmin → GitInspector → ReportWriter

**Example:**
```bash
python crew.py code "review agent.py and fix bugs"
python crew.py research "latest Python features"
python crew.py devops "full system health report"
```

---

### 3. **agent_graph.py** — Advanced Control

**Best for:** Tasks needing approval, retry, or validation

**Features:**
- ✅ Human-in-the-loop approval (for file writes)
- ✅ Automatic retry logic (up to 2x on failure)
- ✅ Conditional branching (skip unnecessary steps)
- ✅ Validation loop (iterative refinement)
- ✅ Checkpointing (resume after restart)

**Example:**
```bash
python agent_graph.py "create a config.json file"
# Shows preview, waits for approval

python agent_graph.py "curl https://api.example.com" --no-approval
# Automatically retries if it fails

python agent_graph.py --resume
# Resume from last checkpoint
```

---

## 🧠 Memory System

All three agents share the same RAG (Retrieval-Augmented Generation) memory:

**What it stores:**
- Personal facts ("my name is Rohit")
- Preferences ("I prefer dark mode")
- Project context ("I'm building an AI agent")

**What it doesn't store:**
- System query results (disk usage, ports) — always runs fresh
- Temporary data

**Storage:** `rag.store.json` (768-dim vectors via `nomic-embed-text`)

**Example:**
```bash
# Session 1
python agent.py "my name is Rohit and I work at AIT Global India"

# Session 2 (next day, fresh process)
python agent.py "what is my name and where do I work?"
# → "Your name is Rohit and you work at AIT Global India"
```

---

## 🛠️ Available Tools

All agents have access to these 7 tools:

| Tool | What it does |
|---|---|
| `run_shell` | Execute shell commands (ps, df, free, uptime, etc.) |
| `read_file` | Read any file from disk |
| `write_file` | Create or overwrite files |
| `list_directory` | List files and folders |
| `web_search` | Search DuckDuckGo (or Brave with API key) |
| `http_request` | Call any REST API |
| `git_tool` | Read-only git commands (log, status, diff) |

---

## 📊 Performance Comparison

| Metric | agent.py | crew.py | agent_graph.py |
|---|---|---|---|
| Speed | ⚡ Fast | 🐌 Slow | ⚡ Medium |
| Safety | ⚠️ None | ✅ Specialists | ✅✅ Approval+Retry |
| Complexity | Simple | Medium | High |
| Best for | Quick tasks | Multi-step | Sensitive ops |

---

## 🎯 Which Agent Should I Use?

```
Need to...
│
├─ Check system info, list files, quick query
│  → agent.py
│
├─ Review code → fix bugs → write tests
│  → crew.py code
│
├─ Research topic → analyze → write report
│  → crew.py research
│
├─ Create/edit files (need approval)
│  → agent_graph.py
│
├─ Run command that might fail (need retry)
│  → agent_graph.py
│
└─ Long task you might pause and resume
   → agent_graph.py
```

---

## 🔧 Configuration

### Environment Variables (.env)

```bash
# Optional: Brave Search API (better web search)
BRAVE_API_KEY=your_key_here

# Optional: Cloudflare Workers AI (not used by default)
CF_API_TOKEN=your_token_here
```

### Ollama Models

```bash
# Required
ollama pull qwen2:7b           # Main LLM
ollama pull nomic-embed-text   # Embeddings for RAG

# Optional alternatives
ollama pull llama3.1:8b
ollama pull qwen3.5
```

---

## 📚 Documentation

- **[LANGGRAPH_GUIDE.md](LANGGRAPH_GUIDE.md)** — Deep dive into LangGraph features
- **[COMPARISON.md](COMPARISON.md)** — Detailed comparison with examples

---

## 🧪 Testing

```bash
# Test simple agent
python agent.py "what is the current date"

# Test crew
python crew.py devops "quick health check"

# Test graph agent (no approval for testing)
python agent_graph.py "list files" --no-approval --no-checkpoints
```

---

## 🚧 Troubleshooting

**"Ollama connection refused"**
```bash
# Start Ollama
ollama serve
```

**"Model not found"**
```bash
# Pull the model
ollama pull qwen2:7b
```

**"OPENAI_API_KEY not set" (CrewAI memory)**
- CrewAI memory requires OpenAI by default
- Your RAG memory works without any API key
- See LANGGRAPH_GUIDE.md for details

**Agent is slow**
- Ollama models are CPU-intensive
- Use smaller models: `qwen2:3b` instead of `qwen2:7b`
- Or use `--no-checkpoints` flag for agent_graph.py

---

## 🎓 Learning Path

1. **Start with agent.py** — understand the basics
2. **Try crew.py** — see multi-agent collaboration
3. **Explore agent_graph.py** — learn advanced control flow
4. **Read the code** — everything is documented inline

---

## 🔮 What's Next

Potential additions:
- More tools (database, email, Slack, etc.)
- More crews (data analysis, DevOps automation)
- Web UI (Gradio or Streamlit)
- MCP server (expose tools to other IDEs)
- Voice interface (Whisper + TTS)

---

## 📝 License

This is a learning project. Use it however you want.

---

## 🙏 Acknowledgments

Built with:
- [LangChain](https://langchain.com) — agent framework
- [LangGraph](https://langchain-ai.github.io/langgraph/) — graph workflows
- [CrewAI](https://crewai.com) — multi-agent orchestration
- [Ollama](https://ollama.ai) — local LLM inference

---

**Questions?** Read the guides or check the inline code comments — everything is documented.
