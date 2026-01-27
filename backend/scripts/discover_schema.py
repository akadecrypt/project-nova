#!/usr/bin/env python3
"""
Database Schema Discovery Script for NOVA

This script connects to the SQL agent and discovers the actual database schema,
then generates an updated sql_schema.md context file.

Usage:
    python scripts/discover_schema.py
    
    # Or with custom SQL agent URL
    python scripts/discover_schema.py --url http://your-sql-agent:9001/execute
"""
import sys
import json
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

# Load SQL URL from config.json
CONFIG_FILE = Path(__file__).parent.parent / "config.json"

def get_default_sql_url() -> str:
    """Get SQL agent URL from config.json"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get("sql_agent", {}).get("url", "")
    except Exception:
        pass
    return ""

DEFAULT_SQL_URL = get_default_sql_url()


def execute_sql(url: str, sql: str) -> dict:
    """Execute a SQL query"""
    try:
        response = requests.post(url, json={"sql": sql}, timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_tables(url: str) -> list:
    """Get list of all tables"""
    result = execute_sql(url, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    if result.get("status") == "error":
        print(f"Error getting tables: {result.get('error')}")
        return []
    return [row[0] for row in result.get("rows", [])]


def get_table_info(url: str, table_name: str) -> dict:
    """Get detailed info about a table"""
    # Get columns
    columns_result = execute_sql(url, f"PRAGMA table_info({table_name})")
    columns = []
    
    if columns_result.get("status") != "error":
        for row in columns_result.get("rows", []):
            columns.append({
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "primary_key": bool(row[5])
            })
    
    # Get row count
    count_result = execute_sql(url, f"SELECT COUNT(*) FROM {table_name}")
    row_count = 0
    if count_result.get("status") != "error" and count_result.get("rows"):
        row_count = count_result["rows"][0][0]
    
    # Get sample data (first 3 rows)
    sample_result = execute_sql(url, f"SELECT * FROM {table_name} LIMIT 3")
    sample_rows = []
    if sample_result.get("status") != "error":
        sample_rows = sample_result.get("rows", [])
    
    # Get foreign keys
    fk_result = execute_sql(url, f"PRAGMA foreign_key_list({table_name})")
    foreign_keys = []
    if fk_result.get("status") != "error":
        for row in fk_result.get("rows", []):
            foreign_keys.append({
                "from_column": row[3],
                "to_table": row[2],
                "to_column": row[4]
            })
    
    return {
        "name": table_name,
        "columns": columns,
        "row_count": row_count,
        "sample_rows": sample_rows,
        "foreign_keys": foreign_keys
    }


def generate_markdown(tables_info: list) -> str:
    """Generate markdown documentation from table info"""
    lines = [
        "# SQL Analytics Database Schema",
        "",
        "## Overview",
        "This document describes the database schema used for object store analytics and metadata tracking.",
        "The schema is auto-generated from the actual database structure.",
        "",
        f"**Total Tables:** {len(tables_info)}",
        "",
        "## Table of Contents",
        ""
    ]
    
    # Generate TOC
    for table in tables_info:
        lines.append(f"- [{table['name']}](#{table['name'].lower()})")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Generate table documentation
    for table in tables_info:
        table_name = table["name"]
        row_count = table["row_count"]
        columns = table["columns"]
        foreign_keys = table.get("foreign_keys", [])
        
        lines.append(f"## {table_name}")
        lines.append(f"*{row_count:,} rows*")
        lines.append("")
        
        # Columns table
        lines.append("### Columns")
        lines.append("")
        lines.append("| Column | Type | Nullable | Primary Key | Default |")
        lines.append("|--------|------|----------|-------------|---------|")
        
        for col in columns:
            nullable = "Yes" if not col["notnull"] else "No"
            pk = "Yes" if col["primary_key"] else ""
            default = col["default"] if col["default"] else ""
            lines.append(f"| {col['name']} | {col['type']} | {nullable} | {pk} | {default} |")
        
        lines.append("")
        
        # Foreign keys
        if foreign_keys:
            lines.append("### Foreign Keys")
            lines.append("")
            for fk in foreign_keys:
                lines.append(f"- `{fk['from_column']}` → `{fk['to_table']}.{fk['to_column']}`")
            lines.append("")
        
        # Sample query
        col_names = ", ".join([c["name"] for c in columns[:5]])
        lines.append("### Example Query")
        lines.append("")
        lines.append("```sql")
        lines.append(f"SELECT {col_names}")
        lines.append(f"FROM {table_name}")
        lines.append("LIMIT 10;")
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Add common query patterns
    lines.extend([
        "## Common Query Patterns",
        "",
        "### Get Row Counts for All Tables",
        "```sql",
        "SELECT name, ",
        "       (SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=m.name) as row_count",
        "FROM sqlite_master m",
        "WHERE type='table';",
        "```",
        "",
        "### Check Table Structure",
        "```sql",
        "PRAGMA table_info(table_name);",
        "```",
        ""
    ])
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Discover database schema and generate context")
    parser.add_argument("--url", default=DEFAULT_SQL_URL, help="SQL agent URL")
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--json", action="store_true", help="Also output JSON schema")
    args = parser.parse_args()
    
    print(f"🔍 Connecting to SQL agent at {args.url}")
    
    # Get tables
    tables = get_tables(args.url)
    if not tables:
        print("❌ No tables found or could not connect to SQL agent")
        sys.exit(1)
    
    print(f"📋 Found {len(tables)} tables: {', '.join(tables)}")
    
    # Get info for each table
    tables_info = []
    for table in tables:
        print(f"   Analyzing {table}...")
        info = get_table_info(args.url, table)
        tables_info.append(info)
    
    # Generate markdown
    markdown = generate_markdown(tables_info)
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(__file__).parent.parent / "context" / "sql_schema.md"
    
    # Write markdown
    output_path.write_text(markdown, encoding="utf-8")
    print(f"✅ Schema documentation written to {output_path}")
    
    # Optionally write JSON
    if args.json:
        json_path = output_path.with_suffix(".json")
        json_path.write_text(json.dumps(tables_info, indent=2), encoding="utf-8")
        print(f"✅ JSON schema written to {json_path}")
    
    # Print summary
    print("\n📊 Schema Summary:")
    for table in tables_info:
        print(f"   - {table['name']}: {len(table['columns'])} columns, {table['row_count']:,} rows")


if __name__ == "__main__":
    main()
