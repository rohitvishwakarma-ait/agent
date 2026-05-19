"""
agent_graph.py — LangGraph agent with advanced features

Phase 1 (done):
  1. Human-in-the-loop approval for file writes
  2. Automatic retry logic for failed tools
  3. Conditional branching
  4. Iterative refinement loops
  5. Persistent checkpointing

Phase 2 (new):
  6. Test → Fix loop  (run tests after edits, auto-fix failures)
  7. Multi-file planning  (plan all changes before acting)
  8. Git write operations  (commit, branch, stage with approval)

Run:
  python agent_graph.py "fix the bug in rag.py"              # with approval
  python agent_graph.py "check disk usage" --no-approval     # skip approval
  python agent_graph.py "add feature X" --plan               # show plan first
  python agent_graph.py --resume                             # resume last task
"""

import os
import sys
import json
import difflib
import ast
import subprocess
import operator
from pathlib import Path
from typing import Annotated, TypedDict, Literal, Optional
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from rag import RAG

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

CHECKPOINT_FILE = "graph_checkpoint.json"

from llm_config import get_llm
llm = get_llm()

# Detect Cloudflare — doesn't support OpenAI tool schema format
USE_TEXT_TOOLS = getattr(llm, "_cf_text_tools", False)

rag = RAG("rag.store.json")

# ============================================================
# TOOLS
# ============================================================

@tool
def run_shell(command: str) -> str:
    """Run a shell command on the local machine. Use for: checking running processes,
    finding ports, disk usage, current date/time, system info."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout or result.stderr or "(no output)"
        if result.returncode != 0:
            return f"ERROR[{result.returncode}]: {output}"
        return output
    except subprocess.TimeoutExpired:
        return "ERROR[TIMEOUT]: Command timed out after 30s"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def read_file(path: str) -> str:
    """Read the contents of a file from disk."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"ERROR[NOT_FOUND]: File not found: {path}"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file on disk. REQUIRES APPROVAL in interactive mode."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"✅ Written to {path} ({len(content)} chars)"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def list_directory(path: str) -> str:
    """List files and folders in a directory."""
    try:
        entries = sorted(Path(path).iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [f"📁 {e.name}" if e.is_dir() else f"📄 {e.name}" for e in entries]
        return "\n".join(lines) or "(empty)"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def edit_file(path: str, old_str: str, new_str: str) -> str:
    """Surgically replace an exact string in a file. Safer than write_file for edits.
    old_str must match the file content EXACTLY (including indentation).
    Returns a diff of what changed."""
    try:
        p = Path(path)
        if not p.exists():
            return f"ERROR[NOT_FOUND]: File not found: {path}"
        original = p.read_text(encoding="utf-8")
        if old_str not in original:
            return f"ERROR[NOT_FOUND]: old_str not found in {path}. Check indentation."
        count = original.count(old_str)
        if count > 1:
            return f"ERROR[AMBIGUOUS]: old_str appears {count} times. Make it more specific."
        updated = original.replace(old_str, new_str, 1)
        diff = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        ))
        p.write_text(updated, encoding="utf-8")
        diff_str = "".join(diff[:40])
        return f"✅ Edited {path}\n\n{diff_str}"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def run_tests(test_path: str = ".", pattern: str = "") -> str:
    """Run pytest tests and return results. Use after editing code to verify correctness.
    test_path: directory or file to test (default: current directory).
    pattern: optional test name filter e.g. 'test_rag' to run only matching tests."""
    try:
        cmd = ["python", "-m", "pytest", test_path, "-v", "--tb=short", "--no-header"]
        if pattern:
            cmd += ["-k", pattern]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        output = result.stdout + result.stderr
        # Summarise pass/fail counts
        lines = output.splitlines()
        summary = next((l for l in reversed(lines) if "passed" in l or "failed" in l or "error" in l), "")
        status = "✅ PASSED" if result.returncode == 0 else "❌ FAILED"
        return f"{status}\n{summary}\n\n{output[-3000:]}"  # cap output
    except subprocess.TimeoutExpired:
        return "ERROR[TIMEOUT]: Tests timed out after 60s"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


