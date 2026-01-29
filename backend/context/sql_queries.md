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

## ADVANCED LOG ANALYSIS QUERIES

### Get error trends by hour (last 24 hours)
```sql
SELECT 
    (timestamp / 3600) * 3600 as hour_bucket,
    COUNT(*) as error_count,
    COUNT(DISTINCT node_name) as affected_nodes
FROM logs 
WHERE severity IN ('ERROR', 'FATAL') 
AND timestamp > (strftime('%s', 'now') - 86400)
GROUP BY hour_bucket
ORDER BY hour_bucket DESC
```

### Get most problematic nodes
```sql
SELECT 
    node_name,
    object_store_name,
    COUNT(*) as total_errors,
    SUM(CASE WHEN severity = 'FATAL' THEN 1 ELSE 0 END) as fatal_count,
    SUM(CASE WHEN severity = 'ERROR' THEN 1 ELSE 0 END) as error_count
FROM logs 
WHERE severity IN ('ERROR', 'FATAL')
GROUP BY node_name, object_store_name
ORDER BY total_errors DESC
LIMIT 15
```

### Get most common error messages
```sql
SELECT 
    SUBSTR(message, 1, 100) as error_pattern,
    COUNT(*) as occurrences,
    COUNT(DISTINCT node_name) as affected_nodes
FROM logs 
WHERE severity IN ('ERROR', 'FATAL')
GROUP BY SUBSTR(message, 1, 100)
ORDER BY occurrences DESC
LIMIT 20
```

### Get errors with stack traces
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, message, stack_trace
FROM logs 
WHERE stack_trace IS NOT NULL AND stack_trace != ''
ORDER BY timestamp DESC
LIMIT 20
```

### Get authentication/authorization errors
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, bucket_name, message
FROM logs 
WHERE event_type IN ('AUTH_FAIL', 'IAM_ERROR') 
   OR message LIKE '%auth%fail%' 
   OR message LIKE '%permission%denied%'
   OR message LIKE '%unauthorized%'
   OR message LIKE '%access%denied%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get timeout errors
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, message
FROM logs 
WHERE event_type = 'TIMEOUT' 
   OR message LIKE '%timeout%' 
   OR message LIKE '%timed out%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get SSL/TLS errors
```sql
SELECT log_id, timestamp, pod, node_name, message
FROM logs 
WHERE event_type = 'SSL_ERROR' 
   OR message LIKE '%ssl%error%' 
   OR message LIKE '%certificate%'
   OR message LIKE '%tls%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get S3 operation errors
```sql
SELECT log_id, timestamp, pod, node_name, bucket_name, message
FROM logs 
WHERE event_type = 'S3_OP_ERROR' 
   OR message LIKE '%PUT%fail%' 
   OR message LIKE '%GET%fail%'
   OR message LIKE '%DELETE%fail%'
   OR message LIKE '%multipart%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get metadata service errors
```sql
SELECT log_id, timestamp, node_name, object_store_name, event_type, message
FROM logs 
WHERE pod = 'MS'
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 50
```

### Get object controller errors
```sql
SELECT log_id, timestamp, node_name, object_store_name, bucket_name, event_type, message
FROM logs 
WHERE pod = 'OC'
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 50
```

### Get Raft/consensus errors
```sql
SELECT log_id, timestamp, pod, node_name, message
FROM logs 
WHERE event_type = 'RAFT_ERROR' 
   OR message LIKE '%raft%' 
   OR message LIKE '%consensus%'
   OR message LIKE '%leader%election%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get garbage collection errors
```sql
SELECT log_id, timestamp, pod, node_name, bucket_name, message
FROM logs 
WHERE message LIKE '%garbage%collection%' 
   OR message LIKE '%gc%fail%'
   OR message LIKE '%cleanup%error%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get quota/limit errors
```sql
SELECT log_id, timestamp, pod, node_name, bucket_name, message
FROM logs 
WHERE message LIKE '%quota%' 
   OR message LIKE '%limit%exceeded%'
   OR message LIKE '%capacity%'
