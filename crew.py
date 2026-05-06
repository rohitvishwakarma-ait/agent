"""
crew.py — Multi-agent CrewAI system built on top of agent.py

Three crews, each for a different type of complex task:

  1. CodeCrew      — review code → fix bugs → write tests
  2. ResearchCrew  — search web  → analyse  → write report
  3. DevOpsCrew    — check system → check git → write health report

Run:
  python crew.py code     "review agent.py and suggest improvements"
  python crew.py research "latest features in Python 3.13"
  python crew.py devops   "give me a full system and repo health report"
  python crew.py          # interactive menu
"""

import os
import sys
import json
import subprocess
import requests
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import BaseTool

load_dotenv()

# ============================================================
# LLM — CrewAI uses its own LLM wrapper (talks to Ollama via OpenAI-compat API)
# ============================================================

llm = LLM(
    model="ollama/qwen2:7b",
    base_url="http://localhost:11434",
    temperature=0,          # deterministic for tool-calling
    max_tokens=4096,
)

# ============================================================
# TOOL INPUT SCHEMAS
# CrewAI uses Pydantic models to define tool inputs
# (equivalent of Zod schemas in TypeScript)
# ============================================================

class CommandInput(BaseModel):
    command: str = Field(description="Shell command to run")

class FileReadInput(BaseModel):
    path: str = Field(description="Path to the file to read")

class FileWriteInput(BaseModel):
    path: str    = Field(description="Path where the file should be written")
    content: str = Field(description="Full content to write into the file")

class DirectoryInput(BaseModel):
    path: str = Field(description="Directory path to list. Use '.' for current directory")

class SearchInput(BaseModel):
    query: str = Field(description="Search query string")

class GitInput(BaseModel):
    command: str = Field(description="Git subcommand e.g. 'log --oneline -10' or 'status'")

class HttpInput(BaseModel):
    method:  str = Field(description="HTTP method: GET, POST, PUT, DELETE")
    url:     str = Field(description="Full URL to call")
    body:    str = Field(default="", description="Optional JSON body string")
    headers: str = Field(default="", description="Optional JSON headers string")

# ============================================================
# TOOLS — same logic as agent.py but wrapped in BaseTool classes
# so CrewAI agents can use them
# ============================================================

class RunShellTool(BaseTool):
    name: str = "run_shell"
    description: str = (
        "Run a shell command on the local machine. "
        "Use for: checking running processes, finding ports, disk usage, "
        "CPU/RAM stats, current date/time, system info, listing processes."
    )
    args_schema: type[BaseModel] = CommandInput

    def _run(self, command: str) -> str:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            return result.stdout or result.stderr or "(no output)"
        except subprocess.TimeoutExpired:
            return "ERROR: Command timed out"
        except Exception as e:
            return f"ERROR: {e}"


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = (
        "Read the full contents of a file from disk. "
        "Use when you need to inspect source code, config files, or any text file."
    )
    args_schema: type[BaseModel] = FileReadInput

    def _run(self, path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception as e:
            return f"ERROR: {e}"


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = (
        "Create or overwrite a file on disk. "
        "Use when you need to save code, reports, plans, or any text output to a file."
    )
    args_schema: type[BaseModel] = FileWriteInput

    def _run(self, path: str, content: str) -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Written to {path} ({len(content)} chars)"
        except Exception as e:
            return f"ERROR: {e}"


class ListDirectoryTool(BaseTool):
    name: str = "list_directory"
    description: str = (
        "List all files and folders in a directory. "
        "Use '.' for the current project directory."
    )
    args_schema: type[BaseModel] = DirectoryInput

    def _run(self, path: str) -> str:
        try:
            entries = sorted(Path(path).iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = [f"[DIR]  {e.name}" if e.is_dir() else f"[FILE] {e.name}" for e in entries]
            return "\n".join(lines) or "(empty)"
        except Exception as e:
            return f"ERROR: {e}"


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web for current information, documentation, news, or latest versions. "
        "Use when you need up-to-date information that may not be in training data."
    )
    args_schema: type[BaseModel] = SearchInput

    def _run(self, query: str) -> str:
        try:
            brave_key = os.getenv("BRAVE_API_KEY")
            if brave_key:
                res = requests.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": brave_key},
                    params={"q": query, "count": 5},
                    timeout=10,
                )
                res.raise_for_status()
                results = res.json().get("web", {}).get("results", [])
                return "\n\n".join(
                    f"{r['title']}\n{r['url']}\n{r.get('description', '')}"
                    for r in results
                ) or "No results."

            # DuckDuckGo fallback — no key needed
            res = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=10,
            )
            d = res.json()
            parts = []
            if d.get("AbstractText"):
                parts.append(d["AbstractText"])
            if d.get("Answer"):
                parts.append(f"Answer: {d['Answer']}")
            for t in d.get("RelatedTopics", [])[:3]:
                if t.get("Text"):
                    parts.append(t["Text"])
            return "\n\n".join(parts) or f'No results for "{query}".'
        except Exception as e:
            return f"ERROR: {e}"


