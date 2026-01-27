# Log Analysis Guide

This document helps you analyze Nutanix Objects log events stored in the database.

## Log Database Schema

### logs table
Stores metadata for ERROR, WARN, and FATAL log events. Full log content is stored in S3 archives.

| Column | Description |
|--------|-------------|
| log_id | Unique identifier |
| timestamp | Unix epoch seconds when event occurred |
| pod | Component: OC, MS, Atlas, Curator, Stargate |
| node_name | Node identifier (e.g., node-01) |
| object_store_uuid | Object store UUID |
| object_store_name | Object store name |
| bucket_name | Related bucket name if applicable |
| severity | INFO, WARN, ERROR, FATAL |
| event_type | Classified event type |
| message | First 500 chars of log message |
| stack_trace | First 1000 chars of stack trace |
| raw_log_file | S3 URL to original archive |
| raw_file_path | Path within archive |
| raw_line_number | Line number in original file |

## Components (Pods)

| Pod | Full Name | Description |
|-----|-----------|-------------|
| OC | Object Controller | Handles S3 API requests, bucket operations |
| MS | Metadata Service | Manages object metadata, bucket listings |
| Atlas | Atlas | Distributed storage engine |
| Curator | Curator | Background maintenance, garbage collection |
| Stargate | Stargate | Data I/O, disk operations |

## Event Types

| Event Type | Severity | Description | Common Causes |
|------------|----------|-------------|---------------|
| REPLICATION_FAIL | ERROR | Replication between sites failed | Network issues, remote site down |
| IO_ERROR | ERROR | Disk read/write failure | Disk failure, storage full |
| AUTH_FAIL | WARN | Authentication/authorization failed | Invalid credentials, expired tokens |
| DISK_FULL | FATAL | No disk space available | Storage capacity reached |
| OOM | FATAL | Out of memory | Memory leak, insufficient resources |
| TIMEOUT | ERROR | Operation timed out | Slow network, overloaded service |
| CONNECTION_FAIL | ERROR | Connection to service failed | Service down, network partition |
| CORRUPTION | FATAL | Data corruption detected | Disk errors, software bugs |
| QUOTA_EXCEEDED | WARN | Storage quota exceeded | Bucket/user quota limit reached |
| SERVICE_DOWN | FATAL | Critical service unavailable | Service crash, resource exhaustion |

## Query Examples

### Find errors from last 24 hours
```sql
SELECT * FROM logs 
WHERE severity = 'ERROR' AND timestamp > (strftime('%s', 'now') - 86400)
ORDER BY timestamp DESC;
```

### Count errors by component
```sql
SELECT pod, COUNT(*) as error_count 
FROM logs 
WHERE severity IN ('ERROR', 'FATAL')
GROUP BY pod 
ORDER BY error_count DESC;
```

### Find replication failures
```sql
SELECT * FROM logs 
WHERE event_type = 'REPLICATION_FAIL'
ORDER BY timestamp DESC 
LIMIT 20;
```

### Get errors for a specific bucket
```sql
SELECT * FROM logs 
WHERE bucket_name = 'customer-uploads' AND severity = 'ERROR'
ORDER BY timestamp DESC;
```

## Troubleshooting Guidelines

### High Error Rate
1. Check which pod has the most errors: `SELECT pod, COUNT(*) FROM logs WHERE severity='ERROR' GROUP BY pod`
2. Look for patterns in event_type
3. Check if errors are concentrated on specific nodes

### FATAL Events
FATAL events indicate critical failures requiring immediate attention:
1. Check for DISK_FULL - may need storage expansion
2. Check for OOM - may need memory increase or service restart
3. Check for CORRUPTION - may need data recovery

### Replication Issues
1. Check network connectivity between sites
2. Verify remote object store is online
3. Look for timeout patterns

### Performance Issues
1. Check for high TIMEOUT event counts
2. Look for IO_ERROR patterns on specific nodes
3. Monitor error trends over time

## Available Tools

Use these tools to analyze logs:

| Tool | Description |
|------|-------------|
| search_logs | Search with filters: severity, pod, event_type, hours |
| get_error_summary | Get counts by severity, pod, event type |
| get_log_trends | View error trends over past N days |
| get_log_details | Get full details for a specific log_id |
| get_related_events | Find events related to a specific log |

## Response Format

When presenting log analysis:
1. Start with a summary of findings
2. Highlight critical (FATAL) events first
3. Group errors by event_type or pod
4. Provide actionable recommendations
5. Offer to drill down into specific areas
