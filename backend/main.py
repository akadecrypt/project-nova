"""
NOVA Backend - FastAPI Application
AI Agent for Nutanix Objects Operations (linked to nova_persona)
"""
import os
import json
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager

import boto3
import requests
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()

# ==================== Configuration ====================

# OpenAI client
openai_client = None
if os.getenv("OPENAI_API_KEY"):
    openai_client = OpenAI()

# SQL Agent URL
SQL_AGENT_URL = os.getenv("SQL_AGENT_URL", "http://10.118.25.134:9001/execute")

# Session storage for conversations
chat_sessions: Dict[str, List[dict]] = {}

# ==================== System Prompt ====================

SYSTEM_PROMPT = """You are NOVA, Nutanix Object Store Virtual Assistant.
You help with bucket configs, replication, tiering, and logs.
If the user asks to create a bucket without providing a name, generate a random lowercase bucket name and create it.
Use tools whenever object store operations are required.

ADDITIONAL ANALYTICS CONTEXT:
Object store metadata is stored in SQLite using two tables:
1) bucket(bucket_id, object_store_uuid, bucket_name, bucket_owner, versioning, worm, replication_status, tiering_status, created_at)
2) bucket_stats(bucket_id, object_store_uuid, object_count, size_gb, timestamp)

Rules:
- bucket_id + object_store_uuid uniquely identify a bucket
- Use bucket table when bucket_name or configuration is referenced
- Use bucket_stats for time-series analysis
- Always use latest timestamp per day for daily analysis
- Execute SQL ONLY via the sql tool
- After SQL execution, summarize trends, anomalies, and suggest causes
"""

# ==================== Tool Definitions ====================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_bucket",
            "description": "Create a bucket in Nutanix Object Store",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket to create (optional, will generate if not provided)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_buckets",
            "description": "List all buckets in Nutanix Object Store",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": "List objects in a bucket",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "put_object",
            "description": "Upload an object to a bucket",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {"type": "string", "description": "Bucket name"},
                    "key": {"type": "string", "description": "Object key (filename)"},
                    "content": {"type": "string", "description": "Object content as text"}
                },
                "required": ["bucket_name", "key", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute SQL query on object store metadata database for analytics. Use this for questions about bucket statistics, trends, storage usage over time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL query to execute"
                    }
                },
                "required": ["sql"]
            }
        }
    }
]

# ==================== S3 Client ====================

def get_s3_client():
    """Get boto3 S3 client for Nutanix Objects"""
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("NUTANIX_S3_ENDPOINT"),
        aws_access_key_id=os.getenv("NUTANIX_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("NUTANIX_SECRET_KEY"),
        region_name="us-east-1",
        verify=False
    )

# ==================== Tool Implementations ====================

