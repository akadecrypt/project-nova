"""
Chat Router for NOVA Backend

Handles chat endpoints and conversation management.
"""
import json
from typing import Dict, List, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..models import ChatMessage, ChatResponse, SessionInfo
from ..context import get_context_manager
from ..tools import get_tool_manager, execute_tool
from ..llm import get_llm_client
from ..config import get_llm_model

router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory session storage
chat_sessions: Dict[str, List[dict]] = {}


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into human readable string"""
    if num_bytes is None:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} EB"


def get_suggestions(intent: str) -> List[str]:
    """Get contextual suggestions based on intent"""
    suggestions_map = {
        "create_bucket": ["List buckets", "Upload a file", "Show bucket stats"],
        "list_buckets": ["Create a bucket", "Show object stores", "List objects in a bucket"],
        "list_objects": ["Upload a file", "Show bucket stats", "Create another bucket"],
        "put_object": ["List objects", "Create another bucket", "Show storage stats"],
        "execute_sql": ["Show bucket trends", "List buckets by size", "Show daily growth"],
        "get_object_stores": ["Show object store stats", "List buckets", "Show storage trends"],
        "fetch_object_store_stats_v4": ["Show another time range", "Compare object stores", "List buckets"]
    }
    return suggestions_map.get(intent, ["List buckets", "Show object stores", "Help"])


def format_tool_result(tool_name: str, result: dict) -> str:
    """Format tool result into a readable message"""
    if result.get("status") == "error":
        return f"**Error**: {result.get('error', 'Unknown error occurred')}"
    
    # Format based on tool type
    if tool_name == "list_buckets":
        buckets = result.get("buckets", [])
        count = result.get("count", len(buckets))
        if not buckets:
            return "No buckets found."
        lines = [f"**Buckets ({count} found):**\n"]
        lines.append("| Name | Created |")
        lines.append("|------|---------|")
        for b in buckets:
            name = b.get("name", str(b)) if isinstance(b, dict) else str(b)
            created = b.get("created", "N/A") if isinstance(b, dict) else "N/A"
            # Format the datetime if it's an ISO string
            if created and created != "N/A":
                try:
                    created = created.split("T")[0]  # Just show date
                except:
                    pass
            lines.append(f"| {name} | {created} |")
        return "\n".join(lines)
    
    elif tool_name == "get_object_stores":
        stores = result.get("object_stores", [])
        if not stores:
            return "No object stores found."
        lines = [f"**Object Stores ({len(stores)} found):**\n"]
        lines.append("| Name | Domain | State | Total Capacity | Used Capacity |")
        lines.append("|------|--------|-------|----------------|---------------|")
        for store in stores:
            name = store.get('name', 'Unknown')
            domain = store.get('domain', 'N/A')
            state = store.get('state', 'N/A')
            total_bytes = store.get('total_capacity_bytes', 0)
            used_bytes = store.get('used_capacity_bytes', 0)
            total = _format_bytes(total_bytes) if total_bytes else 'N/A'
            used = _format_bytes(used_bytes) if used_bytes else 'N/A'
            lines.append(f"| {name} | {domain} | {state} | {total} | {used} |")
        return "\n".join(lines)
    
    elif tool_name == "list_objects":
        objects = result.get("objects", [])
        bucket = result.get("bucket", "")
        if not objects:
            return f"No objects found in bucket '{bucket}'."
        lines = [f"**Objects in '{bucket}':**\n"]
        lines.append("| Key | Size |")
        lines.append("|-----|------|")
        for obj in objects[:50]:  # Limit to 50
            key = obj.get("key", obj) if isinstance(obj, dict) else obj
            size = obj.get("size", "N/A") if isinstance(obj, dict) else "N/A"
            lines.append(f"| {key} | {size} |")
        if len(objects) > 50:
            lines.append(f"\n*... and {len(objects) - 50} more objects*")
        return "\n".join(lines)
    
    elif tool_name == "execute_sql":
        # Handle different response formats from SQL agent
        columns = result.get("columns", result.get("column_names", []))
        rows = result.get("rows", result.get("data", result.get("results", [])))
        
        # If still no columns, try to infer from first row
        if not columns and rows and isinstance(rows[0], (list, tuple)):
            columns = [f"Col{i+1}" for i in range(len(rows[0]))]
        elif not columns and rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())
            rows = [[r.get(c) for c in columns] for r in rows]
        
        if not rows:
            return "Query returned no results."
        
        lines = [f"**Query Results ({len(rows)} rows):**\n"]
        # Create table header
        lines.append("| " + " | ".join(str(c) for c in columns) + " |")
        lines.append("|" + "|".join(["---"] * len(columns)) + "|")
        # Add rows (limit to 30)
        for row in rows[:30]:
            row_values = row if isinstance(row, (list, tuple)) else [row]
            lines.append("| " + " | ".join(str(v) if v is not None else "NULL" for v in row_values) + " |")
        if len(rows) > 30:
            lines.append(f"\n*... and {len(rows) - 30} more rows*")
        return "\n".join(lines)
    
    elif tool_name == "create_bucket":
        bucket_name = result.get("bucket_name", result.get("bucket", ""))
        return f"✓ Bucket **{bucket_name}** created successfully."
    
    elif tool_name == "put_object":
        return f"✓ Object uploaded successfully to **{result.get('bucket', '')}**"
    
    elif tool_name == "delete_object":
        return f"✓ Object deleted successfully."
    
    elif tool_name == "list_tables":
        tables = result.get("tables", [])
        if not tables:
            return "No tables found in database."
        return "**Available Tables:**\n" + "\n".join(f"- {t}" for t in tables)
    
    elif tool_name == "get_table_schema":
        table = result.get("table", "")
        columns = result.get("columns", [])
        lines = [f"**Schema for '{table}':**\n"]
        lines.append("| Column | Type | Primary Key |")
        lines.append("|--------|------|-------------|")
        for col in columns:
            pk = "Yes" if col.get("primary_key") else ""
            lines.append(f"| {col.get('name')} | {col.get('type')} | {pk} |")
        return "\n".join(lines)
    
    elif tool_name == "get_bucket_info":
        return f"""**Bucket Info:**
