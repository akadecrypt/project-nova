# Nutanix Objects Product Knowledge

## Overview
Nutanix Objects is an S3-compatible object storage solution built on the Nutanix platform. It provides scalable, secure, and cost-effective storage for unstructured data.

## Architecture Components

### Object Store Controller (OC)
- **Port**: 7101
- **URL**: `http://localhost:7101`
- **Function**: Handles S3 API requests, manages object operations

### Metadata Server (MS)
- **Port**: 7102
- **URL**: `http://localhost:7102`
- **Function**: Manages bucket and object metadata, region management

### Atlas (Curator)
- **Port**: 7103
- **URL**: `http://localhost:7103`
- **Function**: Background jobs, garbage collection, tiering, lifecycle policies
- **Scan Types**: Full scan, Partial scan, Selective stats scan, Selective feature scan

### Chronos
- **Port**: 7104
- **URL**: `http://localhost:7104`
- **Function**: Job scheduling, task management

## Key Features

### Bucket Features

#### Versioning
- **States**: Enabled, Disabled, Suspended
- **Required for**: Replication, WORM
- **API**: `put_bucket_versioning`, `get_bucket_versioning`

#### WORM (Object Lock)
- **Modes**: COMPLIANCE, GOVERNANCE
- **Configuration**:
```json
{
  "ObjectLockEnabled": "Enabled",
  "Rule": {
    "DefaultRetention": {
      "Days": 1,
      "Mode": "COMPLIANCE"
    }
  }
}
```
- **Legal Hold**: Can be applied to individual objects
- Prevents deletion during retention period

#### Lifecycle Policies
- **Actions**: Expiration, Transition (tiering), Abort incomplete multipart
- **Filters**: Prefix, Tags
- **Example**:
```json
{
  "Rules": [{
    "Status": "Enabled",
    "Filter": {"Prefix": "logs/"},
    "Expiration": {"Days": 30},
    "Transitions": [{"Days": 7, "Endpoint": "cold-storage"}]
  }]
}
```

#### Replication
- **Types**: Cross-region, Cross-cluster
- **Statuses**: Pending, Completed, Failed, Replica
- **Requirements**: Source bucket must have versioning enabled
- **Max Copy Size**: 5GB per object

#### Tiering
- **Supported Endpoints**:
  - AWS S3: `s3.amazonaws.com`
  - GCP: `storage.googleapis.com`
  - Azure Blob: `blob.core.windows.net`
  - Other S3-compatible: Custom endpoints
- **Jobs**: TransitionRegionTask, CloseRegionTask, ZeroRegionTask

#### Encryption
- **Server-side encryption (SSE)**
- **Algorithms**: AES256, aws:kms
- **API**: `put_bucket_encryption`, `get_bucket_encryption`

#### ACLs (Access Control Lists)
- **Canned ACLs**: private, public-read, public-read-write, authenticated-read
- **Grant Types**: GrantRead, GrantWrite, GrantReadACP, GrantWriteACP, GrantFullControl
- **Permissions**: READ, WRITE, READ_ACP, WRITE_ACP, FULL_CONTROL

#### CORS (Cross-Origin Resource Sharing)
- Configure allowed origins, methods, headers
- **API**: `put_bucket_cors`, `get_bucket_cors`, `delete_bucket_cors`

#### Static Website Hosting
- Configure index and error documents
- **API**: `put_bucket_website`, `get_bucket_website`

#### Bucket Policies
- JSON-based IAM-style policies
- Control access at bucket and object level

#### Tagging
- Key-value pairs for buckets and objects
- Max key size: 128 characters
- Max value size: 255 characters

### Object Features

#### Multipart Upload
- Required for objects > 5GB
- Part size: 5MB - 5GB
- Max parts: 10,000

#### Object Tagging
- Metadata attached to objects
- Searchable and filterable

#### Copy Object
- Max size for copy: 5GB
- Use multipart copy for larger objects

### Notifications
- **Supported Destinations**: NATS, Syslog, Kafka, Objects (local)
- **Event Types**:
  - Object events: Created, Removed, Accessed
  - Bucket events: Created, Removed, Versioning, Policy, WORM, Lifecycle, CORS, Website, Replication, Tagging

### IAM (Identity and Access Management)
- **User Types**: Local, External (LDAP/AD)
- **Authentication**: Access key + Secret key
- **Proxy Port**: 8445
- **Base URL**: `https://{IP}:9440/oss/iam_proxy`

## Objects Lite (PC-Based)
- Lightweight object storage on Prism Central
- **Namespace**: `pc-platform-nci`
- **Pod**: `objects-lite-0`
- **Endpoint**: `https://objects-lite.pc-platform-nci:7201`
- **Ports**: Atlas (7103), Object Store (7101), Metadata Server (7102)
- **External API**: `https://{PC_IP}:9440/api/prism/v4.0/objects/`
- **Internal API**: `https://{PC_IP}:9440/api/objects-lite-internal/v4.0/`

## Default Values

### Credentials
- Default admin: `admin` / `Nutanix.123`
- Default S3: `poseidon_access` / `poseidon_secret`

### Ports
- Prism: 9440
- S3 HTTP: Varies (NodePort or LoadBalancer)
- S3 HTTPS: Varies

### Regions
- Default: `us-east-1`

## Common S3 Operations & Required Permissions

| Operation | Permissions |
|-----------|-------------|
| head_bucket | read, write |
| list_objects | read |
| list_object_versions | read |
| get_object | read |
| put_object | write |
| delete_object | write |
| get_bucket_location | read, write |
| get_bucket_versioning | read |
| put_bucket_versioning | admin |
| put_bucket_policy | admin |
| delete_bucket | admin |

## Monitoring & Health

### Health Check Components
- Atlas
- Metadata Server
- Object Store Controller
- Chronos

### Alert Thresholds
- Memory: 90%
- CPU: 90%
- Storage: 90%

### Monitoring Interval
- Default: 120 seconds
