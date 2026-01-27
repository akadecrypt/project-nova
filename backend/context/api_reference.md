# Nutanix APIs Reference

## Prism Central API

### REST API Versions
| Version | Base Path |
|---------|-----------|
| v0.8 | `/api/nutanix/v0.8` |
| v1 | `/PrismGateway/services/rest/v1` |
| v2.0 | `/PrismGateway/services/rest/v2.0` |
| v3.0 | `/api/nutanix/v3` |
| v4.0 | `/api/prism/v4.0.b1/config` |
| v4.2 | `/api/prism/v4.2/config` |

### Authentication
- **Basic Auth**: `Authorization: Basic <base64(username:password)>`
- **Default Port**: 9440
- **Default Credentials**: `admin` / `Nutanix.123`

### Objects API (v4)

#### Base URL
```
https://{PC_IP}:9440/api/objects/v4.0/
```

#### List Object Stores
```http
GET /config/object-stores
```

**Response Fields**:
- `extId`: Object store UUID
- `name`: Object store name
- `domain`: DNS domain
- `region`: Configured region
- `state`: Deployment state
- `totalCapacityInBytes`: Total storage
- `usedCapacityInBytes`: Used storage

#### Get Object Store Statistics
```http
GET /stats/object-stores/{objectStoreExtId}
```

**Query Parameters**:
| Parameter | Description |
|-----------|-------------|
| `$startTime` | ISO 8601 start time |
| `$endTime` | ISO 8601 end time |
| `$select` | Comma-separated stat names |
| `$samplingInterval` | Interval in seconds |
| `$statType` | Type of statistics |

**Available Statistics**:
- `totalObjectCount`
- `totalBucketCount`
- `totalCapacityBytes`
- `usedCapacityBytes`
- `readIops`
- `writeIops`
- `readThroughputBps`
- `writeThroughputBps`

### Objects Proxy API (v3)
```
https://{PC_IP}:9440/oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/
```

**Endpoints**:
- `buckets/stats` - Bucket statistics
- `buckets/list` - List buckets

## S3 API Operations

### Endpoint Format
```
http://{S3_ENDPOINT}:{PORT}
```

### Authentication
- AWS Signature Version 4
- Access Key ID + Secret Access Key

### Bucket Operations

| Operation | Method | Path | Description |
|-----------|--------|------|-------------|
| ListBuckets | GET | `/` | List all buckets |
| CreateBucket | PUT | `/{bucket}` | Create bucket |
| DeleteBucket | DELETE | `/{bucket}` | Delete bucket |
| HeadBucket | HEAD | `/{bucket}` | Check bucket exists |
| GetBucketLocation | GET | `/{bucket}?location` | Get region |
| GetBucketVersioning | GET | `/{bucket}?versioning` | Get versioning status |
| PutBucketVersioning | PUT | `/{bucket}?versioning` | Set versioning |
| GetBucketAcl | GET | `/{bucket}?acl` | Get ACL |
| PutBucketAcl | PUT | `/{bucket}?acl` | Set ACL |
| GetBucketPolicy | GET | `/{bucket}?policy` | Get policy |
| PutBucketPolicy | PUT | `/{bucket}?policy` | Set policy |
| DeleteBucketPolicy | DELETE | `/{bucket}?policy` | Delete policy |
| GetBucketCors | GET | `/{bucket}?cors` | Get CORS |
| PutBucketCors | PUT | `/{bucket}?cors` | Set CORS |
| DeleteBucketCors | DELETE | `/{bucket}?cors` | Delete CORS |
| GetBucketEncryption | GET | `/{bucket}?encryption` | Get encryption |
| PutBucketEncryption | PUT | `/{bucket}?encryption` | Set encryption |
| DeleteBucketEncryption | DELETE | `/{bucket}?encryption` | Delete encryption |
| GetBucketLifecycle | GET | `/{bucket}?lifecycle` | Get lifecycle |
| PutBucketLifecycle | PUT | `/{bucket}?lifecycle` | Set lifecycle |
| DeleteBucketLifecycle | DELETE | `/{bucket}?lifecycle` | Delete lifecycle |
| GetBucketReplication | GET | `/{bucket}?replication` | Get replication |
| PutBucketReplication | PUT | `/{bucket}?replication` | Set replication |
| DeleteBucketReplication | DELETE | `/{bucket}?replication` | Delete replication |
| GetBucketTagging | GET | `/{bucket}?tagging` | Get tags |
| PutBucketTagging | PUT | `/{bucket}?tagging` | Set tags |
| DeleteBucketTagging | DELETE | `/{bucket}?tagging` | Delete tags |
| GetBucketWebsite | GET | `/{bucket}?website` | Get website config |
| PutBucketWebsite | PUT | `/{bucket}?website` | Set website config |
| DeleteBucketWebsite | DELETE | `/{bucket}?website` | Delete website config |
| GetObjectLockConfiguration | GET | `/{bucket}?object-lock` | Get WORM config |
| PutObjectLockConfiguration | PUT | `/{bucket}?object-lock` | Set WORM config |
| GetBucketNotification | GET | `/{bucket}?notification` | Get notifications |
| PutBucketNotification | PUT | `/{bucket}?notification` | Set notifications |