def create_bucket(bucket_name: str = None) -> dict:
    """Create a bucket in Nutanix Object Store"""
    try:
        s3 = get_s3_client()
        if not bucket_name:
            bucket_name = f"nova-bucket-{uuid.uuid4().hex[:6]}"
        s3.create_bucket(Bucket=bucket_name)
        return {"status": "success", "bucket_name": bucket_name, "message": f"Bucket '{bucket_name}' created successfully"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def list_buckets() -> dict:
    """List all buckets"""
    try:
        s3 = get_s3_client()
        response = s3.list_buckets()
        buckets = [b["Name"] for b in response.get("Buckets", [])]
        return {"status": "success", "count": len(buckets), "buckets": buckets}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def list_objects(bucket_name: str) -> dict:
    """List objects in a bucket"""
    try:
        s3 = get_s3_client()
        response = s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" not in response:
            return {"status": "success", "bucket": bucket_name, "objects": [], "count": 0}
        objects = [{"key": obj["Key"], "size": obj["Size"]} for obj in response["Contents"]]
        return {"status": "success", "bucket": bucket_name, "objects": objects, "count": len(objects)}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def put_object(bucket_name: str, key: str, content: str) -> dict:
    """Upload an object to a bucket"""
    try:
        s3 = get_s3_client()
        s3.put_object(Bucket=bucket_name, Key=key, Body=content.encode("utf-8"))
        return {"status": "success", "bucket": bucket_name, "key": key, "message": f"Object '{key}' uploaded to '{bucket_name}'"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def execute_sql(sql: str) -> dict:
    """Execute SQL on object store metadata database"""
    try:
        response = requests.post(SQL_AGENT_URL, json={"sql": sql}, timeout=10)
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"status": "error", "error": "Cannot connect to SQL agent. Make sure it's running."}
    except Exception as e:
        return {"status": "error", "error": str(e)}

# Tool dispatcher
def execute_tool(tool_name: str, tool_args: dict) -> dict:
    """Execute a tool by name"""
    tools_map = {
        "create_bucket": create_bucket,
        "list_buckets": list_buckets,
        "list_objects": list_objects,
        "put_object": put_object,
        "execute_sql": execute_sql
    }
    
    if tool_name in tools_map:
        return tools_map[tool_name](**tool_args)
    return {"error": f"Unknown tool: {tool_name}"}

# ==================== Pydantic Models ====================

class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    session_id: str = Field(default="default")

class ChatResponse(BaseModel):
    message: str
    intent: str = "chat"
    success: bool = True
    data: Optional[dict] = None
    suggestions: Optional[List[str]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

class LLMConfigRequest(BaseModel):
    provider: str = "openai"
    api_key: Optional[str] = None
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

# ==================== FastAPI App ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    print("🚀 Starting NOVA Backend...")
    print(f"📡 SQL Agent URL: {SQL_AGENT_URL}")
    print(f"🪣 S3 Endpoint: {os.getenv('NUTANIX_S3_ENDPOINT', 'Not configured')}")
    print(f"🤖 OpenAI: {'Configured' if openai_client else 'Not configured'}")
    print("✅ NOVA Backend ready!")
    yield
    print("👋 Shutting down NOVA Backend...")

app = FastAPI(
    title="NOVA API",
    description="Nutanix Objects Virtual Assistant - AI Agent Backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== API Endpoints ====================

@app.get("/api/status")
async def get_status():
    """Get API status"""
    s3_configured = bool(os.getenv("NUTANIX_S3_ENDPOINT"))
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    
    return {
        "status": "online",
        "version": "1.0.0",
        "openai_configured": openai_configured,
        "s3_configured": s3_configured,
        "sql_agent_url": SQL_AGENT_URL,
        "llm_provider": "openai" if openai_configured else "none"
    }

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatMessage):
    """Send a message to NOVA"""
    
    if not openai_client:
        return ChatResponse(
            message="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.",
            intent="error",
            success=False,
            suggestions=["Configure OpenAI API key in .env file"]
        )
    
    session_id = request.session_id
    user_message = request.message
    
    # Initialize session if needed
    if session_id not in chat_sessions:
        chat_sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add user message
    chat_sessions[session_id].append({"role": "user", "content": user_message})
    
    try:
        # Call OpenAI with tools
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=chat_sessions[session_id],
            tools=TOOLS,
            tool_choice="auto"
        )
        
        assistant_msg = response.choices[0].message
        
        # Handle tool calls
        if assistant_msg.tool_calls:
            chat_sessions[session_id].append(assistant_msg)
            
            tool_results = []
            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")
                
                # Execute the tool
                result = execute_tool(tool_name, tool_args)
                tool_results.append({"tool": tool_name, "result": result})
                
                # Add tool result to messages
                chat_sessions[session_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
            
            # Get final response after tool execution
            final_response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=chat_sessions[session_id]
            )
            
            final_msg = final_response.choices[0].message
            chat_sessions[session_id].append(final_msg)
            
            # Determine intent from tool calls
            intent = assistant_msg.tool_calls[0].function.name if assistant_msg.tool_calls else "chat"
            
            return ChatResponse(
                message=final_msg.content or "Operation completed.",
                intent=intent,
                success=True,
                data={"tool_results": tool_results},
                suggestions=get_suggestions(intent)
            )
        else:
            # No tool calls - regular chat response
            chat_sessions[session_id].append(assistant_msg)
            
            return ChatResponse(
                message=assistant_msg.content or "I'm not sure how to help with that.",
                intent="chat",
                success=True,
                suggestions=["List buckets", "Show storage stats", "Help"]
            )
            
    except Exception as e:
        return ChatResponse(
            message=f"Error: {str(e)}",
            intent="error",
            success=False
        )

def get_suggestions(intent: str) -> List[str]:
    """Get contextual suggestions based on intent"""
    suggestions_map = {
        "create_bucket": ["List buckets", "Upload a file", "Show bucket stats"],
        "list_buckets": ["Create a bucket", "Show storage usage", "List objects in a bucket"],
        "list_objects": ["Upload a file", "Show bucket stats", "Create another bucket"],
        "put_object": ["List objects", "Create another bucket", "Show storage stats"],
        "execute_sql": ["Show bucket trends", "List buckets by size", "Show daily growth"],
    }
    return suggestions_map.get(intent, ["List buckets", "Show storage stats", "Help"])

# ==================== Chat History Endpoints ====================

@app.get("/api/chat/sessions")
async def list_sessions():
    """List all chat sessions"""
    sessions = []
    for session_id, messages in chat_sessions.items():
        # Find first user message as title
        first_user_msg = next((m["content"][:50] for m in messages if m["role"] == "user"), "New conversation")
        sessions.append({
            "session_id": session_id,
            "title": first_user_msg,
            "message_count": len([m for m in messages if m["role"] in ["user", "assistant"]])
        })
    return {"sessions": sessions}

@app.get("/api/chat/sessions/{session_id}")
async def get_session(session_id: str):
    """Get chat history for a session"""
    if session_id not in chat_sessions:
        return {"session_id": session_id, "messages": []}
    
    # Filter to user/assistant messages only
    messages = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in chat_sessions[session_id]
        if m["role"] in ["user", "assistant"] and m.get("content")
    ]
    return {"session_id": session_id, "messages": messages}

