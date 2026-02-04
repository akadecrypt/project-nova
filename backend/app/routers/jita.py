"""
JITA Router for NOVA Backend

API endpoints for JITA test run analysis.
"""
import threading
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from ..services.jita_service import get_jita_service
from ..task_manager import get_task_manager, TaskType, TaskStatus
from ..logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)


class AnalyzeRequest(BaseModel):
    """Request body for analyze endpoint (optional, run_id can be in path)."""
    run_id: Optional[str] = None


class AnalyzeResponse(BaseModel):
    """Response from analyze endpoint."""
    status: str
    run_id: str
    task: Optional[Dict[str, Any]] = None
    test_result_count: Optional[Dict[str, int]] = None
    tests_analyzed: int = 0
    log_events_found: int = 0
    error_counts: Optional[Dict[str, int]] = None
    event_types: Optional[Dict[str, int]] = None
    summaries: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


def _run_analysis_background(run_id: str):
    """Background task to run analysis."""
    task_manager = get_task_manager()
    task = task_manager.get_task(f"jita_{run_id}")
    
    try:
        logger.info(f"Background: Starting analysis for {run_id}")
        if task:
            task.start()
            task.update_progress(10, "Fetching task details from JITA...")
        
        service = get_jita_service()
        result = service.analyze_run(run_id)
        
        if "error" in result:
            if task:
                task.fail(result["error"])
            logger.error(f"Background: Analysis failed for {run_id}: {result['error']}")
        else:
            if task:
                task.complete({
                    "tests_analyzed": result.get("tests_analyzed", 0),
                    "log_events_found": result.get("log_events_found", 0)
                })
            logger.info(f"Background: Completed analysis for {run_id}")
        
    except Exception as e:
        logger.error(f"Background: Error analyzing {run_id}: {e}")
        if task:
            task.fail(str(e))


@router.post("/analyze/{run_id}/start")
async def start_analysis(run_id: str):
    """
    Start analysis in background. Returns immediately.
    
    User can poll /analyze/{run_id}/status to check progress.
    """
    task_manager = get_task_manager()
    task_id = f"jita_{run_id}"
    
    # Check if already running
    existing_task = task_manager.get_task(task_id)
    if existing_task and existing_task.status == TaskStatus.RUNNING:
        return {
            "status": "already_running",
            "run_id": run_id,
            "task_id": task_id,
            "message": "Analysis already in progress"
        }
    
    # Create task in task manager
    task = task_manager.create_task(
        task_id=task_id,
        task_type=TaskType.JITA_ANALYSIS,
        name=f"JITA Analysis: {run_id[:12]}...",
        description=f"Analyzing JITA test run {run_id}",
        metadata={"run_id": run_id}
    )
    
    # Start background thread
    thread = threading.Thread(target=_run_analysis_background, args=(run_id,))
    thread.daemon = True
    thread.start()
    
    logger.info(f"API: Started background analysis for {run_id}")
    
    return {
        "status": "started",
        "run_id": run_id,
        "task_id": task_id,
        "message": "Analysis started in background"
    }


@router.get("/analyze/{run_id}/status")
async def get_analysis_status(run_id: str):
    """Check status of a running analysis."""
    task_manager = get_task_manager()
    task_id = f"jita_{run_id}"
    task = task_manager.get_task(task_id)
    
    if not task:
        # Check if already analyzed
        service = get_jita_service()
        runs = service.list_analyzed_runs()
        if run_id in runs:
            return {"status": "completed", "run_id": run_id}
        return {"status": "not_found", "run_id": run_id}
    
    return {
        "run_id": run_id,
        "task_id": task_id,
        "status": task.status.value,
        "progress": task.progress,
        "progress_message": task.progress_message,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "duration_seconds": task.duration_seconds,
        "error": task.error
    }


@router.get("/jobs")
async def list_analysis_jobs():
    """List all JITA analysis jobs and their status."""
    task_manager = get_task_manager()
    tasks = task_manager.list_tasks(task_type=TaskType.JITA_ANALYSIS)
    
    return {
        "jobs": [t.to_dict() for t in tasks]
    }


@router.post("/analyze/{run_id}", response_model=AnalyzeResponse)
async def analyze_jita_run(run_id: str):
    """
    Analyze a JITA test run (synchronous - waits for completion).
    
    Fetches task details, test results, and logs from JITA API,
    parses them for errors, and stores in SQL tables.
    
    Args:
        run_id: JITA task/run ID (e.g., '697a296e8e79ce6b2202f970')
        
    Returns:
        Analysis summary with task info, test counts, and error summary
    """
    logger.info(f"API: Analyzing JITA run {run_id}")
    
    try:
        service = get_jita_service()
        result = service.analyze_run(run_id)
        
        if "error" in result:
            return AnalyzeResponse(
                status="error",
                run_id=run_id,
                error=result["error"]
            )
        
        return AnalyzeResponse(
            status="success",
            run_id=run_id,
            task=result.get("task"),
            test_result_count=result.get("test_result_count"),
            tests_analyzed=result.get("tests_analyzed", 0),
            log_events_found=result.get("log_events_found", 0),
            error_counts=result.get("error_counts"),
            event_types=result.get("event_types"),
            summaries=result.get("summaries")
        )
        
    except Exception as e:
        logger.error(f"Error analyzing run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs")
