"""
llm_config.py — Unified LLM configuration for all agents

Supports:
  - Ollama (local)
  - Cloudflare Workers AI
  - OpenAI
  - Anthropic Claude
  - Google Gemini
  - Groq

Usage:
  from llm_config import get_llm
  
  llm = get_llm("ollama")           # local Ollama
  llm = get_llm("cloudflare")       # Cloudflare Workers AI
  llm = get_llm("openai")           # OpenAI GPT-4
  llm = get_llm()                   # uses LLM_PROVIDER from .env
"""

import os
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

# Type for supported providers
LLMProvider = Literal["ollama", "cloudflare", "openai", "anthropic", "gemini", "groq"]

# ============================================================
# PROVIDER CONFIGURATIONS
# ============================================================

PROVIDER_CONFIGS = {
    "ollama": {
        "model": os.getenv("OLLAMA_MODEL", "qwen2:7b"),
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "temperature": 0,
        "description": "Local Ollama (free, private, no API key needed)",
    },
    "cloudflare": {
        # Model name — for AI Gateway prefix with "workers-ai/", for direct API use "@cf/..." format
        "model": os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
        "account_id": os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
        # Direct Workers AI token (from dash.cloudflare.com/profile/api-tokens)
        "api_token": os.getenv("CLOUDFLARE_API_TOKEN", ""),
        # AI Gateway token (CF_AIG_TOKEN from your gateway setup) — optional
        "aig_token": os.getenv("CLOUDFLARE_AIG_TOKEN", ""),
        # AI Gateway name (the slug in your gateway URL, e.g. "default")
        "gateway_name": os.getenv("CLOUDFLARE_GATEWAY_NAME", "default"),
        "temperature": 0,
        "description": "Cloudflare Workers AI (fast, cheap, requires API token)",
    },
    "openai": {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "temperature": 0,
        "description": "OpenAI GPT (powerful, requires API key)",
    },
    "anthropic": {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "temperature": 0,
        "description": "Anthropic Claude (excellent reasoning, requires API key)",
    },
    "gemini": {
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp"),
        "api_key": os.getenv("GOOGLE_API_KEY", ""),
        "temperature": 0,
        "description": "Google Gemini (fast, large context, requires API key)",
    },
    "groq": {
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "api_key": os.getenv("GROQ_API_KEY", ""),
        "temperature": 0,
        "description": "Groq (extremely fast inference, requires API key)",
    },
}


# ============================================================
# GET LLM INSTANCE
# ============================================================

def get_llm(provider: str = None, **override_params):
    """
    Get an LLM instance for the specified provider.
    
    Args:
        provider: One of: ollama, cloudflare, openai, anthropic, gemini, groq
                  If None, reads from LLM_PROVIDER env var (defaults to ollama)
        **override_params: Override any config parameter (e.g., temperature=0.7)
    
    Returns:
        LLM instance compatible with LangChain
    
    Examples:
        llm = get_llm("ollama")
        llm = get_llm("openai", temperature=0.7)
        llm = get_llm()  # uses LLM_PROVIDER from .env
    """
    # Default to env var or ollama
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    
    provider = provider.lower()
    
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(
            f"Unknown provider: {provider}. "
            f"Supported: {', '.join(PROVIDER_CONFIGS.keys())}"
        )
    
    config = PROVIDER_CONFIGS[provider].copy()
    config.update(override_params)
    
    # Import and instantiate the appropriate LLM
    if provider == "ollama":
        return _get_ollama_llm(config)
    elif provider == "cloudflare":
        return _get_cloudflare_llm(config)
    elif provider == "openai":
        return _get_openai_llm(config)
    elif provider == "anthropic":
        return _get_anthropic_llm(config)
    elif provider == "gemini":
        return _get_gemini_llm(config)
    elif provider == "groq":
        return _get_groq_llm(config)


# ============================================================
# PROVIDER-SPECIFIC IMPLEMENTATIONS
# ============================================================

def _get_ollama_llm(config):
    """Get Ollama LLM instance."""
    from langchain_ollama import ChatOllama
    
    return ChatOllama(
        model=config["model"],
        base_url=config["base_url"],
        temperature=config["temperature"],
    )


def _get_cloudflare_llm(config):
    """
    Get Cloudflare Workers AI LLM instance.

    Supports two modes:
      1. AI Gateway  — uses CLOUDFLARE_AIG_TOKEN + gateway URL (your curl setup)
      2. Direct API  — uses CLOUDFLARE_API_TOKEN + workers AI URL

    AI Gateway URL format:
      https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_name}/workers-ai/v1

    Direct API URL format:
      https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1
    """
    from langchain_openai import ChatOpenAI

    account_id = config.get("account_id", "")
    aig_token  = config.get("aig_token", "")
    api_token  = config.get("api_token", "")

    if not account_id:
        raise ValueError(
            "CLOUDFLARE_ACCOUNT_ID not set in .env.\n"
            "  Find it in your gateway URL: gateway.ai.cloudflare.com/v1/{ACCOUNT_ID}/..."
        )

    # ── Mode 1: AI Gateway (preferred if AIG token is set) ──────────────────
    if aig_token:
        gateway_name = config.get("gateway_name", "default")
        base_url = (
            f"https://gateway.ai.cloudflare.com/v1/{account_id}"
            f"/{gateway_name}/workers-ai/v1"
        )
        # Model must be prefixed with "workers-ai/" for the gateway compat endpoint
        model = config["model"]
        if not model.startswith("workers-ai/") and not model.startswith("@cf/"):
            model = f"workers-ai/{model}"
        # Strip "workers-ai/" prefix — the base_url already routes to workers-ai
        if model.startswith("workers-ai/"):
            model = model[len("workers-ai/"):]

        return ChatOpenAI(
            model=model,
            api_key=aig_token,
            base_url=base_url,
            temperature=config["temperature"],
            default_headers={"cf-aig-authorization": f"Bearer {aig_token}"},
        )

    # ── Mode 2: Direct Workers AI API ───────────────────────────────────────
    if not api_token:
        raise ValueError(
            "No Cloudflare token found. Set one of:\n"
            "  CLOUDFLARE_AIG_TOKEN  — for AI Gateway (your curl setup)\n"
            "  CLOUDFLARE_API_TOKEN  — for direct Workers AI API\n"
            "Get tokens at: https://dash.cloudflare.com/profile/api-tokens"
        )

    return ChatOpenAI(
        model=config["model"],
        api_key=api_token,
        base_url=f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        temperature=config["temperature"],
    )


