"""
Chat Router for NOVA Backend

Handles chat endpoints and conversation management.
"""
import json
from typing import Dict, List
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
            final_response = llm_client.chat.completions.create(
                model=model,
                messages=chat_sessions[session_id],
                max_tokens=1024
            )
            
            final_msg = final_response.choices[0].message
            chat_sessions[session_id].append(final_msg)
            
            intent = assistant_msg.tool_calls[0].function.name
            
            return ChatResponse(
                message=final_msg.content or "Operation completed.",
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
