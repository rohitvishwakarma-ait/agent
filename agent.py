"""
agent.py — LangChain agent with RAG, streaming, and 7 tools
Python equivalent of agent.langchain.ts

Run:
  python agent.py "your task here"   # single-shot mode
  python agent.py                    # interactive mode
  python agent.py --clear-memory     # wipe RAG store
"""

import os
import sys
import json
import subprocess
import re
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# LangChain imports — notice how clean these are vs TypeScript
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from rag import RAG

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

OLLAMA_MODEL    = "qwen2:7b"
EMBEDDING_MODEL = "nomic-embed-text"

# ============================================================
# LLM — equivalent of new ChatOllama(...)
# ============================================================

llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url="http://localhost:11434",
    temperature=0,  # deterministic — important for tool-calling agents
)

# ============================================================
# TOOLS
# Each tool is a plain Python function decorated with @tool
# The docstring IS the description — the LLM reads it to decide when to use the tool
# Much cleaner than TypeScript's z.object() schema approach
# ============================================================

@tool
def run_shell(command: str) -> str:
    """Run a shell command on the local machine. Use for: checking running processes,
    finding ports, disk usage, current date/time, system info.
    Input must be a safe, read-only shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout or result.stderr or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: Command timed out"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def read_file(path: str) -> str:
    """Read the contents of a file from disk. Use when the user asks about
    a specific file's contents, config files, or code files."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file on disk with given content.
    Use when the user asks to create a file, save output to a file,
    write code to a file, or edit an existing file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)  # create dirs if needed
        p.write_text(content, encoding="utf-8")
        return f"✅ Written to {path} ({len(content)} chars)"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def list_directory(path: str) -> str:
    """List files and folders in a directory. Use when the user asks what files
    exist in a folder, or before reading/writing files to confirm paths.
    Use '.' for the current directory."""
    try:
        p = Path(path)
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [
            f"📁 {e.name}" if e.is_dir() else f"📄 {e.name}"
            for e in entries
        ]
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def web_search(query: str) -> str:
    """Search the web for current information, news, documentation, or anything
    that requires up-to-date knowledge. Use when the user asks about recent events,
    latest versions, prices, or anything you might not know."""
    try:
        brave_key = os.getenv("BRAVE_API_KEY")

        if brave_key:
            # Brave Search — better results, requires free key from brave.com/search/api
            res = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": brave_key},
                params={"q": query, "count": 5},
                timeout=10,
            )
            res.raise_for_status()
            results = res.json().get("web", {}).get("results", [])
            return "\n\n".join(
                f"**{r['title']}**\n{r['url']}\n{r.get('description', '')}"
                for r in results
            ) or "No results found."

        # DuckDuckGo Instant Answer API — free, no key needed
        res = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        res.raise_for_status()
        d = res.json()
        parts = []
        if d.get("AbstractText"):
            parts.append(d["AbstractText"])
        if d.get("Answer"):
            parts.append(f"Answer: {d['Answer']}")
        if d.get("RelatedTopics"):
            related = [t.get("Text", "") for t in d["RelatedTopics"][:3] if t.get("Text")]
            if related:
                parts.append("Related:\n" + "\n".join(related))
        return "\n\n".join(parts) or f'No instant answer found for "{query}". Try a more specific query.'

    except Exception as e:
        return f"ERROR: {e}"


