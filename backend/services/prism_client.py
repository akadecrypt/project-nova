"""
Nutanix Prism Central API Client
Handles communication with Prism Central for Objects operations

API Reference from nutest-py3-tests/workflows/poseidon/rest_api/rest_constants.py
"""
import httpx
import base64
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import asyncio


@dataclass
class PrismConfig:
    """Prism connection configuration"""
    ip: str
    port: int = 9440
    username: str = "admin"
    password: str = ""
    verify_ssl: bool = False


class PrismClient:
    """
    Async client for Nutanix Prism Central API
    Based on nutest-py3-tests API patterns
    """
    
    # API URL patterns from nutest reference
    PC_GROUPS_URL = "/api/nutanix/v3/groups"
    PC_CLUSTERS_LIST_URL = "/api/nutanix/v3/clusters/list"
    OSS_GROUPS_URL = "/oss/api/nutanix/v3/groups"
    OBJECTSTORES_URL = "/oss/api/nutanix/v3/objectstores"
    OBJECTSTORE_PROXY_URL = "/oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}"
    IAM_PROXY_URL = "/oss/iam_proxy"
    
    def __init__(self, config: PrismConfig):
        self.config = config
        self.base_url = f"https://{config.ip}:{config.port}"
        self._client: Optional[httpx.AsyncClient] = None
        
    @property
    def auth_header(self) -> str:
        """Generate Basic Auth header"""
        credentials = f"{self.config.username}:{self.config.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"
    
    @property
    def headers(self) -> Dict[str, str]:
        """Default headers for API requests"""
        return {
            "Authorization": self.auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                verify=self.config.verify_ssl,
                timeout=30.0,
                headers=self.headers
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    def _get_url(self, path: str, **kwargs) -> str:
        """Build full URL with optional path formatting"""
        return f"{self.base_url}{path.format(**kwargs)}"
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to Prism Central"""
        try:
            client = await self.get_client()
            # Use clusters/list POST endpoint for connection test
            response = await client.post(
                self._get_url(self.PC_CLUSTERS_LIST_URL),
                json={"kind": "cluster", "length": 1}
            )
            
            if response.status_code == 200:
                return {"success": True, "message": "Connected to Prism Central"}
            elif response.status_code == 401:
                return {"success": False, "message": "Authentication failed - check credentials"}
            else:
                return {"success": False, "message": f"Connection failed: {response.status_code}"}
        except httpx.ConnectError:
            return {"success": False, "message": f"Cannot connect to {self.config.ip}:{self.config.port}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    # ==================== Cluster Operations ====================
    
    async def list_clusters(self) -> List[Dict[str, Any]]:
        """List all clusters"""
        client = await self.get_client()
        response = await client.post(
            self._get_url(self.PC_CLUSTERS_LIST_URL),
            json={"kind": "cluster", "length": 100}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("entities", [])
    
    # ==================== Objects Store Operations ====================
    
    async def list_object_stores(self) -> List[Dict[str, Any]]:
        """
        List all Object Stores using groups API
        Reference: PRISM_V3_OSS_LIST in rest_constants.py
        URL: oss/api/nutanix/v3/groups
        Method: POST
        """
        client = await self.get_client()
        
        # Method 1: Use groups API (recommended)
        try:
            response = await client.post(
                self._get_url(self.OSS_GROUPS_URL),
                json={
                    "entity_type": "objectstore",
                    "group_member_sort_attribute": "name",
                    "group_member_sort_order": "ASCENDING",
                    "group_member_count": 100,
                    "group_member_offset": 0,
                    "group_member_attributes": [
                        {"attribute": "uuid"},
                        {"attribute": "name"},
                        {"attribute": "deployment_version"},
                        {"attribute": "domain"},
                        {"attribute": "client_access_network_ip_used_list"}
                    ]
                }
            )
            if response.status_code == 200:
                data = response.json()
                # Parse groups API response format
                results = []
                group_results = data.get("group_results", [])
                if group_results:
                    for entity in group_results[0].get("entity_results", []):
                        entity_data = {}
                        for attr in entity.get("data", []):
                            attr_name = attr.get("name")
                            values = attr.get("values", [{}])
                            if values:
                                entity_data[attr_name] = values[0].get("values", [""])[0]
                        results.append(entity_data)
                return results
        except Exception as e:
            print(f"Groups API failed: {e}")
        
        # Method 2: Try objectstores/list endpoint
        try:
            response = await client.get(
                self._get_url(self.OBJECTSTORES_URL + "/list")
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("entities", [])
        except Exception as e:
            print(f"List API failed: {e}")
            
        return []
    
    async def get_object_store(self, oss_uuid: str) -> Dict[str, Any]:
        """
        Get Object Store details
        Reference: PRISM_V3_OSS_INFO in rest_constants.py
        URL: oss/api/nutanix/v3/objectstores/{oss_uuid}
        Method: GET
        """
        client = await self.get_client()
        response = await client.get(
            self._get_url(self.OBJECTSTORES_URL + "/{oss_uuid}", oss_uuid=oss_uuid)
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== Bucket Operations ====================
    
    async def list_buckets(self, oss_uuid: str = None) -> List[Dict[str, Any]]:
        """
        List all buckets in an Object Store using groups API
        Reference: PRISM_V3_BUCKET_LIST in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/groups
        Method: POST
        """
        client = await self.get_client()
        
        # If no oss_uuid provided, get first object store
        if not oss_uuid:
            stores = await self.list_object_stores()
            if not stores:
                return []
            oss_uuid = stores[0].get("uuid")
            if not oss_uuid:
                return []
        
        try:
            url = self._get_url(
                self.OBJECTSTORE_PROXY_URL + "/groups",
                oss_uuid=oss_uuid
            )
            response = await client.post(
                url,
                json={
                    "entity_type": "bucket",
                    "group_member_sort_attribute": "name",
                    "group_member_sort_order": "ASCENDING",
                    "group_member_count": 500,
                    "group_member_offset": 0,
                    "group_member_attributes": [
                        {"attribute": "name"},
                        {"attribute": "uuid"},
                        {"attribute": "storage_usage_bytes"},
                        {"attribute": "object_count"},
                        {"attribute": "versioning"},
                        {"attribute": "worm"},
                        {"attribute": "retention_duration_days"},
                        {"attribute": "owner_name"}
                    ]
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                # Parse groups API response format
                results = []
                group_results = data.get("group_results", [])
                if group_results:
                    for entity in group_results[0].get("entity_results", []):
                        bucket_data = {"oss_uuid": oss_uuid}
                        for attr in entity.get("data", []):
                            attr_name = attr.get("name")
                            values = attr.get("values", [{}])
                            if values:
                                val = values[0].get("values", [""])[0]
                                # Convert numeric strings
                                if attr_name in ["storage_usage_bytes", "object_count", "retention_duration_days"]:
                                    try:
                                        val = int(val) if val else 0
                                    except (ValueError, TypeError):
                                        val = 0
                                bucket_data[attr_name] = val
                        results.append(bucket_data)
                return results
        except Exception as e:
            print(f"Bucket list API failed: {e}")
            
        return []
    
    async def get_bucket(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Get bucket details
        Reference: PRISM_V3_BUCKET_INFO in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}
        Method: GET
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
    
    async def create_bucket(
        self,
        oss_uuid: str,
        name: str,
        versioning: bool = False,
        worm: bool = False,
        worm_retention_days: int = 0
    ) -> Dict[str, Any]:
        """
        Create a new bucket
        Reference: PRISM_V3_BUCKET_CREATE in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets
        Method: POST
        """
        payload = {
            "api_version": "v3",
            "metadata": {
                "kind": "bucket"
            },
            "spec": {
                "description": f"Bucket created by NOVA",
                "name": name,
                "resources": {
                    "features": []
                }
            }
        }
        
        if versioning:
            payload["spec"]["resources"]["features"].append("VERSIONING")
        if worm:
            payload["spec"]["resources"]["features"].append("WORM")
            payload["spec"]["resources"]["worm_retention_days"] = worm_retention_days
        
        if not payload["spec"]["resources"]["features"]:
            payload["spec"]["resources"]["features"] = None
        
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets",
            oss_uuid=oss_uuid
        )
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    async def delete_bucket(self, oss_uuid: str, bucket_name: str) -> bool:
        """Delete a bucket"""
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.delete(url)
        return response.status_code in [200, 202, 204]
    
    # ==================== IAM / Access Keys Operations ====================
    
    async def list_iam_users(self, oss_uuid: str) -> List[Dict[str, Any]]:
        """
        List IAM users
        Reference: IAM_GET_USERS in rest_constants.py
        URL: oss/iam_proxy/users
        Method: GET
        """
        client = await self.get_client()
        response = await client.get(
            self._get_url(self.IAM_PROXY_URL + "/users")
        )
        if response.status_code == 200:
            return response.json().get("entities", [])
        return []
    
    async def create_access_key(
        self,
        oss_uuid: str,
        username: str,
        display_name: str = "NOVA User"
    ) -> Dict[str, Any]:
        """
        Create access key for a user
        Reference: IAM_ADD_USERS in rest_constants.py
        URL: oss/iam_proxy/buckets_access_keys
        Method: POST
        """
        payload = {
            "users": [{
                "type": "external",
                "username": username,
                "display_name": display_name,
                "default_access_key_name": "nova_key"
            }]
        }
        
        client = await self.get_client()
        response = await client.post(
            self._get_url(self.IAM_PROXY_URL + "/buckets_access_keys"),
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    async def list_access_keys(self, oss_uuid: str) -> List[Dict[str, Any]]:
        """
        List access keys for an object store
        """
        client = await self.get_client()
        try:
            # Try using groups API to list access keys
            response = await client.post(
                self._get_url(self.IAM_PROXY_URL + "/groups"),
                json={
                    "entity_type": "access_key",
                    "group_member_count": 100,
                    "group_member_offset": 0,
                    "group_member_attributes": [
                        {"attribute": "access_key_id"},
                        {"attribute": "user_name"},
                        {"attribute": "created_time"}
                    ]
                }
            )
            if response.status_code == 200:
                data = response.json()
                results = []
                group_results = data.get("group_results", [])
                if group_results:
                    for entity in group_results[0].get("entity_results", []):
                        entity_data = {}
                        for attr in entity.get("data", []):
                            attr_name = attr.get("name")
                            values = attr.get("values", [{}])
                            if values:
                                entity_data[attr_name] = values[0].get("values", [""])[0]
                        results.append(entity_data)
                return results
        except Exception as e:
            print(f"Failed to list access keys: {e}")
        return []
    
    # ==================== Lifecycle Rules ====================
    
    async def get_lifecycle_rules(
        self,
        oss_uuid: str,
        bucket_name: str
    ) -> List[Dict[str, Any]]:
        """
        Get lifecycle rules for a bucket
        Reference: GET_LIFECYCLE_RULES in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/lifecycle_rules
        Method: GET
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/lifecycle_rules",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.get(url)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json().get("rules", [])
    
    async def set_lifecycle_rule(
        self,
        oss_uuid: str,
        bucket_name: str,
        rule_id: str,
        prefix: str = "",
        expiration_days: int = 0,
        transition_days: int = 0,
        transition_storage_class: str = "GLACIER"
    ) -> Dict[str, Any]:
        """
        Set lifecycle rule for a bucket
        Reference: SET_LIFECYCLE_RULES in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/lifecycle_rules
        Method: POST
        """
        rule = {
            "id": rule_id,
            "status": "Enabled",
            "filter": {"prefix": prefix} if prefix else {},
        }
        
        if expiration_days > 0:
            rule["expiration"] = {"days": expiration_days}
        if transition_days > 0:
            rule["transitions"] = [{
                "days": transition_days,
                "storage_class": transition_storage_class
            }]
        
        payload = {"rules": [rule]}
        
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/lifecycle_rules",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    
    # ==================== Bucket Stats (via groups API) ====================
    
    async def get_bucket_stats(
        self,
        oss_uuid: str,
        bucket_name: str = None
    ) -> Dict[str, Any]:
        """
        Get bucket usage statistics using groups API
        Reference: PRISM_V3_BUCKET_STATS in rest_constants.py
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/groups",
            oss_uuid=oss_uuid
        )
        
        payload = {
            "entity_type": "bucket",
            "group_member_count": 1,
            "group_member_attributes": [
                {"attribute": "storage_usage_bytes"},
                {"attribute": "owner_name"},
                {"attribute": "object_count"},
                {"attribute": "versioning"},
                {"attribute": "worm"},
                {"attribute": "retention_duration_days"},
                {"attribute": "tiering_usage_bytes"}
            ]
        }
        
        if bucket_name:
            payload["entity_ids"] = [bucket_name]
        
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return {"size_bytes": 0, "object_count": 0}
        
        data = response.json()
        # Parse response
        result = {"size_bytes": 0, "object_count": 0}
        group_results = data.get("group_results", [])
        if group_results:
            for entity in group_results[0].get("entity_results", []):
                for attr in entity.get("data", []):
                    name = attr.get("name")
                    values = attr.get("values", [{}])
                    if values:
                        val = values[0].get("values", ["0"])[0]
                        if name == "storage_usage_bytes":
                            result["size_bytes"] = int(val) if val else 0
                        elif name == "object_count":
                            result["object_count"] = int(val) if val else 0
        return result
    
    async def get_objectstore_stats(self, oss_uuid: str) -> Dict[str, Any]:
        """
        Get Object Store usage statistics using groups API
        Reference: PRISM_V3_STATS_LIST in rest_constants.py
        """
        client = await self.get_client()
        
        payload = {
            "entity_type": "objectstore",
            "entity_ids": [oss_uuid],
            "group_member_attributes": [
                {"attribute": "total_requests_sec", "operation": "AVG"},
                {"attribute": "puts_sec", "operation": "AVG"},
                {"attribute": "gets_sec", "operation": "AVG"},
                {"attribute": "total_throughput_in_sec", "operation": "AVG"},
                {"attribute": "total_throughput_out_sec", "operation": "AVG"}
            ]
        }
        
        response = await client.post(
            self._get_url(self.OSS_GROUPS_URL),
            json=payload
        )
        
        if response.status_code != 200:
            return {}
        
        return response.json()
    
    # ==================== Bucket Versioning Operations ====================
    
    async def suspend_bucket_versioning(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Suspend versioning on a bucket
        Reference: PRISM_V3_BUCKET_SUSPEND_VERSIONING in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/suspend_versioning
        Method: PUT
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/suspend_versioning",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.put(url)
        response.raise_for_status()
        return {"success": True, "message": f"Versioning suspended for {bucket_name}"}
    
    async def restore_bucket_versioning(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Restore versioning on a bucket
        Reference: PRISM_V3_BUCKET_RESTORE_VERSIONING in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/restore_versioning
        Method: PUT
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/restore_versioning",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.put(url)
        response.raise_for_status()
        return {"success": True, "message": f"Versioning restored for {bucket_name}"}
    
    # ==================== Bucket Policy Operations ====================
    
    async def get_bucket_policy(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Get bucket policy
        Reference: BUCKET_POLICY_URL in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/policy
        Method: GET
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/policy",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.get(url)
        if response.status_code == 404:
            return {"policy": None}
        response.raise_for_status()
        return response.json()
    
    async def set_bucket_policy(self, oss_uuid: str, bucket_name: str, policy: Dict) -> Dict[str, Any]:
        """
        Set bucket policy
        Reference: BUCKET_POLICY_URL in rest_constants.py
        URL: oss/api/nutanix/v3/objectstore_proxy/{oss_uuid}/buckets/{bucket_name}/policy
        Method: PUT
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}/policy",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        response = await client.put(url, json=policy)
        response.raise_for_status()
        return {"success": True, "message": f"Policy set for {bucket_name}"}
    
    # ==================== Bucket Sharing Operations ====================
    
    async def get_bucket_share(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Get bucket share information
        Reference: PRISM_V3_BUCKET_USERS in rest_constants.py
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/groups",
            oss_uuid=oss_uuid
        )
        payload = {
            "entity_ids": [bucket_name],
            "entity_type": "bucket",
            "group_member_attributes": [{"attribute": "buckets_share"}]
        }
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return {"shares": []}
        return response.json()
    
    async def get_bucket_owner(self, oss_uuid: str, bucket_name: str) -> Dict[str, Any]:
        """
        Get bucket owner information
        Reference: PRISM_V3_BUCKET_OWNER in rest_constants.py
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/groups",
            oss_uuid=oss_uuid
        )
        payload = {
            "entity_ids": [bucket_name],
            "entity_type": "bucket",
            "group_member_attributes": [
                {"attribute": "owner_name"},
                {"attribute": "owner_id"}
            ]
        }
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return {"owner": None}
        
        data = response.json()
        result = {}
        group_results = data.get("group_results", [])
        if group_results:
            for entity in group_results[0].get("entity_results", []):
                for attr in entity.get("data", []):
                    name = attr.get("name")
                    values = attr.get("values", [{}])
                    if values:
                        result[name] = values[0].get("values", [""])[0]
        return result
    
    # ==================== Alerts Operations ====================
    
    async def list_alerts(self, oss_uuid: str, severity: str = None) -> List[Dict[str, Any]]:
        """
        List alerts for an Object Store
        Reference: PRISM_V3_ALERTS_LIST in rest_constants.py
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/groups",
            oss_uuid=oss_uuid
        )
        payload = {
            "entity_type": "alert",
            "group_member_sort_attribute": "name",
            "group_member_sort_order": "ASCENDING",
            "group_member_count": 100,
            "group_member_offset": 0,
            "group_member_attributes": [
                {"attribute": "name"},
                {"attribute": "description"},
                {"attribute": "severity"},
                {"attribute": "create_time"},
                {"attribute": "state"}
            ]
        }
        
        if severity:
            payload["filter_criteria"] = f"severity=={severity}"
        
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return []
        
        data = response.json()
        results = []
        group_results = data.get("group_results", [])
        if group_results:
            for entity in group_results[0].get("entity_results", []):
                alert_data = {}
                for attr in entity.get("data", []):
                    name = attr.get("name")
                    values = attr.get("values", [{}])
                    if values:
                        alert_data[name] = values[0].get("values", [""])[0]
                results.append(alert_data)
        return results
    
    # ==================== WORM Operations ====================
    
    async def enable_worm(self, oss_uuid: str, bucket_name: str, retention_days: int = 30) -> Dict[str, Any]:
        """
        Enable WORM on a bucket
        Reference: PRISM_V3_BUCKET_CREATE_WORM in rest_constants.py
        """
        client = await self.get_client()
        
        # First get bucket info to get UUID
        bucket = await self.get_bucket(oss_uuid, bucket_name)
        bucket_uuid = bucket.get("metadata", {}).get("uuid", "")
        
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/buckets/{bucket_name}",
            oss_uuid=oss_uuid,
            bucket_name=bucket_name
        )
        
        payload = {
            "api_version": "v3",
            "metadata": {
                "kind": "bucket",
                "uuid": bucket_uuid
            },
            "spec": {
                "description": "enable_worm",
                "name": bucket_name,
                "resources": {
                    "features": ["WORM"],
                    "worm_retention_days": retention_days
                }
            }
        }
        
        response = await client.put(url, json=payload)
        response.raise_for_status()
        return {"success": True, "message": f"WORM enabled for {bucket_name} with {retention_days} day retention"}
    
    # ==================== User Quota Operations ====================
    
    async def get_user_quotas(self, oss_uuid: str) -> List[Dict[str, Any]]:
        """
        Get user quotas
        Reference: OSS_GET_QUOTA_REQUEST in rest_constants.py
        """
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/groups",
            oss_uuid=oss_uuid
        )
        payload = {
            "entity_type": "quota",
            "group_member_sort_attribute": "entity_id",
            "group_member_sort_order": "ASCENDING",
            "group_member_count": 1000,
            "group_member_offset": 0,
            "group_member_attributes": [
                {"attribute": "entity_id"},
                {"attribute": "user_name"},
                {"attribute": "storage_threshold"},
                {"attribute": "buckets_threshold"},
                {"attribute": "storage_used_bytes"},
                {"attribute": "buckets_used"},
                {"attribute": "enforcement_type"}
            ]
        }
        
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            return []
        
        data = response.json()
        results = []
        group_results = data.get("group_results", [])
        if group_results:
            for entity in group_results[0].get("entity_results", []):
                quota_data = {}
                for attr in entity.get("data", []):
                    name = attr.get("name")
                    values = attr.get("values", [{}])
                    if values:
                        quota_data[name] = values[0].get("values", [""])[0]
                results.append(quota_data)
        return results
    
    async def set_user_quota(
        self,
        oss_uuid: str,
        user_uuid: str,
        storage_threshold: int = 0,
        buckets_threshold: int = 0,
        enforcement_type: str = "HARD"
    ) -> Dict[str, Any]:
        """Set user quota"""
        client = await self.get_client()
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + "/users/quota",
            oss_uuid=oss_uuid
        )
        payload = {
            "user_uuid": user_uuid,
            "storage_threshold": storage_threshold,
            "buckets_threshold": buckets_threshold,
            "enforcement_type": enforcement_type
        }
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return {"success": True, "message": "Quota set successfully"}

    # ==================== Object Upload (S3 Compatible) ====================
    
    async def get_object_store_endpoint(self, oss_uuid: str) -> Optional[str]:
        """Get the S3-compatible endpoint for an object store"""
        stores = await self.list_object_stores()
        for store in stores:
            if store.get("uuid") == oss_uuid:
                # The client_access_network_ip_used_list contains the S3 endpoint IP
                ip_list = store.get("client_access_network_ip_used_list", "")
                if ip_list:
                    # Return first IP as endpoint
                    first_ip = ip_list.split(",")[0].strip()
                    return f"https://{first_ip}"
        return None
    
    async def upload_object(
        self,
        oss_uuid: str,
        bucket_name: str,
        object_key: str,
        file_path: str,
        content_type: str = "application/octet-stream"
    ) -> Dict[str, Any]:
        """
        Upload an object to a bucket using S3-compatible API
        
        This uses the Object Store's S3 endpoint, not Prism Central.
        Note: For production use, you'd want to use proper S3 credentials (access key/secret).
        This is a simplified version that attempts direct upload.
        """
        # For now, we'll use Prism's proxy endpoint for uploads
        # In a real implementation, you'd use boto3 with S3 credentials
        
        client = await self.get_client()
        
        # Read file content
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Use Prism proxy to upload (alternative approach)
        # This may need adjustment based on actual Nutanix Objects API
        url = self._get_url(
            self.OBJECTSTORE_PROXY_URL + f"/buckets/{bucket_name}/objects/{object_key}",
            oss_uuid=oss_uuid
        )
        
        try:
            response = await client.put(
                url,
                content=file_content,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(file_content))
                },
                timeout=300.0  # 5 minute timeout for large files
            )
            
            if response.status_code in [200, 201, 204]:
                return {
                    "success": True,
                    "object_key": object_key,
                    "bucket": bucket_name,
                    "size": len(file_content)
                }
            else:
                # If proxy upload fails, return info for S3 upload instead
                endpoint = await self.get_object_store_endpoint(oss_uuid)
                raise Exception(
                    f"Upload via Prism proxy failed (status {response.status_code}). "
                    f"Consider using S3 SDK with endpoint: {endpoint}"
                )
        except httpx.TimeoutException:
            raise Exception("Upload timed out. Try with a smaller file.")
        except Exception as e:
            # Provide helpful error message
            endpoint = await self.get_object_store_endpoint(oss_uuid)
            raise Exception(
                f"Upload failed: {str(e)}. "
                f"For large files, use S3-compatible tools with endpoint: {endpoint}"
            )


# Singleton instance management
_prism_client: Optional[PrismClient] = None


def get_prism_client(config: Optional[PrismConfig] = None) -> Optional[PrismClient]:
    """Get or create Prism client singleton"""
    global _prism_client
    if config:
        _prism_client = PrismClient(config)
    return _prism_client


def configure_prism(ip: str, port: int = 9440, username: str = "admin", password: str = "") -> PrismClient:
    """Configure and return Prism client"""
    config = PrismConfig(ip=ip, port=port, username=username, password=password)
    return get_prism_client(config)
