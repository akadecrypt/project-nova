"""
NOVA Chat Agent Service
Processes user messages and executes Nutanix Objects operations
"""
import re
import json
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncio

from .vector_db import VectorDBService, get_vector_db
from .prism_client import PrismClient, PrismConfig, get_prism_client, configure_prism


@dataclass
class AgentResponse:
    """Response from the chat agent"""
    message: str
    intent: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    code_block: Optional[str] = None
    code_lang: str = "json"
    suggestions: Optional[List[str]] = None


class ChatAgent:
    """
    AI Agent for Nutanix Objects operations
    Uses vector DB for intent matching and knowledge retrieval
    """
    
    def __init__(self, vector_db: VectorDBService):
        self.vector_db = vector_db
        self.prism_client: Optional[PrismClient] = None
        self.current_objectstore_uuid: Optional[str] = None
        
    def set_prism_client(self, client: PrismClient):
        """Set the Prism client"""
        self.prism_client = client
    
    async def process_message(self, message: str, session_id: str = "default", context: dict = None) -> AgentResponse:
        """Process user message and return appropriate response"""
        
        # Store conversation
        self.vector_db.add_conversation(session_id, "user", message)
        
        # Match intent
        intent_result = self.vector_db.match_intent(message)
        intent = intent_result["intent"]
        confidence = intent_result["confidence"]
        
        # Extract entities from message
        entities = self._extract_entities(message)
        
        # Merge context into entities (context takes precedence for object store/bucket selection)
        if context:
            if context.get('objectstore_uuid') and not entities.get('objectstore_uuid'):
                entities['objectstore_uuid'] = context['objectstore_uuid']
            if context.get('bucket_name') and not entities.get('bucket_name'):
                entities['bucket_name'] = context['bucket_name']
        
        # Route to appropriate handler
        try:
            if intent == "help" or confidence < 0.3:
                response = self._handle_help(message)
            elif intent == "test_connection":
                response = await self._handle_test_connection()
            elif intent == "configure_prism":
                response = await self._handle_configure_prism(entities)
            elif intent == "list_object_stores":
                response = await self._handle_list_object_stores()
            elif intent == "list_buckets":
                response = await self._handle_list_buckets(entities)
            elif intent == "create_bucket":
                response = await self._handle_create_bucket(entities, message)
            elif intent == "delete_bucket":
                response = await self._handle_delete_bucket(entities)
            elif intent == "get_bucket_info":
                response = await self._handle_get_bucket_info(entities)
            elif intent == "list_objects":
                response = await self._handle_list_objects(entities)
            elif intent == "set_lifecycle":
                response = await self._handle_set_lifecycle(entities, message)
            elif intent == "get_lifecycle":
                response = await self._handle_get_lifecycle(entities)
            elif intent == "get_stats":
                response = await self._handle_get_stats(entities)
            elif intent == "create_access_key":
                response = await self._handle_create_access_key(entities)
            elif intent == "list_access_keys":
                response = await self._handle_list_access_keys()
            elif intent == "suspend_versioning":
                response = await self._handle_suspend_versioning(entities)
            elif intent == "restore_versioning":
                response = await self._handle_restore_versioning(entities)
            elif intent == "list_alerts":
                response = await self._handle_list_alerts(entities)
            elif intent == "enable_worm":
                response = await self._handle_enable_worm(entities)
            elif intent == "get_bucket_policy":
                response = await self._handle_get_bucket_policy(entities)
            else:
                response = self._handle_unknown(message, intent_result)
        except Exception as e:
            response = AgentResponse(
                message=f"I encountered an error: {str(e)}",
                intent=intent,
                success=False,
                suggestions=["Check Prism connection", "Try 'test connection'"]
            )
        
        # Store response
        self.vector_db.add_conversation(session_id, "assistant", response.message)
        
        return response
    
    def _extract_entities(self, message: str) -> Dict[str, Any]:
        """Extract entities like bucket names, numbers from message"""
        entities = {}
        
        # Extract bucket name patterns
        bucket_patterns = [
            r'bucket\s+(?:named?|called?)?\s*["\']?([a-z0-9][a-z0-9\-]{1,61}[a-z0-9])["\']?',
            r'["\']([a-z0-9][a-z0-9\-]{1,61}[a-z0-9])["\']?\s+bucket',
            r'(?:in|from|to)\s+["\']?([a-z0-9][a-z0-9\-]{1,61}[a-z0-9])["\']?'
        ]
        
        for pattern in bucket_patterns:
            match = re.search(pattern, message.lower())
            if match:
                entities["bucket_name"] = match.group(1)
                break
        
        # Extract numbers (for days, capacity, etc.)
        day_match = re.search(r'(\d+)\s*days?', message.lower())
        if day_match:
            entities["days"] = int(day_match.group(1))
        
        # Extract versioning preference
        if "versioning" in message.lower():
            entities["versioning"] = "enabled" in message.lower() or "with versioning" in message.lower()
        
        # Extract username for access keys
        user_match = re.search(r'user\s+["\']?([a-zA-Z0-9_\-@.]+)["\']?', message)
        if user_match:
            entities["username"] = user_match.group(1)
        
        # Extract prefix for lifecycle
        prefix_match = re.search(r'prefix\s+["\']?([a-zA-Z0-9_\-/]+)["\']?', message)
        if prefix_match:
            entities["prefix"] = prefix_match.group(1)
        
        return entities
    
    def _check_prism_configured(self) -> Tuple[bool, Optional[AgentResponse]]:
        """Check if Prism is configured"""
        if not self.prism_client:
            return False, AgentResponse(
                message="Prism is not configured. Please set up your Prism connection first in Settings, or tell me the Prism IP address.",
                intent="error",
                success=False,
                suggestions=[
                    "Go to Settings and enter Prism IP",
                    "Say 'configure prism at 10.0.0.1'",
                    "Test connection"
                ]
            )
        return True, None
    
    async def _get_default_objectstore(self) -> Optional[str]:
        """Get the first available object store UUID"""
        if self.current_objectstore_uuid:
            return self.current_objectstore_uuid
        
        if not self.prism_client:
            print("Prism client not configured")
            return None
            
        try:
            stores = await self.prism_client.list_object_stores()
            print(f"Found {len(stores) if stores else 0} object stores: {stores}")
            
            if stores:
                # Handle both old format (metadata.uuid) and new groups API format (uuid directly)
                first_store = stores[0]
                if isinstance(first_store, dict):
                    # New groups API format returns uuid directly
                    uuid = first_store.get("uuid")
                    if not uuid:
                        # Try old format with metadata
                        uuid = first_store.get("metadata", {}).get("uuid")
                    print(f"Using objectstore UUID: {uuid}")
                    if uuid:
                        self.current_objectstore_uuid = uuid
                        return self.current_objectstore_uuid
            else:
                print("No object stores returned from API")
        except Exception as e:
            import traceback
            print(f"Error getting default objectstore: {e}")
            traceback.print_exc()
        return None
    
    # ==================== Intent Handlers ====================
    
    def _handle_help(self, message: str) -> AgentResponse:
        """Handle help requests"""
        help_text = """I'm NOVA, your Nutanix Objects Virtual Assistant. Here's what I can help you with:

**Bucket Operations:**
• Create, list, and delete buckets
• Get bucket details and statistics
• Configure versioning and WORM

**Lifecycle Management:**
• Set up lifecycle policies
• Configure auto-archival rules
• Set data expiration

**Object Operations:**
• List objects in buckets
• View object details

**Access Management:**
• Create and list access keys
• Manage credentials

**Analytics:**
• View storage usage statistics
• Get bucket metrics

Just tell me what you'd like to do in natural language!"""
        
        return AgentResponse(
            message=help_text,
            intent="help",
            success=True,
            suggestions=[
                "List all buckets",
                "Create a bucket named my-data",
                "Show storage usage",
                "Set lifecycle policy for logs bucket"
            ]
        )
    
    async def _handle_test_connection(self) -> AgentResponse:
        """Handle connection test"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        result = await self.prism_client.test_connection()
        
        if result["success"]:
            # Get additional info
            try:
                stores = await self.prism_client.list_object_stores()
                store_count = len(stores)
                store_info = f"\n\nFound {store_count} Object Store(s)."
                if stores:
                    # Handle both old and new API formats
                    first_store = stores[0]
                    self.current_objectstore_uuid = first_store.get("uuid") or first_store.get("metadata", {}).get("uuid")
            except:
                store_info = ""
            
            return AgentResponse(
                message=f"✅ Successfully connected to Prism Central at {self.prism_client.config.ip}!{store_info}",
                intent="test_connection",
                success=True,
                data=result
            )
        else:
            return AgentResponse(
                message=f"❌ Connection failed: {result['message']}",
                intent="test_connection",
                success=False,
                suggestions=["Check Prism IP address", "Verify credentials", "Ensure network connectivity"]
            )
    
    async def _handle_configure_prism(self, entities: Dict) -> AgentResponse:
        """Handle Prism configuration"""
        return AgentResponse(
            message="To configure Prism connection, please go to the **Settings** page and enter:\n\n• Prism IP address\n• Port (default: 9440)\n• Username\n• Password\n\nOr use the API endpoint `/api/config/prism` to set it programmatically.",
            intent="configure_prism",
            success=True,
            suggestions=["Go to Settings", "Test connection after configuration"]
        )
    
    async def _handle_list_object_stores(self) -> AgentResponse:
        """Handle listing object stores"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        stores = await self.prism_client.list_object_stores()
        
        if not stores:
            return AgentResponse(
                message="No Object Stores found. You may need to create one first.",
                intent="list_object_stores",
                success=True,
                data={"stores": []}
            )
        
        # Format response - handle both old and new API formats
        store_list = []
        for store in stores:
            # New groups API format has uuid/name at top level
            if "uuid" in store and "name" in store:
                store_list.append({
                    "name": store.get("name", "Unknown"),
                    "uuid": store.get("uuid"),
                    "domain": store.get("domain", "N/A"),
                    "version": store.get("deployment_version", "N/A")
                })
            else:
                # Old format with spec/metadata structure
                spec = store.get("spec", {})
                status = store.get("status", {})
                store_list.append({
                    "name": spec.get("name", "Unknown"),
                    "uuid": store.get("metadata", {}).get("uuid", "Unknown"),
                    "state": status.get("state", "Unknown"),
                    "endpoint": status.get("resources", {}).get("client_access_endpoint", "N/A")
                })
        
        code_block = json.dumps(store_list, indent=2)
        
        return AgentResponse(
            message=f"Found {len(stores)} Object Store(s):",
            intent="list_object_stores",
            success=True,
            data={"stores": store_list},
            code_block=code_block,
            code_lang="json"
        )
    
    async def _handle_list_buckets(self, entities: Dict) -> AgentResponse:
        """Handle listing buckets"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available. Please create an Object Store first.",
                intent="list_buckets",
                success=False
            )
        
        buckets = await self.prism_client.list_buckets(objectstore_uuid)
        
        if not buckets:
            return AgentResponse(
                message="No buckets found. Would you like to create one?",
                intent="list_buckets",
                success=True,
                data={"buckets": []},
                suggestions=["Create a bucket named my-data", "Create bucket with versioning"]
            )
        
        bucket_list = []
        for bucket in buckets:
            # Handle new groups API format (flat structure) and old format
            if "name" in bucket:
                # New groups API format - data is directly in bucket dict
                bucket_list.append({
                    "name": bucket.get("name", "Unknown"),
                    "versioning": bucket.get("versioning", "Disabled"),
                    "worm_enabled": bucket.get("worm", "Disabled") == "Enabled",
                    "size_bytes": bucket.get("storage_usage_bytes", 0),
                    "object_count": bucket.get("object_count", 0)
                })
            else:
                # Old format with spec/resources structure
                spec = bucket.get("spec", {})
                resources = spec.get("resources", {})
                bucket_list.append({
                    "name": spec.get("name", "Unknown"),
                    "versioning": resources.get("versioning", "Disabled"),
                    "worm_enabled": resources.get("worm_spec", {}).get("is_worm_enabled", False)
                })
        
        code_block = json.dumps(bucket_list, indent=2)
        
        return AgentResponse(
            message=f"Found {len(buckets)} bucket(s):",
            intent="list_buckets",
            success=True,
            data={"buckets": bucket_list},
            code_block=code_block,
            code_lang="json"
        )
    
    async def _handle_create_bucket(self, entities: Dict, message: str) -> AgentResponse:
        """Handle bucket creation"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please provide a bucket name. For example: 'Create a bucket named my-data'",
                intent="create_bucket",
                success=False,
                suggestions=["Create a bucket named prod-backups", "Create bucket called logs-archive"]
            )
        
        versioning = entities.get("versioning", False)
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available. Please create an Object Store first.",
                intent="create_bucket",
                success=False
            )
        
        try:
            result = await self.prism_client.create_bucket(
                oss_uuid=objectstore_uuid,
                name=bucket_name,
                versioning=versioning
            )
            
            config = {
                "bucket_name": bucket_name,
                "versioning": "Enabled" if versioning else "Disabled",
                "status": "Created"
            }
            
            return AgentResponse(
                message=f"✅ Successfully created bucket **{bucket_name}**!",
                intent="create_bucket",
                success=True,
                data=config,
                code_block=json.dumps(config, indent=2),
                code_lang="json",
                suggestions=[f"List objects in {bucket_name}", f"Set lifecycle for {bucket_name}"]
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Failed to create bucket: {str(e)}",
                intent="create_bucket",
                success=False
            )
    
    async def _handle_delete_bucket(self, entities: Dict) -> AgentResponse:
        """Handle bucket deletion"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify which bucket to delete. For example: 'Delete bucket named old-data'",
                intent="delete_bucket",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="delete_bucket",
                success=False
            )
        
        try:
            success = await self.prism_client.delete_bucket(objectstore_uuid, bucket_name)
            
            if success:
                return AgentResponse(
                    message=f"✅ Successfully deleted bucket **{bucket_name}**",
                    intent="delete_bucket",
                    success=True
                )
            else:
                return AgentResponse(
                    message=f"❌ Failed to delete bucket {bucket_name}. It may not be empty.",
                    intent="delete_bucket",
                    success=False,
                    suggestions=["Delete all objects first", "Check bucket name"]
                )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error deleting bucket: {str(e)}",
                intent="delete_bucket",
                success=False
            )
    
    async def _handle_get_bucket_info(self, entities: Dict) -> AgentResponse:
        """Handle getting bucket details"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        
        # Check for reserved/invalid bucket names that might be confused with API endpoints
        reserved_names = ["stats", "info", "list", "create", "delete", "policy", "lifecycle", "groups"]
        if not bucket_name or bucket_name.lower() in reserved_names:
            # If user asked for "stats", redirect to get_stats handler
            if bucket_name and bucket_name.lower() == "stats":
                return await self._handle_get_stats(entities)
            return AgentResponse(
                message="Please specify a valid bucket name. For example: 'Show info for bucket prod-data'",
                intent="get_bucket_info",
                success=False,
                suggestions=["List buckets", "Show storage stats"]
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="get_bucket_info",
                success=False
            )
        
        try:
            # First verify the bucket exists using list_buckets
            buckets = await self.prism_client.list_buckets(objectstore_uuid)
            bucket_exists = any(b.get("name") == bucket_name for b in buckets)
            
            if not bucket_exists:
                return AgentResponse(
                    message=f"❌ Bucket '{bucket_name}' not found. Use 'list buckets' to see available buckets.",
                    intent="get_bucket_info",
                    success=False,
                    suggestions=["List buckets"]
                )
            
            # Get stats using the groups API (safer approach)
            stats = await self.prism_client.get_bucket_stats(objectstore_uuid, bucket_name)
            
            # Try to get detailed bucket info, but don't fail if it errors
            bucket = None
            try:
                bucket = await self.prism_client.get_bucket(objectstore_uuid, bucket_name)
            except Exception:
                pass  # Continue with stats only
            
            # Build info from available data
            info = {
                "name": bucket_name,
                "size_bytes": stats.get("size_bytes", 0),
                "object_count": stats.get("object_count", 0),
                "versioning": "Unknown",
                "worm_enabled": False
            }
            
            # Add detailed info if available
            if bucket:
                spec = bucket.get("spec", {})
                resources = spec.get("resources", {})
                info["versioning"] = resources.get("versioning", "Disabled")
                info["worm_enabled"] = resources.get("worm_spec", {}).get("is_worm_enabled", False)
            
            size_human = self._format_bytes(info["size_bytes"])
            
            # Build message based on available info
            msg_parts = [f"**Bucket: {bucket_name}**", "", f"• Size: {size_human}", f"• Objects: {info['object_count']:,}"]
            if info["versioning"] != "Unknown":
                msg_parts.append(f"• Versioning: {info['versioning']}")
                msg_parts.append(f"• WORM: {'Enabled' if info['worm_enabled'] else 'Disabled'}")
            
            return AgentResponse(
                message="\n".join(msg_parts),
                intent="get_bucket_info",
                success=True,
                data=info,
                code_block=json.dumps(info, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error getting bucket info: {str(e)}",
                intent="get_bucket_info",
                success=False,
                suggestions=["List buckets", "Show storage stats"]
            )
    
    async def _handle_list_objects(self, entities: Dict) -> AgentResponse:
        """Handle listing objects"""
        # Note: Full object listing requires S3 API, not Prism API
        # This is a placeholder that shows the pattern
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket. For example: 'List objects in bucket prod-data'",
                intent="list_objects",
                success=False
            )
        
        return AgentResponse(
            message=f"To list objects in **{bucket_name}**, you can use the S3 API with the Objects endpoint.\n\nHere's an example using AWS CLI:",
            intent="list_objects",
            success=True,
            code_block=f"aws s3 ls s3://{bucket_name}/ --endpoint-url https://objects.example.com",
            code_lang="bash",
            suggestions=["Get bucket info", "Set lifecycle policy"]
        )
    
    async def _handle_set_lifecycle(self, entities: Dict, message: str) -> AgentResponse:
        """Handle setting lifecycle policy"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        days = entities.get("days", 30)
        prefix = entities.get("prefix", "")
        
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket. For example: 'Set lifecycle for bucket logs to delete after 90 days'",
                intent="set_lifecycle",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="set_lifecycle",
                success=False
            )
        
        # Determine action type from message
        is_archive = "archive" in message.lower() or "glacier" in message.lower() or "transition" in message.lower()
        is_delete = "delete" in message.lower() or "expire" in message.lower() or "expiration" in message.lower()
        
        try:
            rule_id = f"nova-rule-{int(datetime.now().timestamp())}"
            
            await self.prism_client.set_lifecycle_rule(
                oss_uuid=objectstore_uuid,
                bucket_name=bucket_name,
                rule_id=rule_id,
                prefix=prefix,
                expiration_days=days if is_delete else 0,
                transition_days=days if is_archive else 0,
                transition_storage_class="GLACIER"
            )
            
            action = "transition to GLACIER" if is_archive else "expire"
            
            rule_config = {
                "rule_id": rule_id,
                "bucket": bucket_name,
                "prefix": prefix or "(all objects)",
                "action": action,
                "days": days
            }
            
            return AgentResponse(
                message=f"✅ Created lifecycle rule for **{bucket_name}**\n\nObjects {f'with prefix {prefix} ' if prefix else ''}will {action} after {days} days.",
                intent="set_lifecycle",
                success=True,
                data=rule_config,
                code_block=json.dumps(rule_config, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error setting lifecycle: {str(e)}",
                intent="set_lifecycle",
                success=False
            )
    
    async def _handle_get_lifecycle(self, entities: Dict) -> AgentResponse:
        """Handle getting lifecycle rules"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket. For example: 'Show lifecycle rules for bucket logs'",
                intent="get_lifecycle",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="get_lifecycle",
                success=False
            )
        
        try:
            rules = await self.prism_client.get_lifecycle_rules(objectstore_uuid, bucket_name)
            
            if not rules:
                return AgentResponse(
                    message=f"No lifecycle rules configured for **{bucket_name}**",
                    intent="get_lifecycle",
                    success=True,
                    suggestions=[f"Set lifecycle for {bucket_name} to delete after 30 days"]
                )
            
            return AgentResponse(
                message=f"Lifecycle rules for **{bucket_name}**:",
                intent="get_lifecycle",
                success=True,
                data={"rules": rules},
                code_block=json.dumps(rules, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error getting lifecycle rules: {str(e)}",
                intent="get_lifecycle",
                success=False
            )
    
    async def _handle_get_stats(self, entities: Dict) -> AgentResponse:
        """Handle getting statistics"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="get_stats",
                success=False
            )
        
        bucket_name = entities.get("bucket_name")
        
        try:
            if bucket_name:
                stats = await self.prism_client.get_bucket_stats(objectstore_uuid, bucket_name)
                size = self._format_bytes(stats.get("size_bytes", 0))
                objects = stats.get("object_count", 0)
                
                return AgentResponse(
                    message=f"**{bucket_name} Statistics**\n\n• Total Size: {size}\n• Object Count: {objects:,}",
                    intent="get_stats",
                    success=True,
                    data=stats,
                    code_block=json.dumps(stats, indent=2),
                    code_lang="json"
                )
            else:
                # Get overall stats
                stats = await self.prism_client.get_objectstore_stats(objectstore_uuid)
                buckets = await self.prism_client.list_buckets(objectstore_uuid)
                
                summary = {
                    "total_buckets": len(buckets),
                    "total_size": stats.get("total_size_bytes", 0),
                    "total_objects": stats.get("total_object_count", 0)
                }
                
                size = self._format_bytes(summary["total_size"])
                
                return AgentResponse(
                    message=f"**Storage Statistics**\n\n• Buckets: {summary['total_buckets']}\n• Total Size: {size}\n• Total Objects: {summary['total_objects']:,}",
                    intent="get_stats",
                    success=True,
                    data=summary,
                    code_block=json.dumps(summary, indent=2),
                    code_lang="json"
                )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error getting statistics: {str(e)}",
                intent="get_stats",
                success=False
            )
    
    async def _handle_create_access_key(self, entities: Dict) -> AgentResponse:
        """Handle access key creation"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        username = entities.get("username", "nova-user")
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="create_access_key",
                success=False
            )
        
        try:
            result = await self.prism_client.create_access_key(objectstore_uuid, username)
            
            # Extract key info (be careful not to log secrets!)
            key_info = {
                "access_key_id": result.get("status", {}).get("resources", {}).get("access_key_id", "N/A"),
                "secret_key": "****" + result.get("status", {}).get("resources", {}).get("secret_access_key", "")[-4:],
                "user": username,
                "created": datetime.now().isoformat()
            }
            
            return AgentResponse(
                message=f"✅ Created access key for user **{username}**\n\n⚠️ **Important:** Save the secret key now - it won't be shown again!",
                intent="create_access_key",
                success=True,
                data=result.get("status", {}).get("resources", {}),
                code_block=json.dumps(key_info, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error creating access key: {str(e)}",
                intent="create_access_key",
                success=False
            )
    
    async def _handle_list_access_keys(self) -> AgentResponse:
        """Handle listing access keys"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="list_access_keys",
                success=False
            )
        
        try:
            keys = await self.prism_client.list_access_keys(objectstore_uuid)
            
            if not keys:
                return AgentResponse(
                    message="No access keys found.",
                    intent="list_access_keys",
                    success=True,
                    suggestions=["Create access key for user admin"]
                )
            
            key_list = []
            for key in keys:
                resources = key.get("status", {}).get("resources", {})
                key_list.append({
                    "access_key_id": resources.get("access_key_id", "N/A"),
                    "user_name": resources.get("user_name", "Unknown"),
                    "created": key.get("metadata", {}).get("creation_time", "Unknown")
                })
            
            return AgentResponse(
                message=f"Found {len(keys)} access key(s):",
                intent="list_access_keys",
                success=True,
                data={"keys": key_list},
                code_block=json.dumps(key_list, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error listing access keys: {str(e)}",
                intent="list_access_keys",
                success=False
            )
    
    async def _handle_suspend_versioning(self, entities: Dict) -> AgentResponse:
        """Handle suspending bucket versioning"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket name. For example: 'Suspend versioning on my-bucket'",
                intent="suspend_versioning",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="suspend_versioning",
                success=False
            )
        
        try:
            result = await self.prism_client.suspend_bucket_versioning(objectstore_uuid, bucket_name)
            return AgentResponse(
                message=f"✅ Versioning suspended for bucket **{bucket_name}**",
                intent="suspend_versioning",
                success=True,
                data=result
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Failed to suspend versioning: {str(e)}",
                intent="suspend_versioning",
                success=False
            )
    
    async def _handle_restore_versioning(self, entities: Dict) -> AgentResponse:
        """Handle restoring bucket versioning"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket name. For example: 'Enable versioning on my-bucket'",
                intent="restore_versioning",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="restore_versioning",
                success=False
            )
        
        try:
            result = await self.prism_client.restore_bucket_versioning(objectstore_uuid, bucket_name)
            return AgentResponse(
                message=f"✅ Versioning enabled for bucket **{bucket_name}**",
                intent="restore_versioning",
                success=True,
                data=result
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Failed to enable versioning: {str(e)}",
                intent="restore_versioning",
                success=False
            )
    
    async def _handle_list_alerts(self, entities: Dict) -> AgentResponse:
        """Handle listing alerts"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="list_alerts",
                success=False
            )
        
        severity = entities.get("severity")
        
        try:
            alerts = await self.prism_client.list_alerts(objectstore_uuid, severity)
            
            if not alerts:
                return AgentResponse(
                    message="✅ No alerts found. Everything looks good!",
                    intent="list_alerts",
                    success=True,
                    data={"alerts": []}
                )
            
            return AgentResponse(
                message=f"Found {len(alerts)} alert(s):",
                intent="list_alerts",
                success=True,
                data={"alerts": alerts},
                code_block=json.dumps(alerts, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error listing alerts: {str(e)}",
                intent="list_alerts",
                success=False
            )
    
    async def _handle_enable_worm(self, entities: Dict) -> AgentResponse:
        """Handle enabling WORM on a bucket"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket name. For example: 'Enable WORM on compliance-bucket with 365 days retention'",
                intent="enable_worm",
                success=False
            )
        
        retention_days = entities.get("retention_days", 30)
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="enable_worm",
                success=False
            )
        
        try:
            result = await self.prism_client.enable_worm(objectstore_uuid, bucket_name, retention_days)
            return AgentResponse(
                message=f"✅ WORM enabled for bucket **{bucket_name}** with **{retention_days}** day retention period.\n\n⚠️ **Warning:** Objects in this bucket cannot be deleted until the retention period expires.",
                intent="enable_worm",
                success=True,
                data=result
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Failed to enable WORM: {str(e)}",
                intent="enable_worm",
                success=False
            )
    
    async def _handle_get_bucket_policy(self, entities: Dict) -> AgentResponse:
        """Handle getting bucket policy"""
        configured, error_response = self._check_prism_configured()
        if not configured:
            return error_response
        
        bucket_name = entities.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify a bucket name. For example: 'Show policy for my-bucket'",
                intent="get_bucket_policy",
                success=False
            )
        
        objectstore_uuid = await self._get_default_objectstore()
        if not objectstore_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="get_bucket_policy",
                success=False
            )
        
        try:
            policy = await self.prism_client.get_bucket_policy(objectstore_uuid, bucket_name)
            
            if not policy.get("policy"):
                return AgentResponse(
                    message=f"No policy configured for bucket **{bucket_name}**",
                    intent="get_bucket_policy",
                    success=True,
                    suggestions=[f"Set policy for {bucket_name}"]
                )
            
            return AgentResponse(
                message=f"Policy for bucket **{bucket_name}**:",
                intent="get_bucket_policy",
                success=True,
                data=policy,
                code_block=json.dumps(policy, indent=2),
                code_lang="json"
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error getting bucket policy: {str(e)}",
                intent="get_bucket_policy",
                success=False
            )
    
    def _handle_unknown(self, message: str, intent_result: Dict) -> AgentResponse:
        """Handle unknown intents using knowledge base"""
        # Search knowledge base
        knowledge = self.vector_db.search_knowledge(message, n_results=2)
        
        if knowledge and knowledge[0]["distance"] < 1.0:
            context = knowledge[0]["content"]
            return AgentResponse(
                message=f"Based on my knowledge:\n\n{context}\n\nIs there something specific you'd like me to help you with?",
                intent="knowledge_response",
                success=True,
                suggestions=["List buckets", "Create a bucket", "Show storage stats"]
            )
        
        return AgentResponse(
            message="I'm not sure how to help with that. Here's what I can do:\n\n• Manage buckets (create, list, delete)\n• Configure lifecycle policies\n• View storage statistics\n• Manage access keys\n\nTry asking in a different way, or say 'help' for more options.",
            intent="unknown",
            success=False,
            suggestions=["Help", "List buckets", "Show storage usage"]
        )
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
            if bytes_val < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"


# Factory function
def create_agent() -> ChatAgent:
    """Create chat agent with dependencies"""
    vector_db = get_vector_db()
    return ChatAgent(vector_db)
