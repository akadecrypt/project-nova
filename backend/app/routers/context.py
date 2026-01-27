"""
Context Router for NOVA Backend

Handles context file management endpoints.
"""
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import ContextFile
from ..context import get_context_manager
from ..config import CONTEXT_DIR

router = APIRouter(prefix="/api/context", tags=["context"])


class ContextOrderRequest(BaseModel):
    """Request to update context order"""
    order: List[str]


@router.get("")
async def list_contexts():
    """List all loaded context files with stats"""
    manager = get_context_manager()
    return manager.get_stats()


@router.get("/order")
async def get_context_order():
    """Get current context order"""
    manager = get_context_manager()
    return {
        "order": manager.context_order,
        "available": list(manager.contexts.keys())
    }


@router.post("/order")
async def set_context_order(request: ContextOrderRequest):
    """
    Set the order in which contexts are included in the system prompt.
    
    New .md files added to context/ folder will be appended at the end.
    Use this endpoint or edit context_order.json to control order.
    """
    manager = get_context_manager()
    
    if manager.set_order(request.order):
        return {
            "success": True,
            "message": "Context order updated",
            "order": manager.context_order
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to save context order")


@router.get("/{name}")
async def get_context(name: str):
    """Get a specific context file content"""
    manager = get_context_manager()
    content = manager.get_context(name)
    
    if not content:
        raise HTTPException(status_code=404, detail=f"Context '{name}' not found")
    
    return {"name": name, "content": content}


@router.post("/{name}")
async def update_context(name: str, context: ContextFile):
    """Update or create a context file"""
    manager = get_context_manager()
    
    if manager.save_context(name, context.content):
        return {"success": True, "message": f"Context '{name}' updated"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to save context '{name}'")


@router.delete("/{name}")
async def delete_context(name: str):
    """Delete a context file"""
    manager = get_context_manager()
    file_path = CONTEXT_DIR / f"{name}.md"
    
    try:
        if file_path.exists():
            file_path.unlink()
        if name in manager.contexts:
            del manager.contexts[name]
        return {"success": True, "message": f"Context '{name}' deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_contexts():
    """Reload all context files from disk"""
    manager = get_context_manager()
    count = manager.reload()
    
    return {
        "success": True,
        "contexts_loaded": count
    }


@router.get("/sql/summary")
async def get_sql_summary():
    """Get the current SQL data summary"""
    manager = get_context_manager()
    
    return {
        "summary": manager.sql_summary,
        "last_refresh": manager.last_sql_refresh.isoformat() if manager.last_sql_refresh else None
    }


@router.post("/sql/refresh")
async def refresh_sql_summary():
    """Manually trigger SQL summary refresh"""
    from ..tools.sql_tools import execute_sql
    
    manager = get_context_manager()
    summary_parts = []
    
    try:
        # Get bucket count
        result = execute_sql("SELECT COUNT(*) as count FROM bucket")
        if result.get("status") != "error" and result.get("rows"):
            summary_parts.append(f"- Total buckets in database: {result['rows'][0][0]}")
        
        # Get total storage
        result = execute_sql("""
            SELECT SUM(size_gb) as total_gb, SUM(object_count) as total_objects 
            FROM bucket_stats 
            WHERE timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
        """)
        if result.get("status") != "error" and result.get("rows") and result["rows"][0][0]:
            summary_parts.append(f"- Total storage: {result['rows'][0][0]:.2f} GB")
            summary_parts.append(f"- Total objects: {result['rows'][0][1]}")
        
        # Get table list
        result = execute_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if result.get("status") != "error" and result.get("rows"):
            tables = [row[0] for row in result["rows"]]
            summary_parts.append(f"- Available tables: {', '.join(tables)}")
        
        if summary_parts:
            summary = "\n".join(summary_parts)
            manager.update_sql_summary(summary)
            return {"success": True, "summary": summary}
        else:
            return {"success": False, "message": "No data retrieved from SQL agent"}
            
    except Exception as e:
        return {"success": False, "message": str(e)}
