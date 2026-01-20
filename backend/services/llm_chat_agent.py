"""
NOVA LLM Chat Agent Service
Uses OpenAI/Anthropic/Ollama function calling to understand user intent and execute operations

Supported providers:
- openai: Requires OPENAI_API_KEY
- anthropic: Requires ANTHROPIC_API_KEY  
- ollama: FREE! Just run `ollama pull llama3.1` and `ollama serve`
- groq: Requires GROQ_API_KEY (generous free tier)
"""
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
import os
import httpx

from .prism_client import PrismClient, get_prism_client
from .vector_db import VectorDBService, get_vector_db


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


# Define all available tools/functions the LLM can call
NOVA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_buckets",
            "description": "List all buckets in the Nutanix Object Store. Use this when user wants to see their buckets.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_bucket",
            "description": "Create a new bucket in the Object Store. Use this when user wants to create/make/provision a new bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket to create (3-63 chars, lowercase, alphanumeric and hyphens)"
                    },
                    "versioning": {
                        "type": "boolean",
                        "description": "Whether to enable versioning on the bucket",
                        "default": False
                    },
                    "worm": {
                        "type": "boolean",
                        "description": "Whether to enable WORM (Write Once Read Many) compliance",
                        "default": False
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_bucket",
            "description": "Delete a bucket from the Object Store. Use when user wants to remove/delete a bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket to delete"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_bucket_info",
            "description": "Get detailed information about a specific bucket including size, object count, versioning status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket to get info for"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_storage_stats",
            "description": "Get overall storage statistics including total buckets, objects, and storage usage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Optional: specific bucket to get stats for. If not provided, returns overall stats."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_lifecycle_policy",
            "description": "Set a lifecycle policy on a bucket to automatically expire or archive objects after N days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket to set policy on"
                    },
                    "expiration_days": {
                        "type": "integer",
                        "description": "Number of days after which objects should be deleted (0 to disable)"
                    },
                    "transition_days": {
                        "type": "integer",
                        "description": "Number of days after which objects should be archived to GLACIER (0 to disable)"
                    },
                    "prefix": {
                        "type": "string",
                        "description": "Optional prefix filter - only apply to objects matching this prefix",
                        "default": ""
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_lifecycle_policy",
            "description": "Get the current lifecycle policy/rules for a bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_object_stores",
            "description": "List all Nutanix Object Stores available in the cluster.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_access_key",
            "description": "Create S3 API access key credentials for a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Username to create access key for"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_access_keys",
            "description": "List all S3 API access keys.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enable_versioning",
            "description": "Enable or restore versioning on a bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suspend_versioning",
            "description": "Suspend/disable versioning on a bucket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket"
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "enable_worm",
            "description": "Enable WORM (Write Once Read Many) compliance on a bucket for data immutability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "bucket_name": {
                        "type": "string",
                        "description": "Name of the bucket"
                    },
                    "retention_days": {
                        "type": "integer",
                        "description": "Number of days to retain objects (cannot be deleted during this period)",
                        "default": 30
                    }
                },
                "required": ["bucket_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_alerts",
            "description": "List alerts and warnings for the Object Store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "description": "Filter by severity level",
                        "enum": ["critical", "warning", "info"]
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "test_connection",
            "description": "Test the connection to Prism Central.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "show_help",
            "description": "Show help information about what NOVA can do.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# System prompt for the LLM
SYSTEM_PROMPT = """You are NOVA, a helpful AI assistant for managing Nutanix Objects storage.

Your capabilities include:
- Managing buckets (create, list, delete, get info)
- Setting lifecycle policies for automatic data management
- Managing access keys for S3 API access
- Viewing storage statistics and alerts
- Configuring versioning and WORM compliance

When users ask about storage operations, use the appropriate function to help them.
If the user's request is unclear, ask for clarification.
If Prism is not configured, guide them to set it up first.

Be concise and helpful. Format responses nicely with markdown when appropriate."""


class LLMChatAgent:
    """
    AI Agent using LLM function calling for intent understanding
    Supports OpenAI, Anthropic, Ollama (free/local), and Groq APIs
    """
    
    def __init__(self, vector_db: VectorDBService, api_key: str = None, provider: str = "ollama", 
                 ollama_base_url: str = "http://localhost:11434", ollama_model: str = "llama3.1"):
        self.vector_db = vector_db
        self.prism_client: Optional[PrismClient] = None
        self.current_objectstore_uuid: Optional[str] = None
        self.provider = provider
        self.api_key = api_key
        self.client = None
        self.ollama_base_url = ollama_base_url
        self.ollama_model = ollama_model
        
        self._init_client()
    
    def _init_client(self):
        """Initialize the LLM client based on provider"""
        if self.provider == "ollama":
            # Ollama doesn't need a client library - we use httpx directly
            print(f"🦙 Using Ollama at {self.ollama_base_url} with model {self.ollama_model}")
            self.client = True  # Just a flag that we're ready
        elif self.provider == "openai":
            if not self.api_key:
                self.api_key = os.getenv("OPENAI_API_KEY")
            if self.api_key:
                try:
                    from openai import AsyncOpenAI
                    self.client = AsyncOpenAI(api_key=self.api_key)
                except ImportError:
                    print("OpenAI package not installed. Run: pip install openai")
        elif self.provider == "anthropic":
            if not self.api_key:
                self.api_key = os.getenv("ANTHROPIC_API_KEY")
            if self.api_key:
                try:
                    from anthropic import AsyncAnthropic
                    self.client = AsyncAnthropic(api_key=self.api_key)
                except ImportError:
                    print("Anthropic package not installed. Run: pip install anthropic")
        elif self.provider == "groq":
            if not self.api_key:
                self.api_key = os.getenv("GROQ_API_KEY")
            if self.api_key:
                try:
                    from openai import AsyncOpenAI
                    # Groq uses OpenAI-compatible API
                    self.client = AsyncOpenAI(
                        api_key=self.api_key,
                        base_url="https://api.groq.com/openai/v1"
                    )
                except ImportError:
                    print("OpenAI package not installed. Run: pip install openai")
    
    def set_prism_client(self, client: PrismClient):
        """Set the Prism client"""
        self.prism_client = client
    
    async def process_message(self, message: str, session_id: str = "default", context: dict = None) -> AgentResponse:
        """Process user message using LLM function calling"""
        
        # Store conversation
        self.vector_db.add_conversation(session_id, "user", message)
        
        # If no client configured, fall back to vector-based matching
        if not self.client:
            return await self._fallback_process(message, context)
        
        try:
            if self.provider == "ollama":
                response = await self._process_with_ollama(message, context)
            elif self.provider == "openai":
                response = await self._process_with_openai(message, context)
            elif self.provider == "anthropic":
                response = await self._process_with_anthropic(message, context)
            elif self.provider == "groq":
                response = await self._process_with_groq(message, context)
            else:
                response = await self._fallback_process(message, context)
        except Exception as e:
            import traceback
            traceback.print_exc()
            response = AgentResponse(
                message=f"Error processing message: {str(e)}",
                intent="error",
                success=False
            )
        
        # Store response
        self.vector_db.add_conversation(session_id, "assistant", response.message)
        
        return response
    
    async def _process_with_openai(self, message: str, context: dict = None) -> AgentResponse:
        """Process message using OpenAI function calling"""
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]
        
        # Call OpenAI with tools
        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",  # or gpt-4o for better understanding
            messages=messages,
            tools=NOVA_TOOLS,
            tool_choice="auto"
        )
        
        assistant_message = response.choices[0].message
        
        # Check if the model wants to call a function
        if assistant_message.tool_calls:
            tool_call = assistant_message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # Merge context
            if context:
                if context.get('objectstore_uuid'):
                    function_args['objectstore_uuid'] = context['objectstore_uuid']
                if context.get('bucket_name') and 'bucket_name' not in function_args:
                    function_args['bucket_name'] = context['bucket_name']
            
            # Execute the function
            result = await self._execute_function(function_name, function_args)
            
            return result
        else:
            # No function call - just return the text response
            return AgentResponse(
                message=assistant_message.content or "I'm not sure how to help with that.",
                intent="conversation",
                success=True,
                suggestions=["List buckets", "Show storage stats", "Help"]
            )
    
    async def _process_with_anthropic(self, message: str, context: dict = None) -> AgentResponse:
        """Process message using Anthropic tool use"""
        
        # Convert OpenAI tool format to Anthropic format
        anthropic_tools = []
        for tool in NOVA_TOOLS:
            anthropic_tools.append({
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "input_schema": tool["function"]["parameters"]
            })
        
        response = await self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=anthropic_tools,
            messages=[{"role": "user", "content": message}]
        )
        
        # Check for tool use
        for block in response.content:
            if block.type == "tool_use":
                function_name = block.name
                function_args = block.input
                
                # Merge context
                if context:
                    if context.get('objectstore_uuid'):
                        function_args['objectstore_uuid'] = context['objectstore_uuid']
                    if context.get('bucket_name') and 'bucket_name' not in function_args:
                        function_args['bucket_name'] = context['bucket_name']
                
                # Execute the function
                return await self._execute_function(function_name, function_args)
        
        # No tool use - return text
        text_content = next((b.text for b in response.content if hasattr(b, 'text')), "")
        return AgentResponse(
            message=text_content or "I'm not sure how to help with that.",
            intent="conversation",
            success=True
        )
    
    async def _process_with_ollama(self, message: str, context: dict = None) -> AgentResponse:
        """
        Process message using Ollama (FREE, LOCAL)
        Ollama supports function calling with compatible models like llama3.1
        """
        
        # Convert tools to Ollama format (same as OpenAI format)
        tools = NOVA_TOOLS
        
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message}
            ],
            "tools": tools,
            "stream": False
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.ollama_base_url}/api/chat",
                json=payload
            )
            
            if response.status_code != 200:
                return AgentResponse(
                    message=f"Ollama error: {response.text}. Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull {self.ollama_model}`)",
                    intent="error",
                    success=False
                )
            
            data = response.json()
            assistant_message = data.get("message", {})
            
            # Check for tool calls
            tool_calls = assistant_message.get("tool_calls", [])
            
            if tool_calls:
                tool_call = tool_calls[0]
                function_name = tool_call.get("function", {}).get("name")
                function_args = tool_call.get("function", {}).get("arguments", {})
                
                # Arguments might be a string (JSON) or dict
                if isinstance(function_args, str):
                    function_args = json.loads(function_args)
                
                # Merge context
                if context:
                    if context.get('objectstore_uuid'):
                        function_args['objectstore_uuid'] = context['objectstore_uuid']
                    if context.get('bucket_name') and 'bucket_name' not in function_args:
                        function_args['bucket_name'] = context['bucket_name']
                
                # Execute the function
                return await self._execute_function(function_name, function_args)
            else:
                # No tool call - return text response
                content = assistant_message.get("content", "I'm not sure how to help with that.")
                return AgentResponse(
                    message=content,
                    intent="conversation",
                    success=True,
                    suggestions=["List buckets", "Show storage stats", "Help"]
                )
    
    async def _process_with_groq(self, message: str, context: dict = None) -> AgentResponse:
        """
        Process message using Groq (fast inference, generous free tier)
        Uses OpenAI-compatible API
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]
        
        # Groq supports function calling with llama models
        response = await self.client.chat.completions.create(
            model="llama-3.1-70b-versatile",  # or mixtral-8x7b-32768
            messages=messages,
            tools=NOVA_TOOLS,
            tool_choice="auto"
        )
        
        assistant_message = response.choices[0].message
        
        if assistant_message.tool_calls:
            tool_call = assistant_message.tool_calls[0]
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            # Merge context
            if context:
                if context.get('objectstore_uuid'):
                    function_args['objectstore_uuid'] = context['objectstore_uuid']
                if context.get('bucket_name') and 'bucket_name' not in function_args:
                    function_args['bucket_name'] = context['bucket_name']
            
            return await self._execute_function(function_name, function_args)
        else:
            return AgentResponse(
                message=assistant_message.content or "I'm not sure how to help with that.",
                intent="conversation",
                success=True,
                suggestions=["List buckets", "Show storage stats", "Help"]
            )
    
    async def _execute_function(self, function_name: str, args: dict) -> AgentResponse:
        """Execute the called function and return result"""
        
        # Map function names to handlers
        handlers = {
            "list_buckets": self._handle_list_buckets,
            "create_bucket": self._handle_create_bucket,
            "delete_bucket": self._handle_delete_bucket,
            "get_bucket_info": self._handle_get_bucket_info,
            "get_storage_stats": self._handle_get_stats,
            "set_lifecycle_policy": self._handle_set_lifecycle,
            "get_lifecycle_policy": self._handle_get_lifecycle,
            "list_object_stores": self._handle_list_object_stores,
            "create_access_key": self._handle_create_access_key,
            "list_access_keys": self._handle_list_access_keys,
            "enable_versioning": self._handle_enable_versioning,
            "suspend_versioning": self._handle_suspend_versioning,
            "enable_worm": self._handle_enable_worm,
            "list_alerts": self._handle_list_alerts,
            "test_connection": self._handle_test_connection,
            "show_help": self._handle_help,
        }
        
        handler = handlers.get(function_name)
        if handler:
            return await handler(args)
        else:
            return AgentResponse(
                message=f"Unknown function: {function_name}",
                intent="error",
                success=False
            )
    
    async def _fallback_process(self, message: str, context: dict = None) -> AgentResponse:
        """Fallback to vector-based intent matching when no API key"""
        # Use the original vector DB approach
        intent_result = self.vector_db.match_intent(message)
        
        return AgentResponse(
            message=f"LLM API not configured. Matched intent: {intent_result['intent']} (confidence: {intent_result['confidence']:.2f}). Please set OPENAI_API_KEY or ANTHROPIC_API_KEY.",
            intent=intent_result['intent'],
            success=False,
            suggestions=["Configure API key in .env", "Set OPENAI_API_KEY environment variable"]
        )
    
    # ==================== Handler Methods ====================
    
    def _check_prism_configured(self):
        """Check if Prism is configured"""
        if not self.prism_client:
            return False, AgentResponse(
                message="⚠️ Prism is not configured. Please go to **Settings** and enter your Prism Central connection details.",
                intent="error",
                success=False,
                suggestions=["Go to Settings", "Configure Prism connection"]
            )
        return True, None
    
    async def _get_default_objectstore(self) -> Optional[str]:
        """Get the first available object store UUID"""
        if self.current_objectstore_uuid:
            return self.current_objectstore_uuid
        
        if not self.prism_client:
            return None
            
        try:
            stores = await self.prism_client.list_object_stores()
            if stores:
                first_store = stores[0]
                uuid = first_store.get("uuid") or first_store.get("metadata", {}).get("uuid")
                if uuid:
                    self.current_objectstore_uuid = uuid
                    return uuid
        except Exception as e:
            print(f"Error getting default objectstore: {e}")
        return None
    
    async def _handle_list_buckets(self, args: dict) -> AgentResponse:
        """Handle listing buckets"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(
                message="No Object Store available. Please create one first.",
                intent="list_buckets",
                success=False
            )
        
        buckets = await self.prism_client.list_buckets(oss_uuid)
        
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
            bucket_list.append({
                "name": bucket.get("name", "Unknown"),
                "versioning": bucket.get("versioning", "Disabled"),
                "worm": bucket.get("worm", "Disabled"),
                "size_bytes": bucket.get("storage_usage_bytes", 0),
                "object_count": bucket.get("object_count", 0)
            })
        
        return AgentResponse(
            message=f"Found **{len(buckets)}** bucket(s):",
            intent="list_buckets",
            success=True,
            data={"buckets": bucket_list},
            code_block=json.dumps(bucket_list, indent=2),
            code_lang="json"
        )
    
    async def _handle_create_bucket(self, args: dict) -> AgentResponse:
        """Handle bucket creation"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please provide a bucket name.",
                intent="create_bucket",
                success=False
            )
        
        versioning = args.get("versioning", False)
        worm = args.get("worm", False)
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(
                message="No Object Store available.",
                intent="create_bucket",
                success=False
            )
        
        try:
            await self.prism_client.create_bucket(
                oss_uuid=oss_uuid,
                name=bucket_name,
                versioning=versioning,
                worm=worm
            )
            
            config = {
                "bucket_name": bucket_name,
                "versioning": "Enabled" if versioning else "Disabled",
                "worm": "Enabled" if worm else "Disabled"
            }
            
            return AgentResponse(
                message=f"✅ Successfully created bucket **{bucket_name}**!",
                intent="create_bucket",
                success=True,
                data=config,
                code_block=json.dumps(config, indent=2),
                suggestions=[f"List objects in {bucket_name}", f"Set lifecycle for {bucket_name}"]
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Failed to create bucket: {str(e)}",
                intent="create_bucket",
                success=False
            )
    
    async def _handle_delete_bucket(self, args: dict) -> AgentResponse:
        """Handle bucket deletion"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(
                message="Please specify which bucket to delete.",
                intent="delete_bucket",
                success=False
            )
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="delete_bucket", success=False)
        
        try:
            success = await self.prism_client.delete_bucket(oss_uuid, bucket_name)
            if success:
                return AgentResponse(
                    message=f"✅ Successfully deleted bucket **{bucket_name}**",
                    intent="delete_bucket",
                    success=True
                )
            else:
                return AgentResponse(
                    message=f"❌ Failed to delete bucket. It may not be empty.",
                    intent="delete_bucket",
                    success=False
                )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="delete_bucket", success=False)
    
    async def _handle_get_bucket_info(self, args: dict) -> AgentResponse:
        """Handle getting bucket info"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        
        # Check for reserved/invalid bucket names that might be confused with API endpoints
        reserved_names = ["stats", "info", "list", "create", "delete", "policy", "lifecycle", "groups"]
        if not bucket_name or bucket_name.lower() in reserved_names:
            # If user asked for "stats", redirect to get_stats handler
            if bucket_name and bucket_name.lower() == "stats":
                return await self._handle_get_stats(args)
            return AgentResponse(
                message="Please specify a valid bucket name. For example: 'Show info for bucket prod-data'",
                intent="get_bucket_info",
                success=False,
                suggestions=["List buckets", "Show storage stats"]
            )
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="get_bucket_info", success=False)
        
        try:
            # First verify the bucket exists using list_buckets
            buckets = await self.prism_client.list_buckets(oss_uuid)
            bucket_exists = any(b.get("name") == bucket_name for b in buckets)
            
            if not bucket_exists:
                return AgentResponse(
                    message=f"❌ Bucket '{bucket_name}' not found. Use 'list buckets' to see available buckets.",
                    intent="get_bucket_info",
                    success=False,
                    suggestions=["List buckets"]
                )
            
            stats = await self.prism_client.get_bucket_stats(oss_uuid, bucket_name)
            info = {
                "name": bucket_name,
                "size_bytes": stats.get("size_bytes", 0),
                "object_count": stats.get("object_count", 0)
            }
            
            size_human = self._format_bytes(info["size_bytes"])
            
            return AgentResponse(
                message=f"**Bucket: {bucket_name}**\n\n• Size: {size_human}\n• Objects: {info['object_count']:,}",
                intent="get_bucket_info",
                success=True,
                data=info,
                code_block=json.dumps(info, indent=2)
            )
        except Exception as e:
            return AgentResponse(
                message=f"❌ Error: {str(e)}",
                intent="get_bucket_info",
                success=False,
                suggestions=["List buckets", "Show storage stats"]
            )
    
    async def _handle_get_stats(self, args: dict) -> AgentResponse:
        """Handle getting storage statistics"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="get_stats", success=False)
        
        bucket_name = args.get("bucket_name")
        
        try:
            if bucket_name:
                stats = await self.prism_client.get_bucket_stats(oss_uuid, bucket_name)
                size = self._format_bytes(stats.get("size_bytes", 0))
                return AgentResponse(
                    message=f"**{bucket_name} Statistics**\n\n• Size: {size}\n• Objects: {stats.get('object_count', 0):,}",
                    intent="get_stats",
                    success=True,
                    data=stats
                )
            else:
                buckets = await self.prism_client.list_buckets(oss_uuid)
                total_size = sum(b.get("storage_usage_bytes", 0) for b in buckets)
                total_objects = sum(b.get("object_count", 0) for b in buckets)
                
                summary = {
                    "total_buckets": len(buckets),
                    "total_size_bytes": total_size,
                    "total_size_human": self._format_bytes(total_size),
                    "total_objects": total_objects
                }
                
                return AgentResponse(
                    message=f"**Storage Statistics**\n\n• Buckets: {len(buckets)}\n• Total Size: {summary['total_size_human']}\n• Total Objects: {total_objects:,}",
                    intent="get_stats",
                    success=True,
                    data=summary,
                    code_block=json.dumps(summary, indent=2)
                )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="get_stats", success=False)
    
    async def _handle_set_lifecycle(self, args: dict) -> AgentResponse:
        """Handle setting lifecycle policy"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(message="Please specify a bucket.", intent="set_lifecycle", success=False)
        
        expiration_days = args.get("expiration_days", 0)
        transition_days = args.get("transition_days", 0)
        prefix = args.get("prefix", "")
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="set_lifecycle", success=False)
        
        try:
            rule_id = f"nova-rule-{int(datetime.now().timestamp())}"
            
            await self.prism_client.set_lifecycle_rule(
                oss_uuid=oss_uuid,
                bucket_name=bucket_name,
                rule_id=rule_id,
                prefix=prefix,
                expiration_days=expiration_days,
                transition_days=transition_days
            )
            
            rule_config = {
                "rule_id": rule_id,
                "bucket": bucket_name,
                "prefix": prefix or "(all objects)",
                "expiration_days": expiration_days,
                "transition_days": transition_days
            }
            
            return AgentResponse(
                message=f"✅ Created lifecycle rule for **{bucket_name}**",
                intent="set_lifecycle",
                success=True,
                data=rule_config,
                code_block=json.dumps(rule_config, indent=2)
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="set_lifecycle", success=False)
    
    async def _handle_get_lifecycle(self, args: dict) -> AgentResponse:
        """Handle getting lifecycle rules"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(message="Please specify a bucket.", intent="get_lifecycle", success=False)
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="get_lifecycle", success=False)
        
        try:
            rules = await self.prism_client.get_lifecycle_rules(oss_uuid, bucket_name)
            
            if not rules:
                return AgentResponse(
                    message=f"No lifecycle rules configured for **{bucket_name}**",
                    intent="get_lifecycle",
                    success=True
                )
            
            return AgentResponse(
                message=f"Lifecycle rules for **{bucket_name}**:",
                intent="get_lifecycle",
                success=True,
                data={"rules": rules},
                code_block=json.dumps(rules, indent=2)
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="get_lifecycle", success=False)
    
    async def _handle_list_object_stores(self, args: dict) -> AgentResponse:
        """Handle listing object stores"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        stores = await self.prism_client.list_object_stores()
        
        if not stores:
            return AgentResponse(
                message="No Object Stores found.",
                intent="list_object_stores",
                success=True,
                data={"stores": []}
            )
        
        return AgentResponse(
            message=f"Found **{len(stores)}** Object Store(s):",
            intent="list_object_stores",
            success=True,
            data={"stores": stores},
            code_block=json.dumps(stores, indent=2)
        )
    
    async def _handle_create_access_key(self, args: dict) -> AgentResponse:
        """Handle access key creation"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        username = args.get("username", "nova-user")
        oss_uuid = await self._get_default_objectstore()
        
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="create_access_key", success=False)
        
        try:
            result = await self.prism_client.create_access_key(oss_uuid, username)
            return AgentResponse(
                message=f"✅ Created access key for **{username}**\n\n⚠️ Save the secret key now - it won't be shown again!",
                intent="create_access_key",
                success=True,
                data=result
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="create_access_key", success=False)
    
    async def _handle_list_access_keys(self, args: dict) -> AgentResponse:
        """Handle listing access keys"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="list_access_keys", success=False)
        
        try:
            keys = await self.prism_client.list_access_keys(oss_uuid)
            return AgentResponse(
                message=f"Found **{len(keys)}** access key(s):",
                intent="list_access_keys",
                success=True,
                data={"keys": keys},
                code_block=json.dumps(keys, indent=2) if keys else None
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="list_access_keys", success=False)
    
    async def _handle_enable_versioning(self, args: dict) -> AgentResponse:
        """Handle enabling versioning"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(message="Please specify a bucket.", intent="enable_versioning", success=False)
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="enable_versioning", success=False)
        
        try:
            await self.prism_client.restore_bucket_versioning(oss_uuid, bucket_name)
            return AgentResponse(
                message=f"✅ Versioning enabled for **{bucket_name}**",
                intent="enable_versioning",
                success=True
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="enable_versioning", success=False)
    
    async def _handle_suspend_versioning(self, args: dict) -> AgentResponse:
        """Handle suspending versioning"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(message="Please specify a bucket.", intent="suspend_versioning", success=False)
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="suspend_versioning", success=False)
        
        try:
            await self.prism_client.suspend_bucket_versioning(oss_uuid, bucket_name)
            return AgentResponse(
                message=f"✅ Versioning suspended for **{bucket_name}**",
                intent="suspend_versioning",
                success=True
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="suspend_versioning", success=False)
    
    async def _handle_enable_worm(self, args: dict) -> AgentResponse:
        """Handle enabling WORM"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        bucket_name = args.get("bucket_name")
        if not bucket_name:
            return AgentResponse(message="Please specify a bucket.", intent="enable_worm", success=False)
        
        retention_days = args.get("retention_days", 30)
        oss_uuid = await self._get_default_objectstore()
        
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="enable_worm", success=False)
        
        try:
            await self.prism_client.enable_worm(oss_uuid, bucket_name, retention_days)
            return AgentResponse(
                message=f"✅ WORM enabled for **{bucket_name}** with **{retention_days}** day retention.\n\n⚠️ Objects cannot be deleted during retention period.",
                intent="enable_worm",
                success=True
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="enable_worm", success=False)
    
    async def _handle_list_alerts(self, args: dict) -> AgentResponse:
        """Handle listing alerts"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        oss_uuid = await self._get_default_objectstore()
        if not oss_uuid:
            return AgentResponse(message="No Object Store available.", intent="list_alerts", success=False)
        
        severity = args.get("severity")
        
        try:
            alerts = await self.prism_client.list_alerts(oss_uuid, severity)
            
            if not alerts:
                return AgentResponse(
                    message="✅ No alerts found. Everything looks good!",
                    intent="list_alerts",
                    success=True
                )
            
            return AgentResponse(
                message=f"Found **{len(alerts)}** alert(s):",
                intent="list_alerts",
                success=True,
                data={"alerts": alerts},
                code_block=json.dumps(alerts, indent=2)
            )
        except Exception as e:
            return AgentResponse(message=f"❌ Error: {str(e)}", intent="list_alerts", success=False)
    
    async def _handle_test_connection(self, args: dict) -> AgentResponse:
        """Handle connection test"""
        configured, error = self._check_prism_configured()
        if not configured:
            return error
        
        result = await self.prism_client.test_connection()
        
        if result["success"]:
            return AgentResponse(
                message=f"✅ Successfully connected to Prism Central!",
                intent="test_connection",
                success=True,
                data=result
            )
        else:
            return AgentResponse(
                message=f"❌ Connection failed: {result['message']}",
                intent="test_connection",
                success=False
            )
    
    async def _handle_help(self, args: dict) -> AgentResponse:
        """Handle help request"""
        help_text = """I'm **NOVA**, your Nutanix Objects Virtual Assistant! 🚀

