"""
Vector Database Service using ChromaDB
Stores knowledge base and conversation context for RAG
"""
# SQLite fix for older systems
import sys
import os

# Disable telemetry to avoid posthog errors
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "True"

try:
    __import__('pysqlite3')
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import hashlib
from datetime import datetime


class VectorDBService:
    """
    Service for managing vector embeddings and semantic search
    Uses ChromaDB for local vector storage
    """
    
    def __init__(self, persist_dir: str = "./data/chroma", embedding_model: str = "all-MiniLM-L6-v2"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize ChromaDB client with persistence
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Use sentence-transformers for embeddings
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )
        
        # Initialize collections
        self._init_collections()
    
    def _init_collections(self):
        """Initialize required collections"""
        # Knowledge base collection - stores Nutanix Objects documentation/knowledge
        self.knowledge_collection = self.client.get_or_create_collection(
            name="nova_knowledge",
            embedding_function=self.embedding_fn,
            metadata={"description": "Nutanix Objects knowledge base"}
        )
        
        # Conversation history collection
        self.conversations_collection = self.client.get_or_create_collection(
            name="nova_conversations",
            embedding_function=self.embedding_fn,
            metadata={"description": "User conversation history"}
        )
        
        # Command patterns collection - for intent recognition
        self.commands_collection = self.client.get_or_create_collection(
            name="nova_commands",
            embedding_function=self.embedding_fn,
            metadata={"description": "Command patterns for intent matching"}
        )
        
        # Configuration collection - stores app settings (no embeddings needed)
        self.config_collection = self.client.get_or_create_collection(
            name="nova_config",
            metadata={"description": "Application configuration storage"}
        )
        
        # Seed default command patterns if empty
        if self.commands_collection.count() == 0:
            self._seed_command_patterns()
    
    def _seed_command_patterns(self):
        """Seed default command patterns for intent recognition"""
        patterns = [
            # Bucket operations
            {"intent": "create_bucket", "patterns": [
                "create a new bucket",
                "make a bucket named",
                "set up a new bucket",
                "create bucket with versioning",
                "I need a new storage bucket",
                "provision a bucket"
            ]},
            {"intent": "list_buckets", "patterns": [
                "list all buckets",
                "show me my buckets",
                "what buckets do I have",
                "get all buckets",
                "display buckets",
                "show buckets"
            ]},
            {"intent": "delete_bucket", "patterns": [
                "delete bucket",
                "remove bucket",
                "destroy bucket",
                "delete the bucket named"
            ]},
            {"intent": "get_bucket_info", "patterns": [
                "get bucket details",
                "show bucket info",
                "bucket information",
                "tell me about bucket",
                "describe bucket"
            ]},
            
            # Object operations
            {"intent": "list_objects", "patterns": [
                "list objects in bucket",
                "show files in bucket",
                "what objects are in",
                "display objects",
                "list all objects",
                "show me the files"
            ]},
            {"intent": "upload_object", "patterns": [
                "upload file",
                "upload object",
                "put file in bucket",
                "add file to bucket",
                "store file"
            ]},
            {"intent": "delete_object", "patterns": [
                "delete object",
                "remove file",
                "delete file from bucket"
            ]},
            
            # Lifecycle operations
            {"intent": "set_lifecycle", "patterns": [
                "set lifecycle policy",
                "configure lifecycle",
                "create lifecycle rule",
                "set up data retention",
                "archive old objects",
                "auto-delete after days",
                "transition to glacier"
            ]},
            {"intent": "get_lifecycle", "patterns": [
                "show lifecycle rules",
                "get lifecycle policy",
                "what are the lifecycle rules",
                "display retention policy"
            ]},
            
            # Stats and analytics
            {"intent": "get_stats", "patterns": [
                "show storage usage",
                "get statistics",
                "how much storage",
                "storage analytics",
                "bucket size",
                "usage report",
                "show metrics"
            ]},
            
            # Access keys
            {"intent": "create_access_key", "patterns": [
                "create access key",
                "generate new key",
                "make api key",
                "create credentials"
            ]},
            {"intent": "list_access_keys", "patterns": [
                "list access keys",
                "show api keys",
                "get credentials",
                "display access keys"
            ]},
            
            # Object stores
            {"intent": "list_object_stores", "patterns": [
                "list object stores",
                "show object stores",
                "what object stores exist",
                "display storage endpoints"
            ]},
            
            # Versioning operations
            {"intent": "suspend_versioning", "patterns": [
                "suspend versioning",
                "disable versioning",
                "turn off versioning",
                "pause versioning"
            ]},
            {"intent": "restore_versioning", "patterns": [
                "restore versioning",
                "enable versioning",
                "turn on versioning",
                "resume versioning"
            ]},
            
            # Alerts
            {"intent": "list_alerts", "patterns": [
                "show alerts",
                "list alerts",
                "any warnings",
                "check alerts",
                "display notifications"
            ]},
            
            # WORM operations
            {"intent": "enable_worm", "patterns": [
                "enable worm",
                "set worm",
                "make bucket immutable",
                "compliance mode",
                "write once read many"
            ]},
            
            # Bucket policy
            {"intent": "get_bucket_policy", "patterns": [
                "show bucket policy",
                "get policy",
                "what is the policy",
                "display access policy"
            ]},
            
            # Connection/config
            {"intent": "test_connection", "patterns": [
                "test connection",
                "check prism connection",
                "verify connectivity",
                "is prism connected"
            ]},
            {"intent": "configure_prism", "patterns": [
                "configure prism",
                "set prism ip",
                "connect to prism",
                "update prism settings"
            ]},
            
            # Help
            {"intent": "help", "patterns": [
                "help",
                "what can you do",
                "show commands",
                "list capabilities",
                "how do I use this"
            ]},
        ]
        
        # Add patterns to collection
        all_docs = []
        all_ids = []
        all_metadata = []
        
        for item in patterns:
            intent = item["intent"]
            for i, pattern in enumerate(item["patterns"]):
                doc_id = f"{intent}_{i}"
                all_docs.append(pattern)
                all_ids.append(doc_id)
                all_metadata.append({"intent": intent, "pattern": pattern})
        
        self.commands_collection.add(
            documents=all_docs,
            ids=all_ids,
            metadatas=all_metadata
        )
    
    def add_knowledge(self, documents: List[str], metadata: Optional[List[Dict]] = None) -> int:
        """Add documents to knowledge base"""
        ids = [hashlib.md5(doc.encode()).hexdigest()[:16] for doc in documents]
        
        if metadata is None:
            metadata = [{"source": "manual", "added_at": datetime.now().isoformat()} for _ in documents]
        
        self.knowledge_collection.add(
            documents=documents,
            ids=ids,
            metadatas=metadata
        )
        
        return len(documents)
    
    def search_knowledge(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Search knowledge base for relevant information"""
        results = self.knowledge_collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        items = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                items.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0
                })
        
        return items
    
    def match_intent(self, user_message: str, threshold: float = 1.0) -> Dict[str, Any]:
        """Match user message to command intent"""
        results = self.commands_collection.query(
            query_texts=[user_message],
            n_results=3
        )
        
        if results["documents"] and results["documents"][0]:
            best_match = results["metadatas"][0][0]
            distance = results["distances"][0][0] if results["distances"] else 999
            
            if distance <= threshold:
                return {
                    "intent": best_match["intent"],
                    "confidence": 1 - (distance / 2),  # Normalize to 0-1
                    "matched_pattern": best_match["pattern"],
                    "distance": distance
                }
        
        return {
            "intent": "unknown",
            "confidence": 0,
            "matched_pattern": None,
            "distance": 999
        }
    
    def add_conversation(self, session_id: str, role: str, content: str) -> str:
        """Store conversation message"""
        doc_id = f"{session_id}_{datetime.now().timestamp()}"
        
        self.conversations_collection.add(
            documents=[content],
            ids=[doc_id],
            metadatas=[{
                "session_id": session_id,
                "role": role,
                "timestamp": datetime.now().isoformat()
            }]
        )
        
        return doc_id
    
    def get_conversation_context(self, session_id: str, query: str, n_results: int = 5) -> List[Dict]:
        """Get relevant conversation context"""
        results = self.conversations_collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"session_id": session_id}
        )
        
        items = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                items.append({
                    "content": doc,
                    "role": results["metadatas"][0][i].get("role", "user"),
                    "timestamp": results["metadatas"][0][i].get("timestamp")
                })
        
        return items
    
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Get full conversation history for a session, ordered by timestamp"""
        try:
            results = self.conversations_collection.get(
                where={"session_id": session_id}
            )
            
            items = []
            if results["documents"]:
                for i, doc in enumerate(results["documents"]):
                    items.append({
                        "content": doc,
                        "role": results["metadatas"][i].get("role", "user"),
                        "timestamp": results["metadatas"][i].get("timestamp"),
                        "id": results["ids"][i]
                    })
            
            # Sort by timestamp
            items.sort(key=lambda x: x.get("timestamp", ""))
            return items
        except Exception as e:
            print(f"Error getting conversation history: {e}")
            return []
    
    def list_sessions(self) -> List[Dict]:
        """List all chat sessions with their first message"""
        try:
            results = self.conversations_collection.get()
            
            # Group by session_id
            sessions = {}
            if results["documents"]:
                for i, doc in enumerate(results["documents"]):
                    session_id = results["metadatas"][i].get("session_id", "unknown")
                    timestamp = results["metadatas"][i].get("timestamp", "")
                    role = results["metadatas"][i].get("role", "user")
                    
                    if session_id not in sessions:
                        sessions[session_id] = {
                            "session_id": session_id,
                            "first_message": "",
                            "first_timestamp": "",
                            "last_timestamp": "",
                            "message_count": 0
                        }
                    
                    sessions[session_id]["message_count"] += 1
                    
                    # Track first user message as title
                    if role == "user":
                        if not sessions[session_id]["first_timestamp"] or timestamp < sessions[session_id]["first_timestamp"]:
                            sessions[session_id]["first_message"] = doc[:100]  # First 100 chars
                            sessions[session_id]["first_timestamp"] = timestamp
                    
                    # Track last timestamp
                    if not sessions[session_id]["last_timestamp"] or timestamp > sessions[session_id]["last_timestamp"]:
                        sessions[session_id]["last_timestamp"] = timestamp
            
            # Convert to list and sort by last activity
            session_list = list(sessions.values())
            session_list.sort(key=lambda x: x.get("last_timestamp", ""), reverse=True)
            return session_list
        except Exception as e:
            print(f"Error listing sessions: {e}")
            return []
    
    def delete_session(self, session_id: str) -> bool:
        """Delete all messages in a session"""
        try:
            results = self.conversations_collection.get(
                where={"session_id": session_id}
            )
            
            if results["ids"]:
                self.conversations_collection.delete(ids=results["ids"])
            return True
        except Exception as e:
            print(f"Error deleting session: {e}")
            return False
    
    def clear_knowledge(self) -> bool:
        """Clear all knowledge base entries"""
        try:
            self.client.delete_collection("nova_knowledge")
            self.knowledge_collection = self.client.create_collection(
                name="nova_knowledge",
                embedding_function=self.embedding_fn,
                metadata={"description": "Nutanix Objects knowledge base"}
            )
            return True
        except Exception:
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Get collection statistics"""
        return {
            "knowledge_count": self.knowledge_collection.count(),
            "commands_count": self.commands_collection.count(),
            "conversations_count": self.conversations_collection.count(),
            "config_count": self.config_collection.count()
        }
    
    # ==================== Configuration Storage ====================
    
    def save_config(self, key: str, value: Any) -> bool:
        """Save a configuration value to the database"""
        try:
            # Check if config exists
            existing = self.config_collection.get(ids=[key])
            
            config_value = json.dumps(value) if not isinstance(value, str) else value
            
            if existing and existing['ids']:
                # Update existing
                self.config_collection.update(
                    ids=[key],
                    documents=[config_value],
                    metadatas=[{"key": key, "updated_at": datetime.now().isoformat()}]
                )
            else:
                # Add new
                self.config_collection.add(
                    ids=[key],
                    documents=[config_value],
                    metadatas=[{"key": key, "created_at": datetime.now().isoformat()}]
                )
            return True
        except Exception as e:
            print(f"Error saving config {key}: {e}")
            return False
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value from the database"""
        try:
            result = self.config_collection.get(ids=[key])
            if result and result['documents'] and result['documents'][0]:
                value = result['documents'][0]
                # Try to parse as JSON
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return default
        except Exception as e:
            print(f"Error getting config {key}: {e}")
            return default
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration values"""
        try:
            result = self.config_collection.get()
            config = {}
            if result and result['ids']:
                for i, key in enumerate(result['ids']):
                    value = result['documents'][i] if result['documents'] else None
                    try:
                        config[key] = json.loads(value) if value else None
                    except (json.JSONDecodeError, TypeError):
                        config[key] = value
            return config
        except Exception as e:
            print(f"Error getting all config: {e}")
            return {}
    
    def delete_config(self, key: str) -> bool:
        """Delete a configuration value"""
        try:
            self.config_collection.delete(ids=[key])
            return True
        except Exception as e:
            print(f"Error deleting config {key}: {e}")
            return False
    
    def save_prism_config(self, prism_ip: str, prism_port: int, prism_username: str, prism_password: str) -> bool:
        """Save Prism connection configuration"""
        config = {
            "prism_ip": prism_ip,
            "prism_port": prism_port,
            "prism_username": prism_username,
            "prism_password": prism_password,
            "updated_at": datetime.now().isoformat()
        }
        return self.save_config("prism_config", config)
    
    def get_prism_config(self) -> Dict[str, Any]:
        """Get Prism connection configuration"""
        return self.get_config("prism_config", {})
    
    def save_llm_config(self, provider: str, api_key: str = None, 
                        ollama_url: str = "http://localhost:11434", 
                        ollama_model: str = "llama3.1") -> bool:
        """Save LLM provider configuration"""
        config = {
            "provider": provider,
            "api_key": api_key,
            "ollama_url": ollama_url,
            "ollama_model": ollama_model,
            "updated_at": datetime.now().isoformat()
        }
        return self.save_config("llm_config", config)
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM provider configuration"""
        return self.get_config("llm_config", {
            "provider": "ollama",
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3.1"
        })
    
    def seed_objects_knowledge(self):
        """Seed knowledge base with Nutanix Objects information"""
        knowledge_docs = [
            # Bucket concepts
            "A bucket in Nutanix Objects is a container for storing objects. Buckets have unique names within an object store and can have versioning, WORM (Write Once Read Many), and lifecycle policies.",
            
            "To create a bucket in Nutanix Objects, you need: a unique bucket name (3-63 characters, lowercase letters, numbers, and hyphens), optional versioning for keeping object history, and optional WORM for compliance.",
            
            "Bucket versioning in Nutanix Objects allows you to keep multiple versions of an object. When enabled, deleting an object creates a delete marker instead of permanently removing it.",
            
            # Lifecycle management
            "Lifecycle policies in Nutanix Objects automate data management. You can set rules to transition objects to different storage classes or delete them after a certain number of days.",
            
            "A lifecycle rule consists of: a rule ID, optional prefix filter (to apply only to objects matching the prefix), transition actions (move to GLACIER), and expiration actions (delete after N days).",
            
            # Access management
            "Nutanix Objects uses S3-compatible access keys for authentication. Each access key has an Access Key ID and Secret Access Key. Keys should be stored securely and rotated periodically.",
            
            "Bucket policies in Nutanix Objects control who can access the bucket and what actions they can perform. Policies use JSON format similar to AWS S3 bucket policies.",
            
            # Object Store
            "An Object Store in Nutanix Objects is the top-level entity that contains buckets. Each object store has a unique endpoint URL used for S3 API access.",
            
            "Object Stores require: a cluster to deploy on, network configuration for client access, and storage capacity allocation. Worker nodes handle the object storage operations.",
            
            # Best practices
            "Best practices for Nutanix Objects: use meaningful bucket names, enable versioning for critical data, set lifecycle policies to optimize storage costs, use IAM policies for access control.",
            
            "For large file uploads to Nutanix Objects, use multipart upload. This allows uploading files in parts and provides better performance and reliability for files over 100MB.",
            
            # API information
            "Nutanix Objects provides an S3-compatible API. You can use any S3 SDK (boto3, aws-sdk) by pointing to the Objects endpoint URL and using Objects access keys.",
            
            "Common S3 operations supported: PUT object, GET object, DELETE object, LIST objects, HEAD object, multipart upload, copy object.",
            
            # Storage classes
            "Nutanix Objects supports storage classes for data tiering. STANDARD class is for frequently accessed data, GLACIER class is for archival with lower cost but higher retrieval time.",
        ]
        
        metadata = [{"source": "nutanix_objects_docs", "category": "knowledge_base"} for _ in knowledge_docs]
        
        return self.add_knowledge(knowledge_docs, metadata)


# Singleton instance
_vector_db: Optional[VectorDBService] = None


def get_vector_db(persist_dir: str = "./data/chroma") -> VectorDBService:
    """Get or create vector DB singleton"""
    global _vector_db
    if _vector_db is None:
        _vector_db = VectorDBService(persist_dir=persist_dir)
    return _vector_db