async def list_analyzed_runs(with_metadata: bool = Query(False, description="Include run metadata")):
    """
    List all analyzed JITA runs.
    
    Returns list of run IDs that have been analyzed and stored in SQL.
    Use with_metadata=true to get full details for each run.
    """
    try:
        service = get_jita_service()
        
        if with_metadata:
            runs = service.get_runs_with_metadata()
            return {
                "status": "success",
                "runs": runs,
                "count": len(runs)
            }
        else:
            runs = service.list_analyzed_runs()
            return {
                "status": "success",
                "runs": runs,
                "count": len(runs)
            }
        
    except Exception as e:
        logger.error(f"Error listing runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}")
async def get_run_analysis(run_id: str):
    """
    Get analysis results for a specific run.
    
    Args:
        run_id: JITA run ID
        
    Returns:
        Stored analysis including test summaries and error counts
    """
    try:
        service = get_jita_service()
        result = service.get_run_summary(run_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return {
            "status": "success",
            **result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/summary")
async def get_run_test_summary(run_id: str):
    """
    Get test summaries for a specific run.
    
    Args:
        run_id: JITA run ID
        
    Returns:
        List of test summaries with status, operations, and exception info
    """
    try:
        service = get_jita_service()
        result = service.get_run_summary(run_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return {
            "status": "success",
            "run_id": run_id,
            "tests": result.get("tests", []),
            "count": len(result.get("tests", []))
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/timeline")
async def get_run_timeline(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result")
):
    """
    Get timeline data for a run showing phases with their logs.
    
    Each test execution has phases: Scheduling, Pre-Run Plugin, Test Execution, Post-Run Plugin.
    Logs are correlated with their respective phases by timestamp.
    
    Args:
        run_id: JITA run ID
        test_result_id: Optional filter for specific test
        
    Returns:
        Timeline phases with associated logs and error counts
    """
    try:
        service = get_jita_service()
        result = service.get_timeline(run_id, test_result_id)
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting timeline for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result"),
    phase: Optional[str] = Query(None, description="Filter by phase name"),
    severity: Optional[str] = Query(None, description="Filter by severity (ERROR, WARN, FATAL)"),
    operation: Optional[str] = Query(None, description="Filter by operation name"),
    limit: int = Query(50, description="Number of logs to return"),
    offset: int = Query(0, description="Offset for pagination")
):
    """
    Get paginated logs for a run with filters.
    
    Supports infinite scroll / load more functionality.
    """
    try:
        service = get_jita_service()
        result = service.get_paginated_logs(
            run_id, 
            test_result_id=test_result_id,
            phase=phase,
            severity=severity,
            operation=operation,
            limit=limit,
            offset=offset
        )
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting logs for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/operations")
async def get_run_operations(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result")
):
    """
    Get operations timeline with errors grouped by operation in execution order.
    
    Operations are extracted from log sources like 'op:3.2.1_OpGroup'.
    They are sorted by their numeric prefix to maintain execution order.
    
    Args:
        run_id: JITA run ID
        test_result_id: Optional filter for specific test
        
    Returns:
        Operations with their error counts and details, in execution order
    """
    try:
        service = get_jita_service()
        result = service.get_operations_timeline(run_id, test_result_id)
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting operations for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/runs/{run_id}")
async def delete_run_analysis(run_id: str):
    """
    Delete analysis data for a specific run.
    
    Drops the SQL tables for this run.
    
    Args:
        run_id: JITA run ID
        
    Returns:
        Success/failure status
    """
    try:
        from ..tools.sql_tools import execute_sql
        import re
        
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        logs_table = f"jita_{safe_id}_logs"
        summary_table = f"jita_{safe_id}_summary"
        timeline_table = f"jita_{safe_id}_timeline"
        
        # Drop tables
        execute_sql(f"DROP TABLE IF EXISTS {logs_table}")
        execute_sql(f"DROP TABLE IF EXISTS {summary_table}")
        execute_sql(f"DROP TABLE IF EXISTS {timeline_table}")
        
        logger.info(f"Deleted analysis for run {run_id}")
        
        return {
            "status": "success",
            "message": f"Deleted analysis for run {run_id}"
        }
        
    except Exception as e:
        logger.error(f"Error deleting run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}")
async def get_jita_task(task_id: str):
    """
    Get raw JITA task details (without analysis).
    
    Useful for previewing a task before analyzing.
    
    Args:
        task_id: JITA task ID
        
    Returns:
        Raw task details from JITA API
    """
    try:
        service = get_jita_service()
        task = service.get_task_details(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        # Extract key info
        return {
            "status": "success",
            "task_id": task_id,
            "label": task.get("label", ""),
            "service": task.get("service", ""),
            "created_by": task.get("created_by", ""),
            "task_status": task.get("status", ""),
            "test_result_count": task.get("test_result_count", {}),
            "test_results": len(task.get("AgaveTestResults", [])),
            "scheduler_logs": task.get("scheduler_logs", ""),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
