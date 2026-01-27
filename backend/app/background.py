"""
Background Tasks for NOVA Backend

Handles periodic tasks like SQL summary refresh.
"""
import asyncio
from datetime import datetime

from .context import get_context_manager
from .tools.sql_tools import execute_sql
from .config import get_background_refresh_interval, is_background_refresh_enabled


async def refresh_sql_summary():
    """
    Background task to refresh SQL data summary.
    
    Periodically queries the database and updates the context manager
    with current data statistics.
    """
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
                    tables = [row[0] for row in tables_result["rows"]]
                    summary_parts.append(f"**Available Tables:** {', '.join(tables)}")
                    summary_parts.append("")
                    
                    # Get row counts for each table
                    for table in tables[:10]:  # Limit to first 10 tables
                        count_result = execute_sql(f"SELECT COUNT(*) FROM {table}")
                        if count_result.get("status") != "error" and count_result.get("rows"):
                            count = count_result["rows"][0][0]
                            summary_parts.append(f"- {table}: {count} rows")
                
                # Try to get bucket stats if available
                bucket_stats = execute_sql("""
                    SELECT SUM(size_gb) as total_gb, SUM(object_count) as total_objects 
                    FROM bucket_stats 
                    WHERE timestamp = (SELECT MAX(timestamp) FROM bucket_stats)
                """)
                
                if bucket_stats.get("status") != "error" and bucket_stats.get("rows"):
                    row = bucket_stats["rows"][0]
                    if row[0]:
                        summary_parts.append("")
                        summary_parts.append(f"**Storage Summary:**")
                        summary_parts.append(f"- Total Storage: {row[0]:.2f} GB")
                        summary_parts.append(f"- Total Objects: {row[1]}")
                
                if summary_parts:
                    summary = "\n".join(summary_parts)
                    context_manager.update_sql_summary(summary)
                    print(f"📊 SQL summary refreshed at {datetime.now().isoformat()}")
                
            except Exception as e:
                print(f"⚠️ Failed to refresh SQL summary: {e}")
        
        await asyncio.sleep(interval)


async def start_background_tasks():
    """Start all background tasks"""
    return asyncio.create_task(refresh_sql_summary())
