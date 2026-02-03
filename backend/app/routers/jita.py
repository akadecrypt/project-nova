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
from ..logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

# Track running analysis jobs
_analysis_jobs: Dict[str, Dict] = {}  # run_id -> {status, started_at, error}


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
    global _analysis_jobs
    try:
        logger.info(f"Background: Starting analysis for {run_id}")
        service = get_jita_service()
        result = service.analyze_run(run_id)
        
        if "error" in result:
            _analysis_jobs[run_id] = {
                "status": "failed",
                "error": result["error"],
                "completed_at": datetime.now().isoformat()
            }
        else:
            _analysis_jobs[run_id] = {
                "status": "completed",
                "tests_analyzed": result.get("tests_analyzed", 0),
                "completed_at": datetime.now().isoformat()
            }
        logger.info(f"Background: Completed analysis for {run_id}")
        
    except Exception as e:
        logger.error(f"Background: Error analyzing {run_id}: {e}")
        _analysis_jobs[run_id] = {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        }


@router.post("/analyze/{run_id}/start")
async def start_analysis(run_id: str):
    """
    Start analysis in background. Returns immediately.
    
    User can poll /analyze/{run_id}/status to check progress.
    """
    global _analysis_jobs
    
    # Check if already running
    if run_id in _analysis_jobs and _analysis_jobs[run_id].get("status") == "running":
        return {
            "status": "already_running",
            "run_id": run_id,
            "message": "Analysis already in progress"
        }
    
    # Start background thread
    _analysis_jobs[run_id] = {
        "status": "running",
        "started_at": datetime.now().isoformat()
    }
    
    thread = threading.Thread(target=_run_analysis_background, args=(run_id,))
    thread.daemon = True
    thread.start()
    
    logger.info(f"API: Started background analysis for {run_id}")
    
    return {
        "status": "started",
        "run_id": run_id,
        "message": "Analysis started in background"
    }


@router.get("/analyze/{run_id}/status")
async def get_analysis_status(run_id: str):
    """Check status of a running analysis."""
    if run_id not in _analysis_jobs:
        # Check if already analyzed
        service = get_jita_service()
        runs = service.list_analyzed_runs()
        if run_id in runs:
            return {"status": "completed", "run_id": run_id}
        return {"status": "not_found", "run_id": run_id}
    
    return {"run_id": run_id, **_analysis_jobs[run_id]}


@router.get("/jobs")
async def list_analysis_jobs():
    """List all analysis jobs and their status."""
    return {
        "jobs": [
            {"run_id": rid, **info} 
            for rid, info in _analysis_jobs.items()
        ]
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
async def list_analyzed_runs():
    """
    List all analyzed JITA runs.
    
    Returns list of run IDs that have been analyzed and stored in SQL.
    """
    try:
        service = get_jita_service()
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


@router.get("/runs/{run_id}/logs")
async def get_run_logs(
    run_id: str,
    severity: Optional[str] = Query(None, description="Filter by severity (ERROR, FATAL, WARN)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    test_result_id: Optional[str] = Query(None, description="Filter by test result ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of logs to return")
):
    """
    Get log events for a specific run with optional filters.
    
    Args:
        run_id: JITA run ID
        severity: Filter by severity level
        event_type: Filter by classified event type
        test_result_id: Filter by specific test result
        limit: Maximum number of logs to return
        
    Returns:
        List of log events matching filters
    """
    try:
        service = get_jita_service()
        result = service.get_run_logs(
            run_id=run_id,
            severity=severity,
            event_type=event_type,
            test_result_id=test_result_id,
            limit=limit
        )
        
        if result.get("status") == "error":
            raise HTTPException(status_code=404, detail=result.get("error", "Run not found"))
        
        return {
            "status": "success",
            "run_id": run_id,
            "logs": result.get("rows", []),
            "count": result.get("row_count", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting logs for run {run_id}: {e}")
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
        
        # Drop tables
        execute_sql(f"DROP TABLE IF EXISTS {logs_table}")
        execute_sql(f"DROP TABLE IF EXISTS {summary_table}")
        
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