@tool
def git_write(action: str, message: str = "", files: str = ".", branch: str = "", remote: str = "origin") -> str:
    """Perform git write operations. REQUIRES APPROVAL.
    action: 'stage' | 'commit' | 'push' | 'branch'
    message: commit message (for commit action)
    files: files to stage (default: all changed files)
    branch: branch name (for branch action)
    remote: remote name for push (default: origin)"""
    try:
        if action == "branch":
            if not branch:
                return "ERROR: branch name required"
            result = subprocess.run(
                f"git checkout -b {branch}",
                shell=True, capture_output=True, text=True
            )
            return result.stdout or result.stderr
        elif action == "stage":
            result = subprocess.run(
                f"git add {files}",
                shell=True, capture_output=True, text=True
            )
            return f"✅ Staged: {files}\n{result.stdout or result.stderr}"
        elif action == "commit":
            if not message:
                return "ERROR: commit message required"
            result = subprocess.run(
                f'git commit -m "{message}"',
                shell=True, capture_output=True, text=True
            )
            return result.stdout or result.stderr
        elif action == "push":
            # Get current branch if not specified
            if not branch:
                br = subprocess.run(
                    "git rev-parse --abbrev-ref HEAD",
                    shell=True, capture_output=True, text=True
                )
                branch = br.stdout.strip() or "main"
            result = subprocess.run(
                f"git push {remote} {branch}",
                shell=True, capture_output=True, text=True
            )
            output = result.stdout or result.stderr
            if result.returncode == 0:
                return f"✅ Pushed to {remote}/{branch}\n{output}"
            return f"ERROR: push failed\n{output}"
        else:
            return f"ERROR: unknown action '{action}'. Use: stage | commit | push | branch"
    except Exception as e:
        return f"ERROR[EXCEPTION]: {e}"


tools = [run_shell, read_file, write_file, edit_file, list_directory, run_tests, git_write]
tool_node = ToolNode(tools)

# ============================================================
# STATE
# ============================================================

class AgentState(TypedDict):
    messages:          Annotated[list, operator.add]
    task:              str
    plan:              str           # Phase 2: multi-file plan
    plan_approved:     bool          # Phase 2: did user approve the plan?
    retry_count:       int
    needs_approval:    bool
    approved:          bool
    test_result:       str           # Phase 2: last test run output
    test_passed:       bool          # Phase 2: did tests pass?
    fix_attempts:      int           # Phase 2: how many test-fix cycles
    validation_passed: bool
    iteration_count:   int
    changed_files:     list          # Phase 2: track what was edited


# ============================================================
# PHASE 2 — PLANNING NODE
# Produces a structured plan before touching any files
# ============================================================