ORDER BY timestamp DESC
LIMIT 30
```

### Get network errors
```sql
SELECT log_id, timestamp, pod, node_name, message
FROM logs 
WHERE event_type IN ('CONNECTION_ERROR', 'DNS_ERROR', 'SEND_FAIL')
   OR message LIKE '%network%' 
   OR message LIKE '%socket%'
   OR message LIKE '%connect%refused%'
ORDER BY timestamp DESC
LIMIT 30
```

### Errors in last 1 hour
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 3600)
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 50
```

### Errors in last 6 hours
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 21600)
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 100
```

### Errors in last 12 hours
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 43200)
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 100
```

### Errors in last 7 days
```sql
SELECT log_id, timestamp, pod, node_name, object_store_name, severity, event_type, message
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 604800)
AND severity IN ('ERROR', 'FATAL')
ORDER BY timestamp DESC
LIMIT 200
```

### Error count by day (last 7 days)
```sql
SELECT 
    date(timestamp, 'unixepoch') as day,
    COUNT(*) as error_count,
    SUM(CASE WHEN severity = 'FATAL' THEN 1 ELSE 0 END) as fatals
FROM logs 
WHERE timestamp > (strftime('%s', 'now') - 604800)
AND severity IN ('ERROR', 'FATAL')
GROUP BY day
ORDER BY day DESC
```

### Get logs with specific raw log file
```sql
SELECT log_id, timestamp, pod, node_name, severity, message, raw_log_file
FROM logs 
WHERE raw_log_file LIKE '%oss1%'
ORDER BY timestamp DESC
LIMIT 50
```

---

## ADVANCED BUCKET QUERIES

### Get bucket count by owner
```sql
SELECT bucket_owner, COUNT(*) as bucket_count
FROM bucket
GROUP BY bucket_owner
ORDER BY bucket_count DESC
```

### Get buckets created in last 30 days
```sql
SELECT bucket_name, bucket_owner, created_at
FROM bucket
WHERE created_at > datetime('now', '-30 days')
ORDER BY created_at DESC
```

### Get buckets with all features enabled
```sql
SELECT bucket_name, bucket_owner
FROM bucket
WHERE versioning = 1 AND worm = 1 AND replication_status = 'ENABLED'
```

### Get buckets without replication
```sql
SELECT bucket_name, bucket_owner, created_at
FROM bucket
WHERE replication_status != 'ENABLED' OR replication_status IS NULL
ORDER BY bucket_name
```

### Get bucket configuration summary
```sql
SELECT 
    COUNT(*) as total_buckets,
    SUM(CASE WHEN versioning = 1 THEN 1 ELSE 0 END) as versioning_enabled,
    SUM(CASE WHEN worm = 1 THEN 1 ELSE 0 END) as worm_enabled,
    SUM(CASE WHEN replication_status = 'ENABLED' THEN 1 ELSE 0 END) as replication_enabled,
    SUM(CASE WHEN tiering_status = 'ENABLED' THEN 1 ELSE 0 END) as tiering_enabled
FROM bucket
```

---

## ADVANCED STORAGE QUERIES

### Get storage growth (if multiple timestamps exist)
```sql
SELECT 
    b.bucket_name,
    MIN(bs.size_gb) as initial_size,
    MAX(bs.size_gb) as current_size,
    MAX(bs.size_gb) - MIN(bs.size_gb) as growth_gb
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
GROUP BY b.bucket_name
HAVING growth_gb > 0
ORDER BY growth_gb DESC
```

### Get average object size by bucket
```sql
SELECT 
    b.bucket_name,
    bs.size_gb,
    bs.object_count,
    CASE WHEN bs.object_count > 0 
         THEN ROUND(bs.size_gb * 1024 / bs.object_count, 2) 
         ELSE 0 END as avg_object_size_mb
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
WHERE bs.object_count > 0
ORDER BY avg_object_size_mb DESC
```

