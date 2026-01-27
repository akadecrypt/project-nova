# SQL Analytics Database Schema

## Overview
Object store metadata is stored in a SQLite database for analytics and historical tracking. This enables trend analysis, capacity planning, and operational insights.

**Note**: Run `python scripts/discover_schema.py` to auto-generate this document from the actual database.

## Core Tables

### bucket
Stores bucket configuration and metadata.

| Column | Type | Description |
|--------|------|-------------|
| bucket_id | TEXT | Unique identifier for the bucket |
| object_store_uuid | TEXT | UUID of the parent object store |
| bucket_name | TEXT | Human-readable bucket name |
| bucket_owner | TEXT | Owner/creator of the bucket |
| versioning | TEXT | Versioning status (enabled/disabled/suspended) |
| worm | TEXT | WORM status (enabled/disabled) |
| replication_status | TEXT | Replication configuration status |
| tiering_status | TEXT | Tiering configuration status |
| created_at | TIMESTAMP | Bucket creation timestamp |

**Primary Key**: (bucket_id, object_store_uuid)

### bucket_stats
Time-series statistics for buckets.

| Column | Type | Description |
|--------|------|-------------|
| bucket_id | TEXT | References bucket.bucket_id |
| object_store_uuid | TEXT | References bucket.object_store_uuid |
| object_count | INTEGER | Number of objects in the bucket |
| size_gb | REAL | Total size in gigabytes |
| timestamp | TIMESTAMP | When the stats were recorded |

**Primary Key**: (bucket_id, object_store_uuid, timestamp)

## Common Query Patterns

### Basic Queries

#### List All Buckets
```sql
SELECT bucket_name, bucket_owner, versioning, worm, created_at 
FROM bucket 
ORDER BY created_at DESC;
```

#### Get Bucket Configuration
```sql
SELECT bucket_name, versioning, worm, replication_status, tiering_status
FROM bucket
WHERE bucket_name = 'my-bucket';
```

#### Latest Statistics for All Buckets
```sql
SELECT b.bucket_name, bs.object_count, bs.size_gb, bs.timestamp
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id 
  AND b.object_store_uuid = bs.object_store_uuid
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
ORDER BY bs.size_gb DESC;
```

### Analytics Queries

#### Total Storage Summary
```sql
SELECT 
  COUNT(DISTINCT b.bucket_id) as total_buckets,
  SUM(bs.object_count) as total_objects,
  SUM(bs.size_gb) as total_size_gb,
  ROUND(AVG(bs.size_gb), 2) as avg_bucket_size_gb
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats);
```

#### Storage Growth Over Time
```sql
SELECT 
  DATE(timestamp) as date, 
  SUM(size_gb) as total_gb,
  SUM(object_count) as total_objects
FROM bucket_stats
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

#### Daily Growth Rate
```sql
WITH daily_totals AS (
  SELECT DATE(timestamp) as date, SUM(size_gb) as total_gb
  FROM bucket_stats
  GROUP BY DATE(timestamp)
)
SELECT 
  date,
  total_gb,
  ROUND(total_gb - LAG(total_gb) OVER (ORDER BY date), 2) as daily_growth_gb
FROM daily_totals
ORDER BY date DESC
LIMIT 14;
```

#### Top Buckets by Size
```sql
SELECT b.bucket_name, bs.size_gb, bs.object_count,
  ROUND(bs.size_gb * 1024 / NULLIF(bs.object_count, 0), 2) as avg_object_mb
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
ORDER BY bs.size_gb DESC
LIMIT 10;
```

#### Buckets by Growth Rate
```sql
WITH bucket_growth AS (
  SELECT 
    bucket_id,
    MAX(CASE WHEN timestamp = (SELECT MAX(timestamp) FROM bucket_stats) THEN size_gb END) as current_size,
    MAX(CASE WHEN timestamp = (SELECT MIN(timestamp) FROM bucket_stats WHERE timestamp >= date('now', '-7 days')) THEN size_gb END) as week_ago_size
  FROM bucket_stats
  GROUP BY bucket_id
)
SELECT b.bucket_name, 
  ROUND(bg.current_size - COALESCE(bg.week_ago_size, 0), 2) as weekly_growth_gb
FROM bucket b
JOIN bucket_growth bg ON b.bucket_id = bg.bucket_id
ORDER BY weekly_growth_gb DESC
LIMIT 10;
```

### Feature-Specific Queries

#### Buckets with WORM Enabled
```sql
SELECT bucket_name, bucket_owner, created_at
FROM bucket
WHERE worm = 'enabled'
ORDER BY created_at;
```

#### Versioning-Enabled Buckets
```sql
SELECT bucket_name, bucket_owner, versioning
FROM bucket
WHERE versioning = 'enabled';
```

#### Replication Status Summary
```sql
SELECT 
  replication_status,
  COUNT(*) as bucket_count
FROM bucket
GROUP BY replication_status;
```

#### Buckets with Tiering
```sql
SELECT bucket_name, tiering_status, bucket_owner
FROM bucket
WHERE tiering_status IS NOT NULL AND tiering_status != 'disabled';
```

### Administrative Queries

#### Bucket Count by Owner
```sql
SELECT bucket_owner, COUNT(*) as bucket_count
FROM bucket
GROUP BY bucket_owner
ORDER BY bucket_count DESC;
```

#### Object Store Summary
```sql
SELECT 
  object_store_uuid,
  COUNT(DISTINCT bucket_id) as bucket_count,
  SUM(bs.size_gb) as total_size_gb
FROM bucket b
LEFT JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
GROUP BY object_store_uuid;
```

#### Empty Buckets
```sql
SELECT b.bucket_name, b.created_at
FROM bucket b
LEFT JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
  AND bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
WHERE COALESCE(bs.object_count, 0) = 0;
```

## Query Tips

1. **Always filter by timestamp** for stats queries to get consistent snapshots
2. **Use bucket_id + object_store_uuid** as composite key for joins
3. **Limit results** for large tables to improve performance
4. **Use date functions** for time-based analysis: `date()`, `datetime()`, `strftime()`
5. **Handle NULLs** with `COALESCE()` or `IFNULL()` for calculations