def planner_node(state: AgentState) -> AgentState:
    """Generate a multi-file plan before making any changes."""
    task = state["task"]

    system = SystemMessage(
        """You are a senior software engineer planning a coding task.

Given a task, produce a concise implementation plan in this EXACT format:

PLAN:
1. File: <path>  Action: <read|edit|create|delete>  Reason: <why>
2. File: <path>  Action: <read|edit|create|delete>  Reason: <why>
...

SUMMARY: <one sentence describing the overall approach>

Rules:
- List every file that needs to be touched
- Be specific about what action is needed
- Keep reasons brief (max 10 words)
- Do NOT write any code yet — just the plan"""
    )

    response = llm.invoke([system, HumanMessage(f"Task: {task}")])
    plan_text = response.content.strip()

    print("\n" + "="*60)
    print("📋 IMPLEMENTATION PLAN")
    print("="*60)
    print(plan_text)
    print("="*60)

    # Ask user to approve the plan
    try:
        approval = input("\nApprove this plan? (y/n/edit): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        approval = "y"

    if approval == "n":
        print("❌ Plan rejected. Stopping.")
        return {
            "plan": plan_text,
            "plan_approved": False,
            "messages": [AIMessage("Plan was rejected by user. Task cancelled.")],
        }
    elif approval == "edit":
        print("Enter your revised plan (press Enter twice when done):")
        lines = []
        while True:
            try:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            except (EOFError, KeyboardInterrupt):
                break
        plan_text = "\n".join(lines)
        print("✅ Using your revised plan.")

    print("✅ Plan approved — starting execution...\n")
    return {
        "plan": plan_text,
        "plan_approved": True,
        "messages": [HumanMessage(
            f"Execute this plan:\n{plan_text}\n\nOriginal task: {task}"
        )],
    }


# ============================================================
# PHASE 2 — TEST RUNNER NODE
# Runs tests after code changes and feeds failures back to agent
# ============================================================

def test_runner_node(state: AgentState) -> AgentState:
    """Run tests after code edits. Feed failures back to agent for fixing."""
    fix_attempts = state.get("fix_attempts", 0)
    changed_files = state.get("changed_files", [])

    print(f"\n🧪 Running tests (attempt {fix_attempts + 1}/3)...")

    # Run pytest
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", ".", "-v", "--tb=short", "--no-header", "-q"],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0

        # Extract summary line
        lines = output.splitlines()
        summary = next(
            (l for l in reversed(lines) if "passed" in l or "failed" in l or "error" in l),
            "No test summary found"
        )

        if passed:
            print(f"✅ Tests passed: {summary}")
            return {
                "test_result": output,
                "test_passed": True,
                "fix_attempts": fix_attempts,
            }
        else:
            print(f"❌ Tests failed: {summary}")
            # Feed failure back to agent for fixing
            failure_msg = (
                f"Tests FAILED after your changes.\n"
                f"Summary: {summary}\n\n"
                f"Failure details:\n{output[-2000:]}\n\n"
                f"Changed files: {', '.join(changed_files) if changed_files else 'unknown'}\n"
                f"Please fix the failing tests using edit_file."
            )
            return {
                "test_result": output,
                "test_passed": False,
                "fix_attempts": fix_attempts + 1,
                "messages": [HumanMessage(failure_msg)],
            }
    except subprocess.TimeoutExpired:
        return {
            "test_result": "ERROR: Tests timed out",
            "test_passed": False,
            "fix_attempts": fix_attempts + 1,
            "messages": [HumanMessage("Tests timed out. Check for infinite loops.")],
        }
    except FileNotFoundError:
        # pytest not available — skip test loop
        print("⚠️  pytest not found — skipping test verification")
        return {"test_passed": True, "test_result": "pytest not available"}


# ============================================================
# EXISTING NODES (updated)
# ============================================================

def agent_node(state: AgentState) -> AgentState:
    """Main agent — decides what to do next."""
    messages = state["messages"]
    plan = state.get("plan", "")
    plan_context = f"\nCurrent plan:\n{plan}\n" if plan else ""

    tools_desc = "\n".join([
        f"- {t.name}: {t.description.splitlines()[0]}"
        for t in tools
    ])

    if USE_TEXT_TOOLS:
        # ── Cloudflare text-mode: describe tools as text, parse TOOL_CALL blocks ──
        system_content = (
            f"You are an expert coding agent.\n\n"
            f"AVAILABLE TOOLS:\n{tools_desc}\n\n"
            f"To use a tool respond with:\n"
            f"TOOL_CALL: tool_name\n"
            f"INPUT: {{\"param\": \"value\"}}\n\n"
            f"CRITICAL RULES:\n"
            f"  - CREATE a new file → use write_file (never run_shell with echo/touch)\n"
            f"  - EDIT a file → read_file first, then edit_file\n"
            f"  - GIT stage → git_write action=stage files=<path>\n"
            f"  - GIT commit → git_write action=commit message=<msg>\n"
            f"  - GIT push → git_write action=push\n"
            f"  - Always complete file operations BEFORE git operations\n\n"
            f"WORKFLOW for 'create file and commit':\n"
            f"  1. write_file (create the file)\n"
            f"  2. git_write action=stage files=<filename>\n"
            f"  3. git_write action=commit message=<msg>\n"
            f"  4. git_write action=push (if requested)\n"
            f"  5. FINAL_ANSWER: <summary>\n\n"
            f"When done respond with FINAL_ANSWER: <your answer>\n"
            f"{plan_context}"
        )
        cf_messages = [{"role": "system", "content": system_content}]
        for m in messages:
            if isinstance(m, HumanMessage):
                cf_messages.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                cf_messages.append({"role": "assistant", "content": m.content or ""})
            elif isinstance(m, ToolMessage):
                cf_messages.append({"role": "user", "content": f"Tool result: {m.content}"})

        # ── Multi-tool loop: keep calling tools until FINAL_ANSWER or max_turns ──
        tool_map = {t.name: t for t in tools}
        changed = list(state.get("changed_files", []))
        accumulated_messages = []
        max_turns = 6
        final_text = ""

        for turn in range(max_turns):
            response = llm.invoke(cf_messages)
            text = response.content.strip()
            accumulated_messages.append(response)

            # Check for FINAL_ANSWER first
            if "FINAL_ANSWER:" in text:
                final_text = text.replace("FINAL_ANSWER:", "").strip()
                break

            # Parse TOOL_CALL from response
            if "TOOL_CALL:" in text:
                lines = text.splitlines()
                tool_name  = ""
                tool_input = {}
                for line in lines:
                    if line.startswith("TOOL_CALL:"):
                        tool_name = line.replace("TOOL_CALL:", "").strip()
                    if line.startswith("INPUT:"):
                        try:
                            tool_input = json.loads(line.replace("INPUT:", "").strip())
                        except Exception:
                            tool_input = {}

                if tool_name in tool_map:
                    print(f"\n⚙️  [{tool_name}] running...")
                    try:
                        result = tool_map[tool_name].invoke(tool_input)
                    except Exception as e:
                        result = f"ERROR[EXCEPTION]: {e}"

                    # Track changed files
                    if tool_name in ("edit_file", "write_file"):
                        f = tool_input.get("path", "")
                        if f and f not in changed:
                            changed.append(f)

                    # Feed result back into conversation and continue loop
                    cf_messages.append({"role": "assistant", "content": text})
                    cf_messages.append({
                        "role": "user",
                        "content": (
                            f"Tool result:\n{result}\n\n"
                            f"If the task is complete, respond with FINAL_ANSWER: <summary>. "
                            f"If you need to do more, call the next tool."
                        )
                    })
                    accumulated_messages.append(AIMessage(content=f"[tool:{tool_name}] {result[:200]}"))
                    continue  # next turn
                else:
                    # Unknown tool name — treat response as final answer
                    final_text = text
                    break
            else:
                # No tool call and no FINAL_ANSWER — treat whole response as answer
                final_text = text
                break

        # If we exhausted max_turns without a final answer, use last response
        if not final_text:
            final_text = text

        final_ai_msg = AIMessage(content=final_text)
        return {
            "messages": accumulated_messages + [final_ai_msg],
            "changed_files": changed,
        }

    else:
        # ── Standard mode: Ollama / OpenAI with native tool binding ──
        system_msg = SystemMessage(
            f"""You are an expert coding agent with Claude Code-like capabilities.

AVAILABLE TOOLS:
{tools_desc}
{plan_context}
WORKFLOW:
1. read_file → understand current code
2. edit_file → make surgical changes (never rewrite whole files)
3. run_tests → verify changes work
4. git_write → commit if tests pass

RULES:
- Always use edit_file for modifications, write_file only for new files
- After editing code, always run_tests to verify
- Track which files you changed
- If tests fail, fix them before finishing"""
        )

        response = llm.bind_tools(tools).invoke([system_msg] + messages)

        # Track changed files from tool calls
        changed = list(state.get("changed_files", []))
        if hasattr(response, "tool_calls"):
            for tc in response.tool_calls:
                if tc["name"] in ("edit_file", "write_file"):
                    f = tc["args"].get("path", "")
                    if f and f not in changed:
                        changed.append(f)

        return {"messages": [response], "changed_files": changed}


def check_approval_needed(state: AgentState) -> AgentState:
    """Check if the last message needs human approval."""
    # In Cloudflare text-mode, tools are executed directly in agent_node
    # so there are no pending tool_calls to approve here
    if USE_TEXT_TOOLS:
        return {"needs_approval": False}

    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tc in last_message.tool_calls:
            if tc["name"] in ("write_file", "git_write"):
                return {"needs_approval": True, "approved": False}
    return {"needs_approval": False}


def human_approval_node(state: AgentState) -> AgentState:
    """Pause and ask human for approval before write/git operations."""
    last_message = state["messages"][-1]

    for tc in last_message.tool_calls:
        if tc["name"] not in ("write_file", "git_write"):
            continue

        print("\n" + "="*60)
        if tc["name"] == "write_file":
            path    = tc["args"]["path"]
            content = tc["args"]["content"]
            print("🚨 FILE WRITE APPROVAL REQUIRED")
            print("="*60)
            print(f"Path: {path}")
            print(f"Content preview (first 500 chars):\n{'-'*60}")
            print(content[:500])
            if len(content) > 500:
                print(f"... ({len(content)-500} more chars)")
        else:
            action  = tc["args"].get("action", "")
            message = tc["args"].get("message", "")
            files   = tc["args"].get("files", ".")
            branch  = tc["args"].get("branch", "")
            print("🚨 GIT OPERATION APPROVAL REQUIRED")
            print("="*60)
            print(f"Action : {action}")
            if message: print(f"Message: {message}")
            if files:   print(f"Files  : {files}")
            if branch:  print(f"Branch : {branch}")
        print("-"*60)

        response = input("\nApprove? (y/n): ").strip().lower()
        if response == "y":
            print("✅ Approved")
            return {"approved": True}
        else:
            print("❌ Rejected")
            rejection = ToolMessage(
                content=f"REJECTED: User did not approve {tc['name']}",
                tool_call_id=tc["id"],
            )
            return {"approved": False, "messages": [rejection]}

    return {"approved": True}


def retry_node(state: AgentState) -> AgentState:
    """Handle tool errors with retry logic."""
    last_message = state["messages"][-1]
    retry_count  = state.get("retry_count", 0)

    if isinstance(last_message, ToolMessage) and "ERROR[" in last_message.content:
        if retry_count < 2:
            print(f"\n⚠️  Tool failed, retrying ({retry_count + 1}/2)...")
            return {
                "retry_count": retry_count + 1,
                "messages": [HumanMessage(
                    f"Tool failed: {last_message.content}\nTry a different approach."
                )],
            }
        else:
            print("\n❌ Max retries reached")
            return {
                "retry_count": 0,
                "messages": [HumanMessage(
                    f"After {retry_count} retries the tool still fails. "
                    "Explain the issue and suggest alternatives."
                )],
            }
    return {"retry_count": 0}


def validator_node(state: AgentState) -> AgentState:
    """Validate the agent's output."""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage):
        content = last_message.content
        if len(content) < 10:
            return {
                "validation_passed": False,
                "messages": [HumanMessage("Response too short. Provide more detail.")],
            }
        if "ERROR[" in content and "explain" not in content.lower():
            return {
                "validation_passed": False,
                "messages": [HumanMessage(
                    "You mentioned an error but didn't explain it. "
                    "Explain what went wrong and suggest a fix."
                )],
            }
    return {"validation_passed": True}