### Get buckets over 100GB
```sql
SELECT b.bucket_name, bs.size_gb, bs.object_count
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
WHERE bs.size_gb > 100
ORDER BY bs.size_gb DESC
```

### Get buckets with millions of objects
```sql
SELECT b.bucket_name, bs.object_count, bs.size_gb
FROM bucket_stats bs
JOIN bucket b ON bs.bucket_id = b.bucket_id
WHERE bs.object_count > 1000000
ORDER BY bs.object_count DESC
```

### Get storage by object store
```sql
SELECT 
    os.store_name,
    SUM(bs.size_gb) as total_size_gb,
    SUM(bs.object_count) as total_objects
FROM bucket_stats bs
JOIN object_store os ON bs.object_store_uuid = os.object_store_uuid
GROUP BY os.store_name
ORDER BY total_size_gb DESC
```

---

## ADVANCED ALERT QUERIES

### Get alert history (including resolved)
```sql
SELECT alert_id, alert_type, severity, entity_type, message, first_detected_at, resolved_at
FROM alerts
ORDER BY first_detected_at DESC
LIMIT 50
```

### Get alerts by entity type
```sql
SELECT entity_type, severity, COUNT(*) as count
FROM alerts
WHERE is_active = 1
GROUP BY entity_type, severity
ORDER BY count DESC
```

### Get disk space alerts
```sql
SELECT alert_id, entity_id, message, first_detected_at
FROM alerts
WHERE message LIKE '%space%' OR message LIKE '%disk%' OR message LIKE '%filesystem%'
AND is_active = 1
ORDER BY first_detected_at DESC
```

### Get replication alerts
```sql
SELECT alert_id, bucket_name, message, first_detected_at
FROM alerts
WHERE alert_type LIKE '%REPLICATION%' OR message LIKE '%replication%'
AND is_active = 1
ORDER BY first_detected_at DESC
```

### Count alerts by severity
```sql
SELECT severity, COUNT(*) as count
FROM alerts
WHERE is_active = 1
GROUP BY severity
ORDER BY 
    CASE severity 
        WHEN 'CRITICAL' THEN 1 
        WHEN 'WARNING' THEN 2 
        WHEN 'INFO' THEN 3 
        ELSE 4 
    END
```

---

## CROSS-TABLE ANALYSIS

### Get buckets with errors in last 24 hours
```sql
SELECT DISTINCT 
    l.bucket_name,
    COUNT(*) as error_count,
    MAX(l.timestamp) as last_error
FROM logs l
WHERE l.bucket_name IS NOT NULL 
AND l.severity IN ('ERROR', 'FATAL')
AND l.timestamp > (strftime('%s', 'now') - 86400)
GROUP BY l.bucket_name
ORDER BY error_count DESC
```

### Get object stores with most errors
```sql
SELECT 
    l.object_store_name,
    COUNT(*) as error_count,
    COUNT(DISTINCT l.node_name) as affected_nodes,
    COUNT(DISTINCT l.bucket_name) as affected_buckets
FROM logs l
WHERE l.severity IN ('ERROR', 'FATAL')
AND l.timestamp > (strftime('%s', 'now') - 86400)
GROUP BY l.object_store_name
ORDER BY error_count DESC
```

### Get full bucket health report
```sql
SELECT 
    b.bucket_name,
    b.bucket_owner,
    bs.size_gb,
    bs.object_count,
    b.replication_status,
    (SELECT COUNT(*) FROM logs l WHERE l.bucket_name = b.bucket_name AND l.severity IN ('ERROR', 'FATAL') AND l.timestamp > (strftime('%s', 'now') - 86400)) as recent_errors,
    (SELECT COUNT(*) FROM alerts a WHERE a.bucket_name = b.bucket_name AND a.is_active = 1) as active_alerts
FROM bucket b
LEFT JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
ORDER BY recent_errors DESC
```

