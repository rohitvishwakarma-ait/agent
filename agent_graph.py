"""
agent_graph.py — LangGraph agent with advanced features

Adds to agent.py:
  1. Human-in-the-loop approval for file writes
  2. Automatic retry logic for failed tools
  3. Conditional branching (skip unnecessary steps)
  4. Iterative refinement loops (validate → fix → validate)
  5. Persistent state (resume after restart)

Run:
  python agent_graph.py "create a hello.py file"           # with approval
  python agent_graph.py "check disk usage" --no-approval   # skip approval
  python agent_graph.py --resume                           # resume last task
"""

import os
import sys
import json
import subprocess
import operator
from pathlib import Path
from typing import Annotated, TypedDict, Literal
from dotenv import load_dotenv

from langchain_ollama import ChatOllama
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

OLLAMA_MODEL = "qwen2:7b"
CHECKPOINT_FILE = "graph_checkpoint.json"

llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url="http://localhost:11434",
    temperature=0,
)

rag = RAG("rag.store.json")

# ============================================================
# TOOLS — same as agent.py but with retry-friendly error handling
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
        # Tag errors clearly so retry logic can detect them
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


tools = [run_shell, read_file, write_file, list_directory]
tool_node = ToolNode(tools)

# ============================================================
# STATE — the data that flows through the graph
# ============================================================

class AgentState(TypedDict):
    """State that flows through the graph nodes."""
    messages: Annotated[list, operator.add]  # conversation history
    task: str                                 # original user task
    retry_count: int                          # how many retries so far
    needs_approval: bool                      # does this need human approval?
    approved: bool                            # did human approve?
    validation_passed: bool                   # did validation pass?
    iteration_count: int                      # for iterative refinement


# ============================================================
# GRAPH NODES — each node is a step in the workflow
# ============================================================

def agent_node(state: AgentState) -> AgentState:
    """Main agent — decides what to do next."""
    messages = state["messages"]
    
    # Add system prompt
    system_msg = SystemMessage(
        """You are a helpful AI agent with tools.

AVAILABLE TOOLS:
- run_shell: run shell commands (processes, ports, disk, date, system info)
- read_file: read a file from disk
- write_file: create or overwrite a file (REQUIRES APPROVAL)
- list_directory: list files in a folder

CRITICAL RULES:
- If a tool returns ERROR[...], explain what went wrong
- For write_file, generate the FULL content, then call the tool
- Always give a clear final answer after using tools"""
    )
    
    response = llm.bind_tools(tools).invoke([system_msg] + messages)
    return {"messages": [response]}


def check_approval_needed(state: AgentState) -> AgentState:
    """Check if the last message contains a write_file tool call."""
    last_message = state["messages"][-1]
    
    # Check if it's an AI message with tool calls
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "write_file":
                return {
                    "needs_approval": True,
                    "approved": False,
                }
    
    return {"needs_approval": False}


def human_approval_node(state: AgentState) -> AgentState:
    """Pause and ask human for approval before writing files."""
    last_message = state["messages"][-1]
    
    # Extract the write_file call details
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "write_file":
            path = tool_call["args"]["path"]
            content = tool_call["args"]["content"]
            
            print("\n" + "="*60)
            print("🚨 FILE WRITE APPROVAL REQUIRED")
            print("="*60)
            print(f"Path: {path}")
            print(f"Content preview (first 500 chars):")
            print("-"*60)
            print(content[:500])
            if len(content) > 500:
                print(f"\n... ({len(content) - 500} more chars)")
            print("-"*60)
            
            response = input("\nApprove this write? (y/n): ").strip().lower()
            
            if response == 'y':
                print("✅ Approved — writing file...")
                return {"approved": True}
            else:
                print("❌ Rejected — skipping write")
                # Add a message explaining the rejection
                rejection_msg = ToolMessage(
                    content=f"REJECTED: User did not approve writing to {path}",
                    tool_call_id=tool_call["id"],
                )
                return {
                    "approved": False,
                    "messages": [rejection_msg],
                }
    
    return {"approved": True}  # no write_file found, approve by default


def retry_node(state: AgentState) -> AgentState:
    """Handle tool errors with retry logic."""
    last_message = state["messages"][-1]
    retry_count = state.get("retry_count", 0)
    
    # Check if the last tool result was an error
    if isinstance(last_message, ToolMessage) and "ERROR[" in last_message.content:
        if retry_count < 2:  # max 2 retries
            print(f"\n⚠️  Tool failed, retrying ({retry_count + 1}/2)...")
            return {
                "retry_count": retry_count + 1,
                "messages": [
                    HumanMessage(
                        f"The previous tool call failed with: {last_message.content}\n"
                        f"Please try a different approach or command."
                    )
                ],
            }
        else:
            print(f"\n❌ Max retries reached, giving up")
            return {
                "retry_count": 0,
                "messages": [
                    HumanMessage(
                        f"After {retry_count} retries, the tool still fails. "
                        f"Please explain the issue to the user and suggest alternatives."
                    )
                ],
            }
    
    return {"retry_count": 0}  # reset on success