# ============================================================
# ROUTING FUNCTIONS
# ============================================================

def route_after_plan(state: AgentState) -> Literal["agent", "__end__"]:
    """Continue to agent if plan approved, else end."""
    return "agent" if state.get("plan_approved", True) else "__end__"


def route_after_agent(state: AgentState) -> Literal["tools", "check_approval", "__end__"]:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "check_approval"
    return "__end__"


def route_after_approval_check(state: AgentState) -> Literal["approval", "tools"]:
    return "approval" if state.get("needs_approval", False) else "tools"


def route_after_approval(state: AgentState) -> Literal["tools", "__end__"]:
    return "tools" if state.get("approved", False) else "__end__"


def route_after_tools(state: AgentState) -> Literal["retry", "agent"]:
    last_message = state["messages"][-1]
    if isinstance(last_message, ToolMessage) and "ERROR[" in last_message.content:
        return "retry"
    return "agent"


def route_after_agent_to_tests(
    state: AgentState,
) -> Literal["agent", "check_approval", "run_tests", "__end__"]:
    """After agent responds: route based on last message type."""
    last_message  = state["messages"][-1]
    changed_files = state.get("changed_files", [])

    # Standard mode only: pending tool_calls → go through approval flow
    if not USE_TEXT_TOOLS and hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "check_approval"

    # Code was changed → run tests before finishing
    code_changed = any(f.endswith((".py", ".js", ".ts")) for f in changed_files)
    if code_changed and not state.get("test_passed", False):
        return "run_tests"

    return "__end__"