@app.delete("/api/chat/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session"""
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    return {"success": True, "session_id": session_id}

@app.post("/api/chat/sessions/new")
async def new_session():
    """Create a new chat session"""
    session_id = f"session-{int(datetime.now().timestamp() * 1000)}"
    chat_sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return {"session_id": session_id}

# ==================== LLM Config Endpoints ====================

@app.get("/api/config/llm")
async def get_llm_config():
    """Get LLM configuration"""
    return {
        "provider": "openai" if os.getenv("OPENAI_API_KEY") else "none",
        "is_configured": bool(os.getenv("OPENAI_API_KEY")),
        "status": "configured" if os.getenv("OPENAI_API_KEY") else "not configured",
        "ollama_url": None,
        "ollama_model": None
    }

@app.post("/api/config/llm")
async def set_llm_config(request: LLMConfigRequest):
    """Set LLM configuration (currently only supports OpenAI via env)"""
    return {
        "provider": "openai",
        "is_configured": bool(os.getenv("OPENAI_API_KEY")),
        "status": "OpenAI is configured via OPENAI_API_KEY environment variable",
        "message": "To change API key, update OPENAI_API_KEY in .env file and restart server"
    }

@app.get("/api/config/llm/test-ollama")
async def test_ollama(url: str = "http://localhost:11434"):
    """Test Ollama connection (for future use)"""
    return {
        "success": False,
        "status": "not_supported",
        "error": "This backend uses OpenAI. Ollama support can be added later.",
        "models": []
    }

# ==================== S3 Config Endpoints ====================

@app.get("/api/config/s3")
async def get_s3_config():
    """Get S3 configuration status"""
    return {
        "endpoint": os.getenv("NUTANIX_S3_ENDPOINT", "Not configured"),
        "is_configured": bool(os.getenv("NUTANIX_S3_ENDPOINT")),
        "access_key_set": bool(os.getenv("NUTANIX_ACCESS_KEY"))
    }

# ==================== Objects/Storage Endpoints ====================

@app.get("/api/objects/stats")
async def get_object_stats():
    """Get object storage statistics"""
    try:
        buckets_result = list_buckets()
        if buckets_result.get("status") == "success":
            bucket_count = buckets_result.get("count", 0)
            return {
                "total_buckets": bucket_count,
                "total_objects": 0,  # Would need to iterate through all buckets
                "total_size_gb": 0,
                "buckets": buckets_result.get("buckets", [])
            }
        return {"total_buckets": 0, "total_objects": 0, "total_size_gb": 0, "buckets": []}
    except Exception as e:
        return {"total_buckets": 0, "total_objects": 0, "total_size_gb": 0, "error": str(e)}

@app.get("/api/objects/stores/{oss_uuid}/buckets")
async def get_buckets_by_store(oss_uuid: str):
    """Get buckets for a specific object store"""
    try:
        buckets_result = list_buckets()
        if buckets_result.get("status") == "success":
            return {
                "object_store_uuid": oss_uuid,
                "buckets": [
                    {"name": b, "object_count": 0, "size_gb": 0}
                    for b in buckets_result.get("buckets", [])
                ]
            }
        return {"object_store_uuid": oss_uuid, "buckets": [], "error": buckets_result.get("error")}
    except Exception as e:
        return {"object_store_uuid": oss_uuid, "buckets": [], "error": str(e)}

@app.post("/api/objects/upload")
async def upload_object(bucket: str, key: str, content: str):
    """Upload an object to a bucket"""
    result = put_object(bucket, key, content)
    if result.get("status") == "success":
        return {"success": True, "bucket": bucket, "key": key}
    return {"success": False, "error": result.get("error")}

# ==================== Run Server ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9360,
        reload=True
    )