def validator_node(state: AgentState) -> AgentState:
    """Validate the agent's output (for iterative refinement)."""
    messages = state["messages"]
    last_message = messages[-1]
    
    # Simple validation: check if the response is too short or contains errors
    if isinstance(last_message, AIMessage):
        content = last_message.content
        
        # Validation rules
        if len(content) < 10:
            return {
                "validation_passed": False,
                "messages": [
                    HumanMessage(
                        "Your response is too short. Please provide more detail."
                    )
                ],
            }
        
        if "ERROR[" in content and "explain" not in content.lower():
            return {
                "validation_passed": False,
                "messages": [
                    HumanMessage(
                        "You mentioned an error but didn't explain it. "
                        "Please explain what went wrong and suggest a solution."
                    )
                ],
            }
    
    return {"validation_passed": True}


# ============================================================
# ROUTING FUNCTIONS — decide which node to go to next
# ============================================================

def route_after_agent(state: AgentState) -> Literal["tools", "check_approval", "__end__"]:
    """Decide what to do after the agent responds."""
    last_message = state["messages"][-1]
    
    # If agent called tools, execute them
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "check_approval"
    
    # Otherwise we're done
    return "__end__"


def route_after_approval_check(state: AgentState) -> Literal["approval", "tools"]:
    """Route to human approval if needed, otherwise execute tools."""
    if state.get("needs_approval", False):
        return "approval"
    return "tools"


def route_after_approval(state: AgentState) -> Literal["tools", "__end__"]:
    """Execute tools if approved, otherwise end."""
    if state.get("approved", False):
        return "tools"
    return "__end__"


def route_after_tools(state: AgentState) -> Literal["retry", "agent"]:
    """Check if we need to retry or continue."""
    last_message = state["messages"][-1]
    
    # If tool returned an error, go to retry logic
    if isinstance(last_message, ToolMessage) and "ERROR[" in last_message.content:
        return "retry"
    
    # Otherwise continue to agent
    return "agent"


def route_after_validation(state: AgentState) -> Literal["agent", "__end__"]:
    """Loop back to agent if validation failed, otherwise end."""
    iteration_count = state.get("iteration_count", 0)
    
    if not state.get("validation_passed", True):
        if iteration_count < 3:  # max 3 iterations
            print(f"\n🔄 Validation failed, refining (iteration {iteration_count + 1}/3)...")
            return "agent"
        else:
            print(f"\n⚠️  Max iterations reached, returning current result")
    
    return "__end__"


# ============================================================
# BUILD THE GRAPH
# ============================================================

def build_graph(enable_approval: bool = True) -> StateGraph:
    """Build the LangGraph workflow."""
    
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("check_approval", check_approval_needed)
    workflow.add_node("approval", human_approval_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("retry", retry_node)
    workflow.add_node("validator", validator_node)
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add edges
    workflow.add_conditional_edges("agent", route_after_agent)
    
    if enable_approval:
        workflow.add_conditional_edges("check_approval", route_after_approval_check)
        workflow.add_conditional_edges("approval", route_after_approval)
    else:
        workflow.add_edge("check_approval", "tools")
    
    workflow.add_conditional_edges("tools", route_after_tools)
    workflow.add_edge("retry", "agent")
    workflow.add_conditional_edges("validator", route_after_validation)
    
    return workflow


# ============================================================
# MAIN
# ============================================================

def main():
    rag.load()
    
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    
    enable_approval = "--no-approval" not in flags
    enable_checkpoints = "--no-checkpoints" not in flags
    
    print(f"\n🤖 LangGraph Agent")
    print(f"🧠 LLM: {OLLAMA_MODEL}")
    print(f"🔐 Approval: {'enabled' if enable_approval else 'disabled'}")
    print(f"💾 Checkpoints: {'enabled' if enable_checkpoints else 'disabled'}")
    print()
    
    # Build graph
    workflow = build_graph(enable_approval=enable_approval)
    
    # Add checkpointing if enabled
    if enable_checkpoints:
        memory = MemorySaver()
        app = workflow.compile(checkpointer=memory)
        config = {"configurable": {"thread_id": "main"}}
    else:
        app = workflow.compile()
        config = {}
    
    # Handle resume
    if "--resume" in flags:
        if not enable_checkpoints:
            print("❌ Cannot resume without checkpoints. Remove --no-checkpoints flag.")
            return
        
        print("📂 Resuming from last checkpoint...")
        # Get the last state
        state = app.get_state(config)
        if state and state.values:
            print(f"📋 Last task: {state.values.get('task', 'unknown')}")
            print("🔄 Continuing...\n")
        else:
            print("❌ No checkpoint found to resume from.")
            return
    else:
        # New task
        if not args:
            print("Usage: python agent_graph.py \"your task\" [--no-approval] [--no-checkpoints]")
            print("       python agent_graph.py --resume")
            return
        
        task = args[0]
        print(f"📋 Task: {task}\n")
        
        # Initial state
        initial_state = {
            "messages": [HumanMessage(task)],
            "task": task,
            "retry_count": 0,
            "needs_approval": False,
            "approved": False,
            "validation_passed": True,
            "iteration_count": 0,
        }
        
        # Run the graph
        print("🚀 Starting agent...\n")
        
        final_messages = []
        for event in app.stream(initial_state, config):
            # Print progress
            for node_name, node_state in event.items():
                if node_name != "__end__":
                    print(f"📍 Node: {node_name}")
                    # Collect messages from the last event
                    if "messages" in node_state:
                        final_messages = node_state["messages"]
        
        # Extract final answer from collected messages
        if final_messages:
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    print("\n" + "="*60)
                    print("✅ FINAL ANSWER")
                    print("="*60)
                    print(msg.content)
                    break
        else:
            print("\n⚠️  No response generated")


if __name__ == "__main__":
    main()
