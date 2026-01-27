"""
Log Analysis Tools for NOVA Backend

LLM tools for searching, analyzing, and summarizing log events.
"""
import time
from typing import Optional, List, Dict, Any

from .sql_tools import execute_sql


def search_logs(
    severity: str = None,
    pod: str = None,
    event_type: str = None,
    object_store_name: str = None,
    bucket_name: str = None,
    hours: int = 24,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Search log events with filters.
    
    Args:
        severity: Filter by severity (ERROR, WARN, FATAL, INFO)
        pod: Filter by pod/component (OC, MS, Atlas, Curator, Stargate)
        event_type: Filter by event type (REPLICATION_FAIL, IO_ERROR, etc.)
        object_store_name: Filter by object store name
        bucket_name: Filter by bucket name
        hours: Time range in hours (default 24)
        limit: Max results to return (default 50)
    
    Returns:
        Dict with log events and count
    """
    conditions = []
    
    # Time filter
    cutoff = int(time.time()) - (hours * 3600)
    conditions.append(f"timestamp > {cutoff}")
    
    if severity:
        conditions.append(f"severity = '{severity.upper()}'")
    
    if pod:
        conditions.append(f"pod = '{pod.upper()}'")
    
    if event_type:
        conditions.append(f"event_type = '{event_type.upper()}'")
    
    if object_store_name:
        conditions.append(f"object_store_name = '{object_store_name}'")
    
    if bucket_name:
        conditions.append(f"bucket_name = '{bucket_name}'")
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    sql = f"""
        SELECT log_id, timestamp, pod, node_name, severity, event_type, 
               message, object_store_name, bucket_name, raw_log_file, raw_line_number
        FROM logs 
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    
    result = execute_sql(sql)
    
    if result.get('status') == 'error':
        return {"status": "error", "error": result.get('error')}
    
    # Format rows
    logs = []
    for row in result.get('rows', []):
        if isinstance(row, dict):
            logs.append(row)
        else:
            logs.append({
                "log_id": row[0],
                "timestamp": row[1],
                "pod": row[2],
                "node_name": row[3],
                "severity": row[4],
                "event_type": row[5],
                "message": row[6],
                "object_store_name": row[7],
                "bucket_name": row[8],
                "raw_log_file": row[9],
                "raw_line_number": row[10]
            })
    
    return {
        "status": "success",
        "logs": logs,
        "count": len(logs),
        "filters": {
            "severity": severity,
            "pod": pod,
            "event_type": event_type,
            "hours": hours
        }
    }


def get_error_summary(hours: int = 24) -> Dict[str, Any]:
    """
    Get a summary of errors and warnings from the past N hours.
    
    Args:
        hours: Time range in hours (default 24)
    
    Returns:
        Dict with error/warning counts by severity, pod, event type
    """
    cutoff = int(time.time()) - (hours * 3600)
    
    # Count by severity
    severity_sql = f"""
        SELECT severity, COUNT(*) as count
        FROM logs
        WHERE timestamp > {cutoff}
        GROUP BY severity
        ORDER BY count DESC
    """
    
    severity_result = execute_sql(severity_sql)
    severity_counts = {}
    for row in severity_result.get('rows', []):
        if isinstance(row, dict):
            severity_counts[row.get('severity', 'UNKNOWN')] = row.get('count', 0)
        else:
            severity_counts[row[0]] = row[1]
    
    # Count by pod
    pod_sql = f"""
        SELECT pod, severity, COUNT(*) as count
        FROM logs
        WHERE timestamp > {cutoff} AND severity IN ('ERROR', 'FATAL', 'WARN')
        GROUP BY pod, severity
        ORDER BY count DESC
    """
    
    pod_result = execute_sql(pod_sql)
    pod_counts = {}
    for row in pod_result.get('rows', []):
        if isinstance(row, dict):
            pod = row.get('pod', 'UNKNOWN')
            severity = row.get('severity', 'UNKNOWN')
            count = row.get('count', 0)
        else:
            pod, severity, count = row[0], row[1], row[2]
        
        if pod not in pod_counts:
            pod_counts[pod] = {}
        pod_counts[pod][severity] = count
    
    # Count by event type
    event_sql = f"""
        SELECT event_type, COUNT(*) as count
        FROM logs
        WHERE timestamp > {cutoff} AND event_type IS NOT NULL
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 10
    """
    
    event_result = execute_sql(event_sql)
    event_counts = {}
    for row in event_result.get('rows', []):
        if isinstance(row, dict):
            event_counts[row.get('event_type', 'UNKNOWN')] = row.get('count', 0)
        else:
            event_counts[row[0]] = row[1]
    
    # Get recent critical events
    critical_sql = f"""
        SELECT log_id, timestamp, pod, severity, event_type, message
        FROM logs
        WHERE timestamp > {cutoff} AND severity = 'FATAL'
        ORDER BY timestamp DESC
        LIMIT 5
    """
    
    critical_result = execute_sql(critical_sql)
    critical_events = []
    for row in critical_result.get('rows', []):
        if isinstance(row, dict):
            critical_events.append(row)
        else:
            critical_events.append({
                "log_id": row[0],
                "timestamp": row[1],
                "pod": row[2],
                "severity": row[3],
                "event_type": row[4],
                "message": row[5]
            })
    
    return {
        "status": "success",
        "time_range_hours": hours,
        "severity_counts": severity_counts,
        "pod_breakdown": pod_counts,
        "top_event_types": event_counts,
        "recent_critical_events": critical_events,
        "total_errors": severity_counts.get('ERROR', 0),
        "total_warnings": severity_counts.get('WARN', 0),
        "total_fatals": severity_counts.get('FATAL', 0)
    }


def get_log_trends(days: int = 7) -> Dict[str, Any]:
    """
    Get log trends over the past N days.
    
    Args:
        days: Number of days to analyze (default 7)
    
    Returns:
        Dict with daily error/warning counts
    """
    cutoff = int(time.time()) - (days * 24 * 3600)
    
    # Daily counts by severity
    sql = f"""
        SELECT 
            date(timestamp, 'unixepoch') as log_date,
            severity,
            COUNT(*) as count
        FROM logs
        WHERE timestamp > {cutoff}
        GROUP BY log_date, severity
        ORDER BY log_date
    """
    
    result = execute_sql(sql)
    
    if result.get('status') == 'error':
        return {"status": "error", "error": result.get('error')}
    
    # Organize by date
    trends = {}
    for row in result.get('rows', []):
        if isinstance(row, dict):
            log_date = row.get('log_date')
            severity = row.get('severity')
            count = row.get('count', 0)
        else:
            log_date, severity, count = row[0], row[1], row[2]
        
        if log_date not in trends:
            trends[log_date] = {"ERROR": 0, "WARN": 0, "FATAL": 0, "INFO": 0}
        trends[log_date][severity] = count
    
    return {
        "status": "success",
        "days": days,
        "trends": trends
    }


def get_log_details(log_id: int) -> Dict[str, Any]:
    """
    Get detailed information about a specific log event.
    
    Args:
        log_id: The log event ID
    
    Returns:
        Dict with full log event details
    """
    sql = f"SELECT * FROM logs WHERE log_id = {log_id}"
    result = execute_sql(sql)
    
    if result.get('status') == 'error':
        return {"status": "error", "error": result.get('error')}
    
    if not result.get('rows'):
        return {"status": "error", "error": "Log event not found"}
    
    row = result['rows'][0]
    
    if isinstance(row, dict):
        return {"status": "success", "log": row}
    
    # Map columns
    columns = [
        'log_id', 'timestamp', 'pod', 'node_name', 'object_store_uuid',
        'object_store_name', 'bucket_name', 'severity', 'event_type',
        'message', 'stack_trace', 'raw_log_file', 'raw_file_path',
        'raw_line_number', 'upload_id', 'ingested_at'
    ]
    
    log_data = dict(zip(columns, row))
    return {"status": "success", "log": log_data}


def get_related_events(log_id: int, limit: int = 10) -> Dict[str, Any]:
    """
    Find events related to a specific log event (same pod, similar time, same event type).
    
    Args:
        log_id: The reference log event ID
        limit: Max related events to return
    
    Returns:
        Dict with related log events
    """
    # First get the reference event
    ref_result = get_log_details(log_id)
    if ref_result.get('status') == 'error':
        return ref_result
    
    ref_log = ref_result['log']
    ref_timestamp = ref_log.get('timestamp', 0)
    ref_pod = ref_log.get('pod', '')
    ref_event_type = ref_log.get('event_type', '')
    
    # Find events within 1 hour, same pod or same event type
    time_window = 3600  # 1 hour
    start_time = ref_timestamp - time_window
    end_time = ref_timestamp + time_window
    
    conditions = [
        f"log_id != {log_id}",
        f"timestamp BETWEEN {start_time} AND {end_time}",
        f"(pod = '{ref_pod}'"
    ]
    
    if ref_event_type:
        conditions[-1] += f" OR event_type = '{ref_event_type}'"
    
    conditions[-1] += ")"
    
    sql = f"""
        SELECT log_id, timestamp, pod, severity, event_type, message
        FROM logs
        WHERE {' AND '.join(conditions)}
        ORDER BY ABS(timestamp - {ref_timestamp})
        LIMIT {limit}
    """
    
    result = execute_sql(sql)
    
    if result.get('status') == 'error':
        return {"status": "error", "error": result.get('error')}
    
    related = []
    for row in result.get('rows', []):
        if isinstance(row, dict):
            related.append(row)
        else:
            related.append({
                "log_id": row[0],
                "timestamp": row[1],
                "pod": row[2],
                "severity": row[3],
                "event_type": row[4],
                "message": row[5]
            })
    
    return {
        "status": "success",
        "reference_log_id": log_id,
        "related_events": related,
        "count": len(related)
    }


def get_logs_by_upload(upload_id: int, limit: int = 100) -> Dict[str, Any]:
    """
    Get all log events from a specific upload.
    
    Args:
        upload_id: The log upload ID
        limit: Max events to return
    
    Returns:
        Dict with log events from the upload
    """
    sql = f"""
        SELECT log_id, timestamp, pod, node_name, severity, event_type, message
        FROM logs
        WHERE upload_id = {upload_id}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """
    
    result = execute_sql(sql)
    
    if result.get('status') == 'error':
        return {"status": "error", "error": result.get('error')}
    
    logs = []
    for row in result.get('rows', []):
        if isinstance(row, dict):
            logs.append(row)
        else:
            logs.append({
                "log_id": row[0],
                "timestamp": row[1],
                "pod": row[2],
                "node_name": row[3],
                "severity": row[4],
                "event_type": row[5],
                "message": row[6]
            })
    
    return {
        "status": "success",
        "upload_id": upload_id,
        "logs": logs,
        "count": len(logs)
    }