class GitTool(BaseTool):
    name: str = "git_tool"
    description: str = (
        "Run read-only git commands to inspect the repository. "
        "Allowed: log, status, diff, branch, show, ls-files, remote. "
        "Example: 'log --oneline -10' or 'status'."
    )
    args_schema: type[BaseModel] = GitInput

    def _run(self, command: str) -> str:
        allowed = ["log", "status", "diff", "branch", "show", "ls-files", "remote"]
        verb = command.strip().split()[0] if command.strip() else ""
        if verb not in allowed:
            return f"ERROR: Only read-only git commands allowed: {', '.join(allowed)}"
        try:
            result = subprocess.run(
                f"git {command}", shell=True, capture_output=True, text=True, timeout=10
            )
            return result.stdout or result.stderr or "(no output)"
        except Exception as e:
            return f"ERROR: {e}"


# ============================================================
# TOOL INSTANCES — shared across all crews
# ============================================================

run_shell_tool    = RunShellTool()
read_file_tool    = ReadFileTool()
write_file_tool   = WriteFileTool()
list_dir_tool     = ListDirectoryTool()
web_search_tool   = WebSearchTool()
git_tool_instance = GitTool()


# ============================================================
# CREW 1 — CODE CREW
# Purpose: Review code → find bugs/improvements → fix them → write tests
#
# Flow (sequential):
#   Reviewer  → reads code, lists issues
#   Fixer     → fixes the issues found
#   Tester    → writes tests for the fixed code
# ============================================================