@tool
def http_request(method: str, url: str, body: str = "", headers: str = "") -> str:
    """Make an HTTP request to any URL or REST API. Use for: calling external APIs,
    fetching web pages, checking if a URL is reachable, testing endpoints.
    method: GET, POST, PUT, DELETE. body and headers are optional JSON strings."""
    try:
        parsed_headers = json.loads(headers) if headers else {}
        parsed_body    = json.loads(body)    if body    else None
        res = requests.request(
            method=method.upper(),
            url=url,
            json=parsed_body,
            headers=parsed_headers,
            timeout=10,
        )
        data = res.text[:2000] if isinstance(res.text, str) else json.dumps(res.json(), indent=2)[:2000]
        return f"Status: {res.status_code}\n{data}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def git_tool(command: str) -> str:
    """Run read-only git commands to inspect the repository.
    Use for: showing recent commits, checking git status, viewing diffs,
    listing branches, or showing file history.
    Example commands: 'log --oneline -10', 'status', 'diff HEAD~1'"""
    # Only allow read-only git commands — no push, commit, reset, etc.
    allowed = ["log", "status", "diff", "branch", "show", "ls-files", "remote"]
    verb = command.strip().split()[0] if command.strip() else ""
    if verb not in allowed:
        return f"ERROR: Only read-only git commands allowed: {', '.join(allowed)}"
    try:
        result = subprocess.run(
            f"git {command}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout or result.stderr or "(no output)"
    except Exception as e:
        return f"ERROR: {e}"


tools = [run_shell, read_file, write_file, list_directory, web_search, http_request, git_tool]

# ============================================================
# AGENT — equivalent of createReactAgent(...)
# ============================================================

SYSTEM_PROMPT = """You are a helpful AI agent with memory of past conversations.

AVAILABLE TOOLS:
- run_shell      : run shell commands (processes, ports, disk, date, system info)
- read_file      : read a file from disk
- write_file     : create or overwrite a file on disk
- list_directory : list files in a folder
- web_search     : search the web for current information
- http_request   : call any REST API or URL
- git_tool       : inspect git repo (log, status, diff, branches)

WHEN TO USE TOOLS vs MEMORY:
- Use tools for anything requiring real-time or system data
- Answer from memory for personal facts the user told you (name, preferences, projects)

Always give a clear, direct answer after using tools."""

agent = create_react_agent(llm, tools, prompt=SystemMessage(SYSTEM_PROMPT))

# ============================================================
# RAG
# ============================================================

rag = RAG("rag.store.json")

# Action task patterns — skip RAG injection for these
# (RAG causes model to answer from memory instead of acting)
ACTION_PATTERN = re.compile(
    r"^(create|make|write|save|generate|build|delete|remove|run|execute|"
    r"show me|list|find|search|check|get|fetch|call|send|open|read)",
    re.IGNORECASE,
)

# ============================================================
# RUN ONE TASK — equivalent of runTask()
# ============================================================

def run_task(
    task: str,
    chat_history: list,
) -> tuple[str, bool]:
    """
    Run one task through the agent with streaming output.
    Returns (answer, used_tools).
    """
    is_action_task = bool(ACTION_PATTERN.match(task.strip()))

    # Build RAG context for recall questions only
    rag_context = ""
    if not is_action_task:
        relevant = rag.search(task, top_k=5)
        if relevant:
            lines = [f"[{e.role}]: {e.text}" for e in relevant]
            rag_context = "\n\nRelevant memories from past conversations:\n" + "\n".join(lines)

    system_with_rag = SystemMessage(
        f"""You are a helpful AI agent with memory of past conversations.

AVAILABLE TOOLS:
- run_shell      : run shell commands (processes, ports, disk, date, system info)
- read_file      : read a file from disk
- write_file     : create or overwrite a file on disk
- list_directory : list files in a folder
- web_search     : search the web for current information
- http_request   : call any REST API or URL
- git_tool       : inspect git repo (log, status, diff, branches)

CRITICAL RULES:
- If the task asks to CREATE, WRITE, SAVE, or GENERATE a file → always use write_file. Never just show the code.
- If the task asks to RUN, CHECK, LIST, or FIND something on the system → always use run_shell or list_directory.
- If the task asks to SEARCH the web → always use web_search.
- Only answer from memory for personal facts (name, preferences) — never for action tasks.
{rag_context}"""
    )

    messages = [system_with_rag] + chat_history[-4:] + [HumanMessage(task)]

    answer = ""
    used_tools = False

    # Stream the response — tokens print as they are generated
    print("\n🤖 Agent Working... ", end="", flush=True)

    for chunk in agent.stream({"messages": messages}):
        # chunk["agent"] = LLM thinking / final answer tokens
        if "agent" in chunk:
            for msg in chunk["agent"].get("messages", []):
                content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                if content:
                    print(content, end="", flush=True)  # stream token immediately
                    answer += content

        # chunk["tools"] = tool execution results
        if "tools" in chunk:
            used_tools = True
            for msg in chunk["tools"].get("messages", []):
                tool_name = getattr(msg, "name", "tool")
                print(f"\n⚙️  [{tool_name}] running...\n🤖 Agent Working... ", end="", flush=True)

    print()  # newline after streaming finishes
    return answer.strip(), used_tools


# ============================================================
# INTERACTIVE LOOP — equivalent of main()
# ============================================================

def main():
    rag.load()
    chat_history = []

    print(f"\n🤖 LangChain Agent (Python)")
    print(f"🧠 LLM       : {OLLAMA_MODEL}")
    print(f"📐 Embeddings: {EMBEDDING_MODEL}")
    print(f"🔍 RAG       : {rag.stats()['total']} vectors loaded")
    print(f"\nCommands: /clear  /exit\n")

    # Single-shot mode: task passed as CLI argument
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--clear-memory" in flags:
        rag.clear()
        sys.exit(0)

    if args:
        task = args[0]
        print(f"📋 Task: {task}")
        answer, used_tools = run_task(task, chat_history)

        if not used_tools:
            rag.add(task, "user", "conversational")
            rag.add(answer, "assistant", "conversational")
            rag.save()
            print("💾 Stored in RAG")
        else:
            print("⚡ Not stored (real-time data — always runs fresh)")
        return

    # Interactive mode
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!\n")
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            print("\n👋 Goodbye!\n")
            break

        if user_input == "/clear":
            rag.clear()
            chat_history.clear()
            print("🗑️  Cleared.")
            continue

        answer, used_tools = run_task(user_input, chat_history)

        # Update in-memory chat history for multi-turn context
        chat_history.append(HumanMessage(user_input))
        chat_history.append(AIMessage(answer))

        if not used_tools:
            rag.add(user_input, "user", "conversational")
            rag.add(answer, "assistant", "conversational")
            rag.save()
            print("💾 Stored in RAG")
        else:
            print("⚡ Real-time data — not stored in RAG")


if __name__ == "__main__":
    main()
