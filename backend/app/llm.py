"""
LLM Client Management for NOVA Backend

Handles OpenAI-compatible LLM client creation and management.
"""
from typing import Optional
from openai import OpenAI

from .config import get_llm_api_key, get_llm_base_url


def get_llm_client() -> Optional[OpenAI]:
    """
    Get LLM client based on current configuration.
    
    Returns:
        OpenAI client instance if configured, None otherwise
    """
    api_key = get_llm_api_key()
    
    if api_key:
        return OpenAI(
            base_url=get_llm_base_url(),
            api_key=api_key
        )
    return None


def is_llm_configured() -> bool:
    """Check if LLM is configured"""
    return bool(get_llm_api_key())