### Object Operations

| Operation | Method | Path | Description |
|-----------|--------|------|-------------|
| ListObjects | GET | `/{bucket}` | List objects |
| ListObjectsV2 | GET | `/{bucket}?list-type=2` | List objects (v2) |
| ListObjectVersions | GET | `/{bucket}?versions` | List versions |
| GetObject | GET | `/{bucket}/{key}` | Download object |
| HeadObject | HEAD | `/{bucket}/{key}` | Get object metadata |
| PutObject | PUT | `/{bucket}/{key}` | Upload object |
| CopyObject | PUT | `/{bucket}/{key}` | Copy object (with x-amz-copy-source) |
| DeleteObject | DELETE | `/{bucket}/{key}` | Delete object |
| DeleteObjects | POST | `/{bucket}?delete` | Bulk delete |
| GetObjectAcl | GET | `/{bucket}/{key}?acl` | Get object ACL |
| PutObjectAcl | PUT | `/{bucket}/{key}?acl` | Set object ACL |
| GetObjectTagging | GET | `/{bucket}/{key}?tagging` | Get object tags |
| PutObjectTagging | PUT | `/{bucket}/{key}?tagging` | Set object tags |
| DeleteObjectTagging | DELETE | `/{bucket}/{key}?tagging` | Delete object tags |
| GetObjectRetention | GET | `/{bucket}/{key}?retention` | Get retention |
| PutObjectRetention | PUT | `/{bucket}/{key}?retention` | Set retention |
| GetObjectLegalHold | GET | `/{bucket}/{key}?legal-hold` | Get legal hold |
| PutObjectLegalHold | PUT | `/{bucket}/{key}?legal-hold` | Set legal hold |

### Multipart Upload

| Operation | Method | Path |
|-----------|--------|------|
| CreateMultipartUpload | POST | `/{bucket}/{key}?uploads` |
| UploadPart | PUT | `/{bucket}/{key}?partNumber={n}&uploadId={id}` |
| ListParts | GET | `/{bucket}/{key}?uploadId={id}` |
| ListMultipartUploads | GET | `/{bucket}?uploads` |
| CompleteMultipartUpload | POST | `/{bucket}/{key}?uploadId={id}` |
| AbortMultipartUpload | DELETE | `/{bucket}/{key}?uploadId={id}` |

### Response Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (success, no body) |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden / Access Denied |
| 404 | Not Found |
| 409 | Conflict (bucket exists, etc.) |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

## SQL Agent API

### Endpoint
```http
POST http://{SQL_AGENT_URL}/execute
```

### Request
```json
{
  "sql": "SELECT * FROM bucket LIMIT 10"
}
```

### Success Response
```json
{
  "status": "success",
  "columns": ["bucket_id", "bucket_name", ...],
  "rows": [[...], [...]]
}
```

### Error Response
```json
{
  "status": "error",
  "error": "Error message"
}
```

## IAM API

### Base URLs
| Type | URL |
|------|-----|
| No Auth | `http://{IP}:5556/iam/v1` |
| Basic Auth | `https://{IP}:5554/iam/v1` |
| Cert Auth | `https://{IP}:5553/iam/v1` |
| OSS Proxy | `https://{IP}:9440/oss/iam_proxy` |

### Endpoints
- Token: `/oidc/token`
- Access Keys: `/buckets_access_keys`
- Users: `/users`
- Directory Services: `/directory_services`
