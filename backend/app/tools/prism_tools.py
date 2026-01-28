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


def _normalize_timestamp(ts: str) -> str:
    """
    Normalize timestamp to RFC 3339 format expected by Nutanix API.
    Converts 'Z' suffix to '+00:00' and ensures proper format.
    """
    if not ts:
        return ts
    # Replace Z with +00:00 for RFC 3339 compliance
    if ts.endswith('Z'):
        ts = ts[:-1] + '+00:00'
    # Ensure the timestamp has timezone info
    if '+' not in ts and '-' not in ts[-6:]:
        ts = ts + '+00:00'
    return ts


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
        start_time: Start time in RFC 3339 format (e.g., 2026-01-28T07:55:00+00:00)
        end_time: End time in RFC 3339 format
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
    
    # Normalize timestamps to RFC 3339 format
    start_time = _normalize_timestamp(start_time)
    end_time = _normalize_timestamp(end_time)
    
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


def get_s3_endpoint_from_prism() -> dict:
    """
    Get S3 endpoint URL from the first Object Store in Prism Central.
    
    Returns:
        Result dictionary with S3 endpoint info
    """
    result = get_object_stores()
    
    if result.get("error"):
        return {"success": False, "message": result.get("error")}
    
    stores = result.get("object_stores", [])
    if not stores:
        return {"success": False, "message": "No Object Stores found in Prism Central"}
    
    # Get the first object store (or one that's in COMPLETE state)
    selected_store = None
    for store in stores:
        if store.get("state") == "COMPLETE":
            selected_store = store
            break
    
    if not selected_store:
        selected_store = stores[0]
    
    domain = selected_store.get("domain")
    if not domain:
        return {"success": False, "message": "Object Store has no domain configured"}
    
    # Construct S3 endpoint URL (typically https on port 443 or http on 80)
    # The domain is usually the S3 endpoint
    s3_endpoint = f"https://{domain}"
    
    return {
        "success": True,
        "endpoint": s3_endpoint,
        "object_store_name": selected_store.get("name"),
        "object_store_id": selected_store.get("ext_id"),
        "region": selected_store.get("region") or "us-east-1",
        "all_stores": [
            {
                "name": s.get("name"),
                "domain": s.get("domain"),
                "state": s.get("state")
            }
            for s in stores
        ]
    }


