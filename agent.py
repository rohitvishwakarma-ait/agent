"""
agent.py — LangChain agent with RAG, streaming, and 10 tools
Includes Phase 1 Claude Code-like capabilities:
  - index_codebase : scan project structure + extract symbols
  - edit_file      : surgical str_replace edits (no full rewrites)
  - preview_diff   : show unified diff before applying changes

Run:
  python agent.py "your task here"   # single-shot mode
  python agent.py                    # interactive mode
  python agent.py --clear-memory     # wipe RAG store
"""

import os
import sys
import json
import ast
import difflib
import subprocess
import re
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# LangChain imports
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
try:
    # LangGraph V1 — still works, just deprecated warning
    from langgraph.prebuilt import create_react_agent
except ImportError:
    from langchain.agents import create_react_agent

from rag import RAG

load_dotenv()

# ============================================================
# CONFIG
# ============================================================


# ============================================================
# LLM — equivalent of new ChatOllama(...)
# ============================================================

# Import unified LLM config
from llm_config import get_llm

llm = get_llm()  # Uses LLM_PROVIDER from .env (defaults to ollama)

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


# ============================================================
# PHASE 1 — CLAUDE CODE-LIKE TOOLS
# ============================================================

@tool
def index_codebase(path: str = ".") -> str:
    """Scan the project and return a structured map of all source files,
    their classes, functions, and imports. Call this FIRST before any
    coding task so you understand the full project structure.
    Use '.' for the current project directory."""
    try:
        root = Path(path).resolve()

        # File extensions to index
        CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".h"}
        SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git", "dist", "build", ".mypy_cache"}

        lines = [f"📁 Project: {root.name}", f"📍 Path: {root}\n"]
        total_files = 0

        for file_path in sorted(root.rglob("*")):
            # Skip hidden dirs and common noise dirs
            if any(part in SKIP_DIRS for part in file_path.parts):
                continue
            if not file_path.is_file():
                continue
            if file_path.suffix not in CODE_EXTS:
                continue

            rel = file_path.relative_to(root)
            total_files += 1
            size_kb = file_path.stat().st_size / 1024
            lines.append(f"📄 {rel}  ({size_kb:.1f} KB)")

            # Deep-index Python files — extract symbols via AST
            if file_path.suffix == ".py":
                try:
                    source = file_path.read_text(encoding="utf-8", errors="ignore")
                    tree = ast.parse(source)

                    imports = []
                    classes = []
                    functions = []

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append(alias.name.split(".")[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.append(node.module.split(".")[0])
                        elif isinstance(node, ast.ClassDef):
                            methods = [
                                n.name for n in ast.walk(node)
                                if isinstance(n, ast.FunctionDef) and n.col_offset > node.col_offset
                            ]
                            classes.append(f"{node.name}({', '.join(methods[:5])}{'...' if len(methods) > 5 else ''})")
                        elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                            # Top-level functions only
                            args = [a.arg for a in node.args.args]
                            functions.append(f"{node.name}({', '.join(args[:4])}{'...' if len(args) > 4 else ''})")

                    # Deduplicate imports, show top ones
                    unique_imports = list(dict.fromkeys(imports))[:8]
                    if unique_imports:
                        lines.append(f"   imports : {', '.join(unique_imports)}")
                    if classes:
                        lines.append(f"   classes : {', '.join(classes[:5])}")
                    if functions:
                        lines.append(f"   funcs   : {', '.join(functions[:8])}")

                except SyntaxError:
                    lines.append(f"   (syntax error — could not parse)")
                except Exception:
                    pass

            lines.append("")  # blank line between files

        lines.append(f"─── Total: {total_files} source files indexed ───")
        return "\n".join(lines)

    except Exception as e:
        return f"ERROR: {e}"


@tool
def edit_file(path: str, old_str: str, new_str: str) -> str:
    """Make a surgical edit to a file by replacing an exact string.
    Safer than write_file — only changes the specific part you target.
    Use this for: fixing bugs, updating functions, changing config values,
    refactoring specific lines. old_str must match the file content EXACTLY
    (including indentation and whitespace).
    Returns a diff of what changed."""
    try:
        p = Path(path)
        if not p.exists():
            return f"ERROR: File not found: {path}"

        original = p.read_text(encoding="utf-8")

        if old_str not in original:
            # Help the LLM debug — show nearby content
            lines = original.splitlines()
            # Try to find the closest matching line
            first_line = old_str.strip().splitlines()[0].strip() if old_str.strip() else ""
            matches = [
                f"  line {i+1}: {l}"
                for i, l in enumerate(lines)
                if first_line and first_line[:20].lower() in l.lower()
            ]
            hint = "\nClosest matches:\n" + "\n".join(matches[:3]) if matches else ""
            return (
                f"ERROR: old_str not found in {path}.\n"
                f"Make sure indentation and whitespace match exactly.{hint}"
            )

        # Count occurrences — warn if ambiguous
        count = original.count(old_str)
        if count > 1:
            return (
                f"ERROR: old_str appears {count} times in {path}. "
                f"Make it more specific so it matches exactly once."
            )

        updated = original.replace(old_str, new_str, 1)

        # Generate diff for confirmation
        diff = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        ))

        p.write_text(updated, encoding="utf-8")

        diff_str = "".join(diff[:40])  # cap at 40 lines for readability
        if len(diff) > 40:
            diff_str += f"\n... ({len(diff) - 40} more lines)"

        return f"✅ Edited {path}\n\n{diff_str}"

    except Exception as e:
        return f"ERROR: {e}"


