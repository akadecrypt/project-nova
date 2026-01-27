# SQL Analytics Database Schema

This document describes the SQLite database schema used for Nutanix Objects analytics.

**Database Location:** `/home/nutanix/nova-db/nova.db`

## Database Overview

| Table | Description | Row Count |
|-------|-------------|-----------|
| bucket | Bucket metadata and configuration | 11 |
| bucket_stats | Bucket usage statistics over time | 24 |
| object_store | Object store cluster information | 6 |

---

## Table: `bucket`

Stores bucket metadata and configuration settings.

| Column | Type | Description |
|--------|------|-------------|
| bucket_id | INTEGER | Unique bucket identifier |
| object_store_uuid | TEXT | UUID of the parent object store |
| bucket_name | TEXT | Name of the bucket |
| bucket_owner | TEXT | Owner/creator of the bucket |
| versioning | INTEGER | Versioning enabled (1=yes, 0=no) |
| worm | INTEGER | WORM enabled (1=yes, 0=no) |
| replication_status | TEXT | Replication status (ENABLED/DISABLED) |
| tiering_status | TEXT | Tiering status (ENABLED/DISABLED) |
| lifecycle_policy | TEXT | Lifecycle policy description |
| created_at | TEXT | Bucket creation timestamp |

**Example Query:**
```sql
SELECT bucket_name, bucket_owner, versioning, worm 
FROM bucket 
ORDER BY created_at DESC;
```

---

## Table: `bucket_stats`

Stores time-series statistics for each bucket.

| Column | Type | Description |
|--------|------|-------------|
| bucket_id | INTEGER | Foreign key to bucket table |
| object_store_uuid | TEXT | UUID of the parent object store |
| object_count | INTEGER | Number of objects in bucket |
| size_gb | REAL | Total size in gigabytes |
| timestamp | TEXT | When stats were recorded |

**Example Queries:**
```sql
-- Get latest stats for all buckets
SELECT b.bucket_name, bs.object_count, bs.size_gb, bs.timestamp
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
ORDER BY bs.size_gb DESC;

-- Get storage growth over time
SELECT timestamp, SUM(size_gb) as total_gb, SUM(object_count) as total_objects
FROM bucket_stats
GROUP BY timestamp
ORDER BY timestamp;
```

---

## Table: `object_store`

Stores information about object store clusters.

| Column | Type | Description |
|--------|------|-------------|
| object_store_uuid | TEXT | Unique identifier for the object store |
| store_name | TEXT | Name of the object store cluster |
| ip_address | TEXT | IP address of the object store |
| node_count | INTEGER | Number of nodes in the cluster |
| version | TEXT | Software version |
| location | TEXT | Physical/logical location |
| created_at | TEXT | When the store was created |

**Example Query:**
```sql
SELECT store_name, ip_address, node_count, version, location
FROM object_store
ORDER BY store_name;
```

---

## Common Query Patterns

### List all buckets with their latest stats
```sql
SELECT 
    b.bucket_name,
    b.bucket_owner,
    b.versioning,
    b.worm,
    bs.object_count,
    bs.size_gb
FROM bucket b
LEFT JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats WHERE bucket_id = b.bucket_id)
ORDER BY b.bucket_name;
```

### Get total storage usage
```sql
SELECT 
    SUM(size_gb) as total_storage_gb,
    SUM(object_count) as total_objects,
    COUNT(DISTINCT bucket_id) as bucket_count
FROM bucket_stats
WHERE timestamp = (SELECT MAX(timestamp) FROM bucket_stats);
```

### Find WORM-enabled buckets
```sql
SELECT bucket_name, bucket_owner, created_at
FROM bucket
WHERE worm = 1;
```

### Find buckets with versioning enabled
```sql
SELECT bucket_name, bucket_owner, created_at
FROM bucket
WHERE versioning = 1;
```

### Get buckets by replication status
```sql
SELECT bucket_name, replication_status, tiering_status
FROM bucket
WHERE replication_status = 'ENABLED';
```

### Storage growth trend
```sql
SELECT 
    DATE(timestamp) as date,
    SUM(size_gb) as total_gb,
    SUM(object_count) as total_objects
FROM bucket_stats
GROUP BY DATE(timestamp)
ORDER BY date;
```

### Top buckets by size
```sql
SELECT 
    b.bucket_name,
    bs.size_gb,
    bs.object_count
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
ORDER BY bs.size_gb DESC
LIMIT 10;
```

### Object stores summary
```sql
SELECT 
    os.store_name,
    os.node_count,
    os.version,
    COUNT(DISTINCT b.bucket_id) as bucket_count
FROM object_store os
LEFT JOIN bucket b ON os.object_store_uuid = b.object_store_uuid
GROUP BY os.object_store_uuid
ORDER BY os.store_name;
```

### Buckets per object store
```sql
SELECT 
    os.store_name,
    b.bucket_name,
    b.bucket_owner
FROM object_store os
JOIN bucket b ON os.object_store_uuid = b.object_store_uuid
ORDER BY os.store_name, b.bucket_name;
```

---

## Important Notes

1. **Timestamps**: All timestamps are stored as TEXT in ISO format (YYYY-MM-DD HH:MM:SS)
2. **Boolean fields**: `versioning` and `worm` use INTEGER (1=true, 0=false)
3. **Joins**: Use `bucket_id` to join `bucket` with `bucket_stats`, use `object_store_uuid` to join with `object_store`
4. **Latest stats**: Always filter by `MAX(timestamp)` to get current values
5. **Size units**: `size_gb` is in gigabytes (REAL/float type)
