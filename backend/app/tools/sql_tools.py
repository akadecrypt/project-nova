"""
SQL Tools for NOVA Backend

Implements SQL query execution against the metadata database.
"""
import requests
from typing import Optional, List, Dict, Any

from ..config import get_sql_agent_url
from ..logging_config import get_tools_logger, log_sql_query

logger = get_tools_logger()


def execute_sql(sql: str, timeout: int = 10) -> dict:
    """
    Execute a SQL query on the object store metadata database.
    
    Args:
        sql: SQL query to execute
        timeout: Request timeout in seconds
        
    Returns:
        Result dictionary with status, columns, rows, etc.
    """
    try:
        url = get_sql_agent_url()
        
        # Normalize SQL: strip whitespace and collapse multiple spaces
        sql = ' '.join(sql.split())
        
        logger.info(f"SQL: {sql[:150]}{'...' if len(sql) > 150 else ''}")
        
        response = requests.post(
            url,
            json={"sql": sql},
            timeout=timeout
        )
        
        if response.status_code != 200:
            error_msg = f"SQL agent returned status {response.status_code}"
            logger.error(error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "response": response.text[:500]
            }
        
        result = response.json()
        row_count = result.get("row_count", len(result.get("rows", [])))
        logger.info(f"SQL result: {row_count} rows")
        return result
        
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot connect to SQL agent"
        logger.error(error_msg)
        return {
            "status": "error",
            "error": "Cannot connect to SQL agent. Make sure it's running."
        }
    except requests.exceptions.Timeout:
        error_msg = f"SQL query timed out after {timeout}s"
        logger.error(error_msg)
        return {
            "status": "error",
            "error": f"SQL query timed out after {timeout} seconds"
        }
    except Exception as e:
        logger.error(f"SQL error: {str(e)}")
        return {"status": "error", "error": str(e)}


def get_table_schema(table_name: str) -> dict:
    """
    Get schema information for a specific table.
    
    Since PRAGMA is not allowed, we infer schema from a sample row.
    
    Args:
        table_name: Name of the table
        
    Returns:
        Result dictionary with column information
    """
    # Get a sample row to infer column names
    result = execute_sql(f"SELECT * FROM {table_name} LIMIT 1")
    
    if result.get("status") == "error":
        return result
    
    columns = []
    rows = result.get("rows", [])
    
    if rows and isinstance(rows[0], dict):
        # Dict format: extract column names from keys
        for idx, (col_name, value) in enumerate(rows[0].items()):
            # Infer type from value
            if isinstance(value, int):
                col_type = "INTEGER"
            elif isinstance(value, float):
                col_type = "REAL"
            else:
                col_type = "TEXT"
            
            columns.append({
                "cid": idx,
                "name": col_name,
                "type": col_type,
                "notnull": False,
                "default": None,
                "primary_key": col_name.endswith("_id") or col_name.endswith("_uuid")
            })
    
    return {
        "status": "success",
        "table": table_name,
        "columns": columns
    }


def list_tables() -> dict:
    """
    List all tables in the database.
    
    Returns:
        Result dictionary with table names
    """
    result = execute_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    
    if result.get("status") == "error":
        return result
    
    rows = result.get("rows", [])
    # Handle both dict rows [{"name": "x"}] and array rows [["x"]]
    if rows and isinstance(rows[0], dict):
        tables = [list(row.values())[0] for row in rows]
    else:
        tables = [row[0] for row in rows]
    
    return {
        "status": "success",
        "tables": tables,
        "count": len(tables)
    }


def get_database_summary() -> dict:
    """
    Get a summary of the database structure.
    
    Returns:
        Result dictionary with database overview
    """
    tables_result = list_tables()
    
    if tables_result.get("status") == "error":
        return tables_result
    
    summary = {
        "status": "success",
        "tables": []
    }
    
    for table_name in tables_result.get("tables", []):
        schema = get_table_schema(table_name)
        
        # Get row count
        count_result = execute_sql(f"SELECT COUNT(*) FROM {table_name}")
        row_count = 0
        if count_result.get("status") != "error" and count_result.get("rows"):
            first_row = count_result["rows"][0]
            if isinstance(first_row, dict):
                row_count = list(first_row.values())[0]
            else:
                row_count = first_row[0]
        
        summary["tables"].append({
            "name": table_name,
            "columns": schema.get("columns", []) if schema.get("status") != "error" else [],
            "row_count": row_count
        })
    
    return summary


def generate_schema_context() -> str:
    """
    Generate a markdown context document from the actual database schema.
    
    Returns:
        Markdown string describing the database schema
    """
    summary = get_database_summary()
    
    if summary.get("status") == "error":
        return f"# SQL Database Schema\n\nError retrieving schema: {summary.get('error')}"
    
    lines = [
        "# SQL Analytics Database Schema",
        "",
        "## Overview",
        "Object store metadata is stored in a SQLite database for analytics and historical tracking.",
        "",
        "## Tables",
        ""
    ]
    
    for table in summary.get("tables", []):
        table_name = table["name"]
        row_count = table["row_count"]
        columns = table["columns"]
        
        lines.append(f"### {table_name}")
        lines.append(f"*{row_count} rows*")
        lines.append("")
        lines.append("| Column | Type | Primary Key | Description |")
        lines.append("|--------|------|-------------|-------------|")
        
        for col in columns:
            pk = "Yes" if col["primary_key"] else ""
            lines.append(f"| {col['name']} | {col['type']} | {pk} | |")
        
        lines.append("")
    
    return "\n".join(lines)