def get_or_create_iam_user(username: str = "nova-service-account") -> dict:
    """
    Get or create an IAM user and generate access keys using Prism Central v4 API.
    
    Args:
        username: Username for the IAM service account
        
    Returns:
        Result dictionary with access_key and secret_key
    """
    pc_ip = get_pc_ip()
    if not pc_ip:
        return {"success": False, "message": "Prism Central IP not configured"}
    
    base_url = _get_pc_base_url()
    auth = _get_pc_auth()
    headers = {"Content-Type": "application/json"}
    
    try:
        # Step 1: List users to check if our user exists
        list_url = f"{base_url}/api/iam/v4.0.b1/authn/users"
        response = requests.get(
            list_url,
            auth=auth,
            verify=False,
            timeout=15
        )
        
        user_ext_id = None
        if response.status_code == 200:
            data = response.json()
            users = data.get("data", [])
            for user in users:
                if user.get("username") == username:
                    user_ext_id = user.get("extId")
                    break
        
        # Step 2: Create user if not exists
        if not user_ext_id:
            create_user_url = f"{base_url}/api/iam/v4.0.b1/authn/users"
            user_payload = {
                "username": username,
                "userType": "SERVICE_ACCOUNT",
                "displayName": "NOVA Service Account"
            }
            
            response = requests.post(
                create_user_url,
                auth=auth,
                json=user_payload,
                verify=False,
                timeout=15
            )
            
            if response.status_code in [200, 201, 202]:
                data = response.json()
                user_ext_id = data.get("data", {}).get("extId")
            else:
                return {
                    "success": False, 
                    "message": f"Failed to create user: {response.status_code} - {response.text[:200]}"
                }
        
        if not user_ext_id:
            return {"success": False, "message": "Could not get or create IAM user"}
        
        # Step 3: Create access keys for the user
        create_key_url = f"{base_url}/api/iam/v4.0.b1/authn/users/{user_ext_id}/keys"
        key_payload = {
            "name": f"nova-key-{int(__import__('time').time())}"
        }
        
        response = requests.post(
            create_key_url,
            auth=auth,
            json=key_payload,
            verify=False,
            timeout=15
        )
        
        if response.status_code in [200, 201, 202]:
            data = response.json()
            key_data = data.get("data", {})
            access_key = key_data.get("accessKeyId") or key_data.get("keyDetails", {}).get("accessKey")
            secret_key = key_data.get("secretAccessKey") or key_data.get("keyDetails", {}).get("secretKey")
            
            if access_key and secret_key:
                return {
                    "success": True,
                    "access_key": access_key,
                    "secret_key": secret_key,
                    "user_id": user_ext_id,
                    "username": username,
                    "message": "Successfully created IAM credentials"
                }
            else:
                return {
                    "success": False,
                    "message": "Key created but credentials not in response",
                    "raw_response": data
                }
        else:
            return {
                "success": False, 
                "message": f"Failed to create keys: {response.status_code} - {response.text[:200]}"
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Request to Prism Central timed out"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Cannot connect to Prism Central at {pc_ip}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_object_store_clusters() -> dict:
    """
    Get Object Store cluster IPs from Prism Central.
    
    Queries Prism Central for all object stores and extracts
    the cluster/node IPs that can be used for SSH-based log collection.
    
    Returns:
        Result dictionary with cluster information for each object store
    """
    pc_ip = get_pc_ip()
    if not pc_ip:
        return {"success": False, "message": "Prism Central IP not configured"}
    
    # First get object stores
    stores_result = get_object_stores()
    if stores_result.get("error"):
        return {"success": False, "message": stores_result.get("error")}
    
    def extract_ip_from_object(ip_obj):
        """Extract IP address from Prism v4 API IP object format"""
        if not ip_obj:
            return None
        if isinstance(ip_obj, str):
            return ip_obj
        if isinstance(ip_obj, dict):
            # Handle nested structure: ipv4.value or ipv6.value
            ipv4 = ip_obj.get("ipv4") or ip_obj.get("iPv4")
            if ipv4 and isinstance(ipv4, dict):
                return ipv4.get("value")
            ipv6 = ip_obj.get("ipv6") or ip_obj.get("iPv6")
            if ipv6 and isinstance(ipv6, dict):
                return ipv6.get("value")
            # Direct value field
            return ip_obj.get("value") or ip_obj.get("ip") or ip_obj.get("address")
        return None
    
    clusters = []
    raw_data = stores_result.get("raw_response", {}).get("data", [])
    
    for store in raw_data:
        store_name = store.get("name")
        store_id = store.get("extId")
        domain = store.get("domain")
        state = store.get("state")
        
        # Extract cluster IPs from various fields in the API response
        cluster_ips = []
        
        # Get from publicNetworkIps (list of IP objects)
        public_ips = store.get("publicNetworkIps") or []
        for ip_obj in public_ips:
            ip = extract_ip_from_object(ip_obj)
            if ip:
                cluster_ips.append(ip)
        
        # Get from storageNetworkVip (single IP object)
        storage_vip = store.get("storageNetworkVip")
        if storage_vip:
            ip = extract_ip_from_object(storage_vip)
            if ip:
                cluster_ips.append(ip)
        
        # Get from storageNetworkDnsIp
        storage_dns = store.get("storageNetworkDnsIp")
        if storage_dns:
            ip = extract_ip_from_object(storage_dns)
            if ip:
                cluster_ips.append(ip)
        
        # Try to get from clusterReference
        cluster_ref = store.get("clusterReference") or store.get("cluster_reference")
        if cluster_ref:
            ip = extract_ip_from_object(cluster_ref)
            if ip:
                cluster_ips.append(ip)
        
        # Try to get from nodes/nodeIpList
        nodes = store.get("nodes") or store.get("nodeIpList") or store.get("node_ip_list")
        if nodes and isinstance(nodes, list):
            for node in nodes:
                ip = extract_ip_from_object(node)
                if ip:
                    cluster_ips.append(ip)
        
        # Try to extract from domain if no IPs found
        if not cluster_ips and domain:
            import re
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', domain)
            if ip_match:
                cluster_ips.append(ip_match.group(1))
        
        # Remove duplicates while preserving order
        seen = set()
        unique_ips = []
        for ip in cluster_ips:
            if ip and ip not in seen:
                seen.add(ip)
                unique_ips.append(ip)
        
        clusters.append({
            "object_store_name": store_name,
            "object_store_id": store_id,
            "domain": domain,
            "state": state,
            "cluster_ips": unique_ips,
            "primary_ip": unique_ips[0] if unique_ips else None
        })
    
    # Filter to active stores (COMPLETE or OBJECT_STORE_AVAILABLE)
    active_states = ["COMPLETE", "OBJECT_STORE_AVAILABLE"]
    active_clusters = [c for c in clusters if c.get("state") in active_states]
    
    return {
        "success": True,
        "count": len(active_clusters),
        "clusters": active_clusters,
        "all_clusters": clusters
    }


def auto_configure_s3_from_prism() -> dict:
    """
    Auto-configure S3 settings by fetching endpoint and creating IAM credentials from Prism Central.
    
    Returns:
        Complete S3 configuration including endpoint, access_key, and secret_key
    """
    # Get S3 endpoint from Object Store
    endpoint_result = get_s3_endpoint_from_prism()
    if not endpoint_result.get("success"):
        return endpoint_result
    
    # Get or create IAM user and keys
    iam_result = get_or_create_iam_user()
    if not iam_result.get("success"):
        return {
            "success": False,
            "message": f"Got endpoint but failed to create credentials: {iam_result.get('message')}",
            "endpoint": endpoint_result.get("endpoint")
        }
    
    return {
        "success": True,
        "endpoint": endpoint_result.get("endpoint"),
        "access_key": iam_result.get("access_key"),
        "secret_key": iam_result.get("secret_key"),
        "region": endpoint_result.get("region", "us-east-1"),
        "object_store_name": endpoint_result.get("object_store_name"),
        "iam_username": iam_result.get("username"),
        "message": "S3 configuration auto-provisioned from Prism Central"
    }
