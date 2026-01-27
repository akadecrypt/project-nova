"""
Objects Router for NOVA Backend

Handles object storage related endpoints.
"""
from fastapi import APIRouter

from ..tools.s3_tools import list_buckets, get_bucket_info
from ..tools.prism_tools import get_object_stores

router = APIRouter(prefix="/api/objects", tags=["objects"])


@router.get("/stats")
async def get_object_stats():
    """Get object storage statistics"""
    try:
        buckets_result = list_buckets()
        
        if buckets_result.get("status") == "success":
            bucket_list = buckets_result.get("buckets", [])
            bucket_count = len(bucket_list)
            
            return {
                "total_buckets": bucket_count,
                "total_objects": 0,
                "total_size_gb": 0,
                "buckets": [b.get("name", b) if isinstance(b, dict) else b for b in bucket_list]
            }
        
        return {
            "total_buckets": 0,
            "total_objects": 0,
            "total_size_gb": 0,
            "buckets": [],
            "error": buckets_result.get("error")
        }
    except Exception as e:
        return {
            "total_buckets": 0,
            "total_objects": 0,
            "total_size_gb": 0,
            "error": str(e)
        }


@router.get("/stores")
async def get_stores():
    """Get all object stores from Prism Central"""
    return get_object_stores()


@router.get("/buckets")
async def list_all_buckets():
    """List all buckets"""
    return list_buckets()


@router.get("/buckets/{bucket_name}")
async def get_bucket(bucket_name: str):
    """Get information about a specific bucket"""
    return get_bucket_info(bucket_name)
