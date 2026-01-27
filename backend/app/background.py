"""
Background Tasks for NOVA Backend

Handles periodic tasks like SQL summary refresh, dynamic schema loading,
and automated log collection.
"""
import asyncio
from datetime import datetime

from .context import get_context_manager
from .tools.sql_tools import execute_sql, get_database_summary
from .config import (
    get_background_refresh_interval, is_background_refresh_enabled,
    get_collection_interval_hours, is_auto_collect_enabled, get_initial_delay_minutes
)


def get_row_value(row, index=0):
    """Helper to get value from row (handles both dict and array rows)"""
    if isinstance(row, dict):
        return list(row.values())[index]
    return row[index]


def generate_dynamic_schema():
    """
    Generate SQL schema documentation from the actual database.
    
    Returns:
        Markdown string with complete schema information
    """
    lines = [
        "# SQL Analytics Database Schema (Auto-Generated)",
        "",
        "This schema was automatically detected from the connected database.",
        "",
        "## Available Tables",
        ""
    ]
    
    try:
        summary = get_database_summary()
        
        if summary.get("status") == "error":
            return f"# SQL Database\n\nError loading schema: {summary.get('error')}"
        
        tables = summary.get("tables", [])
        
        if not tables:
            return "# SQL Database\n\nNo tables found in database."
        
        for table in tables:
            table_name = table.get("name", "Unknown")
            row_count = table.get("row_count", 0)
            columns = table.get("columns", [])
            
            lines.append(f"### {table_name}")
            lines.append(f"*{row_count:,} rows*")
            lines.append("")
            
            if columns:
                lines.append("| Column | Type | Primary Key |")
                lines.append("|--------|------|-------------|")
                for col in columns:
                    pk = "Yes" if col.get("primary_key") else ""
                    col_name = col.get("name", "")
                    col_type = col.get("type", "TEXT")
                    lines.append(f"| {col_name} | {col_type} | {pk} |")
            
            lines.append("")
        
        # Add query examples
        lines.extend([
            "## Common Query Patterns",
            "",
            "### List all data from a table",
            "```sql",
            f"SELECT * FROM {tables[0]['name']} LIMIT 100;",
            "```",
            "",
            "### Get row counts",
            "```sql",
            f"SELECT COUNT(*) FROM {tables[0]['name']};",
            "```",
            ""
        ])
        
        # Add table-specific examples if bucket table exists
        table_names = [t['name'] for t in tables]
        if 'bucket' in table_names:
            lines.extend([
                "### Bucket queries",
                "```sql",
                "SELECT * FROM bucket ORDER BY created_at DESC;",
                "```",
                ""
            ])
        
        if 'bucket_stats' in table_names:
            lines.extend([
                "### Bucket statistics",
                "```sql",
                "SELECT bucket_id, size_gb, object_count, timestamp",
                "FROM bucket_stats",
                "ORDER BY timestamp DESC LIMIT 100;",
                "```",
                ""
            ])
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"# SQL Database\n\nError generating schema: {str(e)}"


async def refresh_sql_summary():
    """
    Background task to refresh SQL data summary.
    
    Periodically queries the database and updates the context manager
    with current data statistics.
    """
    # Initial schema load on startup (after short delay)
    await asyncio.sleep(5)
    await load_dynamic_schema()
    
    while True:
        interval = get_background_refresh_interval()
        enabled = is_background_refresh_enabled()
        
        if enabled:
            try:
                context_manager = get_context_manager()
                summary_parts = []
                
                # Get table list first
                tables_result = execute_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                
                if tables_result.get("status") != "error" and tables_result.get("rows"):
                    rows = tables_result["rows"]
                    tables = [get_row_value(row, 0) for row in rows]
                    summary_parts.append(f"**Available Tables:** {', '.join(tables)}")
                    summary_parts.append("")
                    
                    # Get row counts for each table
                    for table in tables[:10]:  # Limit to first 10 tables
                        count_result = execute_sql(f"SELECT COUNT(*) FROM {table}")
                        if count_result.get("status") != "error" and count_result.get("rows"):
                            count = get_row_value(count_result["rows"][0], 0)
                            summary_parts.append(f"- {table}: {count} rows")
                
                # Try to get bucket stats if available
                bucket_stats = execute_sql("""
                    SELECT SUM(size_gb) as total_gb, SUM(object_count) as total_objects 
                    FROM bucket_stats 
                    WHERE timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
                """)
                
                if bucket_stats.get("status") != "error" and bucket_stats.get("rows"):
                    row = bucket_stats["rows"][0]
                    total_gb = get_row_value(row, 0)
                    total_objects = get_row_value(row, 1)
                    if total_gb:
                        summary_parts.append("")
                        summary_parts.append(f"**Storage Summary:**")
                        summary_parts.append(f"- Total Storage: {total_gb:.2f} GB")
                        summary_parts.append(f"- Total Objects: {total_objects}")
                
                if summary_parts:
                    summary = "\n".join(summary_parts)
                    context_manager.update_sql_summary(summary)
                    print(f"📊 SQL summary refreshed at {datetime.now().isoformat()}")
                
            except Exception as e:
                print(f"⚠️ Failed to refresh SQL summary: {e}")
        
        await asyncio.sleep(interval)


