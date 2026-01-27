"""
Prism Central Tools for NOVA Backend

Implements Prism Central API operations for Object Store management.
"""
import urllib3
import requests
from typing import Optional, List

from ..config import get_pc_ip, get_pc_port, get_pc_username, get_pc_password

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _get_pc_base_url() -> str:
    """Get Prism Central base URL"""
    return f"https://{get_pc_ip()}:{get_pc_port()}"


def _get_pc_auth() -> tuple:
    """Get Prism Central auth tuple"""
    return (get_pc_username(), get_pc_password())


def get_object_stores(verify_ssl: bool = False) -> dict:
    """
    Get Object Store configurations from Prism Central.
    
    Args:
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Result dictionary with object stores data
    """
    pc_ip = get_pc_ip()
    if not pc_ip:
        return {"error": "Prism Central IP not configured"}
    
    url = f"{_get_pc_base_url()}/api/objects/v4.0/config/object-stores"
    
    try:
        response = requests.get(
            url,
            auth=_get_pc_auth(),
            verify=verify_ssl,
            timeout=15
        )
        
        if response.status_code == 401:
            return {
                "error": "Authentication failed",
                "status_code": 401,
                "hint": "Check Prism Central username and password"
            }
        
        if response.status_code != 200:
            return {
                "error": "Failed to fetch object stores",
                "status_code": response.status_code,
                "response_text": response.text[:500]
            }
        
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return {
                "error": "Non-JSON response from Prism Central",
                "content_type": content_type,
                "response_text": response.text[:500]
            }
        
        data = response.json()
        
        # Extract relevant information
        object_stores = []
        for store in data.get("data", []):
            object_stores.append({
                "ext_id": store.get("extId"),
                "name": store.get("name"),
                "domain": store.get("domain"),
                "region": store.get("region"),
                "state": store.get("state"),
                "total_capacity_bytes": store.get("totalCapacityInBytes"),
                "used_capacity_bytes": store.get("usedCapacityInBytes")
            })
        
        return {
            "status": "success",
            "count": len(object_stores),
            "object_stores": object_stores,
            "raw_response": data
        }
        
    except requests.exceptions.Timeout:
        return {"error": "Connection to Prism Central timed out"}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to Prism Central at {pc_ip}"}
    except Exception as e:
        return {"error": str(e)}


def fetch_object_store_stats_v4(
    object_store_ext_id: str,
    start_time: str,
    end_time: str,
    select_stats: Optional[List[str]] = None,
    sampling_interval: Optional[int] = None,
    stat_type: Optional[str] = None,
    verify_ssl: bool = False
) -> dict:
    """
    Fetch Object Store statistics using Prism Central v4 API.
    
    Args:
        object_store_ext_id: External ID (UUID) of the object store
        start_time: Start time in ISO 8601 format
        end_time: End time in ISO 8601 format
        select_stats: List of statistics to retrieve
        sampling_interval: Sampling interval in seconds
        stat_type: Type of statistics
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Result dictionary with statistics data
    """
    pc_ip = get_pc_ip()
    if not pc_ip:
        return {"error": "Prism Central IP not configured"}
    
    url = f"{_get_pc_base_url()}/api/objects/v4.0/stats/object-stores/{object_store_ext_id}"
    
    params = {
        "$startTime": start_time,
        "$endTime": end_time
    }
    
    if select_stats:
        params["$select"] = ",".join(select_stats)
    if sampling_interval is not None:
        params["$samplingInterval"] = sampling_interval
    if stat_type is not None:
        params["$statType"] = stat_type
    
    try:
        response = requests.get(
            url,
            params=params,
            auth=_get_pc_auth(),
            verify=verify_ssl,
            timeout=20
        )
        
        if response.status_code == 401:
            return {
                "error": "Authentication failed",
                "status_code": 401
            }
        
        if response.status_code == 404:
            return {
                "error": f"Object store '{object_store_ext_id}' not found",
                "status_code": 404
            }
        
        if response.status_code != 200:
            return {
                "error": "Failed to fetch object store stats",
                "status_code": response.status_code,
                "url": response.url,
                "response_text": response.text[:500]
            }
        
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return {
                "error": "Non-JSON stats response",
                "url": response.url,
                "response_text": response.text[:500]
            }
        
        payload = response.json()
        stats = payload.get("data", {}).get("stats", [])
        
        return {
            "status": "success",
            "object_store_ext_id": object_store_ext_id,
            "start_time": start_time,
            "end_time": end_time,
            "stats_count": len(stats),
            "stats": stats
        }
        
    except requests.exceptions.Timeout:
        return {"error": "Stats request timed out"}
    except requests.exceptions.ConnectionError:
        return {"error": f"Cannot connect to Prism Central at {pc_ip}"}
    except Exception as e:
        return {"error": str(e)}


def test_prism_connection() -> dict:
    """
    Test connection to Prism Central.
    
    Returns:
        Result dictionary with connection status
    """
    pc_ip = get_pc_ip()
    if not pc_ip:
        return {"success": False, "message": "Prism Central IP not configured"}
    
    url = f"{_get_pc_base_url()}/api/objects/v4.0/config/object-stores"
    
    try:
        response = requests.get(
            url,
            auth=_get_pc_auth(),
            verify=False,
            timeout=10
        )
        
        if response.status_code == 200:
            return {"success": True, "message": "Connected to Prism Central"}
        elif response.status_code == 401:
            return {"success": False, "message": "Authentication failed - check credentials"}
        else:
            return {"success": False, "message": f"HTTP {response.status_code}"}
            
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Cannot connect to {pc_ip}"}
    except Exception as e:
        return {"success": False, "message": str(e)}
