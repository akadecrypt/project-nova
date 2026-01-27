# Best Practices for Nutanix Objects

## Bucket Design

### Naming Conventions
- Use descriptive, lowercase names
- Include environment prefix: `prod-`, `dev-`, `test-`
- Include purpose: `logs-`, `backup-`, `media-`
- Example: `prod-application-logs`, `dev-user-uploads`

### Bucket Organization
- Create separate buckets for different data types
- Use prefixes (folders) for logical organization within buckets
- Don't create too many small buckets; consolidate related data
- Consider access patterns when designing bucket structure

## Security Best Practices

### Access Control
1. **Principle of Least Privilege**
   - Grant minimum required permissions
   - Use IAM policies for fine-grained control
   - Regularly audit and review permissions

2. **Bucket Policies**
   - Deny public access by default
   - Use conditions to restrict access (IP, time, etc.)
   - Enable bucket policy logging

3. **Authentication**
   - Rotate access keys regularly
   - Never embed credentials in code
   - Use environment variables or secret management

### Data Protection
1. **Enable Versioning** for critical data
   - Protects against accidental deletion
   - Enables recovery of previous versions
   - Required for cross-region replication

2. **Use WORM** for compliance data
   - Write Once Read Many for immutable storage
   - Required for regulatory compliance (SEC, FINRA, etc.)
   - Plan retention periods carefully

3. **Enable Encryption**
   - Use server-side encryption (SSE)
   - Manage encryption keys securely
   - Consider client-side encryption for sensitive data

## Performance Optimization

### Upload Optimization
- Use multipart upload for files > 100MB
- Parallelize uploads for multiple files
- Consider compression for text-based data
- Use appropriate part sizes (5MB-100MB)

### Download Optimization
- Use range requests for partial downloads
- Implement caching for frequently accessed objects
- Use byte-range fetches for large files
- Consider CDN for public content

### Key Naming
- Avoid sequential prefixes (causes hot partitions)
- Add random prefixes for high-throughput workloads
- Example: Instead of `logs/2024/01/01/file.log`
- Use: `a1b2c3/logs/2024/01/01/file.log`

## Lifecycle Management

### Implement Lifecycle Policies
1. **Expiration Rules**
   - Delete temporary data after use
   - Remove old log files automatically
   - Clean up incomplete multipart uploads

2. **Transition Rules**
   - Move infrequently accessed data to cold storage
   - Define clear tiering strategy based on access patterns

### Example Lifecycle Strategy
```
Days 0-30:    Hot storage (frequent access)
Days 30-90:   Warm storage (occasional access)
Days 90-365:  Cold storage (rare access)
Days 365+:    Archive or delete
```

## Replication Strategy

### Cross-Site Replication
- Enable for disaster recovery
- Ensure versioning is enabled on source
- Monitor replication lag
- Test recovery procedures regularly

### Replication Considerations
- Bandwidth requirements
- Data residency requirements
- RPO/RTO objectives
- Cost implications

## Monitoring and Alerting

### Key Metrics to Monitor
1. **Capacity**
   - Storage utilization percentage
   - Object count growth
   - Bucket size trends

2. **Performance**
   - Request latency (GET, PUT)
   - Throughput (read/write)
   - Error rates

3. **Operations**
   - Failed requests
   - Replication status
   - Lifecycle policy execution

### Set Up Alerts For
- Storage capacity > 80%
- Error rate > threshold
- Replication lag > acceptable limit
- Failed lifecycle operations

## Cost Optimization

### Storage Efficiency
- Implement lifecycle policies to move/delete old data
- Use appropriate storage tiers
- Compress data when possible
- Remove duplicate objects

### Request Optimization
- Batch operations where possible
- Cache frequently accessed objects
- Use appropriate request methods
- Minimize cross-region requests

## Operational Best Practices

### Documentation
- Document bucket purposes and ownership
- Maintain access control documentation
- Keep runbooks for common operations
- Document disaster recovery procedures

### Testing
- Test backup and restore procedures
- Validate replication failover
- Test lifecycle policies in non-prod
- Regular security assessments

### Automation
- Automate routine operations
- Use infrastructure as code
- Implement CI/CD for deployments
- Schedule regular maintenance tasks

## SQL Query Best Practices

### Efficient Queries
```sql
-- Use indexes (bucket_id, object_store_uuid)
-- Always filter by timestamp for stats
-- Limit results for large tables
-- Use aggregate functions for summaries
```

### Common Patterns
```sql
-- Latest stats only
WHERE timestamp = (SELECT MAX(timestamp) FROM bucket_stats)

-- Time-based analysis
WHERE timestamp >= date('now', '-7 days')

-- Specific bucket
WHERE bucket_name = 'target-bucket'
```
