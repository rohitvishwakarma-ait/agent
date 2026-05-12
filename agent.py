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
    """Run a shell command on the local machine.

    Use for: checking running processes, finding ports, disk usage,
    current date/time, system info.
    Input must be a safe, read-only shell command.

    Args:
        command (str): The shell command to execute.

    Returns:
        str: stdout/stderr output, or an error message on failure.
    """
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
    a specific file's contents, config files, or code files. This function takes a file path as input and returns the file contents as a string."""

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


# ============================================================
# PHASE 3 — POLISH TOOLS
# ============================================================

@tool
def extract_symbol(path: str, symbol: str) -> str:
    """Extract a specific function, class, or method from a source file using AST.
    Much more token-efficient than read_file — loads only what you need.
    Use instead of read_file when you know the exact function/class name.

    Examples:
        extract_symbol("rag.py", "cosine_similarity")
        extract_symbol("agent.py", "run_task")
        extract_symbol("crew.py", "RunShellTool")
    """
    try:
        p = Path(path)
        if not p.exists():
            return f"ERROR: File not found: {path}"

        source = p.read_text(encoding="utf-8")
        lines  = source.splitlines()

        # Non-Python files — do a text search with context
        if p.suffix != ".py":
            symbol_lower = symbol.lower()
            matches = [(i, l) for i, l in enumerate(lines) if symbol_lower in l.lower()]
            if not matches:
                return f"ERROR: '{symbol}' not found in {path}"
            idx   = matches[0][0]
            start = max(0, idx - 2)
            end   = min(len(lines), idx + 20)
            snippet = "\n".join(f"{start+i+1:4}: {l}" for i, l in enumerate(lines[start:end]))
            return f"Found '{symbol}' at line {idx+1} in {path}:\n\n{snippet}"

        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    start_line = node.lineno - 1
                    end_line   = node.end_lineno
                    # Include decorators
                    if node.decorator_list:
                        start_line = node.decorator_list[0].lineno - 1

                    snippet_lines = lines[start_line:end_line]
                    snippet = "\n".join(
                        f"{start_line+i+1:4}: {l}" for i, l in enumerate(snippet_lines)
                    )
                    token_est = len(" ".join(snippet_lines).split())
                    full_est  = len(source.split())
                    return (
                        f"📍 {symbol} in {path} "
                        f"(lines {start_line+1}–{end_line}, "
                        f"~{token_est} tokens vs ~{full_est} for full file)\n\n"
                        f"{snippet}"
                    )

        available = ", ".join(
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        return f"ERROR: '{symbol}' not found in {path}.\nAvailable: {available}"

    except SyntaxError as e:
        return f"ERROR: Syntax error in {path}: {e}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def fetch_url(url: str, max_chars: int = 5000) -> str:
    """Fetch and return the text content of a URL. Use when you need to read
    a full webpage, documentation page, GitHub file, or any URL.
    Returns cleaned text content (HTML tags removed).
    max_chars: maximum characters to return (default 5000)."""
    try:
        import re as _re
        res = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        # Strip HTML tags
        text = _re.sub(r'<[^>]+>', ' ', res.text)
        # Collapse whitespace
        text = _re.sub(r'\s+', ' ', text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... (truncated, {len(res.text)} chars total)"
        return text
    except Exception as e:
        return f"ERROR: {e}"


tools = [
    run_shell, read_file, write_file, list_directory,
    web_search, http_request, git_tool,
    # Phase 1 — Claude Code-like tools
    index_codebase, edit_file, preview_diff,
    # Phase 3 — Token-efficient context loading
    extract_symbol,
    # Phase 3 — Web fetch
    fetch_url,
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
- extract_symbol : extract a specific function/class (token-efficient, use instead of read_file when you know the symbol name)
- fetch_url      : fetch and return the full text content of a URL (use for docs, GitHub files, web pages)

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

# Detect if provider needs text-mode tool calling (Cloudflare Workers AI)
# Cloudflare doesn't support OpenAI-style tool schemas — use plain text instead
USE_TEXT_TOOLS = getattr(llm, "_cf_text_tools", False)

if USE_TEXT_TOOLS:
    # Cloudflare mode: no tool binding — agent gets tools described in text,
    # executes them by parsing the response manually
    print("⚡ Cloudflare mode: using text-based tool calling")
    agent = None  # will use cf_run_task() instead
else:
    agent = create_react_agent(llm, tools, prompt=SystemMessage(SYSTEM_PROMPT))

# ============================================================
# RAG
# ============================================================

rag = RAG("rag.store.json")

# ============================================================
# SESSION CONTINUITY (#7)
# Persist last N messages between runs so context carries over
# ============================================================

SESSION_FILE = "session.json"


def load_session() -> list:
    """Load the last 4 messages from session.json as chat_history."""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        messages = []
        for m in data.get("messages", [])[-4:]:
            if m.get("role") == "user":
                messages.append(HumanMessage(m["content"]))
            elif m.get("role") == "assistant":
                messages.append(AIMessage(m["content"]))
        return messages
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_session(chat_history: list) -> None:
    """Save chat_history to session.json, keeping max 20 messages."""
    messages = []
    for m in chat_history:
        if isinstance(m, HumanMessage):
            messages.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            messages.append({"role": "assistant", "content": m.content})
    # Keep only the last 20
    messages = messages[-20:]
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"messages": messages}, f, indent=2)


# ============================================================
# TOKEN TRACKING (#10)
# ============================================================

class TokenTracker:
    def __init__(self):
        self.total_input = 0
        self.total_output = 0

    def track(self, response) -> None:
        """Extract token usage from LLM response if available."""
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.total_input  += response.usage_metadata.get('input_tokens', 0)
            self.total_output += response.usage_metadata.get('output_tokens', 0)
        elif hasattr(response, 'response_metadata'):
            meta = response.response_metadata
            self.total_input  += meta.get('prompt_tokens', 0) or meta.get('input_tokens', 0)
            self.total_output += meta.get('completion_tokens', 0) or meta.get('output_tokens', 0)

    def summary(self) -> str:
        total = self.total_input + self.total_output
        if total == 0:
            return ""
        # Rough cost estimate (Cloudflare: ~$0.20/M tokens)
        cost = total / 1_000_000 * 0.20
        return f"📊 Tokens: {self.total_input} in + {self.total_output} out = {total} total (~${cost:.4f})"


token_tracker = TokenTracker()

# Action task patterns — skip RAG injection for these
# (RAG causes model to answer from memory instead of acting)
ACTION_PATTERN = re.compile(
    r"^(create|make|write|save|generate|build|delete|remove|run|execute|"
    r"show me|list|find|search|check|get|fetch|call|send|open|read|"
    r"add|edit|fix|update|change|modify|refactor|rename|move|index|"
    r"install|deploy|test|debug|analyse|analyze|review|improve|optimize)",
    re.IGNORECASE,
)

# Tool name → function map for text-mode execution
TOOL_MAP = {t.name: t for t in tools}


# ============================================================
# CLOUDFLARE TEXT-MODE RUNNER
# Cloudflare Workers AI doesn't support OpenAI tool schemas.
# Instead: describe tools in the prompt, parse TOOL_CALL: blocks from response,
# execute them directly, feed results back, get final answer.
# ============================================================

def cf_run_task(task: str, preflight_context: str = "", rag_context: str = "") -> tuple[str, bool]:
    """Run a task using Cloudflare with text-based tool calling."""

    tools_desc = "\n".join([
        f"- {t.name}: {t.description.splitlines()[0]}"
        for t in tools
    ])

    system = (
        "You are an expert coding agent with memory of past conversations. "
        "You have access to these tools:\n\n"
        f"{tools_desc}\n\n"
        "To use a tool, respond with EXACTLY this format (nothing else on that line):\n"
        "TOOL_CALL: tool_name\n"
        "INPUT: {\"param\": \"value\"}\n\n"
        "WORKFLOW for coding tasks:\n"
        "  1. Call read_file to read the target file first\n"
        "  2. Call edit_file with old_str copied EXACTLY from the file\n"
        "  3. Respond with FINAL_ANSWER: <summary of what was done>\n\n"
        "For recall questions (name, preferences, past facts), answer from memory below.\n"
        "For action tasks (run, check, edit, create), use tools.\n"
        "After getting a tool result, either call the next tool or give FINAL_ANSWER.\n"
        f"{rag_context}"
        f"{preflight_context}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": task},
    ]

    used_tools = False
    final_answer = ""
    max_turns = 6

    print("\n🤖 Agent Working... ", end="", flush=True)

    for turn in range(max_turns):
        # Retry LLM call on transient errors
        response = None
        for attempt in range(3):
            try:
                response = llm.invoke(messages)
                token_tracker.track(response)
                break
            except KeyboardInterrupt:
                print("\n⚠️  Interrupted")
                return "(interrupted)", used_tools
            except Exception as e:
                if attempt < 2:
                    import time
                    wait = 2 ** attempt
                    print(f"\n⚠️  LLM error (attempt {attempt+1}/3): {str(e)[:80]}")
                    print(f"   Retrying in {wait}s... ", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f"\n❌ LLM failed after 3 attempts: {str(e)[:120]}")
                    return f"Error: {str(e)[:200]}", used_tools

        text = response.content.strip()

        # Check for tool call
        if "TOOL_CALL:" in text:
            lines = text.splitlines()
            tool_name = ""
            tool_input = {}

            for i, line in enumerate(lines):
                if line.startswith("TOOL_CALL:"):
                    tool_name = line.replace("TOOL_CALL:", "").strip()
                if line.startswith("INPUT:"):
                    try:
                        tool_input = json.loads(line.replace("INPUT:", "").strip())
                    except Exception:
                        tool_input = {}

            if tool_name in TOOL_MAP:
                print(f"\n⚙️  [{tool_name}] running...\n🤖 Agent Working... ", end="", flush=True)
                try:
                    result = TOOL_MAP[tool_name].invoke(tool_input)
                except Exception as e:
                    result = f"ERROR: {e}"
                used_tools = True

                # Feed result back
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Tool result:\n{result}\n\n"
                        f"If the task is complete, respond with FINAL_ANSWER: <your summary>. "
                        f"If you need to do more, call the next tool."
                    )
                })

                # Auto-stop if edit_file succeeded — task is done
                if tool_name == "edit_file" and result.startswith("✅"):
                    final_answer = f"Done. {result}"
                    break
            else:
                # Unknown tool — treat as final answer
                final_answer = text
                break

        elif "FINAL_ANSWER:" in text:
            final_answer = text.replace("FINAL_ANSWER:", "").strip()
            break
        else:
            # No tool call and no FINAL_ANSWER marker — treat whole response as answer
            final_answer = text
            break

    # Simulate streaming: print word by word with a tiny delay
    # (Cloudflare doesn't support true token streaming)
    import time as _time
    words = final_answer.split()
    for i, word in enumerate(words):
        print(word, end=" " if i < len(words) - 1 else "", flush=True)
        _time.sleep(0.02)  # 20ms per word — fast enough to not be annoying
    print()  # newline

    return final_answer or text, used_tools