def _get_openai_llm(config):
    """Get OpenAI LLM instance."""
    from langchain_openai import ChatOpenAI
    
    if not config["api_key"]:
        raise ValueError(
            "OPENAI_API_KEY not set in .env. "
            "Get one at: https://platform.openai.com/api-keys"
        )
    
    return ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        temperature=config["temperature"],
    )


def _get_anthropic_llm(config):
    """Get Anthropic Claude LLM instance."""
    from langchain_anthropic import ChatAnthropic
    
    if not config["api_key"]:
        raise ValueError(
            "ANTHROPIC_API_KEY not set in .env. "
            "Get one at: https://console.anthropic.com/settings/keys"
        )
    
    return ChatAnthropic(
        model=config["model"],
        api_key=config["api_key"],
        temperature=config["temperature"],
    )


def _get_gemini_llm(config):
    """Get Google Gemini LLM instance."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    
    if not config["api_key"]:
        raise ValueError(
            "GOOGLE_API_KEY not set in .env. "
            "Get one at: https://makersuite.google.com/app/apikey"
        )
    
    return ChatGoogleGenerativeAI(
        model=config["model"],
        google_api_key=config["api_key"],
        temperature=config["temperature"],
    )


def _get_groq_llm(config):
    """Get Groq LLM instance."""
    from langchain_groq import ChatGroq
    
    if not config["api_key"]:
        raise ValueError(
            "GROQ_API_KEY not set in .env. "
            "Get one at: https://console.groq.com/keys"
        )
    
    return ChatGroq(
        model=config["model"],
        api_key=config["api_key"],
        temperature=config["temperature"],
    )


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def list_providers():
    """List all available providers with their descriptions."""
    print("\n📋 Available LLM Providers:\n")
    for name, config in PROVIDER_CONFIGS.items():
        print(f"  {name:12} — {config['description']}")
        print(f"               Model: {config.get('model', 'N/A')}")
        
        # Check if configured
        if name == "ollama":
            status = "✅ Ready"
        elif name == "cloudflare":
            status = "✅ Configured" if (config.get("api_token") or config.get("aig_token")) else "❌ Not configured"
        else:
            status = "✅ Configured" if config.get("api_key") else "❌ Not configured"
        
        print(f"               Status: {status}\n")


def get_current_provider():
    """Get the currently configured provider from env."""
    return os.getenv("LLM_PROVIDER", "ollama").lower()


def validate_provider(provider: str) -> tuple[bool, str]:
    """
    Validate if a provider is properly configured.
    
    Returns:
        (is_valid, error_message)
    """
    if provider not in PROVIDER_CONFIGS:
        return False, f"Unknown provider: {provider}"
    
    config = PROVIDER_CONFIGS[provider]
    
    # Check required credentials
    if provider == "ollama":
        return True, ""
    elif provider == "cloudflare":
        if not config.get("aig_token") and not config.get("api_token"):
            return False, "Set either CLOUDFLARE_AIG_TOKEN (AI Gateway) or CLOUDFLARE_API_TOKEN (direct API)"
        if not config.get("account_id"):
            return False, "CLOUDFLARE_ACCOUNT_ID not set in .env"
    else:
        if not config.get("api_key"):
            key_name = f"{provider.upper()}_API_KEY"
            return False, f"{key_name} not set in .env"
    
    return True, ""


# ============================================================
# CLI FOR TESTING
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            list_providers()
        elif sys.argv[1] == "test":
            provider = sys.argv[2] if len(sys.argv) > 2 else get_current_provider()
            
            print(f"\n🧪 Testing provider: {provider}\n")
            
            # Validate
            is_valid, error = validate_provider(provider)
            if not is_valid:
                print(f"❌ {error}")
                sys.exit(1)
            
            # Try to instantiate
            try:
                llm = get_llm(provider)
                print(f"✅ LLM instance created: {type(llm).__name__}")
                print(f"   Model: {PROVIDER_CONFIGS[provider]['model']}")
                
                # Try a simple call
                print(f"\n🤖 Testing with a simple query...")
                response = llm.invoke("Say 'Hello' and nothing else")
                print(f"   Response: {response.content}")
                print(f"\n✅ Provider '{provider}' is working!")
                
            except Exception as e:
                print(f"❌ Error: {e}")
                sys.exit(1)
        else:
            print("Usage:")
            print("  python llm_config.py list              # list all providers")
            print("  python llm_config.py test [provider]   # test a provider")
    else:
        list_providers()
        print(f"Current provider: {get_current_provider()}")
