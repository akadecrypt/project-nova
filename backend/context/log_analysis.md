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

### log_uploads table
Tracks log file uploads and processing status.

| Column | Description |
|--------|-------------|
| upload_id | Unique identifier |
| s3_key | S3 object key |
| s3_url | Full S3 URL |
| cluster_name | Source cluster name/IP |
| uploaded_at | Unix epoch when uploaded |
| processed_at | Unix epoch when processed |
| status | pending, processing, completed, failed |
| log_count | Number of log events extracted |
| period_start | Unix epoch start of log period |
| period_end | Unix epoch end of log period |

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

---

## Natural Language to SQL Examples

### Time-Based Queries

**User: "Show me errors from the last hour"**
```sql
SELECT log_id, datetime(timestamp, 'unixepoch') as time, pod, severity, event_type, message FROM logs WHERE severity = 'ERROR' AND timestamp > (strftime('%s', 'now') - 3600) ORDER BY timestamp DESC;
```

**User: "What happened in the last 24 hours?"**
```sql
SELECT severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) GROUP BY severity ORDER BY count DESC;
```

**User: "Show errors from yesterday"**
```sql
SELECT * FROM logs WHERE timestamp >= strftime('%s', 'now', '-1 day', 'start of day') AND timestamp < strftime('%s', 'now', 'start of day') AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC;
```

**User: "Show me last week's errors"**
```sql
SELECT date(timestamp, 'unixepoch') as day, COUNT(*) as errors FROM logs WHERE timestamp > (strftime('%s', 'now') - 604800) AND severity IN ('ERROR', 'FATAL') GROUP BY day ORDER BY day;
```

**User: "Any issues in the past 30 minutes?"**
```sql
SELECT * FROM logs WHERE timestamp > (strftime('%s', 'now') - 1800) AND severity IN ('ERROR', 'FATAL', 'WARN') ORDER BY timestamp DESC LIMIT 50;
```

### Component-Based Queries

**User: "Show OC errors"** or **"What's wrong with Object Controller?"**
```sql
SELECT log_id, datetime(timestamp, 'unixepoch') as time, severity, event_type, message FROM logs WHERE pod = 'OC' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 50;
```

**User: "Is Metadata Service having issues?"**
```sql
SELECT severity, event_type, COUNT(*) as count FROM logs WHERE pod = 'MS' AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY severity, event_type ORDER BY count DESC;
```

**User: "Show Atlas storage errors"**
```sql
SELECT * FROM logs WHERE pod = 'Atlas' AND event_type IN ('IO_ERROR', 'DISK_FULL', 'CORRUPTION') ORDER BY timestamp DESC LIMIT 30;
```

**User: "Which component has the most errors?"**
```sql
SELECT pod, COUNT(*) as error_count, COUNT(CASE WHEN severity = 'FATAL' THEN 1 END) as fatal_count FROM logs WHERE severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY pod ORDER BY error_count DESC;
```

**User: "Compare error rates across components"**
```sql
SELECT pod, severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) GROUP BY pod, severity ORDER BY pod, count DESC;
```

### Severity-Based Queries

**User: "Show all FATAL errors"** or **"Critical issues?"**
```sql
SELECT log_id, datetime(timestamp, 'unixepoch') as time, pod, event_type, node_name, message FROM logs WHERE severity = 'FATAL' ORDER BY timestamp DESC LIMIT 50;
```

**User: "Any critical issues today?"**
```sql
SELECT * FROM logs WHERE severity = 'FATAL' AND timestamp > strftime('%s', 'now', 'start of day') ORDER BY timestamp DESC;
```

**User: "Show warnings that might become errors"**
```sql
SELECT event_type, COUNT(*) as warn_count FROM logs WHERE severity = 'WARN' AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY event_type HAVING warn_count > 5 ORDER BY warn_count DESC;
```

**User: "Error summary"** or **"Give me an overview"**
```sql
SELECT severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) GROUP BY severity;
```

### Event Type Queries

**User: "Show replication failures"**
```sql
SELECT log_id, datetime(timestamp, 'unixepoch') as time, pod, object_store_name, bucket_name, message FROM logs WHERE event_type = 'REPLICATION_FAIL' ORDER BY timestamp DESC LIMIT 30;
```

