"""
S3 Tools for NOVA Backend

Implements S3/Object Storage operations using boto3.
"""
import uuid
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from ..config import get_s3_endpoint, get_s3_access_key, get_s3_secret_key, get_s3_region


def get_s3_client():
    """
    Get boto3 S3 client configured for Nutanix Objects.
    
    Returns:
        boto3 S3 client instance
    """
    return boto3.client(
        "s3",
        endpoint_url=get_s3_endpoint(),
        aws_access_key_id=get_s3_access_key(),
        aws_secret_access_key=get_s3_secret_key(),
        region_name=get_s3_region(),
        verify=False
    )


def create_bucket(bucket_name: str = None) -> dict:
    """
    Create a bucket in Nutanix Object Store.
    
    Args:
        bucket_name: Name of bucket to create. If not provided, generates a unique name.
        
    Returns:
        Result dictionary with status and bucket_name
    """
    try:
        s3 = get_s3_client()
        
        if not bucket_name:
            bucket_name = f"nova-bucket-{uuid.uuid4().hex[:6]}"
        
        s3.create_bucket(Bucket=bucket_name)
        
        return {
            "status": "success",
            "bucket_name": bucket_name,
            "message": f"Bucket '{bucket_name}' created successfully"
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code == 'BucketAlreadyExists':
            return {"status": "error", "error": f"Bucket '{bucket_name}' already exists"}
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_buckets() -> dict:
    """
    List all buckets in the Object Store.
    
    Returns:
        Result dictionary with status, count, and buckets list
    """
    try:
        s3 = get_s3_client()
        response = s3.list_buckets()
        
        buckets = [
            {
                "name": b["Name"],
                "created": b.get("CreationDate", "").isoformat() if b.get("CreationDate") else None
            }
            for b in response.get("Buckets", [])
        ]
        
        return {
            "status": "success",
            "count": len(buckets),
            "buckets": buckets
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_objects(bucket_name: str, prefix: str = "", max_keys: int = 1000) -> dict:
    """
    List objects in a bucket.
    
    Args:
        bucket_name: Name of the bucket
        prefix: Optional prefix to filter objects
        max_keys: Maximum number of objects to return
        
    Returns:
        Result dictionary with status, count, and objects list
    """
    try:
        s3 = get_s3_client()
        
        params = {"Bucket": bucket_name, "MaxKeys": max_keys}
        if prefix:
            params["Prefix"] = prefix
        
        response = s3.list_objects_v2(**params)
        
        if "Contents" not in response:
            return {
                "status": "success",
                "bucket": bucket_name,
                "objects": [],
                "count": 0
            }
        
        objects = [
            {
                "key": obj["Key"],
                "size": obj["Size"],
                "size_human": _format_size(obj["Size"]),
                "last_modified": obj.get("LastModified", "").isoformat() if obj.get("LastModified") else None
            }
            for obj in response["Contents"]
        ]
        
        return {
            "status": "success",
            "bucket": bucket_name,
            "objects": objects,
            "count": len(objects),
            "is_truncated": response.get("IsTruncated", False)
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code == 'NoSuchBucket':
            return {"status": "error", "error": f"Bucket '{bucket_name}' not found"}
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def put_object(bucket_name: str, key: str, content: str) -> dict:
    """
    Upload a text object to a bucket.
    
    Args:
        bucket_name: Target bucket name
        key: Object key (filename/path)
        content: Text content to upload
        
    Returns:
        Result dictionary with status and details
    """
    try:
        s3 = get_s3_client()
        
        body = content.encode("utf-8")
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=body,
            ContentType="text/plain"
        )
        
        return {
            "status": "success",
            "bucket": bucket_name,
            "key": key,
            "size": len(body),
            "message": f"Object '{key}' uploaded to '{bucket_name}'"
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code == 'NoSuchBucket':
            return {"status": "error", "error": f"Bucket '{bucket_name}' not found"}
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def delete_object(bucket_name: str, key: str) -> dict:
    """
    Delete an object from a bucket.
    
    Args:
        bucket_name: Bucket containing the object
        key: Object key to delete
        
    Returns:
        Result dictionary with status
    """
    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=bucket_name, Key=key)
        
        return {
            "status": "success",
            "bucket": bucket_name,
            "key": key,
            "message": f"Object '{key}' deleted from '{bucket_name}'"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_bucket_info(bucket_name: str) -> dict:
    """
    Get information about a specific bucket.
    
    Args:
        bucket_name: Name of the bucket
        
    Returns:
        Result dictionary with bucket details
    """
    try:
        s3 = get_s3_client()
        
        # Check if bucket exists
        s3.head_bucket(Bucket=bucket_name)
        
        # Get object count and size
        total_size = 0
        total_count = 0
        
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get('Contents', []):
                total_count += 1
                total_size += obj['Size']
        
        return {
            "status": "success",
            "bucket": bucket_name,
            "object_count": total_count,
            "total_size": total_size,
            "total_size_human": _format_size(total_size)
        }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        if error_code in ['NoSuchBucket', '404']:
            return {"status": "error", "error": f"Bucket '{bucket_name}' not found"}
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PB"
