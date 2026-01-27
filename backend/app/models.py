"""
Pydantic Models for NOVA Backend

Request/Response models for API endpoints.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ==================== Chat Models ====================

class ChatMessage(BaseModel):
    """Incoming chat message from user"""
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: str = Field(default="default")


class ChatResponse(BaseModel):
    """Response to a chat message"""
    message: str
    intent: str = "chat"
    success: bool = True
    data: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SessionInfo(BaseModel):
    """Information about a chat session"""
    session_id: str
    title: str
    message_count: int


# ==================== Configuration Models ====================

class LLMConfig(BaseModel):
    """LLM configuration"""
    provider: str = "nutanix-ai"
    hackathon_api_key: str = ""
    base_url: str = "https://hkn12.ai.nutanix.com/enterpriseai/v1/"
    model: str = "hack-reason"


class PrismConfig(BaseModel):
    """Prism Central configuration"""
    ip: str = ""
    port: int = 9440
    username: str = ""
    password: str = ""


class S3Config(BaseModel):
    """S3 configuration"""
    endpoint: str = ""
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"


class SQLAgentConfig(BaseModel):
    """SQL Agent configuration"""
    url: str = ""


class BackgroundConfig(BaseModel):
    """Background task configuration"""
    sql_refresh_interval_seconds: int = 300
    enable_background_refresh: bool = True


class FullConfig(BaseModel):
    """Complete configuration"""
    llm: LLMConfig = LLMConfig()
    prism_central: PrismConfig = PrismConfig()
    s3: S3Config = S3Config()
    sql_agent: SQLAgentConfig = SQLAgentConfig()
    background: BackgroundConfig = BackgroundConfig()


# ==================== Context Models ====================

class ContextFile(BaseModel):
    """Context file content"""
    name: str
    content: str


class ContextInfo(BaseModel):
    """Information about loaded contexts"""
    contexts: List[str]
    count: int
    sql_summary_available: bool
    last_sql_refresh: Optional[str] = None


# ==================== Tool Models ====================

class ToolInfo(BaseModel):
    """Basic tool information"""
    name: str
    description: str


class ToolListResponse(BaseModel):
    """Response for tool listing"""
    tools: List[ToolInfo]
    count: int
    categories: Dict[str, Any]


# ==================== Status Models ====================

class StatusResponse(BaseModel):
    """API status response"""
    status: str
    version: str
    llm_configured: bool
    llm_provider: str
    s3_configured: bool
    prism_central_configured: bool
    sql_agent_url: str
    context_files_loaded: int
    tools_loaded: int
    sql_summary_last_refresh: Optional[str] = None


# ==================== Connection Test Models ====================

class ConnectionTestResponse(BaseModel):
    """Response for connection tests"""
    success: bool
    message: str