**User: "Any authentication failures?"**
```sql
SELECT datetime(timestamp, 'unixepoch') as time, bucket_name, message FROM logs WHERE event_type = 'AUTH_FAIL' ORDER BY timestamp DESC LIMIT 50;
```

**User: "Show disk issues"** or **"Storage problems?"**
```sql
SELECT * FROM logs WHERE event_type IN ('DISK_FULL', 'IO_ERROR') ORDER BY timestamp DESC LIMIT 30;
```

**User: "Connection problems?"**
```sql
SELECT pod, node_name, COUNT(*) as failures FROM logs WHERE event_type IN ('CONNECTION_FAIL', 'TIMEOUT') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY pod, node_name ORDER BY failures DESC;
```

**User: "Memory issues?"**
```sql
SELECT * FROM logs WHERE event_type = 'OOM' ORDER BY timestamp DESC LIMIT 20;
```

**User: "What types of errors are happening?"**
```sql
SELECT event_type, severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) GROUP BY event_type, severity ORDER BY count DESC;
```

### Bucket-Specific Queries

**User: "Errors for bucket X"** or **"Issues with customer-data bucket?"**
```sql
SELECT datetime(timestamp, 'unixepoch') as time, pod, severity, event_type, message FROM logs WHERE bucket_name = 'customer-data' ORDER BY timestamp DESC LIMIT 50;
```

**User: "Which buckets have the most errors?"**
```sql
SELECT bucket_name, COUNT(*) as error_count FROM logs WHERE bucket_name IS NOT NULL AND severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY bucket_name ORDER BY error_count DESC LIMIT 10;
```

**User: "Show bucket replication status"**
```sql
SELECT bucket_name, COUNT(*) as failures FROM logs WHERE event_type = 'REPLICATION_FAIL' AND bucket_name IS NOT NULL GROUP BY bucket_name ORDER BY failures DESC;
```

### Object Store Queries

**User: "Errors for object store prod-objects"**
```sql
SELECT datetime(timestamp, 'unixepoch') as time, pod, severity, event_type, message FROM logs WHERE object_store_name = 'prod-objects' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 50;
```

**User: "Compare object stores"**
```sql
SELECT object_store_name, severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) GROUP BY object_store_name, severity ORDER BY object_store_name, count DESC;
```

### Node-Specific Queries

**User: "Errors on node-01"**
```sql
SELECT datetime(timestamp, 'unixepoch') as time, pod, severity, event_type, message FROM logs WHERE node_name = 'node-01' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC;
```

**User: "Which nodes have issues?"**
```sql
SELECT node_name, COUNT(*) as error_count FROM logs WHERE severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY node_name ORDER BY error_count DESC;
```

### Trend Analysis Queries

**User: "Show error trends"** or **"Are errors increasing?"**
```sql
SELECT date(timestamp, 'unixepoch') as day, COUNT(*) as errors, COUNT(CASE WHEN severity = 'FATAL' THEN 1 END) as fatal FROM logs WHERE timestamp > (strftime('%s', 'now') - 604800) GROUP BY day ORDER BY day;
```

**User: "Hourly error breakdown"**
```sql
SELECT strftime('%Y-%m-%d %H:00', timestamp, 'unixepoch') as hour, COUNT(*) as errors FROM logs WHERE timestamp > (strftime('%s', 'now') - 86400) AND severity IN ('ERROR', 'FATAL') GROUP BY hour ORDER BY hour;
```

**User: "Peak error times?"**
```sql
SELECT strftime('%H', timestamp, 'unixepoch') as hour_of_day, COUNT(*) as errors FROM logs WHERE severity IN ('ERROR', 'FATAL') GROUP BY hour_of_day ORDER BY errors DESC LIMIT 5;
```

### Correlation Queries

**User: "Find related errors"**
```sql
SELECT l2.log_id, datetime(l2.timestamp, 'unixepoch') as time, l2.pod, l2.event_type, l2.message FROM logs l1 JOIN logs l2 ON l2.timestamp BETWEEN l1.timestamp - 300 AND l1.timestamp + 300 AND l2.log_id != l1.log_id WHERE l1.log_id = ? ORDER BY l2.timestamp;
```

