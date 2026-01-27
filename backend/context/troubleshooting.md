# Troubleshooting Guide

## Common Issues and Solutions

### Bucket Operations

#### Cannot Create Bucket
**Symptoms**: Bucket creation fails with error.

**Possible Causes & Solutions**:
1. **Bucket name already exists**
   - Bucket names must be globally unique within the object store
   - Try a different name or add a unique suffix
   
2. **Invalid bucket name**
   - Names must be 3-63 characters
   - Only lowercase letters, numbers, and hyphens allowed
   - Cannot start or end with hyphen
   - Cannot contain consecutive hyphens

3. **Permission denied**
   - Verify IAM credentials have `s3:CreateBucket` permission
   - Check if bucket creation is restricted by policy

4. **Object store capacity limit reached**
   - Check object store capacity via Prism Central
   - Request capacity expansion if needed

#### Cannot Access Bucket
**Symptoms**: Access denied or bucket not found errors.

**Solutions**:
1. Verify bucket exists: `list_buckets`
2. Check IAM user permissions
3. Verify bucket policy allows access
4. Check if bucket has WORM enabled and operation is restricted

### Object Operations

#### Upload Failures
**Symptoms**: Object upload fails or times out.

**Solutions**:
1. **Large files**: Use multipart upload for files > 5GB
2. **Network issues**: Check connectivity to S3 endpoint
3. **Storage capacity**: Verify bucket/object store has space
4. **Key naming**: Avoid special characters in object keys

#### Object Versioning Issues
**Symptoms**: Cannot find expected version or unexpected versions appearing.

**Solutions**:
1. Check if versioning is enabled: `get_bucket_versioning`
2. List object versions to find specific version
3. Use version ID for specific version operations

### Replication Problems

#### Replication Not Working
**Symptoms**: Objects not appearing in destination bucket.

**Checklist**:
1. Verify replication rule is enabled
2. Check source bucket versioning is enabled (required for replication)
3. Verify destination bucket exists and is accessible
4. Check replication status: `get_bucket_replication`
5. Look for replication errors in Prism Central alerts

#### Replication Lag
**Symptoms**: Objects take too long to replicate.

**Solutions**:
1. Check network connectivity between sites
2. Review replication queue size
3. Consider bandwidth limitations
4. Check for object size (large objects take longer)

### Lifecycle Policy Issues

#### Objects Not Expiring
**Symptoms**: Objects remain after expected expiration.

**Solutions**:
1. Verify lifecycle rule is enabled
2. Check rule prefix matches objects
3. Rules apply at midnight UTC - wait for next cycle
4. Verify rule conditions are met (age, transition state)

#### Unexpected Object Deletion
**Symptoms**: Objects deleted unexpectedly.

**Solutions**:
1. Review all lifecycle rules on bucket
2. Check for expiration rules with short periods
3. Enable versioning to protect against accidental deletion
4. Review bucket policy for delete permissions

### Performance Issues

#### Slow Uploads/Downloads
**Solutions**:
1. Use multipart upload for large files
2. Increase connection pool size
3. Use regional endpoint closest to client
4. Consider enabling transfer acceleration
5. Check network bandwidth and latency

#### High Latency
**Solutions**:
1. Monitor object store IOPS via Prism Central
2. Check cluster load and resource utilization
3. Review concurrent request patterns
4. Consider caching for frequently accessed objects

### Prism Central Connection Issues

#### Cannot Connect to Prism Central
**Symptoms**: API calls fail with connection errors.

**Solutions**:
1. Verify PC IP address is correct
2. Check port 9440 is accessible
3. Verify credentials (username/password)
4. Check SSL certificate if using HTTPS
5. Verify network connectivity from NOVA backend

#### Authentication Failures
**Symptoms**: 401 Unauthorized errors.

**Solutions**:
1. Verify username and password are correct
2. Check if user account is locked
3. Verify user has required permissions
4. Check if password has expired

## Error Code Reference

| Error Code | Description | Solution |
|------------|-------------|----------|
| 400 | Bad Request | Check request parameters |
| 401 | Unauthorized | Verify credentials |
| 403 | Forbidden | Check permissions/policies |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource already exists |
| 500 | Server Error | Check server logs, retry |
| 503 | Service Unavailable | Service is down, retry later |

## Diagnostic Queries

### Check Bucket Health
```sql
SELECT bucket_name, versioning, worm, replication_status
FROM bucket
WHERE bucket_name = '<bucket_name>';
```

### Find Large Buckets
```sql
SELECT b.bucket_name, bs.size_gb, bs.object_count
FROM bucket b
JOIN bucket_stats bs ON b.bucket_id = bs.bucket_id
WHERE bs.timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
ORDER BY bs.size_gb DESC
LIMIT 10;
```

### Storage Growth Trend
```sql
SELECT DATE(timestamp) as date, SUM(size_gb) as total_gb
FROM bucket_stats
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

## When to Escalate

Escalate to Nutanix Support when:
- Cluster is unresponsive
- Data corruption is suspected
- Replication is stuck for extended periods
- Performance degradation affects business operations
- Hardware failures are suspected
