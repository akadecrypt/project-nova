"""
NOVA Backend - FastAPI Application
AI Agent for Nutanix Objects Operations
"""
# Disable telemetry BEFORE any imports
import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "True"

# SQLite fix for older systems - MUST be before chromadb import
import sqlite_fix

import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import tempfile
import shutil

from config import (
    settings, 
    load_prism_config, 
    save_prism_config,
    load_llm_config,
    save_llm_config
)
from services import (
    get_vector_db,
    PrismConfig,
    configure_prism,
    get_prism_client,
    create_agent,
    create_llm_agent,
    AgentResponse
)


# ==================== Pydantic Models ====================

class ChatContext(BaseModel):
    """Context for chat operations"""
    objectstore_uuid: Optional[str] = None
    bucket_name: Optional[str] = None

class ChatMessage(BaseModel):
    """Chat message from user"""
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="default")
    context: Optional[ChatContext] = None


class ChatResponse(BaseModel):
    """Response from chat agent"""
    message: str
    intent: str
    success: bool
    data: Optional[dict] = None
    code_block: Optional[str] = None
    code_lang: str = "json"
    suggestions: Optional[List[str]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class PrismConfigRequest(BaseModel):
    """Prism configuration request"""
    prism_ip: str = Field(..., min_length=7, max_length=255)
    prism_port: int = Field(default=9440, ge=1, le=65535)
    prism_username: str = Field(default="admin")
    prism_password: str = Field(default="")


class PrismConfigResponse(BaseModel):
    """Prism configuration response"""
    prism_ip: Optional[str] = None
    prism_port: int = 9440
    prism_username: Optional[str] = None
    is_configured: bool = False
    connection_status: Optional[str] = None


class KnowledgeAddRequest(BaseModel):
    """Request to add knowledge"""
    documents: List[str]


class LLMConfigRequest(BaseModel):
    """LLM configuration request"""
    provider: str = Field(..., description="LLM provider: ollama, openai, anthropic, groq")
    api_key: Optional[str] = Field(default=None, description="API key for cloud providers")
    ollama_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    ollama_model: str = Field(default="llama3.1", description="Ollama model name")


class LLMConfigResponse(BaseModel):
    """LLM configuration response"""
    provider: str
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    is_configured: bool = False
    status: Optional[str] = None


class StatusResponse(BaseModel):
    """API status response"""
    status: str
    version: str
    prism_configured: bool
    llm_provider: str
    vector_db_stats: dict


# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    # Startup
    print("🚀 Starting NOVA Backend...")
    
    # Initialize vector DB
    vector_db = get_vector_db(settings.chroma_persist_dir)
    print(f"📊 Vector DB initialized: {vector_db.get_stats()}")
    
    # Seed knowledge base if empty
    stats = vector_db.get_stats()
    if stats["knowledge_count"] == 0:
        count = vector_db.seed_objects_knowledge()
        print(f"📚 Seeded {count} knowledge documents")
    
    # Load saved Prism config from DB
    prism_config = load_prism_config()
    if prism_config.get("prism_ip"):
        print(f"🔧 Loading saved Prism config: {prism_config['prism_ip']}")
        configure_prism(
            ip=prism_config["prism_ip"],
            port=prism_config.get("prism_port", 9440),
            username=prism_config.get("prism_username", "admin"),
            password=prism_config.get("prism_password", "")
        )
    
    # Load LLM config from DB
    llm_config = load_llm_config()
    provider = llm_config.get("provider", "ollama")
    api_key = llm_config.get("api_key")
    ollama_url = llm_config.get("ollama_url", "http://localhost:11434")
    ollama_model = llm_config.get("ollama_model", "llama3.1")
    
    # Create agent based on saved config or auto-detect
    def create_configured_agent():
        """Create agent based on configuration"""
        import httpx
        
        if provider == "ollama":
            # Check if Ollama is running
            try:
                response = httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
                if response.status_code == 200:
                    print(f"🦙 Using Ollama (FREE, LOCAL) at {ollama_url} with model {ollama_model}")
                    return create_llm_agent(provider="ollama", ollama_base_url=ollama_url, ollama_model=ollama_model)
            except:
                print("⚠️ Ollama not available, falling back...")
        
        elif provider == "openai" and api_key:
            print("🤖 Using OpenAI function calling")
            return create_llm_agent(api_key=api_key, provider="openai")
        
        elif provider == "anthropic" and api_key:
            print("🤖 Using Anthropic Claude")
            return create_llm_agent(api_key=api_key, provider="anthropic")
        
        elif provider == "groq" and api_key:
            print("⚡ Using Groq (fast inference)")
            return create_llm_agent(api_key=api_key, provider="groq")
        
        # Fallback: try Ollama, then env vars, then vector-based
        try:
            response = httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
            if response.status_code == 200:
                print(f"🦙 Auto-detected Ollama at {ollama_url}")
                return create_llm_agent(provider="ollama", ollama_base_url=ollama_url, ollama_model=ollama_model)
        except:
            pass
        
        if settings.openai_api_key:
            return create_llm_agent(api_key=settings.openai_api_key, provider="openai")
        if os.getenv("ANTHROPIC_API_KEY"):
            return create_llm_agent(api_key=os.getenv("ANTHROPIC_API_KEY"), provider="anthropic")
        if os.getenv("GROQ_API_KEY"):
            return create_llm_agent(api_key=os.getenv("GROQ_API_KEY"), provider="groq")
        
        print("📊 Using vector-based agent (no LLM configured)")
        print("   💡 Tip: Configure LLM in Settings or run `ollama serve`")
        return create_agent()
    
    app.state.agent = create_configured_agent()
    
    # If Prism is configured, set it on agent
    prism_client = get_prism_client()
    if prism_client:
        app.state.agent.set_prism_client(prism_client)
    
    print("✅ NOVA Backend ready!")
    
    yield
    
    # Shutdown
    print("👋 Shutting down NOVA Backend...")
    prism_client = get_prism_client()
    if prism_client:
        await prism_client.close()


# ==================== FastAPI Application ====================

app = FastAPI(
    title="NOVA API",
    description="Nutanix Objects Virtual Assistant - AI Agent Backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API Routes ====================

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get API status"""
    vector_db = get_vector_db()
    prism_client = get_prism_client()
    llm_config = load_llm_config()
    
    return StatusResponse(
        status="online",
        version="1.0.0",
        prism_configured=prism_client is not None,
        llm_provider=llm_config.get("provider", "vector-based"),
        vector_db_stats=vector_db.get_stats()
    )


# -------------------- Chat Endpoints --------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatMessage):
    """
    Send a message to NOVA
    
    The agent will process your message and perform relevant operations.
    """
    try:
        agent = app.state.agent
        
        # Build context dict
        context = {}
        if request.context:
            if request.context.objectstore_uuid:
                context['objectstore_uuid'] = request.context.objectstore_uuid
            if request.context.bucket_name:
                context['bucket_name'] = request.context.bucket_name
        
        response: AgentResponse = await agent.process_message(
            message=request.message,
            session_id=request.session_id,
            context=context
        )
        
        return ChatResponse(
            message=response.message,
            intent=response.intent,
            success=response.success,
            data=response.data,
            code_block=response.code_block,
            code_lang=response.code_lang,
            suggestions=response.suggestions
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Chat History Endpoints --------------------

@app.get("/api/chat/sessions")
async def list_chat_sessions():
    """List all chat sessions"""
    vector_db = get_vector_db()
    sessions = vector_db.list_sessions()
    return {"sessions": sessions}


@app.get("/api/chat/sessions/{session_id}")
async def get_chat_history(session_id: str):
    """Get full chat history for a session"""
    vector_db = get_vector_db()
    messages = vector_db.get_conversation_history(session_id)
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete a chat session"""
    vector_db = get_vector_db()
    success = vector_db.delete_session(session_id)
    return {"success": success, "session_id": session_id}


# -------------------- Configuration Endpoints --------------------

@app.get("/api/config/prism", response_model=PrismConfigResponse)
async def get_prism_config_endpoint():
    """Get current Prism configuration"""
    config = load_prism_config()
    prism_client = get_prism_client()
    
    response = PrismConfigResponse(
        prism_ip=config.get("prism_ip"),
        prism_port=config.get("prism_port", 9440),
        prism_username=config.get("prism_username"),
        is_configured=prism_client is not None
    )
    
    # Test connection if configured
    if prism_client:
        try:
            result = await prism_client.test_connection()
            response.connection_status = "connected" if result["success"] else result["message"]
        except:
            response.connection_status = "error"
    
    return response


@app.post("/api/config/prism", response_model=PrismConfigResponse)
async def set_prism_config_endpoint(request: PrismConfigRequest):
    """
    Configure Prism connection
    
    This will save the configuration to the database and test the connection.
    """
    # Save config to database
    save_prism_config(
        prism_ip=request.prism_ip,
        prism_port=request.prism_port,
        prism_username=request.prism_username,
        prism_password=request.prism_password
    )
    
    # Configure client
    prism_client = configure_prism(
        ip=request.prism_ip,
        port=request.prism_port,
        username=request.prism_username,
        password=request.prism_password
    )
    
    # Update agent
    app.state.agent.set_prism_client(prism_client)
    
    # Test connection
    result = await prism_client.test_connection()
    
    return PrismConfigResponse(
        prism_ip=request.prism_ip,
        prism_port=request.prism_port,
        prism_username=request.prism_username,
        is_configured=True,
        connection_status="connected" if result["success"] else result["message"]
    )


@app.post("/api/config/prism/test")
async def test_prism_connection():
    """Test Prism connection"""
    prism_client = get_prism_client()
    
    if not prism_client:
        return {"success": False, "message": "Prism not configured"}
    
    result = await prism_client.test_connection()
    return result


# -------------------- LLM Configuration Endpoints --------------------

@app.get("/api/config/llm", response_model=LLMConfigResponse)
async def get_llm_config_endpoint():
    """Get current LLM configuration"""
    config = load_llm_config()
    
    # Check if provider is available
    status = None
    if config.get("provider") == "ollama":
        try:
            import httpx
            ollama_url = config.get("ollama_url", "http://localhost:11434")
            response = httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
            status = "running" if response.status_code == 200 else "not running"
        except:
            status = "not running"
    elif config.get("api_key"):
        status = "configured"
    else:
        status = "not configured"
    
    return LLMConfigResponse(
        provider=config.get("provider", "ollama"),
        ollama_url=config.get("ollama_url", "http://localhost:11434"),
        ollama_model=config.get("ollama_model", "llama3.1"),
        is_configured=status in ["running", "configured"],
        status=status
    )


@app.post("/api/config/llm", response_model=LLMConfigResponse)
async def set_llm_config_endpoint(request: LLMConfigRequest):
    """
    Configure LLM provider
    
    Providers:
    - ollama: FREE, local. Just run `ollama serve`
    - openai: Requires API key
    - anthropic: Requires API key
    - groq: Fast inference, generous free tier
    """
    # Save config to database
    save_llm_config(
        provider=request.provider,
        api_key=request.api_key,
        ollama_url=request.ollama_url,
        ollama_model=request.ollama_model
    )
    
    # Recreate agent with new config
    try:
        if request.provider == "ollama":
            import httpx
            response = httpx.get(f"{request.ollama_url}/api/tags", timeout=2.0)
            if response.status_code == 200:
                app.state.agent = create_llm_agent(
                    provider="ollama",
                    ollama_base_url=request.ollama_url,
                    ollama_model=request.ollama_model
                )
                status = "running"
            else:
                status = "not running"
        elif request.provider in ["openai", "anthropic", "groq"] and request.api_key:
            app.state.agent = create_llm_agent(
                provider=request.provider,
                api_key=request.api_key
            )
            status = "configured"
        else:
            status = "not configured"
            app.state.agent = create_agent()  # Fallback to vector-based
    except Exception as e:
        status = f"error: {str(e)}"
        app.state.agent = create_agent()
    
    # Set Prism client on new agent
    prism_client = get_prism_client()
    if prism_client:
        app.state.agent.set_prism_client(prism_client)
    
    return LLMConfigResponse(
        provider=request.provider,
        ollama_url=request.ollama_url,
        ollama_model=request.ollama_model,
        is_configured=status in ["running", "configured"],
        status=status
    )


@app.get("/api/config/llm/providers")
async def get_available_providers():
    """Get list of available LLM providers and their status"""
    import httpx
    
    providers = []
    
    # Check Ollama
    ollama_status = "not running"
    ollama_models = []
    try:
        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if response.status_code == 200:
            ollama_status = "running"
            data = response.json()
            ollama_models = [m["name"] for m in data.get("models", [])]
    except:
        pass
    
    providers.append({
        "name": "ollama",
        "display_name": "Ollama (Free, Local)",
        "status": ollama_status,
        "requires_api_key": False,
        "available_models": ollama_models,
        "description": "Run AI locally on your machine. No API key needed!"
    })
    
    providers.append({
        "name": "openai",
        "display_name": "OpenAI",
        "status": "available" if os.getenv("OPENAI_API_KEY") else "requires key",
        "requires_api_key": True,
        "available_models": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
        "description": "OpenAI's GPT models with function calling"
    })
    
    providers.append({
        "name": "anthropic",
        "display_name": "Anthropic Claude",
        "status": "available" if os.getenv("ANTHROPIC_API_KEY") else "requires key",
        "requires_api_key": True,
        "available_models": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
        "description": "Anthropic's Claude models with tool use"
    })
    
    providers.append({
        "name": "groq",
        "display_name": "Groq (Fast)",
        "status": "available" if os.getenv("GROQ_API_KEY") else "requires key",
        "requires_api_key": True,
        "available_models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
        "description": "Ultra-fast inference with generous free tier"
    })
    
    return {"providers": providers}


# -------------------- Knowledge Base Endpoints --------------------

@app.post("/api/knowledge/add")
async def add_knowledge(request: KnowledgeAddRequest):
    """Add documents to the knowledge base"""
    vector_db = get_vector_db()
    count = vector_db.add_knowledge(request.documents)
    return {"success": True, "documents_added": count}


@app.get("/api/knowledge/search")
async def search_knowledge(query: str, limit: int = 5):
    """Search the knowledge base"""
    vector_db = get_vector_db()
    results = vector_db.search_knowledge(query, n_results=limit)
    return {"results": results}


@app.post("/api/knowledge/seed")
async def seed_knowledge():
    """Seed the knowledge base with Nutanix Objects documentation"""
    vector_db = get_vector_db()
    count = vector_db.seed_objects_knowledge()
    return {"success": True, "documents_added": count}


@app.get("/api/knowledge/stats")
async def get_knowledge_stats():
    """Get knowledge base statistics"""
    vector_db = get_vector_db()
    return vector_db.get_stats()


# -------------------- Objects API Endpoints (Convenience) --------------------

@app.get("/api/objects/stores")
async def list_object_stores():
    """List all Object Stores"""
    prism_client = get_prism_client()
    if not prism_client:
        raise HTTPException(status_code=400, detail="Prism not configured")
    
    try:
        stores = await prism_client.list_object_stores()
        return {"stores": stores}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/objects/buckets")
async def list_buckets(objectstore_uuid: Optional[str] = None):
    """List all buckets"""
    prism_client = get_prism_client()
    if not prism_client:
        return {"buckets": [], "error": "Prism not configured"}
    
    try:
        # list_buckets handles finding the OSS UUID if not provided
        buckets = await prism_client.list_buckets(objectstore_uuid)
        return {"buckets": buckets}
    except Exception as e:
        return {"buckets": [], "error": str(e)}


@app.post("/api/objects/buckets")
async def create_bucket(
    name: str,
    objectstore_uuid: Optional[str] = None,
    versioning: bool = False
):
    """Create a new bucket"""
    prism_client = get_prism_client()
    if not prism_client:
        raise HTTPException(status_code=400, detail="Prism not configured")
    
    try:
        if not objectstore_uuid:
            stores = await prism_client.list_object_stores()
            if not stores:
                raise HTTPException(status_code=400, detail="No Object Store available")
            # Get UUID from groups API response format
            objectstore_uuid = stores[0].get("uuid")
            if not objectstore_uuid:
                raise HTTPException(status_code=400, detail="Could not get Object Store UUID")
        
        result = await prism_client.create_bucket(
            oss_uuid=objectstore_uuid,
            name=name,
            versioning=versioning
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/objects/stats")
async def get_storage_stats(oss_uuid: Optional[str] = None):
    """Get storage statistics from Prism using groups API"""
    prism_client = get_prism_client()
    if not prism_client:
        return {
            "connected": False,
            "object_stores": [],
            "total_buckets": 0,
            "total_objects": 0,
            "total_size_bytes": 0,
            "total_size_human": "0 B"
        }
    
    def format_bytes(b):
        if b == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
            if b < 1024:
                return f"{b:.2f} {unit}"
            b /= 1024
        return f"{b:.2f} PB"
    
    try:
        # First get all object stores
        object_stores = await prism_client.list_object_stores()
        
        if not object_stores:
            return {
                "connected": True,
                "object_stores": [],
                "total_buckets": 0,
                "total_objects": 0,
                "total_size_bytes": 0,
                "total_size_human": "0 B",
                "message": "No Object Stores found. Please create an Object Store first."
            }
        
        # If oss_uuid provided, get buckets for that specific object store
        if oss_uuid:
            buckets = await prism_client.list_buckets(oss_uuid)
        else:
            # Get buckets for first object store
            first_oss_uuid = object_stores[0].get("uuid")
            buckets = await prism_client.list_buckets(first_oss_uuid) if first_oss_uuid else []
        
        # Calculate totals from groups API response
        total_objects = 0
        total_size = 0
        bucket_details = []
        
        for bucket in buckets:
            bucket_info = {
                "name": bucket.get("name", "Unknown"),
                "size_bytes": bucket.get("storage_usage_bytes", 0),
                "object_count": bucket.get("object_count", 0),
                "versioning": bucket.get("versioning", "Disabled"),
                "worm": bucket.get("worm", "Disabled"),
                "owner": bucket.get("owner_name", ""),
                "oss_uuid": bucket.get("oss_uuid", "")
            }
            bucket_details.append(bucket_info)
            total_objects += bucket_info["object_count"]
            total_size += bucket_info["size_bytes"]
        
        return {
            "connected": True,
            "object_stores": object_stores,
            "total_object_stores": len(object_stores),
            "total_buckets": len(buckets),
            "total_objects": total_objects,
            "total_size_bytes": total_size,
            "total_size_human": format_bytes(total_size),
            "buckets": bucket_details
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "connected": True,
            "error": str(e),
            "object_stores": [],
            "total_buckets": 0,
            "total_objects": 0,
            "total_size_bytes": 0,
            "total_size_human": "0 B"
        }


@app.get("/api/objects/stores/{oss_uuid}/buckets")
async def get_buckets_for_store(oss_uuid: str):
    """Get buckets for a specific object store"""
    prism_client = get_prism_client()
    if not prism_client:
        return {"buckets": [], "error": "Prism not configured"}
    
    try:
        buckets = await prism_client.list_buckets(oss_uuid)
        return {"buckets": buckets, "oss_uuid": oss_uuid}
    except Exception as e:
        return {"buckets": [], "error": str(e)}


# -------------------- File Upload Endpoint --------------------

@app.post("/api/objects/upload")
async def upload_file(
    file: UploadFile = File(...),
    oss_uuid: str = Form(...),
    bucket_name: str = Form(...)
):
    """
    Upload a file to a bucket in the Object Store
    """
    prism_client = get_prism_client()
    if not prism_client:
        raise HTTPException(status_code=400, detail="Prism not configured")
    
    if not oss_uuid or not bucket_name:
        raise HTTPException(status_code=400, detail="Object Store and Bucket must be specified")
    
    try:
        # Save the uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        
        try:
            # Upload to Nutanix Objects using S3 API
            result = await prism_client.upload_object(
                oss_uuid=oss_uuid,
                bucket_name=bucket_name,
                object_key=file.filename,
                file_path=tmp_path,
                content_type=file.content_type or "application/octet-stream"
            )
            
            return {
                "success": True,
                "message": f"File '{file.filename}' uploaded successfully",
                "bucket": bucket_name,
                "object_key": file.filename,
                "size": file.size
            }
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Static File Serving ====================

# Serve frontend if available
FRONTEND_DIR = Path(__file__).parent.parent
if (FRONTEND_DIR / "index.html").exists():
    @app.get("/")
    async def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")
    
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    
    @app.get("/{path:path}")
    async def serve_static(path: str):
        file_path = FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")


# ==================== Run Server ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
