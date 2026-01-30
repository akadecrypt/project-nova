#!/usr/bin/env python3
"""
NOVA SQL Agent Server

A lightweight FastAPI server that provides SQL query execution against SQLite database.
This is bundled with NOVA to make deployment self-contained.

Usage:
    python sql_agent.py [--port 9001] [--db nova.db]
"""

import os
import sys
import argparse
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Configuration
DEFAULT_PORT = 9001
DEFAULT_DB_PATH = os.path.expanduser("~/nova.db")

app = FastAPI(
    title="NOVA SQL Agent",
    description="SQL query execution service for NOVA",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global database path
DB_PATH = DEFAULT_DB_PATH


class SQLRequest(BaseModel):
    sql: str
    limit: Optional[int] = None


class SQLResponse(BaseModel):
    type: str
    row_count: Optional[int] = None
    rows: Optional[List[Dict[str, Any]]] = None
    rows_affected: Optional[int] = None
    columns: Optional[List[str]] = None
    error: Optional[str] = None


@contextmanager
def get_db_connection():
    """Get a database connection with proper cleanup."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        if conn:
            conn.close()


def init_database():
    """Initialize the database with required tables if they don't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create logs table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,
                severity TEXT,
                pod TEXT,
                event_type TEXT,
                message TEXT,
                node_name TEXT,
                object_store_name TEXT,
                bucket_name TEXT,
                raw_log_file TEXT,
                raw_file_path TEXT,
                raw_line_number INTEGER,
                stack_trace TEXT
            )
        """)
        
        # Create log_uploads table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_uploads (
                upload_id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_store_name TEXT,
                s3_key TEXT,
                upload_time INTEGER,
                status TEXT,
                logs_processed INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        
        # Create bucket table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bucket (
                bucket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                owner TEXT,
                region TEXT,
                versioning_enabled INTEGER DEFAULT 0,
                worm_enabled INTEGER DEFAULT 0,
                lifecycle_enabled INTEGER DEFAULT 0,
                created_at INTEGER
            )
        """)
        
        # Create bucket_stats table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bucket_stats (
                stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_name TEXT,
                timestamp INTEGER,
                size_gb REAL,
                object_count INTEGER
            )
        """)
        
        # Create object_store table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS object_store (
                store_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                uuid TEXT,
                cluster_ip TEXT,
                status TEXT DEFAULT 'active',
                created_at INTEGER
            )
        """)
        
        # Create alerts table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT,
                severity TEXT,
                entity_type TEXT,
                entity_id TEXT,
                source_store_uuid TEXT,
                bucket_name TEXT,
                message TEXT,
                first_detected_at INTEGER,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Create bucket_replication table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bucket_replication (
                replication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_bucket TEXT,
                target_bucket TEXT,
                target_store TEXT,
                status TEXT,
                pending_bytes INTEGER DEFAULT 0,
                last_sync_time INTEGER
            )
        """)
        
        # Create bucket_replication_stats table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bucket_replication_stats (
                stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_bucket TEXT,
                target_bucket TEXT,
                timestamp INTEGER,
                bytes_replicated INTEGER,
                objects_replicated INTEGER,
                lag_seconds INTEGER
            )
        """)
        
        # Create pod_resource_usage table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pod_resource_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pod_name TEXT,
                node_name TEXT,
                timestamp INTEGER,
                cpu_percent REAL,
                memory_mb REAL
            )
        """)
        
        conn.commit()
        print(f"✓ Database initialized: {DB_PATH}")


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    init_database()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        return {"status": "healthy", "database": DB_PATH}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.post("/execute")
async def execute_sql(request: SQLRequest) -> dict:
    """
    Execute a SQL query against the database.
    
    Args:
        request: SQLRequest with sql query and optional limit
        
    Returns:
        Query results with type, row_count, rows/rows_affected
    """
    sql = request.sql.strip()
    
    if not sql:
        raise HTTPException(status_code=400, detail="SQL query is required")
    
    # Determine if it's a read or write operation
    sql_upper = sql.upper()
    is_write = sql_upper.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"))
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Apply limit if provided and it's a SELECT
            if request.limit and sql_upper.startswith("SELECT") and "LIMIT" not in sql_upper:
                sql = f"{sql} LIMIT {request.limit}"
            
            cursor.execute(sql)
            
            if is_write:
                conn.commit()
                return {
                    "type": "write",
                    "rows_affected": cursor.rowcount
                }
            else:
                rows = cursor.fetchall()
                
                # Convert rows to list of dicts
                if rows:
                    columns = [description[0] for description in cursor.description]
                    result_rows = [dict(zip(columns, row)) for row in rows]
                else:
                    columns = [description[0] for description in cursor.description] if cursor.description else []
                    result_rows = []
                
                return {
                    "type": "read",
                    "row_count": len(result_rows),
                    "rows": result_rows,
                    "columns": columns
                }
                
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@app.get("/tables")
async def list_tables():
    """List all tables in the database."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            return {"tables": tables, "count": len(tables)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tables/{table_name}/schema")
async def get_table_schema(table_name: str):
    """Get schema for a specific table."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    "cid": row[0],
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "default": row[4],
                    "primary_key": bool(row[5])
                })
            return {"table": table_name, "columns": columns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="NOVA SQL Agent Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to run on (default: {DEFAULT_PORT})")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help=f"Database path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    
    args = parser.parse_args()
    
    global DB_PATH
    DB_PATH = os.path.expanduser(args.db)
    
    # Ensure database directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    print(f"""
╔══════════════════════════════════════════╗
║         NOVA SQL Agent Server            ║
╠══════════════════════════════════════════╣
║  Database: {DB_PATH:<28} ║
║  Endpoint: http://{args.host}:{args.port}/execute{' ' * (15 - len(str(args.port)))}║
╚══════════════════════════════════════════╝
    """)
    
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