**User: "Errors happening together"**
```sql
SELECT a.event_type as event1, b.event_type as event2, COUNT(*) as occurrences FROM logs a JOIN logs b ON b.timestamp BETWEEN a.timestamp - 60 AND a.timestamp + 60 AND a.log_id < b.log_id WHERE a.severity IN ('ERROR', 'FATAL') AND b.severity IN ('ERROR', 'FATAL') GROUP BY event1, event2 HAVING occurrences > 3 ORDER BY occurrences DESC;
```

### Upload and Processing Queries

**User: "Show recent log uploads"**
```sql
SELECT upload_id, cluster_name, datetime(uploaded_at, 'unixepoch') as uploaded, status, log_count FROM log_uploads ORDER BY uploaded_at DESC LIMIT 20;
```

**User: "Any failed uploads?"**
```sql
SELECT * FROM log_uploads WHERE status = 'failed' ORDER BY uploaded_at DESC;
```

**User: "How many logs processed today?"**
```sql
SELECT SUM(log_count) as total_logs FROM log_uploads WHERE processed_at > strftime('%s', 'now', 'start of day') AND status = 'completed';
```

---

## Common Investigation Workflows

### Workflow 1: High Error Rate Investigation

When users report "too many errors" or "system seems unhealthy":

1. **Get overall picture:**
```sql
SELECT severity, COUNT(*) as count FROM logs WHERE timestamp > (strftime('%s', 'now') - 3600) GROUP BY severity;
```

2. **Identify problem component:**
```sql
SELECT pod, COUNT(*) as errors FROM logs WHERE severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 3600) GROUP BY pod ORDER BY errors DESC;
```

3. **Find root cause event types:**
```sql
SELECT event_type, COUNT(*) as count, MIN(datetime(timestamp, 'unixepoch')) as first_seen FROM logs WHERE pod = '[problem_pod]' AND severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 3600) GROUP BY event_type ORDER BY count DESC;
```

4. **Check specific error messages:**
```sql
SELECT message, COUNT(*) as occurrences FROM logs WHERE pod = '[problem_pod]' AND event_type = '[problem_type]' GROUP BY message ORDER BY occurrences DESC LIMIT 10;
```

### Workflow 2: FATAL Event Response

When FATAL events occur, investigate immediately:

1. **Find recent FATAL events:**
```sql
SELECT log_id, datetime(timestamp, 'unixepoch') as time, pod, event_type, node_name, message FROM logs WHERE severity = 'FATAL' AND timestamp > (strftime('%s', 'now') - 3600) ORDER BY timestamp DESC;
```

2. **Check for cascading failures:**
```sql
SELECT pod, event_type, COUNT(*) as count FROM logs WHERE timestamp BETWEEN [fatal_timestamp - 300] AND [fatal_timestamp + 300] GROUP BY pod, event_type ORDER BY count DESC;
```

3. **Get full details with stack trace:**
```sql
SELECT * FROM logs WHERE log_id = [fatal_log_id];
```

### Workflow 3: Replication Issue Diagnosis

For replication failures:

1. **Count recent failures:**
```sql
SELECT COUNT(*) as failures FROM logs WHERE event_type = 'REPLICATION_FAIL' AND timestamp > (strftime('%s', 'now') - 86400);
```

2. **Find affected buckets:**
```sql
SELECT bucket_name, object_store_name, COUNT(*) as failures FROM logs WHERE event_type = 'REPLICATION_FAIL' GROUP BY bucket_name, object_store_name ORDER BY failures DESC;
```

3. **Check for network issues:**
```sql
SELECT event_type, COUNT(*) FROM logs WHERE event_type IN ('CONNECTION_FAIL', 'TIMEOUT') AND timestamp > (strftime('%s', 'now') - 3600) GROUP BY event_type;
```

### Workflow 4: Storage Capacity Investigation

For disk/storage issues:

1. **Check disk-related events:**
```sql
SELECT node_name, event_type, COUNT(*) as count FROM logs WHERE event_type IN ('DISK_FULL', 'IO_ERROR', 'QUOTA_EXCEEDED') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY node_name, event_type ORDER BY count DESC;
```