def route_after_tests(state: AgentState) -> Literal["agent", "__end__"]:
    """If tests failed and we haven't exceeded fix attempts, go back to agent."""
    if state.get("test_passed", True):
        return "__end__"
    if state.get("fix_attempts", 0) >= 3:
        print("\n⚠️  Max fix attempts reached — returning current state")
        return "__end__"
    return "agent"


def route_after_validation(state: AgentState) -> Literal["agent", "__end__"]:
    iteration_count = state.get("iteration_count", 0)
    if not state.get("validation_passed", True):
        if iteration_count < 3:
            print(f"\n🔄 Validation failed, refining ({iteration_count + 1}/3)...")
            return "agent"
        print("\n⚠️  Max iterations reached")
    return "__end__"


# ============================================================
# BUILD THE GRAPH
# ============================================================

def build_graph(
    enable_approval: bool = True,
    enable_planning: bool = False,
    enable_tests:    bool = True,
) -> StateGraph:
    """Build the LangGraph workflow with Phase 2 features."""

    workflow = StateGraph(AgentState)

    # ── Nodes ──────────────────────────────────────────────
    workflow.add_node("planner",    planner_node)
    workflow.add_node("agent",      agent_node)
    workflow.add_node("check_approval", check_approval_needed)
    workflow.add_node("approval",   human_approval_node)
    workflow.add_node("tools",      tool_node)
    workflow.add_node("retry",      retry_node)
    workflow.add_node("run_tests",  test_runner_node)
    workflow.add_node("validator",  validator_node)

    # ── Entry point ────────────────────────────────────────
    if enable_planning:
        workflow.set_entry_point("planner")
        workflow.add_conditional_edges("planner", route_after_plan)
    else:
        workflow.set_entry_point("agent")

    # ── Agent → tools or tests ─────────────────────────────
    if enable_tests:
        workflow.add_conditional_edges(
            "agent",
            route_after_agent_to_tests,
            {
                "agent":          "agent",
                "check_approval": "check_approval",
                "run_tests":      "run_tests",
                "__end__":        END,
            }
        )
    else:
        workflow.add_conditional_edges("agent", route_after_agent)

    # ── Approval flow ──────────────────────────────────────
    if enable_approval:
        workflow.add_conditional_edges("check_approval", route_after_approval_check)
        workflow.add_conditional_edges("approval", route_after_approval)
    else:
        workflow.add_edge("check_approval", "tools")

    # ── Tools → retry or agent ─────────────────────────────
    workflow.add_conditional_edges("tools", route_after_tools)
    workflow.add_edge("retry", "agent")

    # ── Test loop ──────────────────────────────────────────
    workflow.add_conditional_edges("run_tests", route_after_tests)

    # ── Validation ─────────────────────────────────────────
    workflow.add_conditional_edges("validator", route_after_validation)

    return workflow