def build_code_crew(task_description: str) -> Crew:
    """
    Builds a 3-agent crew for code review, fixing, and test writing.
    Each agent gets only the tools it needs — principle of least privilege.
    """

    # Agent 1: reads code and finds problems
    reviewer = Agent(
        role="Senior Code Reviewer",
        goal="Thoroughly review Python code and identify bugs, bad practices, and improvements",
        backstory=(
            "You are a senior Python engineer with 10 years of experience. "
            "You have a sharp eye for bugs, security issues, and code quality problems. "
            "You write clear, actionable review comments."
        ),
        tools=[read_file_tool, list_dir_tool],
        llm=llm,
        verbose=True,
    )

    # Agent 2: fixes the issues the reviewer found
    fixer = Agent(
        role="Python Developer",
        goal="Fix all issues identified in the code review and write clean, improved code",
        backstory=(
            "You are a skilled Python developer who takes code review feedback seriously. "
            "You write clean, well-commented code that follows best practices. "
            "You always explain what you changed and why."
        ),
        tools=[read_file_tool, write_file_tool],
        llm=llm,
        verbose=True,
    )

    # Agent 3: writes tests for the fixed code
    tester = Agent(
        role="QA Engineer",
        goal="Write comprehensive tests that cover the fixed code",
        backstory=(
            "You are a QA engineer who believes untested code is broken code. "
            "You write pytest tests that cover happy paths, edge cases, and error conditions. "
            "Your tests are readable and well-documented."
        ),
        tools=[read_file_tool, write_file_tool],
        llm=llm,
        verbose=True,
    )

    # Tasks — each builds on the previous one's output
    review_task = Task(
        description=(
            f"Task: {task_description}\n\n"
            "1. List the files in the current directory to understand the project structure.\n"
            "2. Read the relevant Python file(s).\n"
            "3. Identify and list: bugs, security issues, missing error handling, "
            "code quality problems, and improvement opportunities.\n"
            "4. Be specific — include line numbers and exact issues."
        ),
        expected_output=(
            "A numbered list of issues found in the code, each with: "
            "file name, line number (if applicable), issue description, and suggested fix."
        ),
        agent=reviewer,
    )

    fix_task = Task(
        description=(
            "Using the code review findings from the previous task:\n"
            "1. Read the original file(s) again.\n"
            "2. Fix all identified issues.\n"
            "3. Write the improved code to a new file with '_fixed' suffix "
            "(e.g. agent_fixed.py).\n"
            "4. Add a comment at the top of the file listing what was changed."
        ),
        expected_output=(
            "Confirmation that the fixed file was written, with a summary of "
            "all changes made and why."
        ),
        agent=fixer,
        context=[review_task],   # receives reviewer's output as context
    )

    test_task = Task(
        description=(
            "Using the fixed code from the previous task:\n"
            "1. Read the fixed file.\n"
            "2. Write pytest tests covering the main functions and classes.\n"
            "3. Include: happy path tests, edge cases, and error condition tests.\n"
            "4. Save the tests to 'test_<original_filename>.py'."
        ),
        expected_output=(
            "Confirmation that the test file was written, with a summary of "
            "what test cases were included and why."
        ),
        agent=tester,
        context=[fix_task],      # receives fixer's output as context
    )

    return Crew(
        agents=[reviewer, fixer, tester],
        tasks=[review_task, fix_task, test_task],
        process=Process.sequential,   # reviewer → fixer → tester
        verbose=True,
    )


# ============================================================
# CREW 2 — RESEARCH CREW
# Purpose: Search web → analyse findings → write a clean report
#
# Flow (sequential):
#   Researcher → gathers raw information from the web
#   Analyst    → filters, structures, and verifies the data
#   Writer     → produces a clean markdown report saved to disk
# ============================================================

