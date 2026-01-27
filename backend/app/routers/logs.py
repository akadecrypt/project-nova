"""
Logs Router for NOVA Backend

API endpoints for log analysis and management.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from ..services.log_processor import get_log_processor
from ..tools.log_tools import (
    search_logs, get_error_summary, get_log_trends,
    get_log_details, get_related_events, get_logs_by_upload
)

router = APIRouter(prefix="/api/logs", tags=["logs"])


# Request/Response models
class LogUploadRequest(BaseModel):
    s3_key: str
    s3_url: Optional[str] = None
    cluster_name: Optional[str] = None
    period_start: int
    period_end: int
    object_store_name: Optional[str] = None


class LogSearchRequest(BaseModel):
    severity: Optional[str] = None
    pod: Optional[str] = None
    event_type: Optional[str] = None
    object_store_name: Optional[str] = None
    bucket_name: Optional[str] = None
    hours: int = 24
    limit: int = 50


# Endpoints
@router.post("/upload")
async def upload_logs(request: LogUploadRequest, background_tasks: BackgroundTasks):
    """
    Register a new log upload and trigger processing.
    
    Called by the logbay_upload.py script after uploading logs to S3.
    """
    processor = get_log_processor()
    
    # Generate S3 URL if not provided
    s3_url = request.s3_url
    if not s3_url:
        config = processor.config
        bucket = config.get('log_analysis', {}).get('logs_bucket', 'nova-logs')
        endpoint = config.get('s3', {}).get('endpoint', '')
        s3_url = f"{endpoint}/{bucket}/{request.s3_key}"
    
    # Create upload record
    upload_id = processor.create_upload_record(
        s3_key=request.s3_key,
        s3_url=s3_url,
        cluster_name=request.cluster_name or "unknown",
        period_start=request.period_start,
        period_end=request.period_end
    )
    
    if not upload_id:
        raise HTTPException(status_code=500, detail="Failed to create upload record")
    
    # Trigger processing in background
    background_tasks.add_task(
        processor.process_upload,
        upload_id=upload_id,
        s3_key=request.s3_key,
        s3_url=s3_url,
        object_store_name=request.object_store_name
    )
    
    return {
        "success": True,
        "upload_id": upload_id,
        "message": "Log upload registered, processing started"
    }


@router.get("/uploads")
async def list_uploads(limit: int = 20):
    """List recent log uploads"""
    processor = get_log_processor()
    uploads = processor.list_uploads(limit)
    
    return {
        "uploads": uploads,
        "count": len(uploads)
    }


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: int):
    """Get status of a specific log upload"""
    processor = get_log_processor()
    upload = processor.get_upload_status(upload_id)
    
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    
    return upload


@router.get("/uploads/{upload_id}/logs")
async def get_upload_logs(upload_id: int, limit: int = 100):
    """Get log events from a specific upload"""
    result = get_logs_by_upload(upload_id, limit)
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/search")
async def search(
    severity: Optional[str] = None,
    pod: Optional[str] = None,
    event_type: Optional[str] = None,
    object_store_name: Optional[str] = None,
    bucket_name: Optional[str] = None,
    hours: int = 24,
    limit: int = 50
):
    """
    Search log events with filters.
    
    Query parameters:
    - severity: ERROR, WARN, FATAL, INFO
    - pod: OC, MS, Atlas, Curator, Stargate
    - event_type: REPLICATION_FAIL, IO_ERROR, etc.
    - object_store_name: Filter by object store
    - bucket_name: Filter by bucket
    - hours: Time range (default 24)
    - limit: Max results (default 50)
    """
    result = search_logs(
        severity=severity,
        pod=pod,
        event_type=event_type,
        object_store_name=object_store_name,
        bucket_name=bucket_name,
        hours=hours,
        limit=limit
    )
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.post("/search")
async def search_post(request: LogSearchRequest):
    """Search log events (POST version for complex queries)"""
    result = search_logs(
        severity=request.severity,
        pod=request.pod,
        event_type=request.event_type,
        object_store_name=request.object_store_name,
        bucket_name=request.bucket_name,
        hours=request.hours,
        limit=request.limit
    )
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/summary")
async def summary(hours: int = 24):
    """
    Get error/warning summary for the past N hours.
    
    Returns counts by severity, pod, and event type.
    """
    result = get_error_summary(hours)
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/trends")
async def trends(days: int = 7):
    """
    Get log trends over the past N days.
    
    Returns daily error/warning counts.
    """
    result = get_log_trends(days)
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/{log_id}")
async def get_log(log_id: int):
    """Get details for a specific log event"""
    result = get_log_details(log_id)
    
    if result.get('status') == 'error':
        if 'not found' in result.get('error', '').lower():
            raise HTTPException(status_code=404, detail="Log event not found")
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/{log_id}/related")
async def get_related(log_id: int, limit: int = 10):
    """Get events related to a specific log event"""
    result = get_related_events(log_id, limit)
    
    if result.get('status') == 'error':
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return result


@router.get("/stats/overview")
async def stats_overview():
    """Get overall log statistics"""
    from ..tools.sql_tools import execute_sql
    
    # Total counts
    total_result = execute_sql("SELECT COUNT(*) FROM logs")
    total_logs = 0
    if total_result.get('rows'):
        row = total_result['rows'][0]
        total_logs = list(row.values())[0] if isinstance(row, dict) else row[0]
    
    # Uploads count
    uploads_result = execute_sql("SELECT COUNT(*) FROM log_uploads")
    total_uploads = 0
    if uploads_result.get('rows'):
        row = uploads_result['rows'][0]
        total_uploads = list(row.values())[0] if isinstance(row, dict) else row[0]
    
    # Time range
    range_result = execute_sql("SELECT MIN(timestamp), MAX(timestamp) FROM logs")
    min_time, max_time = None, None
    if range_result.get('rows'):
        row = range_result['rows'][0]
        if isinstance(row, dict):
            values = list(row.values())
            min_time, max_time = values[0], values[1]
        else:
            min_time, max_time = row[0], row[1]
    
    # Recent activity (last 24h)
    summary = get_error_summary(24)
    
    return {
        "total_log_events": total_logs,
        "total_uploads": total_uploads,
        "time_range": {
            "earliest": min_time,
            "latest": max_time
        },
        "last_24h": {
            "errors": summary.get('total_errors', 0),
            "warnings": summary.get('total_warnings', 0),
            "fatals": summary.get('total_fatals', 0)
        }
    }