### Get cluster health summary
```sql
SELECT 
    os.store_name,
    os.state,
    os.node_count,
    (SELECT COUNT(*) FROM logs l WHERE l.object_store_name = os.store_name AND l.severity = 'FATAL' AND l.timestamp > (strftime('%s', 'now') - 86400)) as fatals_24h,
    (SELECT COUNT(*) FROM logs l WHERE l.object_store_name = os.store_name AND l.severity = 'ERROR' AND l.timestamp > (strftime('%s', 'now') - 86400)) as errors_24h,
    (SELECT COUNT(*) FROM alerts a WHERE a.source_store_uuid = os.object_store_uuid AND a.is_active = 1) as active_alerts
FROM object_store os
```

---

## EXPANDED COMMON USER QUESTIONS → QUERIES

| Question | Query |
|----------|-------|
| "How many errors today?" | `SELECT COUNT(*) as count FROM logs WHERE severity IN ('ERROR', 'FATAL') AND timestamp > (strftime('%s', 'now') - 86400)` |
| "Show me crashes" | `SELECT timestamp, pod, node_name, object_store_name, bucket_name, message, stack_trace FROM logs WHERE event_type = 'CRASH' OR severity = 'FATAL' ORDER BY timestamp DESC LIMIT 20` |
| "What's wrong with oss1?" | `SELECT timestamp, pod, node_name, severity, event_type, message FROM logs WHERE object_store_name = 'oss1' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 30` |
| "What's wrong with oss3?" | `SELECT timestamp, pod, node_name, severity, event_type, message FROM logs WHERE object_store_name = 'oss3' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 30` |
| "Show errors for nova-logs bucket" | `SELECT timestamp, pod, node_name, severity, message FROM logs WHERE bucket_name = 'nova-logs' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 30` |
| "Any disk problems?" | `SELECT timestamp, node_name, message FROM logs WHERE event_type = 'DISK_ERROR' OR message LIKE '%disk%' OR message LIKE '%I/O error%' ORDER BY timestamp DESC LIMIT 20` |
| "Memory issues?" | `SELECT timestamp, node_name, message FROM logs WHERE event_type = 'OUT_OF_MEMORY' OR message LIKE '%OOM%' OR message LIKE '%memory%' ORDER BY timestamp DESC LIMIT 20` |
| "Replication problems?" | `SELECT timestamp, bucket_name, message FROM logs WHERE event_type = 'REPLICATION_FAIL' ORDER BY timestamp DESC LIMIT 20` |
| "Which nodes have problems?" | `SELECT node_name, COUNT(*) as errors FROM logs WHERE severity IN ('ERROR', 'FATAL') GROUP BY node_name ORDER BY errors DESC LIMIT 10` |
| "Error summary" | `SELECT severity, event_type, COUNT(*) as count FROM logs GROUP BY severity, event_type ORDER BY count DESC LIMIT 20` |
| "Bucket sizes" | `SELECT b.bucket_name, bs.size_gb, bs.object_count FROM bucket_stats bs JOIN bucket b ON bs.bucket_id = b.bucket_id ORDER BY bs.size_gb DESC` |
| "Total storage" | `SELECT ROUND(SUM(size_gb), 2) as total_gb, SUM(object_count) as total_objects FROM bucket_stats` |
| "Critical alerts" | `SELECT entity_id, message, first_detected_at FROM alerts WHERE severity = 'CRITICAL' AND is_active = 1` |
| "All alerts" | `SELECT severity, entity_type, entity_id, message FROM alerts WHERE is_active = 1 ORDER BY first_detected_at DESC` |
| "How many buckets?" | `SELECT COUNT(*) as bucket_count FROM bucket` |
| "How many object stores?" | `SELECT COUNT(*) as store_count FROM object_store` |
| "Pending replications" | `SELECT b.bucket_name, br.pending_objects, br.pending_size_gb FROM bucket_replication br JOIN bucket b ON br.source_bucket_id = b.bucket_id WHERE br.pending_objects > 0` |
| "Log collection status" | `SELECT cluster_name, status, errors_found, uploaded_at FROM log_uploads ORDER BY uploaded_at DESC LIMIT 10` |
| "Object controller errors" | `SELECT timestamp, node_name, event_type, message FROM logs WHERE pod = 'OC' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 30` |
| "Metadata service errors" | `SELECT timestamp, node_name, event_type, message FROM logs WHERE pod = 'MS' AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 30` |
| "Connection issues" | `SELECT timestamp, node_name, message FROM logs WHERE event_type = 'CONNECTION_ERROR' OR message LIKE '%connection%' ORDER BY timestamp DESC LIMIT 20` |
| "Authentication failures" | `SELECT timestamp, node_name, bucket_name, message FROM logs WHERE event_type IN ('AUTH_FAIL', 'IAM_ERROR') ORDER BY timestamp DESC LIMIT 20` |
| "SSL errors" | `SELECT timestamp, node_name, message FROM logs WHERE event_type = 'SSL_ERROR' OR message LIKE '%ssl%' ORDER BY timestamp DESC LIMIT 20` |
| "Errors this hour" | `SELECT timestamp, pod, node_name, severity, message FROM logs WHERE timestamp > (strftime('%s', 'now') - 3600) AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC` |
| "Errors last 6 hours" | `SELECT timestamp, pod, node_name, severity, message FROM logs WHERE timestamp > (strftime('%s', 'now') - 21600) AND severity IN ('ERROR', 'FATAL') ORDER BY timestamp DESC LIMIT 100` |
| "WORM buckets" | `SELECT bucket_name, bucket_owner FROM bucket WHERE worm = 1` |
| "Versioned buckets" | `SELECT bucket_name, bucket_owner FROM bucket WHERE versioning = 1` |
| "Largest bucket" | `SELECT b.bucket_name, bs.size_gb FROM bucket_stats bs JOIN bucket b ON bs.bucket_id = b.bucket_id ORDER BY bs.size_gb DESC LIMIT 1` |
| "Bucket with most objects" | `SELECT b.bucket_name, bs.object_count FROM bucket_stats bs JOIN bucket b ON bs.bucket_id = b.bucket_id ORDER BY bs.object_count DESC LIMIT 1` |