def build_research_crew(topic: str) -> Crew:
    """
    Builds a 3-agent crew for web research and report writing.
    """

    researcher = Agent(
        role="Research Specialist",
        goal="Find comprehensive, accurate, and up-to-date information on any topic",
        backstory=(
            "You are a meticulous researcher who leaves no stone unturned. "
            "You search for information from multiple angles, verify facts, "
            "and always note the source of your findings."
        ),
        tools=[web_search_tool],
        llm=llm,
        verbose=True,
    )

    analyst = Agent(
        role="Data Analyst",
        goal="Analyse raw research data, remove noise, identify key insights, and structure findings",
        backstory=(
            "You are an analytical thinker who turns raw information into clear insights. "
            "You identify patterns, separate facts from opinions, and structure "
            "information in a logical, easy-to-understand way."
        ),
        tools=[],   # no tools needed — works purely with the researcher's output
        llm=llm,
        verbose=True,
    )

    writer = Agent(
        role="Technical Writer",
        goal="Write clear, well-structured markdown reports that are easy to read and actionable",
        backstory=(
            "You are a technical writer who turns complex information into clear documents. "
            "You write in plain English, use headers and bullet points effectively, "
            "and always include a summary and key takeaways section."
        ),
        tools=[write_file_tool],
        llm=llm,
        verbose=True,
    )

    research_task = Task(
        description=(
            f"Research topic: {topic}\n\n"
            "Search the web from multiple angles:\n"
            "1. Search for the main topic overview.\n"
            "2. Search for latest news or updates on the topic.\n"
            "3. Search for practical use cases or examples.\n"
            "Collect all findings with their sources."
        ),
        expected_output=(
            "A comprehensive collection of raw research findings with sources, "
            "covering: overview, latest updates, and practical examples."
        ),
        agent=researcher,
    )

    analysis_task = Task(
        description=(
            "Analyse the research findings from the previous task:\n"
            "1. Remove duplicate or irrelevant information.\n"
            "2. Identify the 5 most important facts or insights.\n"
            "3. Structure the information into clear sections: "
            "Overview, Key Facts, Latest Updates, Practical Use Cases, Conclusion.\n"
            "4. Note any conflicting information or uncertainties."
        ),
        expected_output=(
            "A structured analysis with clearly defined sections, key insights highlighted, "
            "and a brief conclusion."
        ),
        agent=analyst,
        context=[research_task],
    )

    write_task = Task(
        description=(
            f"Write a professional markdown report on: {topic}\n\n"
            "Using the structured analysis from the previous task:\n"
            "1. Write a clean markdown report with proper headers.\n"
            "2. Include sections: Summary, Overview, Key Facts, "
            "Latest Updates, Use Cases, Conclusion.\n"
            "3. Keep it concise — aim for quality over quantity.\n"
            f"4. Save the report to 'report_{topic[:20].replace(' ', '_').lower()}.md'."
        ),
        expected_output=(
            "Confirmation that the report was saved, with the filename and "
            "a brief description of what the report covers."
        ),
        agent=writer,
        context=[analysis_task],
    )

    return Crew(
        agents=[researcher, analyst, writer],
        tasks=[research_task, analysis_task, write_task],
        process=Process.sequential,
        verbose=True,
    )


# ============================================================
# CREW 3 — DEVOPS CREW
# Purpose: Check system health → check git repo → write a combined report
#
# Flow (sequential):
#   System Monitor  → checks CPU, RAM, disk, running processes
#   Git Inspector   → checks commits, status, recent changes
#   Report Writer   → combines both into a health report
# ============================================================

def build_devops_crew(task_description: str) -> Crew:
    """
    Builds a 3-agent crew for system and repository health monitoring.
    """

    system_monitor = Agent(
        role="System Administrator",
        goal="Monitor system health and identify any resource issues or anomalies",
        backstory=(
            "You are an experienced sysadmin who knows exactly which commands "
            "to run to get a complete picture of system health. "
            "You check CPU, memory, disk, and running processes systematically."
        ),
        tools=[run_shell_tool],
        llm=llm,
        verbose=True,
    )

    git_inspector = Agent(
        role="DevOps Engineer",
        goal="Inspect the git repository and summarise recent development activity",
        backstory=(
            "You are a DevOps engineer who keeps a close eye on the codebase. "
            "You check recent commits, current branch status, and any uncommitted changes "
            "to give a clear picture of where the project stands."
        ),
        tools=[git_tool_instance, list_dir_tool],
        llm=llm,
        verbose=True,
    )

    report_writer = Agent(
        role="Technical Report Writer",
        goal="Combine system and git findings into a clear, actionable health report",
        backstory=(
            "You write concise technical reports that give engineers exactly what they need "
            "to know. You highlight issues that need attention and confirm what is healthy. "
            "Your reports are structured, scannable, and saved to disk."
        ),
        tools=[write_file_tool],
        llm=llm,
        verbose=True,
    )

    system_task = Task(
        description=(
            f"Task: {task_description}\n\n"
            "Check system health by running these commands:\n"
            "1. 'free -h'                    — RAM usage\n"
            "2. 'df -h'                      — disk usage\n"
            "3. 'uptime'                     — system uptime and load\n"
            "4. 'ps aux --sort=-%cpu | head -10' — top CPU processes\n"
            "Summarise what is healthy and what needs attention."
        ),
        expected_output=(
            "A system health summary covering: RAM status, disk status, "
            "uptime/load, and top processes. Flag anything above 80% usage."
        ),
        agent=system_monitor,
    )

    git_task = Task(
        description=(
            "Inspect the git repository:\n"
            "1. 'status'              — any uncommitted changes?\n"
            "2. 'log --oneline -10'   — last 10 commits\n"
            "3. 'branch'              — current branch\n"
            "4. List the project directory to see current files.\n"
            "Summarise the current state of the repository."
        ),
        expected_output=(
            "A git status summary covering: current branch, last 10 commits, "
            "any uncommitted/untracked files, and overall repo health."
        ),
        agent=git_inspector,
    )

    report_task = Task(
        description=(
            "Write a combined health report using findings from both previous tasks.\n"
            "Structure the report as:\n"
            "# System Health Report\n"
            "## System Status (RAM, Disk, CPU, Uptime)\n"
            "## Repository Status (Branch, Recent Commits, Uncommitted Changes)\n"
            "## Issues Requiring Attention\n"
            "## Everything Looks Good\n\n"
            "Save the report to 'health_report.md'."
        ),
        expected_output=(
            "Confirmation that health_report.md was saved, with a one-line "
            "summary of the overall system and repo health."
        ),
        agent=report_writer,
        context=[system_task, git_task],   # receives BOTH agents' outputs
    )

    return Crew(
        agents=[system_monitor, git_inspector, report_writer],
        tasks=[system_task, git_task, report_task],
        process=Process.sequential,
        verbose=True,
    )


