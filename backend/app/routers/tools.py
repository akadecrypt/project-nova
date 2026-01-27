"""
Tools Router for NOVA Backend

Handles tool management and introspection endpoints.
"""
from fastapi import APIRouter, HTTPException

from ..tools import get_tool_manager

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    """List all available tools"""
    manager = get_tool_manager()
    
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"]
            }
            for t in manager.get_tools()
        ],
        "count": len(manager.get_tools()),
        "categories": manager.get_categories()
    }


@router.get("/{name}")
async def get_tool(name: str):
    """Get detailed info about a specific tool"""
    manager = get_tool_manager()
    tool_info = manager.get_tool_info(name)
    
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    
    return tool_info


@router.post("/reload")
async def reload_tools():
    """Reload tools from disk"""
    manager = get_tool_manager()
    count = manager.reload()
    
    return {
        "success": True,
        "tools_loaded": count
    }


@router.get("/categories/{category}")
async def get_tools_by_category(category: str):
    """Get all tools in a specific category"""
    manager = get_tool_manager()
    tools = manager.get_tools_by_category(category)
    
    return {
        "category": category,
        "tools": tools,
        "count": len(tools)
    }