**What I can do:**

📦 **Bucket Operations**
• Create, list, delete buckets
• Enable versioning and WORM compliance
• View bucket details and statistics

⏰ **Lifecycle Management**
• Set automatic expiration policies
• Configure archival rules

🔑 **Access Management**
• Create S3 API access keys
• List existing credentials

📊 **Analytics**
• View storage usage
• Check alerts and warnings

Just ask me in natural language! For example:
• "Create a bucket called prod-logs with versioning"
• "Show me all my buckets"
• "Set lifecycle to delete objects after 90 days in logs bucket"
"""
        return AgentResponse(
            message=help_text,
            intent="help",
            success=True,
            suggestions=["List buckets", "Show storage stats", "Create a bucket"]
        )
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"


# Factory function
def create_llm_agent(
    api_key: str = None, 
    provider: str = "ollama",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3.1"
) -> LLMChatAgent:
    """
    Create LLM chat agent with dependencies
    
    Providers:
    - "ollama": FREE, local. Requires `ollama serve` running
    - "openai": Requires OPENAI_API_KEY
    - "anthropic": Requires ANTHROPIC_API_KEY
    - "groq": Fast, generous free tier. Requires GROQ_API_KEY
    """
    vector_db = get_vector_db()
    return LLMChatAgent(
        vector_db, 
        api_key=api_key, 
        provider=provider,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model
    )