# ============================================================
# MAIN
# ============================================================

def main():
    rag.load()

    args  = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]

    enable_approval  = "--no-approval"  not in flags
    enable_checkpoints = "--no-checkpoints" not in flags
    enable_planning  = "--plan"         in flags
    enable_tests     = "--no-tests"     not in flags

    print(f"\n🤖 LangGraph Agent (Phase 2)")
    print(f"🧠 LLM        : {llm.model if hasattr(llm, 'model') else type(llm).__name__}")
    print(f"🔐 Approval   : {'enabled' if enable_approval else 'disabled'}")
    print(f"💾 Checkpoints: {'enabled' if enable_checkpoints else 'disabled'}")
    print(f"📋 Planning   : {'enabled' if enable_planning else 'disabled (use --plan)'}")
    print(f"🧪 Test loop  : {'enabled' if enable_tests else 'disabled'}")
    print()

    workflow = build_graph(
        enable_approval=enable_approval,
        enable_planning=enable_planning,
        enable_tests=enable_tests,
    )

    if enable_checkpoints:
        memory = MemorySaver()
        app    = workflow.compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "main"}}
    else:
        app    = workflow.compile()
        config = {}

    if "--resume" in flags:
        if not enable_checkpoints:
            print("❌ Cannot resume without checkpoints.")
            return
        print("📂 Resuming from last checkpoint...")
        state = app.get_state(config)
        if state and state.values:
            print(f"📋 Last task: {state.values.get('task', 'unknown')}")
        else:
            print("❌ No checkpoint found.")
            return
    else:
        if not args:
            print("Usage: python agent_graph.py \"your task\" [flags]")
            print("Flags:")
            print("  --no-approval     skip human approval for writes")
            print("  --no-checkpoints  disable state persistence")
            print("  --plan            show implementation plan before acting")
            print("  --no-tests        skip test verification loop")
            print("  --resume          resume last checkpointed task")
            return

        task = args[0]
        print(f"📋 Task: {task}\n")

        initial_state = {
            "messages":         [HumanMessage(task)],
            "task":             task,
            "plan":             "",
            "plan_approved":    True,
            "retry_count":      0,
            "needs_approval":   False,
            "approved":         False,
            "test_result":      "",
            "test_passed":      False,
            "fix_attempts":     0,
            "validation_passed": True,
            "iteration_count":  0,
            "changed_files":    [],
        }

        print("🚀 Starting agent...\n")

        all_messages = []
        for event in app.stream(initial_state, config):
            for node_name, node_state in event.items():
                if node_name != "__end__":
                    print(f"📍 Node: {node_name}")
                    # Accumulate ALL messages across all nodes
                    if "messages" in node_state:
                        all_messages.extend(node_state["messages"])

        # Find last meaningful AIMessage across all accumulated messages
        changed = initial_state.get("changed_files", [])
        found_answer = False
        for msg in reversed(all_messages):
            if isinstance(msg, AIMessage) and msg.content:
                content = msg.content.strip()
                # Skip raw TOOL_CALL responses — not the final answer
                if content.startswith("TOOL_CALL:") or content.startswith("INPUT:"):
                    continue
                # Strip FINAL_ANSWER: prefix if present
                if content.startswith("FINAL_ANSWER:"):
                    content = content.replace("FINAL_ANSWER:", "").strip()
                print("\n" + "="*60)
                print("✅ FINAL ANSWER")
                print("="*60)
                print(content)
                found_answer = True
                break

        if not found_answer:
            print("\n⚠️  No response generated")

        if changed:
            print(f"\n📝 Files changed this session: {', '.join(changed)}")


if __name__ == "__main__":
    main()
