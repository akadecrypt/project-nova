"""
NOVA Backend - FastAPI Application Entry Point

Nutanix Objects Virtual Assistant - AI Agent Backend
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import (
    get_sql_agent_url, get_s3_endpoint, get_pc_ip
)
from .context import initialize_context_manager, get_context_manager
from .tools import initialize_tool_manager, get_tool_manager
from .llm import get_llm_client
from .background import start_background_tasks, generate_dynamic_schema
from .routers import (
    chat_router,
    config_router,
    context_router,
    tools_router,
    objects_router,
    database_router,
    logs_router
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle"""
    print("🚀 Starting NOVA Backend...")
    print(f"   Version: {__version__}")
    
    # Initialize context manager
    context_manager = initialize_context_manager()
    print(f"📄 Context files loaded: {len(context_manager.contexts)}")
    
    # Load dynamic SQL schema from database (replaces static sql_schema.md)
    try:
        dynamic_schema = generate_dynamic_schema()
        context_manager.set_context("sql_schema", dynamic_schema)
        print("📊 Dynamic SQL schema loaded from database")
    except Exception as e:
        print(f"⚠️ Could not load dynamic schema: {e}")
    
    # Initialize tool manager
    tool_manager = initialize_tool_manager()
    print(f"🔧 Tools loaded: {len(tool_manager.get_tools())}")
    
    # Print configuration status
    print(f"📡 SQL Agent: {get_sql_agent_url()}")
    print(f"🪣 S3 Endpoint: {get_s3_endpoint() or 'Not configured'}")
    print(f"🖥️  Prism Central: {get_pc_ip() or 'Not configured'}")
    print(f"🤖 LLM: {'Configured' if get_llm_client() else 'Not configured'}")
    
    # Start background tasks
    background_task = await start_background_tasks()
    
    print("✅ NOVA Backend ready!")
    print("   API Docs: http://localhost:9360/docs")
    
    yield
    
    # Cleanup
    background_task.cancel()
    try:
        await background_task
    except asyncio.CancelledError:
        pass
    
    print("👋 NOVA Backend shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="NOVA API",
    description="Nutanix Objects Virtual Assistant - AI Agent Backend",
    version=__version__,
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

# Register routers
app.include_router(chat_router)
app.include_router(config_router)
app.include_router(context_router)
app.include_router(tools_router)
app.include_router(objects_router)
app.include_router(database_router)
app.include_router(logs_router)


# Root endpoints
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "NOVA API",
        "version": __version__,
        "description": "Nutanix Objects Virtual Assistant"
    }


@app.get("/api/status")
async def get_status():
    """Get API status"""
    context_manager = get_context_manager()
    tool_manager = get_tool_manager()
    llm_client = get_llm_client()
    
    return {
        "status": "online",
        "version": __version__,
        "llm_configured": llm_client is not None,
        "llm_provider": "nutanix-ai" if llm_client else "none",
        "s3_configured": bool(get_s3_endpoint()),
        "prism_central_configured": bool(get_pc_ip()),
        "sql_agent_configured": bool(get_sql_agent_url()),
        "sql_agent_url": get_sql_agent_url(),
        "context_files_loaded": len(context_manager.contexts),
        "tools_loaded": len(tool_manager.get_tools()),
        "sql_summary_last_refresh": (
            context_manager.last_sql_refresh.isoformat() 
            if context_manager.last_sql_refresh else None
        )
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