@tool
def preview_diff(path: str, new_content: str) -> str:
    """Preview what a full file rewrite would change, WITHOUT applying it.
    Use this before write_file when you want to show the user what will
    change and get confirmation. Shows a unified diff format."""
    try:
        p = Path(path)
        if not p.exists():
            # New file — show it as all additions
            new_lines = new_content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                [],
                new_lines,
                fromfile="/dev/null",
                tofile=f"b/{path}",
                lineterm="",
            )
            result = "".join(diff)
            return f"📄 New file: {path}\n\n{result}" if result else "(empty file)"

        original = p.read_text(encoding="utf-8")
        diff = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        ))

        if not diff:
            return f"✅ No changes — new content is identical to {path}"

        diff_str = "".join(diff[:60])
        if len(diff) > 60:
            diff_str += f"\n... ({len(diff) - 60} more lines not shown)"

        added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        return (
            f"📊 Diff for {path}: +{added} lines, -{removed} lines\n\n"
            f"{diff_str}\n\n"
            f"⚠️  This is a PREVIEW only. Use write_file to apply."
        )

    except Exception as e:
        return f"ERROR: {e}"


tools = [
    run_shell, read_file, write_file, list_directory,
    web_search, http_request, git_tool,
    # Phase 1 — Claude Code-like tools
    index_codebase, edit_file, preview_diff,
]

# ============================================================
# AGENT — equivalent of createReactAgent(...)
# ============================================================

SYSTEM_PROMPT = """You are an expert coding agent with Claude Code-like capabilities.

AVAILABLE TOOLS:
- run_shell      : run shell commands (processes, ports, disk, date, system info)
- read_file      : read a file from disk
- write_file     : create or overwrite a WHOLE file (use for new files only)
- list_directory : list files in a folder
- web_search     : search the web for current information
- http_request   : call any REST API or URL
- git_tool       : inspect git repo (log, status, diff, branches)
- index_codebase : scan entire project — extract all files, classes, functions
- edit_file      : surgically replace exact text in a file (PREFERRED for edits)
- preview_diff   : show what a file change would look like before applying it

CODING WORKFLOW (follow this order):
1. index_codebase — understand the project structure first
2. read_file      — read the specific file(s) you need to change
3. preview_diff   — show the user what will change (for large edits)
4. edit_file      — make surgical changes (ALWAYS prefer over write_file for edits)
5. write_file     — only for creating brand new files

RULES:
- NEVER rewrite an entire file just to change a few lines — use edit_file
- ALWAYS read a file before editing it
- For coding tasks, call index_codebase first to understand the project
- old_str in edit_file must match the file EXACTLY (copy-paste from read_file output)
- Use preview_diff before write_file on large files so user can review

WHEN TO USE TOOLS vs MEMORY:
- Use tools for anything requiring real-time or system data
- Answer from memory for personal facts the user told you (name, preferences, projects)"""

