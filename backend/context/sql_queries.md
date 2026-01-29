# SQL Query Reference for NOVA

Use the `execute_sql` tool to run these queries. Always use exact column names shown below.

## Database Schema

### Tables:
- `bucket` - Bucket configurations
- `bucket_stats` - Bucket size/object statistics  
- `object_store` - Object store clusters
- `logs` - Error/warning log entries
- `log_uploads` - Log collection records
- `alerts` - Active system alerts
- `bucket_replication` - Replication status

---

## LOGS QUERIES

### Get recent error logs (last 24 hours)
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, severity, event_type, message 
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 86400)
ORDER BY timestamp DESC 
LIMIT 50
```

### Get FATAL logs only
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, event_type, message, stack_trace
FROM logs 
WHERE severity = 'FATAL'
ORDER BY timestamp DESC
LIMIT 20
```

### Get ERROR logs only
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, event_type, message
FROM logs 
WHERE severity = 'ERROR'
ORDER BY timestamp DESC
LIMIT 50
```

### Count logs by severity
```sql
SELECT severity, COUNT(*) as count 
FROM logs 
GROUP BY severity 
ORDER BY count DESC
```

### Count logs by event type
```sql
SELECT event_type, COUNT(*) as count 
FROM logs 
WHERE event_type IS NOT NULL
GROUP BY event_type 
ORDER BY count DESC
LIMIT 20
```

### Get logs for specific object store
```sql
SELECT log_id, timestamp, pod, node_name, bucket_name, severity, event_type, message
FROM logs 
WHERE object_store_name = 'oss1'
ORDER BY timestamp DESC
LIMIT 50
```

### Get logs for specific bucket
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE bucket_name = 'api-request-logs'
ORDER BY timestamp DESC
LIMIT 50
```

### Get logs by component/pod (OC, MS, Atlas, Curator)
```sql
SELECT log_id, timestamp, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE pod = 'OC'
ORDER BY timestamp DESC
LIMIT 50
```

### Get crash logs (SIGSEGV, SIGABRT, etc.)
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, message, stack_trace
FROM logs 
WHERE event_type = 'CRASH' OR message LIKE '%SIGSEGV%' OR message LIKE '%SIGABRT%'
ORDER BY timestamp DESC
LIMIT 20
```

### Get connection errors
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, message
FROM logs 
WHERE event_type = 'CONNECTION_ERROR' OR message LIKE '%connection%fail%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get replication failures
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, message
FROM logs 
WHERE event_type = 'REPLICATION_FAIL'
ORDER BY timestamp DESC
LIMIT 30
```

### Get disk/storage errors
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, message
FROM logs 
WHERE event_type = 'DISK_ERROR' OR message LIKE '%disk%' OR message LIKE '%storage%' OR message LIKE '%I/O%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get out of memory errors
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, message
FROM logs 
WHERE event_type = 'OUT_OF_MEMORY' OR message LIKE '%OOM%' OR message LIKE '%out of memory%'
ORDER BY timestamp DESC
LIMIT 20
```

### Count errors by node
```sql
SELECT node_name, COUNT(*) as error_count 
FROM logs 
WHERE severity IN ('ERROR', 'FATAL')
GROUP BY node_name 
ORDER BY error_count DESC
```

### Count errors by object store
```sql
SELECT object_store_name, severity, COUNT(*) as count 
FROM logs 
WHERE object_store_name IS NOT NULL
GROUP BY object_store_name, severity 
ORDER BY object_store_name, count DESC
```

### Get log summary for last N hours (replace 24 with desired hours)
```sql
SELECT 
    severity,
    COUNT(*) as count,
    COUNT(DISTINCT node_name) as affected_nodes,
    COUNT(DISTINCT object_store_name) as affected_stores
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 86400)
GROUP BY severity
```

---

## BUCKET QUERIES

### List all buckets
```sql
SELECT bucket_id, bucket_name, bucket_owner, versioning, worm, replication_status, tiering_status, created_at
FROM bucket
ORDER BY bucket_name
```

### Get bucket details by name
```sql
SELECT * FROM bucket WHERE bucket_name = 'api-request-logs'
```

### List buckets with replication enabled
```sql
SELECT bucket_id, bucket_name, bucket_owner, replication_status
FROM bucket
WHERE replication_status = 'ENABLED'
```

### List buckets with WORM enabled
```sql
SELECT bucket_id, bucket_name, bucket_owner, worm
FROM bucket
WHERE worm = 1
```

### List buckets with versioning enabled
```sql
SELECT bucket_id, bucket_name, bucket_owner, versioning
FROM bucket
WHERE versioning = 1
```

---

## BUCKET STATS QUERIES

### Get bucket sizes (latest stats)
```sql
SELECT b.bucket_name, bs.object_count, bs.size_gb, bs.timestamp
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
ORDER BY bs.size_gb DESC
```

### Get total storage used
```sql
SELECT 
    SUM(size_gb) as total_size_gb,
    SUM(object_count) as total_objects
