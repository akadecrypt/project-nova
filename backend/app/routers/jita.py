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
    """Background task to run AI-powered analysis."""
    import asyncio
    task_manager = get_task_manager()
    task = task_manager.get_task(f"jita_{run_id}")
    
    try:
        logger.info(f"Background: Starting AI analysis for {run_id}")
        if task:
            task.start()
            task.update_progress(10, "Fetching task details from JITA...")
        
        service = get_jita_service()
        
        # Use the new AI-powered analysis
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if task:
                task.update_progress(20, "Analyzing logs with AI...")
            result = loop.run_until_complete(service.analyze_run_with_ai(run_id))
        finally:
            loop.close()
        
        if "error" in result:
            if task:
                task.fail(result["error"])
            logger.error(f"Background: AI analysis failed for {run_id}: {result['error']}")
        else:
            if task:
                task.complete({
                    "tests_analyzed": result.get("tests_analyzed", 0),
                    "ai_errors_found": result.get("ai_errors_found", 0)
                })
            logger.info(f"Background: Completed AI analysis for {run_id}")
        
    except Exception as e:
        logger.error(f"Background: Error in AI analysis for {run_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
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


@router.get("/runs/{run_id}/stats")
async def get_run_error_stats(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result")
):
    """
    Get aggregated error statistics for a run.
    
    Returns total counts by severity, event_type, log_source, and priority -
    all computed from DB without loading full data.
    """
    try:
        service = get_jita_service()
        result = service.get_error_stats(run_id, test_result_id)
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting stats for run {run_id}: {e}")
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
    NOTE: This endpoint returns legacy regex-parsed logs. Use /runs/{run_id}/errors for AI-analyzed errors.
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


@router.get("/runs/{run_id}/errors")
async def get_ai_errors(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result"),
    severity: Optional[str] = Query(None, description="Filter by severity (CRITICAL, HIGH, MEDIUM, LOW)"),
    category: Optional[str] = Query(None, description="Filter by error category"),
    limit: int = Query(100, description="Number of errors to return"),
    offset: int = Query(0, description="Offset for pagination")
):
    """
    Get AI-identified errors for a run.
    
    Returns errors identified by AI analysis with root cause, impact, and suggested fixes.
    This is the primary endpoint for viewing test failures and issues.
    
    Args:
        run_id: JITA run ID
        test_result_id: Optional filter for specific test
        severity: Filter by CRITICAL, HIGH, MEDIUM, LOW
        category: Filter by error category
        limit: Max results (default 100)
        offset: Pagination offset
        
    Returns:
        AI-analyzed errors with full context and suggestions
    """
    try:
        service = get_jita_service()
        result = service.get_ai_errors(
            run_id,
            test_result_id=test_result_id,
            severity=severity,
            category=category,
            limit=limit,
            offset=offset
        )
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting AI errors for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/errors/stats")
async def get_ai_error_stats(
    run_id: str,
    test_result_id: Optional[str] = Query(None, description="Filter by specific test result")
):
    """
    Get aggregated AI error statistics.
    
    Returns counts by severity and category for dashboard display.
    """
    try:
        service = get_jita_service()
        result = service.get_ai_error_stats(run_id, test_result_id)
        
        return {
            "status": "success",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error getting AI error stats for run {run_id}: {e}")
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


@router.post("/runs/{run_id}/ai-analyze")
async def ai_analyze_test(
    run_id: str,
    test_result_id: str = Query(..., description="Test result ID to analyze")
):
    """
    Analyze logs for a specific test using AI.
    
    Fetches raw logs directly from JITA and analyzes them with AI to identify:
    - Real errors vs false positives
    - Root causes
    - Impact assessment
    - Suggested fixes
    
    Args:
        run_id: JITA run ID
        test_result_id: Specific test result to analyze
        
    Returns:
        AI-analyzed errors with classifications and suggestions
    """
    try:
        from ..services.jita_ai_analyzer import get_jita_ai_analyzer
        
        jita_service = get_jita_service()
        ai_analyzer = get_jita_ai_analyzer()
        
        # Get test result from JITA
        test_result = jita_service.get_test_result(test_result_id)
        if not test_result:
            raise HTTPException(status_code=404, detail=f"Test result {test_result_id} not found")
        
        # Run AI analysis
        result = await ai_analyzer.analyze_test(run_id, test_result)
        
        # Store results in database
        if result.get('errors'):
            jita_service._insert_ai_errors(run_id, [e.__dict__ if hasattr(e, '__dict__') else e for e in result['errors']])
        
        if result.get('log_urls'):
            jita_service._insert_log_urls(run_id, result['log_urls'])
        
        return {
            "status": "success",
            "run_id": run_id,
            "test_result_id": test_result_id,
            "errors_found": len(result.get('errors', [])),
            "log_urls_found": len(result.get('log_urls', [])),
            "summary": result.get('summary', {}),
            "errors": [e.__dict__ if hasattr(e, '__dict__') else e for e in result.get('errors', [])]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in AI analysis for run {run_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}/ai-status")
async def get_ai_analysis_status(run_id: str):
    """
    Check if AI analysis has been completed for a run.
    """
    try:
        service = get_jita_service()
        stats = service.get_ai_error_stats(run_id)
        
        return {
            "status": "success",
            "has_analysis": stats.get('total', 0) > 0,
            "error_count": stats.get('total', 0),
            "severity_counts": stats.get('by_severity', {}),
            "category_counts": stats.get('by_category', {})
        }
        
    except Exception as e:
        logger.error(f"Error checking AI status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{run_id}/reanalyze")
async def reanalyze_run(run_id: str):
    """
    Re-run AI analysis for a run, clearing previous results.
    """
    try:
        import re
        from ..tools.sql_tools import execute_sql
        
        # Clear existing AI errors
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        execute_sql(f"DELETE FROM jita_{safe_id}_ai_errors")
        execute_sql(f"DELETE FROM jita_{safe_id}_log_urls")
        
        # Trigger new analysis
        service = get_jita_service()
        result = await service.analyze_run_with_ai(run_id)
        
        return {
            "status": "success",
            "message": f"Re-analysis started for run {run_id}",
            **result
        }
        
    except Exception as e:
        logger.error(f"Error re-analyzing run {run_id}: {e}")
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
        summary_table = f"jita_{safe_id}_summary"
        timeline_table = f"jita_{safe_id}_timeline"
        ai_errors_table = f"jita_{safe_id}_ai_errors"
        log_urls_table = f"jita_{safe_id}_log_urls"
        
        # Drop tables (new schema)
        execute_sql(f"DROP TABLE IF EXISTS {summary_table}")
        execute_sql(f"DROP TABLE IF EXISTS {timeline_table}")
        execute_sql(f"DROP TABLE IF EXISTS {ai_errors_table}")
        execute_sql(f"DROP TABLE IF EXISTS {log_urls_table}")
        
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


@router.get("/runs/{run_id}/raw-log")
async def get_raw_log(
    run_id: str,
    url: str = Query(..., description="Log URL to fetch"),
    max_lines: int = Query(1000, description="Maximum number of lines to return")
):
    """
    Proxy endpoint to fetch raw log content from JITA log servers.
    
    Used by the UI to display raw log content when user wants to see full details.
    
    Args:
        run_id: JITA run ID (for authorization context)
        url: The log URL to fetch (can be JITA API URL or direct log server URL)
        max_lines: Maximum lines to return (default 1000)
        
    Returns:
        Raw log content
    """
    try:
        import requests
        from ..services.jita_ai_analyzer import get_jita_ai_analyzer
        
        analyzer = get_jita_ai_analyzer()
        
        # Resolve JITA URL if needed
        if 'jita.eng.nutanix.com' in url:
            resolved_url = analyzer._resolve_jita_log_url(url)
            if not resolved_url:
                raise HTTPException(status_code=404, detail="Could not resolve log URL")
            url = resolved_url
        
        # Fetch the log content
        content = analyzer._fetch_log_content(url, max_size=max_lines * 200)  # ~200 chars per line
        
        if not content:
            raise HTTPException(status_code=404, detail="Could not fetch log content")
        
        # Limit lines
        lines = content.split('\n')
        if len(lines) > max_lines:
            lines = lines[-max_lines:]  # Get last N lines
            content = '\n'.join(lines)
        
        return {
            "status": "success",
            "url": url,
            "lines": len(lines),
            "content": content
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching raw log: {e}")
        raise HTTPException(status_code=500, detail=str(e))