async def load_dynamic_schema():
    """Load the database schema dynamically and update the context"""
    try:
        context_manager = get_context_manager()
        schema_md = generate_dynamic_schema()
        
        # Update the sql_schema context with dynamic content
        context_manager.set_context("sql_schema", schema_md)
        print("📊 Dynamic SQL schema loaded from database")
        
    except Exception as e:
        print(f"⚠️ Failed to load dynamic schema: {e}")


async def refresh_schema_periodically():
    """Periodically refresh the database schema (every 10 minutes)"""
    while True:
        await asyncio.sleep(600)  # Every 10 minutes
        await load_dynamic_schema()


async def save_learning_periodically():
    """Periodically save learning data to disk"""
    from .learning import get_learning_manager
    
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        try:
            learning_manager = get_learning_manager()
            learning_manager.save()
            print("💾 Learning data auto-saved")
        except Exception as e:
            print(f"⚠️ Failed to auto-save learning data: {e}")


async def collect_logs_periodically():
    """
    Periodically collect logs from all object store clusters.
    
    Discovers clusters from Prism Central and runs logbay collection
    on each cluster, uploading results to S3 for analysis.
    """
    from .services.log_collector import get_log_collector, run_log_collection
    
    # Check if auto-collection is enabled
    if not is_auto_collect_enabled():
        print("📋 Log auto-collection is disabled")
        return
    
    # Initial delay to let other services start
    initial_delay = get_initial_delay_minutes() * 60
    print(f"📋 Log collection will start in {get_initial_delay_minutes()} minutes...")
    await asyncio.sleep(initial_delay)
    
    # Get collector and check prerequisites
    collector = get_log_collector()
    if not collector.has_sshpass:
        print("⚠️ sshpass not installed - log collection requires sshpass for SSH access")
        print("   Install with: brew install hudochenkov/sshpass/sshpass (macOS)")
        print("   Or: sudo apt-get install sshpass (Ubuntu/Debian)")
        return
    
    # Get collection interval
    interval_hours = get_collection_interval_hours()
    interval_seconds = interval_hours * 3600
    
    print(f"🔄 Starting automated log collection (every {interval_hours} hour(s))")
    
    while True:
        try:
            print(f"\n{'='*50}")
            print(f"📋 Log Collection Cycle - {datetime.now().isoformat()}")
            print(f"{'='*50}")
            
            # Run collection for the past hour
            results = await run_log_collection(hours=interval_hours)
            
            if results.get("clusters_collected", 0) > 0:
                print(f"✅ Collection complete: {results['clusters_collected']} cluster(s) processed")
            elif results.get("message"):
                print(f"⚠️ Collection skipped: {results['message']}")
            
        except Exception as e:
            print(f"❌ Log collection error: {e}")
        
        # Wait for next collection cycle
        print(f"⏰ Next collection in {interval_hours} hour(s)")
        await asyncio.sleep(interval_seconds)


async def start_background_tasks():
    """Start all background tasks"""
    tasks = [
        asyncio.create_task(refresh_sql_summary()),
        asyncio.create_task(save_learning_periodically()),
        asyncio.create_task(refresh_schema_periodically()),
        asyncio.create_task(collect_logs_periodically())
    ]
    return tasks