# ============================================================
# RUN ONE TASK — equivalent of runTask()
# ============================================================

def run_task(
    task: str,
    chat_history: list,
    project_context: str = "",
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
    preflight_context = ""
    if is_coding_task:
        if USE_TEXT_TOOLS:
            # Cloudflare — capable model, no file pre-loading needed
            coding_instruction = (
                "\n\nIMPORTANT: This is a coding task. You MUST use tools.\n"
                "Steps: 1) call read_file to read the target file, "
                "2) call edit_file with old_str copied EXACTLY from the file content, "
                "3) respond with FINAL_ANSWER."
            )
        else:
            # Ollama — small model needs file content pre-loaded into prompt
            file_match = re.search(r"([\w./\\-]+\.(?:py|js|ts|jsx|tsx|go|rs|java|cpp|c|h|json|yaml|yml|toml))", task)
            if file_match:
                target_file = file_match.group(1)
                try:
                    file_content = Path(target_file).read_text(encoding="utf-8")
                    preflight_context = (
                        f"\n\n--- CURRENT CONTENT OF {target_file} ---\n"
                        f"{file_content}\n"
                        f"--- END OF {target_file} ---\n"
                    )
                    print(f"\n📂 Pre-loaded: {target_file} ({len(file_content)} chars)")
                except Exception:
                    pass  # file not found — agent will handle it

            coding_instruction = (
                "\n\nIMPORTANT: This is a coding task. The file content is shown above."
                "\nYou MUST call edit_file to make the actual change — do NOT just show code."
                "\nUse the EXACT text from the file content above as old_str in edit_file."
            )

    # ── Cloudflare text-mode routing ──
    # Cloudflare's 70B model is capable enough to call read_file itself —
    # no need to pre-load file content (saves tokens, avoids context limits)
    if USE_TEXT_TOOLS:
        return cf_run_task(task, coding_instruction, rag_context)

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
- extract_symbol : extract a specific function/class (token-efficient, use instead of read_file when you know the symbol name)

CODING WORKFLOW:
1. extract_symbol → get just the function/class you need (saves tokens)
   OR read_file   → if you need the whole file
2. edit_file      → make surgical changes (ALWAYS prefer over write_file for edits)
3. write_file     → only for brand new files

CRITICAL RULES:
- NEVER answer a coding task from memory — always use extract_symbol or read_file first
- NEVER rewrite an entire file to change a few lines — use edit_file
- old_str in edit_file must match the file EXACTLY (copy from extract_symbol/read_file output)
- For CREATE/WRITE/SAVE/GENERATE a new file → use write_file
- For RUN/CHECK/LIST/FIND on the system → use run_shell or list_directory
- For SEARCH the web → use web_search
- Only answer from memory for personal facts — never for action tasks.
{rag_context}{preflight_context}{coding_instruction}{project_context}"""
    )

    messages = [system_with_rag] + chat_history[-4:] + [HumanMessage(task)]

    answer = ""
    used_tools = False

    # Stream the response — tokens print as they are generated
    print("\n🤖 Agent Working... ", end="", flush=True)

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            for chunk in agent.stream({"messages": messages}):
                # chunk["agent"] = LLM thinking / final answer tokens
                if "agent" in chunk:
                    for msg in chunk["agent"].get("messages", []):
                        content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
                        if content:
                            print(content, end="", flush=True)
                            answer += content

                # chunk["tools"] = tool execution results
                if "tools" in chunk:
                    used_tools = True
                    for msg in chunk["tools"].get("messages", []):
                        tool_name = getattr(msg, "name", "tool")
                        print(f"\n⚙️  [{tool_name}] running...\n🤖 Agent Working... ", end="", flush=True)
            break  # success — exit retry loop

        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
            answer = "(interrupted)"
            break

        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries:
                wait = 2 ** attempt  # exponential backoff: 1s, 2s
                print(f"\n⚠️  Error (attempt {attempt+1}/{max_retries+1}): {error_msg[:80]}")
                print(f"   Retrying in {wait}s...", end="", flush=True)
                import time; time.sleep(wait)
                print(" retrying...")
            else:
                print(f"\n❌ Failed after {max_retries+1} attempts: {error_msg[:120]}")
                answer = f"Sorry, I encountered an error: {error_msg[:200]}"

    print()  # newline after streaming finishes
    return answer.strip(), used_tools


# ============================================================
# INTERACTIVE LOOP — equivalent of main()
# ============================================================

# ============================================================
# PHASE 3 — PROJECT CONTEXT + SESSION TRACKER
# ============================================================

def load_project_context() -> str:
    """
    Auto-load project context on startup:
    - README.md summary (first 50 lines)
    - Project file structure (source files only)
    - Tech stack detected from imports/config files

    Returns a compact context string injected into the system prompt.
    """
    context_parts = []

    # 1. README summary
    for readme in ["README.md", "readme.md", "README.txt"]:
        p = Path(readme)
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:50]
            context_parts.append(f"📖 README:\n" + "\n".join(lines))
            break

    # 2. Project file structure (source files only, skip venv/cache)
    SKIP_DIRS = {"venv", ".venv", "node_modules", "__pycache__", ".git", "dist", "build"}
    CODE_EXTS  = {".py", ".js", ".ts", ".go", ".rs", ".java", ".json", ".yaml", ".toml", ".md"}
    files = []
    for p in sorted(Path(".").rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in CODE_EXTS:
            files.append(str(p))

    if files:
        context_parts.append("📁 Project files:\n" + "\n".join(f"  {f}" for f in files[:30]))

    # 3. Tech stack detection
    stack = []
    if Path("requirements.txt").exists():
        reqs = Path("requirements.txt").read_text(errors="ignore").lower()
        if "langchain"  in reqs: stack.append("LangChain")
        if "langgraph"  in reqs: stack.append("LangGraph")
        if "crewai"     in reqs: stack.append("CrewAI")
        if "fastapi"    in reqs: stack.append("FastAPI")
        if "django"     in reqs: stack.append("Django")
        if "flask"      in reqs: stack.append("Flask")
        if "pytest"     in reqs: stack.append("pytest")
        if "openai"     in reqs: stack.append("OpenAI")
        if "anthropic"  in reqs: stack.append("Anthropic")
    if Path("package.json").exists():
        stack.append("Node.js")
    if stack:
        context_parts.append(f"🔧 Stack: {', '.join(stack)}")

    if not context_parts:
        return ""

    return "\n\n--- PROJECT CONTEXT ---\n" + "\n\n".join(context_parts) + "\n--- END PROJECT CONTEXT ---\n"


class SessionTracker:
    """
    Phase 3: Track all file changes made during the current session.
    Shows a summary at the end so you know exactly what was touched.
    """
    def __init__(self):
        self.changes: dict[str, int] = {}   # file → edit count
        self.start_time = datetime.now()

    def record(self, path: str) -> None:
        self.changes[path] = self.changes.get(path, 0) + 1

    def summary(self) -> str:
        if not self.changes:
            return ""
        duration = (datetime.now() - self.start_time).seconds
        lines = [f"\n📝 Session Summary ({duration}s):"]
        for path, count in sorted(self.changes.items()):
            lines.append(f"   {path:<30} — {count} edit{'s' if count > 1 else ''}")
        lines.append("\n   Run 'git diff' to review all changes")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        return len(self.changes) == 0


# Global session tracker
session = SessionTracker()


def main():
    rag.load()
    chat_history = load_session()

    # ── Phase 3: Load project context on startup ──────────────
    project_context = load_project_context()

    print(f"\n🤖 LangChain Agent (Python)")
    print(f"🧠 LLM       : {llm.model if hasattr(llm, 'model') else type(llm).__name__}")
    print(f"🔍 RAG       : {rag.stats()['total']} vectors loaded")
    if chat_history:
        print(f"💬 Session   : {len(chat_history)} messages restored")
    if project_context:
        # Count files detected
        file_count = project_context.count("\n  .")
        stack_line = next((l for l in project_context.splitlines() if "Stack:" in l), "")
        print(f"📁 Project   : {file_count} files indexed")
        if stack_line:
            print(f"🔧 {stack_line.strip()}")
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
        answer, used_tools = run_task(task, chat_history, project_context)

        # Phase 3: track session changes
        file_match = re.search(r"([\w./\\-]+\.(?:py|js|ts|go|rs|java|json|yaml|toml))", task)
        if file_match and used_tools:
            session.record(file_match.group(1))

        # Update session
        chat_history.append(HumanMessage(task))
        chat_history.append(AIMessage(answer))
        save_session(chat_history)

        if not used_tools:
            rag.add(task, "user", "conversational")
            rag.add(answer, "assistant", "conversational")
            rag.save()
            print("💾 Stored in RAG")
        else:
            print("⚡ Not stored (real-time data — always runs fresh)")

        # Token summary
        summary = token_tracker.summary()
        if summary:
            print(summary)

        # Phase 3: print session summary
        if not session.is_empty():
            print(session.summary())
        return

    # Interactive mode
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            if not session.is_empty():
                print(session.summary())
            print("\n👋 Goodbye!\n")
            break

        if not user_input:
            continue

        if user_input in ("/exit", "/quit"):
            if not session.is_empty():
                print(session.summary())
            print("\n👋 Goodbye!\n")
            break

        if user_input == "/clear":
            rag.clear()
            chat_history.clear()
            print("🗑️  Cleared.")
            continue

        if user_input == "/session":
            print(session.summary() or "No files changed this session.")
            continue

        answer, used_tools = run_task(user_input, chat_history, project_context)

        # Phase 3: track session changes
        file_match = re.search(r"([\w./\\-]+\.(?:py|js|ts|go|rs|java|json|yaml|toml))", user_input)
        if file_match and used_tools:
            session.record(file_match.group(1))

        # Update in-memory chat history for multi-turn context
        chat_history.append(HumanMessage(user_input))
        chat_history.append(AIMessage(answer))
        save_session(chat_history)

        if not used_tools:
            rag.add(user_input, "user", "conversational")
            rag.add(answer, "assistant", "conversational")
            rag.save()
            print("💾 Stored in RAG")
        else:
            print("⚡ Real-time data — not stored in RAG")

        # Token summary
        summary = token_tracker.summary()
        if summary:
            print(summary)


if __name__ == "__main__":
    main()