- Name: {result.get('bucket_name', 'N/A')}
- Objects: {result.get('object_count', 'N/A')}
- Size: {result.get('total_size', 'N/A')}"""
    
    elif tool_name == "fetch_object_store_stats_v4":
        # Handle Object Store stats
        stats = result.get("stats", result)
        if isinstance(stats, dict):
            lines = ["**Object Store Statistics:**\n"]
            for key, value in stats.items():
                if key != "status":
                    formatted_key = key.replace("_", " ").title()
                    if isinstance(value, (int, float)) and value > 1000000:
                        value = _format_bytes(int(value))
                    lines.append(f"- **{formatted_key}**: {value}")
            return "\n".join(lines)
    
    # Default: format as readable output
    if isinstance(result, dict):
        # Remove status field and format nicely
        display_result = {k: v for k, v in result.items() if k != "status"}
        if display_result:
            lines = ["**Result:**\n"]
            for key, value in display_result.items():
                formatted_key = key.replace("_", " ").title()
                if isinstance(value, list) and value:
                    lines.append(f"**{formatted_key}:**")
                    for item in value[:20]:
                        lines.append(f"  - {item}")
                    if len(value) > 20:
                        lines.append(f"  - *... and {len(value) - 20} more*")
                elif isinstance(value, dict):
                    lines.append(f"**{formatted_key}:**")
                    for k, v in value.items():
                        lines.append(f"  - {k}: {v}")
                else:
                    lines.append(f"- **{formatted_key}**: {value}")
            return "\n".join(lines)
    
    return f"```json\n{json.dumps(result, indent=2, default=str)}\n```"


@router.post("", response_model=ChatResponse)
async def chat(request: ChatMessage):
    """Send a message to NOVA"""
    
    llm_client = get_llm_client()
    if not llm_client:
        return ChatResponse(
            message="LLM not configured. Please configure the API key in Settings.",
            intent="error",
            success=False,
            suggestions=["Go to Settings"]
        )
    
    session_id = request.session_id
    user_message = request.message
    
    # Get managers
    context_manager = get_context_manager()
    tool_manager = get_tool_manager()
    
    # Build dynamic system prompt
    system_prompt = context_manager.build_system_prompt()
    
    # Initialize or update session
    if session_id not in chat_sessions:
        chat_sessions[session_id] = [{"role": "system", "content": system_prompt}]
    else:
        # Update system prompt with latest context
        chat_sessions[session_id][0] = {"role": "system", "content": system_prompt}
    
    # Add user message
    chat_sessions[session_id].append({"role": "user", "content": user_message})
    
    model = get_llm_model()
    tools = tool_manager.get_tools()
    
    try:
        # Call LLM with tools
        response = llm_client.chat.completions.create(
            model=model,
            messages=chat_sessions[session_id],
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            max_tokens=1024
        )
        
        assistant_msg = response.choices[0].message
        
        # Handle tool calls
        if assistant_msg.tool_calls:
            chat_sessions[session_id].append(assistant_msg)
            
            tool_results = []
            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")
                
                # Execute the tool
                result = execute_tool(tool_name, tool_args)
                tool_results.append({"tool": tool_name, "result": result})
                
                # Add tool result to messages
                chat_sessions[session_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
            
            # Get final response after tool execution
            try:
                final_response = llm_client.chat.completions.create(
                    model=model,
                    messages=chat_sessions[session_id],
                    max_tokens=2048
                )
                final_msg = final_response.choices[0].message
                final_content = final_msg.content
                print(f"[NOVA] Tool results: {[tr['tool'] for tr in tool_results]}")
                print(f"[NOVA] LLM response length: {len(final_content) if final_content else 0}")
                print(f"[NOVA] LLM response preview: {final_content[:200] if final_content else 'None'}...")
            except Exception as e:
                print(f"[NOVA] Error getting final response: {e}")
                final_content = None
            
            intent = assistant_msg.tool_calls[0].function.name
            
            # Check if LLM's response is too generic or missing actual data
            needs_formatting = False
            if not final_content:
                needs_formatting = True
            else:
                content_lower = final_content.strip().lower()
                # Check for generic completion messages
                generic_patterns = [
                    "operation completed", "done", "completed", "finished",
                    "executed successfully", "query executed", "has been executed",
                    "here is the", "here are the", "i have",
                    "the results", "the data"
                ]
                # If response is short and generic, format it ourselves
                if len(final_content.strip()) < 100:
                    for pattern in generic_patterns:
                        if pattern in content_lower:
                            needs_formatting = True
                            break
                # Also check if response contains SQL query instead of results
                if "SELECT" in final_content.upper() and "|" not in final_content:
                    needs_formatting = True
            
            if needs_formatting:
                formatted_results = []
                for tr in tool_results:
                    formatted_results.append(format_tool_result(tr["tool"], tr["result"]))
                final_content = "\n\n".join(formatted_results)
            
            # Store the response in session
            chat_sessions[session_id].append({"role": "assistant", "content": final_content})
            
            return ChatResponse(
                message=final_content,
                intent=intent,
                success=True,
                data={"tool_results": tool_results},
                suggestions=get_suggestions(intent)
            )
        else:
            chat_sessions[session_id].append(assistant_msg)
            
            return ChatResponse(
                message=assistant_msg.content or "I'm not sure how to help with that.",
                intent="chat",
                success=True,
                suggestions=["List buckets", "Show object stores", "Help"]
            )
            
    except Exception as e:
        return ChatResponse(
            message=f"Error: {str(e)}",
            intent="error",
            success=False
        )


@router.get("/sessions")
async def list_sessions():
    """List all chat sessions"""
    sessions = []
    for session_id, messages in chat_sessions.items():
        first_user_msg = next(
            (m["content"][:50] for m in messages if m["role"] == "user"),
            "New conversation"
        )
        sessions.append({
            "session_id": session_id,
            "title": first_user_msg,
            "message_count": len([m for m in messages if m["role"] in ["user", "assistant"]])
        })
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get chat history for a session"""
    if session_id not in chat_sessions:
        return {"session_id": session_id, "messages": []}
    
    messages = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in chat_sessions[session_id]
        if m["role"] in ["user", "assistant"] and m.get("content")
    ]
    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session"""
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    return {"success": True, "session_id": session_id}


@router.post("/sessions/new")
async def new_session():
    """Create a new chat session"""
    session_id = f"session-{int(datetime.now().timestamp() * 1000)}"
    context_manager = get_context_manager()
    system_prompt = context_manager.build_system_prompt()
    chat_sessions[session_id] = [{"role": "system", "content": system_prompt}]
    return {"session_id": session_id}