# ============================================================
# MAIN — CLI entry point
# ============================================================

CREW_HELP = """
╔══════════════════════════════════════════════════════════╗
║              CrewAI Multi-Agent System                   ║
╠══════════════════════════════════════════════════════════╣
║  Crews available:                                        ║
║                                                          ║
║  code     — Review → Fix → Test your Python code        ║
║  research — Search → Analyse → Write a report           ║
║  devops   — System health + Git status report           ║
╠══════════════════════════════════════════════════════════╣
║  Usage:                                                  ║
║    python crew.py code     "review agent.py"            ║
║    python crew.py research "Python 3.13 new features"   ║
║    python crew.py devops   "full health check"          ║
║    python crew.py          (interactive menu)           ║
╚══════════════════════════════════════════════════════════╝
"""

def run_crew(crew_type: str, task: str) -> None:
    print(f"\n🚀 Starting {crew_type.upper()} crew...")
    print(f"📋 Task: {task}\n")

    if crew_type == "code":
        crew = build_code_crew(task)
    elif crew_type == "research":
        crew = build_research_crew(task)
    elif crew_type == "devops":
        crew = build_devops_crew(task)
    else:
        print(f"❌ Unknown crew type: '{crew_type}'. Choose: code, research, devops")
        return

    result = crew.kickoff()
    print("\n" + "═" * 60)
    print("✅ CREW FINISHED")
    print("═" * 60)
    print(result)


def interactive_menu() -> None:
    print(CREW_HELP)
    while True:
        try:
            crew_type = input("Choose crew (code / research / devops) or 'exit': ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if crew_type in ("exit", "quit"):
            print("👋 Goodbye!")
            break

        if crew_type not in ("code", "research", "devops"):
            print("❌ Invalid choice. Enter: code, research, or devops")
            continue

        try:
            task = input("Describe the task: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if task:
            run_crew(crew_type, task)


def main():
    args = sys.argv[1:]

    if not args:
        interactive_menu()
        return

    if args[0] in ("--help", "-h"):
        print(CREW_HELP)
        return

    if len(args) >= 2:
        crew_type = args[0].lower()
        task = " ".join(args[1:])
        run_crew(crew_type, task)
    else:
        print("❌ Usage: python crew.py <code|research|devops> \"your task\"")
        print(CREW_HELP)


if __name__ == "__main__":
    main()
