"""
Tools Package for NOVA Backend

Contains tool implementations and the tool manager.
"""
from .manager import ToolManager, get_tool_manager, initialize_tool_manager
from .s3_tools import (
    create_bucket, list_buckets, list_objects, put_object, 
    delete_object, get_bucket_info, get_s3_client
)
from .sql_tools import (
    execute_sql, get_table_schema, list_tables, get_database_summary
)
from .prism_tools import get_object_stores, fetch_object_store_stats_v4

# Tool function registry
TOOLS_REGISTRY = {
    # S3/Bucket tools
    "create_bucket": create_bucket,
    "list_buckets": list_buckets,
    "list_objects": list_objects,
    "put_object": put_object,
    "delete_object": delete_object,
    "get_bucket_info": get_bucket_info,
    # SQL/Analytics tools
    "execute_sql": execute_sql,
    "get_table_schema": get_table_schema,
    "list_tables": list_tables,
    "get_database_summary": get_database_summary,
    # Prism Central tools
    "get_object_stores": get_object_stores,
    "fetch_object_store_stats_v4": fetch_object_store_stats_v4
}


def execute_tool(tool_name: str, tool_args: dict) -> dict:
    """
    Execute a tool by name with given arguments.
    
    Args:
        tool_name: Name of the tool to execute
        tool_args: Arguments to pass to the tool
        
    Returns:
        Tool execution result as dictionary
    """
    if tool_name in TOOLS_REGISTRY:
        try:
            return TOOLS_REGISTRY[tool_name](**tool_args)
        except Exception as e:
            return {"status": "error", "error": str(e)}
    return {"status": "error", "error": f"Unknown tool: {tool_name}"}