FROM bucket_stats
```

### Get largest buckets
```sql
SELECT b.bucket_name, bs.size_gb, bs.object_count
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
ORDER BY bs.size_gb DESC
LIMIT 10
```

### Get buckets with most objects
```sql
SELECT b.bucket_name, bs.object_count, bs.size_gb
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
ORDER BY bs.object_count DESC
LIMIT 10
```

---

## OBJECT STORE QUERIES

### List all object stores
```sql
SELECT object_store_uuid, store_name, pc_address, state, node_count, os_version, location
FROM object_store
ORDER BY store_name
```

### Get object store by name
```sql
SELECT * FROM object_store WHERE store_name LIKE '%Production%'
```

### Get active object stores
```sql
SELECT object_store_uuid, store_name, node_count, os_version, location
FROM object_store
WHERE state = 'ACTIVE'
```

---

## ALERTS QUERIES

### Get all active alerts
```sql
SELECT alert_id, alert_type, severity, entity_type, entity_id, source_store_uuid, bucket_name, message, first_detected_at
FROM alerts
WHERE is_active = 1
ORDER BY first_detected_at DESC
```

### Get critical alerts
```sql
SELECT alert_id, entity_type, entity_id, message, first_detected_at
FROM alerts
WHERE severity = 'CRITICAL' AND is_active = 1
ORDER BY first_detected_at DESC
```

### Get alerts by type
```sql
SELECT alert_type, severity, COUNT(*) as count
FROM alerts
WHERE is_active = 1
GROUP BY alert_type, severity
ORDER BY count DESC
```

### Get alerts for specific bucket
```sql
SELECT alert_id, alert_type, severity, message, first_detected_at
FROM alerts
WHERE bucket_name = 'api-request-logs'
ORDER BY first_detected_at DESC
```

---

## REPLICATION QUERIES

### Get all replication status
```sql
SELECT 
    br.replication_id,
    b.bucket_name as source_bucket,
    br.target_bucket_name,
    br.replication_status,
    br.replicated_objects,
    br.pending_objects,
    br.replicated_size_gb,
    br.pending_size_gb,
    br.last_sync_time
FROM bucket_replication br
JOIN bucket b ON br.source_bucket_id = b.bucket_id
ORDER BY br.pending_objects DESC
```

### Get buckets with pending replication
```sql
SELECT 
    b.bucket_name,
    br.target_bucket_name,
    br.pending_objects,
    br.pending_size_gb,
    br.last_sync_time
FROM bucket_replication br
JOIN bucket b ON br.source_bucket_id = b.bucket_id
WHERE br.pending_objects > 0
ORDER BY br.pending_objects DESC
```

### Get replication lag
```sql
SELECT 
    b.bucket_name,
    br.pending_objects,
    br.pending_size_gb,
    br.last_sync_time,
    br.last_error
FROM bucket_replication br
JOIN bucket b ON br.source_bucket_id = b.bucket_id
WHERE br.replication_status != 'COMPLETED'
```

---

## LOG UPLOADS QUERIES

### Get recent log uploads
```sql
SELECT upload_id, s3_key, cluster_name, status, errors_found, warnings_found, uploaded_at, processed_at
FROM log_uploads
ORDER BY uploaded_at DESC
LIMIT 20
```

### Get failed log uploads
```sql
SELECT upload_id, s3_key, cluster_name, status, error_message, uploaded_at
FROM log_uploads
WHERE status = 'FAILED'
ORDER BY uploaded_at DESC
```

### Get log collection summary by cluster
```sql
SELECT 
    cluster_name,
    COUNT(*) as uploads,
    SUM(errors_found) as total_errors,
    SUM(warnings_found) as total_warnings,
    MAX(uploaded_at) as last_upload
FROM log_uploads
WHERE status = 'COMPLETED'
GROUP BY cluster_name
```

---

## COMMON USER QUESTIONS → QUERIES

| Question | Query |
|----------|-------|
| "Show me all errors" | `SELECT * FROM logs WHERE severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 50` |
| "Any crashes today?" | `SELECT * FROM logs WHERE event_type = 'CRASH' AND timestamp > (strftime('%s', 'now') - 86400) ORDER BY timestamp DESC` |
| "Show fatal errors" | `SELECT * FROM logs WHERE severity = 'FATAL' ORDER BY timestamp DESC LIMIT 20` |
| "List all buckets" | `SELECT bucket_name, bucket_owner, replication_status FROM bucket ORDER BY bucket_name` |
| "Biggest buckets" | `SELECT b.bucket_name, bs.size_gb, bs.object_count FROM bucket_stats bs JOIN bucket b ON bs.bucket_id = b.bucket_id ORDER BY bs.size_gb DESC LIMIT 10` |
| "Any alerts?" | `SELECT * FROM alerts WHERE is_active = 1 ORDER BY first_detected_at DESC` |
| "Errors on oss1" | `SELECT * FROM logs WHERE object_store_name = 'oss1' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 50` |
| "Replication status" | `SELECT b.bucket_name, br.replication_status, br.pending_objects FROM bucket_replication br JOIN bucket b ON br.source_bucket_id = b.bucket_id` |
| "Storage used" | `SELECT SUM(size_gb) as total_gb, SUM(object_count) as total_objects FROM bucket_stats` |
| "Connection errors" | `SELECT * FROM logs WHERE event_type = 'CONNECTION_ERROR' ORDER BY timestamp DESC LIMIT 30` |
| "Disk errors" | `SELECT * FROM logs WHERE event_type = 'DISK_ERROR' ORDER BY timestamp DESC LIMIT 30` |
| "Errors by type" | `SELECT event_type, COUNT(*) as count FROM logs GROUP BY event_type ORDER BY count DESC` |
| "Object stores" | `SELECT store_name, state, node_count, os_version FROM object_store` |

---

## IMPORTANT NOTES

1. **Timestamps**: The `logs` table uses Unix epoch timestamps (integers). Use `strftime('%s', 'now')` for current time.
2. **Time filtering**: For last N hours, use: `timestamp > (strftime('%s', 'now') - N*3600)`
3. **Severity values**: 'FATAL', 'ERROR', 'WARN', 'INFO'
4. **Pod values**: 'OC' (Object Controller), 'MS' (Metadata Service), 'Atlas', 'Curator', 'Stargate'
5. **Object stores**: Check `object_store_name` in logs, common values are 'oss1', 'oss3'
6. **Always use LIMIT**: Add LIMIT clause to prevent returning too many rows
