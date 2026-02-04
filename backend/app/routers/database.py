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
    all_tables = []
    
    # Get tables from SQL agent (nova.db)
    config_check = check_sql_configured()
    if not config_check:
        result = get_database_summary()
        if result.get("status") != "error":
            for table in result.get("tables", []):
                table["source"] = "nova"
                all_tables.append(table)
    
    # Also get tables from JITA database
    jita_tables = get_jita_database_summary()
    all_tables.extend(jita_tables)
    
    if not all_tables:
        return {
            "success": False,
            "tables": [],
            "error": "No database tables found"
        }
    
    return {
        "success": True,
        "tables": all_tables
    }


# ============= JITA Database Functions =============
import os
import sqlite3

JITA_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "jita_data.db")


def get_jita_database_summary():
    """Get summary of JITA database tables"""
    tables = []
    
    if not os.path.exists(JITA_DB_PATH):
        return tables
    
    try:
        conn = sqlite3.connect(JITA_DB_PATH)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = [row[0] for row in cursor.fetchall()]
        
        for table_name in table_names:
            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]
            
            # Get schema
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = []
            for col in cursor.fetchall():
                columns.append({
                    "name": col[1],
                    "type": col[2],
                    "nullable": not col[3],
                    "primary_key": bool(col[5])
                })
            
            tables.append({
                "name": table_name,
                "row_count": row_count,
                "columns": columns,
                "source": "jita"
            })
        
        conn.close()
    except Exception as e:
        print(f"Error reading JITA database: {e}")
    
    return tables


def execute_jita_sql(sql: str, limit: int = 100):
    """Execute SQL on JITA database"""
    if not os.path.exists(JITA_DB_PATH):
        return {"status": "error", "error": "JITA database not found"}
    
    try:
        conn = sqlite3.connect(JITA_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        if rows:
            columns = list(rows[0].keys())
            result_rows = [list(row) for row in rows]
        else:
            columns = []
            result_rows = []
        
        conn.close()
        
        return {
            "status": "success",
            "columns": columns,
            "rows": result_rows
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.get("/jita/tables")
async def get_jita_tables():
    """List all tables in the JITA database"""
    tables = get_jita_database_summary()
    return {
        "success": True,
        "tables": [t["name"] for t in tables],
        "count": len(tables)
    }


@router.get("/jita/tables/{table_name}/data")
async def get_jita_table_data(table_name: str, limit: int = 100, offset: int = 0):
    """Get data from a JITA table with pagination"""
    # Sanitize table name
    if not table_name.replace("_", "").isalnum():
        return {"success": False, "error": "Invalid table name"}
    
    # Get total count
    count_result = execute_jita_sql(f"SELECT COUNT(*) as cnt FROM {table_name}")
    total = 0
    if count_result.get("status") == "success" and count_result.get("rows"):
        total = count_result["rows"][0][0]
    
    # Get data
    result = execute_jita_sql(f"SELECT * FROM {table_name} LIMIT {limit} OFFSET {offset}")
    
    if result.get("status") == "error":
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "error": result.get("error")
        }
    
    return {
        "success": True,
        "table": table_name,
        "columns": result.get("columns", []),
        "rows": result.get("rows", []),
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/jita/tables/{table_name}/schema")
async def get_jita_table_schema(table_name: str):
    """Get schema for a JITA table"""
    tables = get_jita_database_summary()
    
    for table in tables:
        if table["name"] == table_name:
            return {
                "success": True,
                "table": table_name,
                "columns": table["columns"]
            }
    
    return {
        "success": False,
        "columns": [],
        "error": f"Table {table_name} not found"
    }


@router.post("/jita/query")
async def run_jita_query(request: QueryRequest):
    """Execute a SQL query on JITA database"""
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
    
    result = execute_jita_sql(sql)
    
    if result.get("status") == "error":
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "error": result.get("error")
        }
    
    rows = result.get("rows", [])
    return {
        "success": True,
        "columns": result.get("columns", []),
        "rows": rows,
        "row_count": len(rows)
    }
