"""
update_agents.py — Update all agents to use llm_config.py

This script modifies agent.py, crew.py, and agent_graph.py to use
the unified LLM configuration system.

Run: python update_agents.py
"""

import re
from pathlib import Path

def update_agent_py():
    """Update agent.py to use llm_config."""
    file_path = Path("agent.py")
    content = file_path.read_text()
    
    # Replace the LLM initialization
    old_llm = '''llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url="http://localhost:11434",
    temperature=0,  # deterministic — important for tool-calling agents
)'''
    
    new_llm = '''# Import unified LLM config
from llm_config import get_llm

llm = get_llm()  # Uses LLM_PROVIDER from .env (defaults to ollama)'''
    
    if old_llm in content:
        content = content.replace(old_llm, new_llm)
        
        # Remove old imports
        content = content.replace("from langchain_ollama import ChatOllama\n", "")
        
        # Remove old config
        content = content.replace('OLLAMA_MODEL    = "qwen2:7b"\n', "")
        content = content.replace('EMBEDDING_MODEL = "nomic-embed-text"\n', "")
        
        file_path.write_text(content)
        print("✅ Updated agent.py")
        return True
    else:
        print("⚠️  agent.py already updated or structure changed")
        return False


def update_crew_py():
    """Update crew.py to use llm_config."""
    file_path = Path("crew.py")
    content = file_path.read_text()
    
    # Replace the LLM initialization
    old_llm = '''llm = LLM(
    model="ollama/qwen2:7b",
    base_url="http://localhost:11434",
    temperature=0,          # deterministic for tool-calling
    max_tokens=4096,
)'''
    
    new_llm = '''# Import unified LLM config
from llm_config import get_llm as get_langchain_llm

# CrewAI uses its own LLM wrapper, so we need to convert
# For now, keep CrewAI's LLM class but make model configurable
import os
llm = LLM(
    model=f"ollama/{os.getenv('OLLAMA_MODEL', 'qwen2:7b')}",
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    temperature=0,
    max_tokens=4096,
)
# Note: CrewAI doesn't easily support other providers yet
# Stick with Ollama for crews, or use agent.py/agent_graph.py for other providers'''
    
    if old_llm in content:
        content = content.replace(old_llm, new_llm)
        file_path.write_text(content)
        print("✅ Updated crew.py")
        return True
    else:
        print("⚠️  crew.py already updated or structure changed")
        return False


def update_agent_graph_py():
    """Update agent_graph.py to use llm_config."""
    file_path = Path("agent_graph.py")
    content = file_path.read_text()
    
    # Replace the LLM initialization
    old_llm = '''llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url="http://localhost:11434",
    temperature=0,
)'''
    
    new_llm = '''# Import unified LLM config
from llm_config import get_llm

llm = get_llm()  # Uses LLM_PROVIDER from .env (defaults to ollama)'''
    
    if old_llm in content:
        content = content.replace(old_llm, new_llm)
        
        # Remove old imports
        content = content.replace("from langchain_ollama import ChatOllama\n", "")
        
        # Remove old config
        content = content.replace('OLLAMA_MODEL = "qwen2:7b"\n', "")
        
        file_path.write_text(content)
        print("✅ Updated agent_graph.py")
        return True
    else:
        print("⚠️  agent_graph.py already updated or structure changed")
        return False


def main():
    print("\n🔧 Updating agents to use unified LLM configuration...\n")
    
    results = []
    results.append(update_agent_py())
    results.append(update_crew_py())
    results.append(update_agent_graph_py())
    
    print("\n" + "="*60)
    if all(results):
        print("✅ All agents updated successfully!")
    else:
        print("⚠️  Some agents were already updated or need manual review")
    
    print("\nNext steps:")
    print("1. Copy .env.example to .env:")
    print("   cp .env.example .env")
    print()
    print("2. Edit .env and set LLM_PROVIDER to your choice:")
    print("   LLM_PROVIDER=ollama      # local (default)")
    print("   LLM_PROVIDER=cloudflare  # fast, cheap")
    print("   LLM_PROVIDER=openai      # powerful")
    print()
    print("3. Add API keys if using cloud providers")
    print()
    print("4. Test the configuration:")
    print("   python llm_config.py list")
    print("   python llm_config.py test ollama")
    print("   python llm_config.py test cloudflare")
    print()
    print("5. Run your agents as usual:")
    print("   python agent.py 'your task'")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