---

## IMPORTANT NOTES

1. **Timestamps**: The `logs` table uses Unix epoch timestamps (integers). Use `strftime('%s', 'now')` for current time.
2. **Time filtering**: 
   - Last 1 hour: `timestamp > (strftime('%s', 'now') - 3600)`
   - Last 6 hours: `timestamp > (strftime('%s', 'now') - 21600)`
   - Last 12 hours: `timestamp > (strftime('%s', 'now') - 43200)`
   - Last 24 hours: `timestamp > (strftime('%s', 'now') - 86400)`
   - Last 7 days: `timestamp > (strftime('%s', 'now') - 604800)`
3. **Severity values**: 'FATAL', 'ERROR', 'WARN', 'INFO'
4. **Pod/Component values**: 'OC' (Object Controller), 'MS' (Metadata Service), 'Atlas', 'Curator', 'Stargate'
5. **Object stores**: Common values are 'oss1', 'oss3' - check `object_store_name` column
6. **Event types**: CRASH, CONNECTION_ERROR, DISK_ERROR, OUT_OF_MEMORY, REPLICATION_FAIL, AUTH_FAIL, SSL_ERROR, TIMEOUT, RAFT_ERROR, FILE_NOT_FOUND, etc.
7. **Always use LIMIT**: Add LIMIT clause to prevent returning too many rows
8. **Case sensitive**: SQL keywords can be any case, but column/table names and string values are case-sensitive