agent = create_react_agent(llm, tools, prompt=SystemMessage(SYSTEM_PROMPT))

# ============================================================
# RAG
# ============================================================

rag = RAG("rag.store.json")

# Action task patterns — skip RAG injection for these
# (RAG causes model to answer from memory instead of acting)
ACTION_PATTERN = re.compile(
    r"^(create|make|write|save|generate|build|delete|remove|run|execute|"
    r"show me|list|find|search|check|get|fetch|call|send|open|read|"
    r"add|edit|fix|update|change|modify|refactor|rename|move|index|"
    r"install|deploy|test|debug|analyse|analyze|review|improve|optimize)",
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

    # Detect coding/file tasks — these must NEVER use RAG, always use tools
    CODING_PATTERN = re.compile(
        r"(\.py|\.js|\.ts|\.go|\.java|\.cpp|\.c|\.h|\.json|\.yaml|\.yml|\.toml|"
        r"function|class|method|docstring|import|variable|bug|error|fix|refactor|"
        r"edit|modify|change|update|add to|add a|in agent|in crew|in the file)",
        re.IGNORECASE,
    )
    is_coding_task = bool(CODING_PATTERN.search(task))

    # Build RAG context for recall questions only — never for action/coding tasks
    rag_context = ""
    if not is_action_task and not is_coding_task:
        relevant = rag.search(task, top_k=5)
        if relevant:
            lines = [f"[{e.role}]: {e.text}" for e in relevant]
            rag_context = "\n\nRelevant memories from past conversations:\n" + "\n".join(lines)

    # For coding tasks, prepend a strong instruction to use tools
    coding_instruction = ""
    if is_coding_task:
        coding_instruction = (
            "\n\nIMPORTANT: This is a coding task. You MUST use tools — do NOT answer from memory.\n"
            "Required steps:\n"
            "  1. Call read_file to read the target file first\n"
            "  2. Call edit_file to make the change surgically\n"
            "  3. Confirm what was changed\n"
            "Never show code in chat without actually writing it to the file."
        )

    system_with_rag = SystemMessage(
        f"""You are an expert coding agent with Claude Code-like capabilities.

AVAILABLE TOOLS:
- run_shell      : run shell commands (processes, ports, disk, date, system info)
- read_file      : read a file from disk
- write_file     : create or overwrite a WHOLE file (new files only)
- list_directory : list files in a folder
- web_search     : search the web for current information
- http_request   : call any REST API or URL
- git_tool       : inspect git repo (log, status, diff, branches)
- index_codebase : scan entire project — extract all files, classes, functions
- edit_file      : surgically replace exact text in a file (PREFERRED for edits)
- preview_diff   : show what a file change would look like before applying it

CODING WORKFLOW:
1. read_file      → read the file you need to change
2. edit_file      → make surgical changes (ALWAYS prefer over write_file for edits)
3. write_file     → only for brand new files

CRITICAL RULES:
- NEVER answer a coding task from memory — always use read_file then edit_file
- NEVER rewrite an entire file to change a few lines — use edit_file
- old_str in edit_file must match the file EXACTLY (copy from read_file output)
- For CREATE/WRITE/SAVE/GENERATE a new file → use write_file
- For RUN/CHECK/LIST/FIND on the system → use run_shell or list_directory
- For SEARCH the web → use web_search
- Only answer from memory for personal facts — never for action tasks.
{rag_context}{coding_instruction}"""
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
    print(f"🧠 LLM       : {llm.model if hasattr(llm, 'model') else type(llm).__name__}")
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
