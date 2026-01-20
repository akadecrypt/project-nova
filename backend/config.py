"""
NOVA Configuration Management
Stores configuration in ChromaDB instead of JSON files
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, Dict, Any


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file"""
    
    # Server settings
    host: str = Field(default="0.0.0.0", env="NOVA_HOST")
    port: int = Field(default=9360, env="NOVA_PORT")
    debug: bool = Field(default=True, env="NOVA_DEBUG")
    
    # Prism settings (can be overridden by DB config)
    prism_ip: Optional[str] = Field(default=None, env="PRISM_IP")
    prism_port: int = Field(default=9440, env="PRISM_PORT")
    prism_username: Optional[str] = Field(default=None, env="PRISM_USERNAME")
    prism_password: Optional[str] = Field(default=None, env="PRISM_PASSWORD")
    
    # Objects settings
    objects_endpoint: Optional[str] = Field(default=None, env="OBJECTS_ENDPOINT")
    objects_access_key: Optional[str] = Field(default=None, env="OBJECTS_ACCESS_KEY")
    objects_secret_key: Optional[str] = Field(default=None, env="OBJECTS_SECRET_KEY")
    
    # Vector DB settings
    chroma_persist_dir: str = Field(default="./data/chroma", env="CHROMA_PERSIST_DIR")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="EMBEDDING_MODEL")
    
    # LLM settings (optional - for enhanced responses)
    # Priority: Ollama (free) > OpenAI > Anthropic > Groq
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    groq_api_key: Optional[str] = Field(default=None, env="GROQ_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", env="LLM_MODEL")
    
    # Ollama settings (FREE, LOCAL - recommended!)
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3.1", env="OLLAMA_MODEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Lazy-loaded vector DB for config storage
_config_db = None


def _get_config_db():
    """Get vector DB instance for config storage (lazy load to avoid circular imports)"""
    global _config_db
    if _config_db is None:
        from services.vector_db import get_vector_db
        _config_db = get_vector_db()
    return _config_db


def load_config_from_db() -> dict:
    """Load configuration from ChromaDB"""
    try:
        db = _get_config_db()
        return db.get_all_config()
    except Exception as e:
        print(f"Could not load config from DB: {e}")
        return {}


def save_config_to_db(config: dict) -> bool:
    """Save configuration to ChromaDB"""
    try:
        db = _get_config_db()
        for key, value in config.items():
            db.save_config(key, value)
        return True
    except Exception as e:
        print(f"Could not save config to DB: {e}")
        return False


def load_prism_config() -> dict:
    """Load Prism configuration from DB"""
    try:
        db = _get_config_db()
        return db.get_prism_config()
    except Exception as e:
        print(f"Could not load Prism config: {e}")
        return {}


def save_prism_config(prism_ip: str, prism_port: int, prism_username: str, prism_password: str) -> bool:
    """Save Prism configuration to DB"""
    try:
        db = _get_config_db()
        return db.save_prism_config(prism_ip, prism_port, prism_username, prism_password)
    except Exception as e:
        print(f"Could not save Prism config: {e}")
        return False


def load_llm_config() -> dict:
    """Load LLM configuration from DB"""
    try:
        db = _get_config_db()
        return db.get_llm_config()
    except Exception as e:
        print(f"Could not load LLM config: {e}")
        return {
            "provider": "ollama",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3.1"
        }


def save_llm_config(provider: str, api_key: str = None, 
                    ollama_url: str = "http://localhost:11434", 
                    ollama_model: str = "llama3.1") -> bool:
    """Save LLM configuration to DB"""
    try:
        db = _get_config_db()
        return db.save_llm_config(provider, api_key, ollama_url, ollama_model)
    except Exception as e:
        print(f"Could not save LLM config: {e}")
        return False


# Legacy compatibility functions
def load_config_file() -> dict:
    """Legacy: Load config (now from DB)"""
    return load_prism_config()


def save_config_file(config: dict) -> None:
    """Legacy: Save config (now to DB)"""
    if "prism_ip" in config:
        save_prism_config(
            config.get("prism_ip", ""),
            config.get("prism_port", 9440),
            config.get("prism_username", "admin"),
            config.get("prism_password", "")
        )


# Keep CONFIG_FILE for backward compatibility but don't use it
CONFIG_FILE = None


def get_settings() -> Settings:
    """Get settings from environment variables"""
    return Settings()


# Global settings instance
settings = get_settings()
