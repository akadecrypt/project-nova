"""
Database Browser Router for NOVA Backend

Provides endpoints for browsing and querying the SQLite analytics database.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Any

from ..tools.sql_tools import execute_sql, list_tables, get_table_schema, get_database_summary
from ..config import get_sql_agent_url

router = APIRouter(prefix="/api/database", tags=["database"])


def check_sql_configured():
    """Check if SQL agent is configured"""
    url = get_sql_agent_url()
    if not url:
        return {"success": False, "error": "SQL Agent not configured. Go to Settings > SQL Agent Configuration."}
    return None  # Explicitly return None when configured


class QueryRequest(BaseModel):
    """SQL query request"""
    sql: str
    limit: Optional[int] = 100


class QueryResponse(BaseModel):
    """SQL query response"""
    success: bool
    columns: List[str] = []
    rows: List[List[Any]] = []
    row_count: int = 0
    error: Optional[str] = None


@router.get("/tables")
async def get_tables():
    """List all tables in the database"""
    config_check = check_sql_configured()
    if config_check:
        return config_check
    
    result = list_tables()
    
    if result.get("status") == "error":
        return {
            "success": False,
            "tables": [],
            "error": result.get("error")
        }
    
    return {
        "success": True,
        "tables": result.get("tables", []),
        "count": result.get("count", 0)
    }


@router.get("/tables/{table_name}/schema")
async def get_schema(table_name: str):
    """Get schema for a specific table"""
    result = get_table_schema(table_name)
    
    if result.get("status") == "error":
        return {
            "success": False,
            "columns": [],
            "error": result.get("error")
        }
    
    return {
        "success": True,
        "table": table_name,
        "columns": result.get("columns", [])
    }


def normalize_rows(rows, columns=None):
    """Convert dict rows to array rows for frontend"""
    if not rows:
        return [], columns or []
    
    # If rows are dicts, extract columns and convert to arrays
    if isinstance(rows[0], dict):
        if not columns:
            columns = list(rows[0].keys())
        return [[row.get(col) for col in columns] for row in rows], columns
    
    return rows, columns or []


@router.get("/tables/{table_name}/data")
async def get_table_data(table_name: str, limit: int = 100, offset: int = 0):
    """Get data from a table with pagination"""
    # Sanitize table name to prevent SQL injection
    if not table_name.replace("_", "").isalnum():
        return {"success": False, "error": "Invalid table name"}
    
    # Get total count
    count_result = execute_sql(f"SELECT COUNT(*) as cnt FROM {table_name}")
    total = 0
    if count_result.get("rows"):
        first_row = count_result["rows"][0]
        if isinstance(first_row, dict):
            total = list(first_row.values())[0]
        else:
            total = first_row[0]
    
    # Get data
    result = execute_sql(f"SELECT * FROM {table_name} LIMIT {limit} OFFSET {offset}")
    
    if result.get("status") == "error":
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "error": result.get("error")
        }
    
    rows, columns = normalize_rows(result.get("rows", []), result.get("columns"))
    
    return {
        "success": True,
        "table": table_name,
        "columns": columns,
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.post("/query")
async def run_query(request: QueryRequest):
    """Execute a SQL query"""
    config_check = check_sql_configured()
    if config_check:
        return {**config_check, "columns": [], "rows": []}
    
    sql = request.sql.strip()
    
    # Only allow SELECT queries for safety
    if not sql.upper().startswith("SELECT"):
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "error": "Only SELECT queries are allowed"
        }
    
    # Add LIMIT if not present
    if "LIMIT" not in sql.upper():
        sql = f"{sql} LIMIT {request.limit}"
    
    result = execute_sql(sql)
    
    if result.get("status") == "error":
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "error": result.get("error")
        }
    
    rows, columns = normalize_rows(result.get("rows", []), result.get("columns"))
    return {
        "success": True,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows)
    }


@router.get("/summary")
async def get_summary():
    """Get database summary with all tables and their info"""
    config_check = check_sql_configured()
    if config_check:
        return config_check
    
    result = get_database_summary()
    
    if result.get("status") == "error":
        return {
            "success": False,
            "tables": [],
            "error": result.get("error")
        }
    
    return {
        "success": True,
        "tables": result.get("tables", [])
    }
