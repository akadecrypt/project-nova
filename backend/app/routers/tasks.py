"""
Tasks Router - API endpoints for task management

Provides endpoints to view and manage background tasks.
"""
from fastapi import APIRouter, Query
from typing import Optional, List

from ..task_manager import get_task_manager, TaskStatus, TaskType

router = APIRouter()


@router.get("/")
async def list_all_tasks(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, description="Max tasks to return")
):
    """List all tasks with optional filters"""
    manager = get_task_manager()
    
    # Convert string filters to enums
    type_filter = None
    if task_type:
        try:
            type_filter = TaskType(task_type)
        except ValueError:
            pass
    
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            pass
    
    tasks = manager.list_tasks(task_type=type_filter, status=status_filter)
    
    return {
        "success": True,
        "count": len(tasks[:limit]),
        "tasks": [t.to_dict() for t in tasks[:limit]]
    }


@router.get("/summary")
async def get_tasks_summary():
    """Get summary of all tasks"""
    manager = get_task_manager()
    summary = manager.get_summary()
    
    return {
        "success": True,
        **summary
    }


@router.get("/running")
async def get_running_tasks():
    """Get all currently running tasks"""
    manager = get_task_manager()
    tasks = manager.get_running_tasks()
    
    return {
        "success": True,
        "count": len(tasks),
        "tasks": [t.to_dict() for t in tasks]
    }


@router.get("/active")
async def get_active_tasks():
    """Get all pending and running tasks"""
    manager = get_task_manager()
    tasks = manager.get_active_tasks()
    
    return {
        "success": True,
        "count": len(tasks),
        "tasks": [t.to_dict() for t in tasks]
    }


@router.get("/{task_id}")
async def get_task(task_id: str):
    """Get details of a specific task"""
    manager = get_task_manager()
    task = manager.get_task(task_id)
    
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found"
        }
    
    return {
        "success": True,
        "task": task.to_dict()
    }


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running task (if supported)"""
    manager = get_task_manager()
    task = manager.get_task(task_id)
    
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found"
        }
    
    if task.status != TaskStatus.RUNNING:
        return {
            "success": False,
            "error": f"Task is not running (status: {task.status.value})"
        }
    
    # Mark as cancelled (actual cancellation depends on task implementation)
    task.cancel()
    
    return {
        "success": True,
        "message": f"Task {task_id} marked as cancelled"
    }


@router.delete("/cleanup")
async def cleanup_old_tasks():
    """Remove old completed tasks"""
    manager = get_task_manager()
    manager.cleanup_old_tasks()
    
    return {
        "success": True,
        "message": "Old tasks cleaned up"
    }