2. **Identify affected nodes:**
```sql
SELECT DISTINCT node_name, pod FROM logs WHERE event_type = 'DISK_FULL' ORDER BY timestamp DESC LIMIT 10;
```

### Workflow 5: Performance Degradation Analysis

For slow performance reports:

1. **Check timeout patterns:**
```sql
SELECT pod, COUNT(*) as timeouts FROM logs WHERE event_type = 'TIMEOUT' AND timestamp > (strftime('%s', 'now') - 3600) GROUP BY pod ORDER BY timeouts DESC;
```

2. **Look at hourly trends:**
```sql
SELECT strftime('%H:00', timestamp, 'unixepoch') as hour, COUNT(*) as errors FROM logs WHERE event_type IN ('TIMEOUT', 'CONNECTION_FAIL') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY hour ORDER BY hour;
```

3. **Check for resource exhaustion:**
```sql
SELECT event_type, COUNT(*) FROM logs WHERE event_type IN ('OOM', 'DISK_FULL', 'QUOTA_EXCEEDED') AND timestamp > (strftime('%s', 'now') - 86400) GROUP BY event_type;
```

---

## Time Range Reference

Use these epoch calculations for common time ranges:

| Time Range | Epoch Calculation |
|------------|-------------------|
| Last 15 minutes | `strftime('%s', 'now') - 900` |
| Last 30 minutes | `strftime('%s', 'now') - 1800` |
| Last hour | `strftime('%s', 'now') - 3600` |
| Last 6 hours | `strftime('%s', 'now') - 21600` |
| Last 12 hours | `strftime('%s', 'now') - 43200` |
| Last 24 hours | `strftime('%s', 'now') - 86400` |
| Last 7 days | `strftime('%s', 'now') - 604800` |
| Last 30 days | `strftime('%s', 'now') - 2592000` |
| Today (start) | `strftime('%s', 'now', 'start of day')` |
| Yesterday | `strftime('%s', 'now', '-1 day', 'start of day')` |

---

## Available Tools

Use these tools to analyze logs:

| Tool | Description | Parameters |
|------|-------------|------------|
| search_logs | Search with filters | severity, pod, event_type, object_store_name, bucket_name, hours, limit |
| get_error_summary | Get counts by severity, pod, event type | hours (default: 24) |
| get_log_trends | View error trends over past N days | days (default: 7) |
| get_log_details | Get full details for a specific log | log_id (required) |
| get_related_events | Find events related to a specific log | log_id (required), limit |

### Tool Usage Examples

**Search for OC errors:**
- Tool: `search_logs`
- Parameters: `{"pod": "OC", "severity": "ERROR", "hours": 24}`

**Get summary of last 6 hours:**
- Tool: `get_error_summary`
- Parameters: `{"hours": 6}`

**Check weekly trends:**
- Tool: `get_log_trends`
- Parameters: `{"days": 7}`

---

## Response Format Guidelines

When presenting log analysis:

1. **Start with summary** - Total counts, severity breakdown
2. **Highlight FATAL first** - Critical issues need immediate attention
3. **Group by relevance** - By event_type, pod, or time
4. **Show trends** - Is it getting better or worse?
5. **Provide context** - What does this error mean?
6. **Give recommendations** - Actionable next steps
7. **Offer drill-down** - Ask if user wants more details

### Example Response Format:

```
## Log Analysis Summary (Last 24 Hours)

**Overview:**
- Total Events: 150
- Errors: 45 | Warnings: 90 | Fatal: 15

**Critical Issues (Immediate Attention):**
1. DISK_FULL on node-03 (5 events) - Storage at capacity
2. OOM in Atlas (3 events) - Memory exhaustion

**Top Error Categories:**
- REPLICATION_FAIL: 20 events (OC component)
- TIMEOUT: 15 events (MS component)
- IO_ERROR: 10 events (Atlas component)

**Recommendations:**
1. Check disk space on node-03 immediately
2. Restart Atlas service or increase memory allocation
3. Investigate network connectivity for replication

Would you like details on any specific issue?
```
