"""
JITA Service for NOVA Backend

Integrates with JITA (Jita Is a Test Automation) to analyze test runs,
fetch logs, parse errors, and store results in SQL tables.
"""
import re
import os
import sqlite3
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from ..logging_config import get_logger

disable_warnings(InsecureRequestWarning)

logger = get_logger(__name__)

# Local SQLite database path for JITA data
JITA_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "jita_data.db")


def execute_sql(sql: str) -> dict:
    """Execute SQL directly on the local JITA SQLite database."""
    try:
        conn = sqlite3.connect(JITA_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        logger.debug(f"JITA SQL: {sql[:150]}...")
        cursor.execute(sql)
        conn.commit()
        
        # For SELECT statements, fetch results
        if sql.strip().upper().startswith('SELECT'):
            rows = [dict(row) for row in cursor.fetchall()]
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            conn.close()
            return {
                "status": "success",
                "columns": columns,
                "rows": rows,
                "row_count": len(rows)
            }
        else:
            affected = cursor.rowcount
            conn.close()
            return {
                "status": "success",
                "rows_affected": affected
            }
            
    except Exception as e:
        logger.error(f"JITA SQL error: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


class JitaService:
    """
    Service for analyzing JITA test runs.
    
    Fetches task details, test results, and logs from JITA API,
    parses them for errors, and stores in run-specific SQL tables.
    """
    
    JITA_BASE_URL = "https://jita.eng.nutanix.com/api/v2"
    AUTH = ("agave_bot", "admin")
    
    # Key log files to analyze (in priority order)
    KEY_LOG_FILES = [
        'nutest_test.log',           # Main test log
        'nutest_test_ERROR.log',     # Filtered error log
        'nutest_test_WARN.log',      # Filtered warning log
        'steps.log',                  # Test steps
        'nutest_class.log',          # Class-level log
        'nutest.log',                 # Root nutest log
        'nutest_resource_object_creation.log',  # Resource creation
        'test_exit_details.log',     # Exit details
        'log_normalization.log',     # Normalized logs
    ]
    
    # Failure log patterns
    FAILURE_LOG_PATTERNS = [
        r'.*_failure_.*\.log',       # Failure logs
        r'.*Error.*\.log',           # Error logs
        r'.*_error\.log',            # Error suffix logs
    ]
    
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.auth = self.AUTH
        # Cache for resolved log server URLs (jita_url -> direct_url)
        self._log_url_cache = {}
    
    def analyze_run(self, run_id: str) -> Dict[str, Any]:
        """
        Analyze a JITA run and store results in SQL.
        
        Args:
            run_id: JITA task/run ID (e.g., '697a296e8e79ce6b2202f970')
            
        Returns:
            Analysis summary with task info, test counts, and error summary
        """
        logger.info(f"Analyzing JITA run: {run_id}")
        
        # 1. Get task details
        task = self.get_task_details(run_id)
        if not task:
            return {"error": f"Task {run_id} not found"}
        
        # 2. Create tables for this run
        self.create_run_tables(run_id)
        
        # 3. Get all test results
        test_result_ids = self._extract_test_result_ids(task)
        logger.info(f"Found {len(test_result_ids)} test results")
        
        test_summaries = []
        all_log_events = []
        
        # 4. Process each test result
        for result_id in test_result_ids:
            result = self.get_test_result(result_id)
            if not result:
                continue
            
            # Extract summary
            summary = self._extract_test_summary(result_id, result)
            test_summaries.append(summary)
            
            # Extract timeline phases
            timeline_phases = self._extract_timeline_phases(result_id, result)
            
            # Extract log events from exception/stack trace
            events = self._extract_events_from_result(result_id, result)
            all_log_events.extend(events)
            
            # Fetch and parse logs with timeline correlation
            log_events = self._fetch_and_parse_logs(result_id, result, timeline_phases)
            all_log_events.extend(log_events)
            
            # Insert timeline data
            self._insert_timeline(run_id, timeline_phases)
        
        # 5. Insert data into SQL
        self._insert_summaries(run_id, test_summaries)
        self._insert_log_events(run_id, all_log_events)
        
        # 6. Save run metadata for quick listing
        test_counts = task.get('test_result_count', {})
        self.save_run_metadata(run_id, task, test_counts)
        
        # 7. Return analysis summary
        return self._build_analysis_response(run_id, task, test_summaries, all_log_events)
    
    def get_task_details(self, task_id: str) -> Optional[Dict]:
        """Fetch task details from JITA API."""
        try:
            url = f"{self.JITA_BASE_URL}/agave_tasks/{task_id}"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch task {task_id}: {response.status_code}")
                return None
            
            data = response.json()
            return data.get('data', data)
            
        except Exception as e:
            logger.error(f"Error fetching task {task_id}: {e}")
            return None
    
    def get_test_result(self, result_id: str) -> Optional[Dict]:
        """Fetch test result details from JITA API."""
        try:
            url = f"{self.JITA_BASE_URL}/test_results/{result_id}"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch result {result_id}: {response.status_code}")
                return None
            
            data = response.json()
            return data.get('data', data)
            
        except Exception as e:
            logger.error(f"Error fetching result {result_id}: {e}")
            return None
    
    def fetch_log_content(self, log_url: str) -> str:
        """Fetch log content from JITA log endpoint."""
        try:
            response = self.session.get(log_url, timeout=60)
            if response.status_code == 200:
                return response.text
            return ""
        except Exception as e:
            logger.warning(f"Error fetching log: {e}")
            return ""
    
    def create_run_tables(self, run_id: str, clear_existing: bool = True):
        """
        Create SQL tables for storing run analysis.
        
        Args:
            run_id: JITA run ID
            clear_existing: If True, clears existing data before re-analysis
        """
        # Sanitize run_id for table name (only alphanumeric)
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        
        # Create logs table
        logs_table = f"jita_{safe_id}_logs"
        create_logs_sql = f"""
        CREATE TABLE IF NOT EXISTS {logs_table} (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_result_id TEXT,
            test_name TEXT,
            log_source TEXT,
            timestamp INTEGER,
            severity TEXT,
            event_type TEXT,
            message TEXT,
            stack_trace TEXT,
            line_number INTEGER,
            phase TEXT,
            priority TEXT
        )
        """
        execute_sql(create_logs_sql)
        
        # Create summary table
        summary_table = f"jita_{safe_id}_summary"
        create_summary_sql = f"""
        CREATE TABLE IF NOT EXISTS {summary_table} (
            test_result_id TEXT PRIMARY KEY,
            test_name TEXT,
            status TEXT,
            total_ops INTEGER,
            successful_ops INTEGER,
            exception_summary TEXT,
            exception_full TEXT,
            duration_seconds INTEGER,
            cluster_info TEXT,
            cmd_executed TEXT,
            log_url TEXT
        )
        """
        execute_sql(create_summary_sql)
        
        # Create global runs metadata table (if not exists)
        execute_sql("""
            CREATE TABLE IF NOT EXISTS jita_runs_metadata (
                run_id TEXT PRIMARY KEY,
                label TEXT,
                service TEXT,
                created_by TEXT,
                task_status TEXT,
                total_tests INTEGER,
                passed_tests INTEGER,
                failed_tests INTEGER,
                analyzed_at TEXT
            )
        """)
        
        # Create timeline table for this run
        timeline_table = f"jita_{safe_id}_timeline"
        create_timeline_sql = f"""
        CREATE TABLE IF NOT EXISTS {timeline_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_result_id TEXT,
            test_name TEXT,
            phase_name TEXT,
            phase_order INTEGER,
            start_time INTEGER,
            end_time INTEGER,
            duration_seconds INTEGER,
            status TEXT,
            log_url TEXT
        )
        """
        execute_sql(create_timeline_sql)
        
        if clear_existing:
            execute_sql(f"DELETE FROM {timeline_table}")
        
        # Clear existing data if re-analyzing (to avoid duplicates)
        if clear_existing:
            execute_sql(f"DELETE FROM {logs_table}")
            execute_sql(f"DELETE FROM {summary_table}")
            logger.info(f"Cleared existing data from tables: {logs_table}, {summary_table}")
        
        logger.info(f"Tables ready: {logs_table}, {summary_table}")
    
    def save_run_metadata(self, run_id: str, task: Dict, test_counts: Dict):
        """Save run metadata for quick listing."""
        from datetime import datetime
        
        def escape(val):
            if isinstance(val, str):
                return val.replace("'", "''")
            return val or ''
        
        sql = f"""
            INSERT OR REPLACE INTO jita_runs_metadata 
            (run_id, label, service, created_by, task_status, total_tests, passed_tests, failed_tests, analyzed_at)
            VALUES (
                '{run_id}',
                '{escape(task.get("label", ""))}',
                '{escape(task.get("service", ""))}',
                '{escape(task.get("created_by", ""))}',
                '{escape(task.get("status", ""))}',
                {test_counts.get("Total", 0)},
                {test_counts.get("Succeeded", 0)},
                {test_counts.get("Failed", 0)},
                '{datetime.now().isoformat()}'
            )
        """
        execute_sql(sql)
    
    def get_runs_with_metadata(self) -> List[Dict]:
        """Get all analyzed runs with their metadata."""
        result = execute_sql("""
            SELECT run_id, label, service, created_by, task_status, 
                   total_tests, passed_tests, failed_tests, analyzed_at
            FROM jita_runs_metadata
            ORDER BY analyzed_at DESC
        """)
        
        if result.get("status") == "error":
            return []
        
        return result.get("rows", [])
    
    def get_run_summary(self, run_id: str) -> Dict[str, Any]:
        """Get summary of an analyzed run from SQL."""
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        summary_table = f"jita_{safe_id}_summary"
        logs_table = f"jita_{safe_id}_logs"
        
        # Get test summaries
        summary_result = execute_sql(f"SELECT * FROM {summary_table}")
        if summary_result.get("status") == "error":
            return {"error": f"Run {run_id} not found or not analyzed"}
        
        # Get error counts
        error_counts = execute_sql(f"""
            SELECT severity, COUNT(*) as count 
            FROM {logs_table} 
            GROUP BY severity
        """)
        
        # Get event type distribution
        event_types = execute_sql(f"""
            SELECT event_type, COUNT(*) as count 
            FROM {logs_table} 
            WHERE event_type IS NOT NULL
            GROUP BY event_type 
            ORDER BY count DESC 
            LIMIT 10
        """)
        
        return {
            "run_id": run_id,
            "tests": summary_result.get("rows", []),
            "error_counts": error_counts.get("rows", []),
            "event_types": event_types.get("rows", [])
        }
    
    def get_run_logs(
        self, 
        run_id: str, 
        severity: str = None,
        event_type: str = None,
        test_result_id: str = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Query logs for a specific run with optional filters."""
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        logs_table = f"jita_{safe_id}_logs"
        
        conditions = []
        if severity:
            conditions.append(f"severity = '{severity}'")
        if event_type:
            conditions.append(f"event_type = '{event_type}'")
        if test_result_id:
            conditions.append(f"test_result_id = '{test_result_id}'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        sql = f"""
            SELECT * FROM {logs_table}
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        
        result = execute_sql(sql)
        return result
    
    def get_timeline(self, run_id: str, test_result_id: str = None) -> Dict[str, Any]:
        """Get timeline data for a run or specific test (optimized)."""
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        timeline_table = f"jita_{safe_id}_timeline"
        logs_table = f"jita_{safe_id}_logs"
        
        # Build timeline query
        if test_result_id:
            timeline_sql = f"""
                SELECT * FROM {timeline_table}
                WHERE test_result_id = '{test_result_id}'
                ORDER BY phase_order
            """
            where_clause = f"test_result_id = '{test_result_id}'"
        else:
            timeline_sql = f"SELECT * FROM {timeline_table} ORDER BY test_result_id, phase_order"
            where_clause = "1=1"
        
        timeline_result = execute_sql(timeline_sql)
        phases = timeline_result.get("rows", [])
        
        # Get aggregated counts per phase using SQL (much faster)
        counts_sql = f"""
            SELECT 
                phase,
                SUM(CASE WHEN severity IN ('ERROR', 'FATAL') THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN severity = 'WARN' THEN 1 ELSE 0 END) as warn_count,
                COUNT(*) as total_count
            FROM {logs_table}
            WHERE {where_clause}
            GROUP BY phase
        """
        counts_result = execute_sql(counts_sql)
        counts_by_phase = {r.get('phase', ''): r for r in counts_result.get("rows", [])}
        
        # Only fetch ERROR/FATAL/WARN logs for display (limit per phase)
        logs_sql = f"""
            SELECT * FROM {logs_table}
            WHERE {where_clause}
              AND severity IN ('ERROR', 'FATAL', 'WARN')
            ORDER BY 
                CASE severity WHEN 'FATAL' THEN 1 WHEN 'ERROR' THEN 2 ELSE 3 END,
                timestamp DESC
            LIMIT 200
        """
        logs_result = execute_sql(logs_sql)
        logs = logs_result.get("rows", [])
        
        # Enrich phases with counts and limited logs
        total_logs = 0
        for phase in phases:
            phase_name = phase.get('phase_name', '')
            counts = counts_by_phase.get(phase_name, {})
            phase['error_count'] = counts.get('error_count', 0)
            phase['warn_count'] = counts.get('warn_count', 0)
            total_logs += counts.get('total_count', 0)
            # Only include top 20 logs per phase
            phase['logs'] = [l for l in logs if l.get('phase') == phase_name][:20]
        
        return {
            "run_id": run_id,
            "test_result_id": test_result_id,
            "phases": phases,
            "total_logs": total_logs
        }
    
    def get_paginated_logs(
        self, 
        run_id: str, 
        test_result_id: str = None,
        phase: str = None,
        severity: str = None,
        operation: str = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get paginated logs with filters for infinite scroll."""
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        logs_table = f"jita_{safe_id}_logs"
        
        # Build WHERE clause
        conditions = []
        if test_result_id:
            conditions.append(f"test_result_id = '{test_result_id}'")
        if phase:
            conditions.append(f"phase = '{phase}'")
        if severity:
            if severity.upper() == 'ERROR':
                conditions.append("severity IN ('ERROR', 'FATAL')")
            else:
                conditions.append(f"severity = '{severity.upper()}'")
        if operation:
            conditions.append(f"log_source LIKE 'op:{operation}%'")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Get total count
        count_sql = f"SELECT COUNT(*) as cnt FROM {logs_table} WHERE {where_clause}"
        count_result = execute_sql(count_sql)
        rows = count_result.get("rows", [])
        total = rows[0].get("cnt", 0) if rows and len(rows) > 0 else 0
        
        # Get paginated logs
        logs_sql = f"""
            SELECT * FROM {logs_table}
            WHERE {where_clause}
            ORDER BY 
                CASE severity WHEN 'FATAL' THEN 1 WHEN 'ERROR' THEN 2 WHEN 'WARN' THEN 3 ELSE 4 END,
                timestamp DESC
            LIMIT {limit} OFFSET {offset}
        """
        logs_result = execute_sql(logs_sql)
        logs = logs_result.get("rows", [])
        
        return {
            "run_id": run_id,
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(logs) < total
        }
    
    def get_operations_timeline(self, run_id: str, test_result_id: str = None) -> Dict[str, Any]:
        """Get operations timeline with errors grouped by operation in execution order (optimized)."""
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        logs_table = f"jita_{safe_id}_logs"
        
        # First get aggregated counts per operation (fast)
        if test_result_id:
            where_clause = f"test_result_id = '{test_result_id}'"
        else:
            where_clause = "1=1"
        
        counts_sql = f"""
            SELECT 
                REPLACE(REPLACE(log_source, 'op:', ''), '/failed_tasks', '') as op_name,
                SUM(CASE WHEN severity = 'FATAL' THEN 1 ELSE 0 END) as fatal_count,
                SUM(CASE WHEN severity = 'ERROR' THEN 1 ELSE 0 END) as error_count,
                SUM(CASE WHEN severity = 'WARN' THEN 1 ELSE 0 END) as warn_count,
                MAX(CASE WHEN event_type = 'TASK_FAILED' THEN 1 ELSE 0 END) as has_task_failure
            FROM {logs_table}
            WHERE {where_clause}
              AND log_source LIKE 'op:%'
            GROUP BY REPLACE(REPLACE(log_source, 'op:', ''), '/failed_tasks', '')
        """
        counts_result = execute_sql(counts_sql)
        op_counts = {r.get('op_name', ''): r for r in counts_result.get("rows", [])}
        
        # Only fetch actual error/fatal/warn logs for operations with issues (limited)
        logs_sql = f"""
            SELECT log_source, severity, event_type, message, timestamp, priority, stack_trace, line_number
            FROM {logs_table}
            WHERE {where_clause}
              AND log_source LIKE 'op:%'
              AND severity IN ('ERROR', 'FATAL', 'WARN')
            ORDER BY 
                CASE severity WHEN 'FATAL' THEN 1 WHEN 'ERROR' THEN 2 ELSE 3 END,
                timestamp DESC
            LIMIT 500
        """
        result = execute_sql(logs_sql)
        logs = result.get("rows", [])
        
        # Build operations from aggregated counts first
        operations = {}
        for op_name, counts in op_counts.items():
            if not op_name:
                continue
            operations[op_name] = {
                'name': op_name,
                'display_name': self._format_op_name(op_name),
                'errors': [],
                'warnings': [],
                'fatal': [],
                'error_count': counts.get('error_count', 0),
                'warn_count': counts.get('warn_count', 0),
                'fatal_count': counts.get('fatal_count', 0),
                'has_task_failure': bool(counts.get('has_task_failure', 0))
            }
        
        # Add log entries to operations (already limited by SQL)
        for log in logs:
            source = log.get('log_source', '')
            op_name = source.replace('op:', '').replace('/failed_tasks', '')
            
            if op_name not in operations:
                continue
            
            op = operations[op_name]
            severity = log.get('severity', '')
            
            log_entry = {
                'message': log.get('message', '')[:500],
                'timestamp': log.get('timestamp', 0),
                'event_type': log.get('event_type', ''),
                'priority': log.get('priority', 'P3'),
                'log_source': source,
                'stack_trace': log.get('stack_trace', ''),
                'line_number': log.get('line_number', 0)
            }
            
            # Limit entries per category
            if severity == 'FATAL' and len(op['fatal']) < 10:
                op['fatal'].append(log_entry)
            elif severity == 'ERROR' and len(op['errors']) < 20:
                op['errors'].append(log_entry)
            elif severity == 'WARN' and len(op['warnings']) < 10:
                op['warnings'].append(log_entry)
        
        # Sort operations by numeric prefix (execution order)
        def sort_key(op_name):
            # Extract numeric prefix for sorting (e.g., "3.2.1" from "3.2.1_OpGroup")
            parts = op_name.split('_')[0].split('.')
            try:
                return tuple(int(p) for p in parts)
            except:
                return (9999,)
        
        sorted_ops = sorted(operations.values(), key=lambda x: sort_key(x['name']))
        
        # Add execution order
        for i, op in enumerate(sorted_ops):
            op['order'] = i + 1
            # Limit logs per operation to avoid huge responses
            op['errors'] = op['errors'][:20]
            op['warnings'] = op['warnings'][:10]
            op['fatal'] = op['fatal'][:10]
        
        # Compute summary stats
        total_errors = sum(op['error_count'] for op in sorted_ops)
        total_warnings = sum(op['warn_count'] for op in sorted_ops)
        failed_ops = [op for op in sorted_ops if op['has_task_failure'] or op['fatal_count'] > 0]
        
        return {
            "run_id": run_id,
            "test_result_id": test_result_id,
            "operations": sorted_ops,
            "operation_count": len(sorted_ops),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "failed_operations": len(failed_ops),
            "failed_op_names": [op['name'] for op in failed_ops]
        }
    
    def _format_op_name(self, op_name: str) -> str:
        """Format operation name for display."""
        # Remove numeric prefix
        parts = op_name.split('_', 1)
        if len(parts) > 1:
            name = parts[1]
        else:
            name = op_name
        
        # Add spaces before capitals and clean up
        import re
        name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
        name = name.replace('Op', ' Op').replace('Group', ' Group').strip()
        
        # Capitalize first letter
        return name if name else op_name
    
    def list_analyzed_runs(self) -> List[str]:
        """List all analyzed JITA runs (by finding jita_*_summary tables)."""
        result = execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'jita_%_summary'"
        )
        
        if result.get("status") == "error":
            return []
        
        runs = []
        for row in result.get("rows", []):
            table_name = row.get("name", "") if isinstance(row, dict) else row[0]
            # Extract run_id from table name: jita_{run_id}_summary
            match = re.match(r'jita_([a-zA-Z0-9]+)_summary', table_name)
            if match:
                runs.append(match.group(1))
        
        return runs
    
    def _extract_test_result_ids(self, task: Dict) -> List[str]:
        """Extract test result IDs from task data."""
        result_ids = []
        test_results = task.get('AgaveTestResults', [])
        
        for tr in test_results:
            if isinstance(tr, dict):
                oid = tr.get('$oid')
                if oid:
                    result_ids.append(oid)
            elif isinstance(tr, str):
                result_ids.append(tr)
        
        return result_ids
    
    def _extract_test_summary(self, result_id: str, result: Dict) -> Dict:
        """Extract summary info from a test result."""
        test_info = result.get('test', {})
        custom_data = result.get('custom_data', {})
        
        # Calculate duration
        start_time = result.get('start_time', {}).get('$date', 0)
        end_time = result.get('end_time', {}).get('$date', 0)
        duration = (end_time - start_time) // 1000 if start_time and end_time else 0
        
        # Get cluster info
        resources = result.get('allocated_resources', [])
        cluster_info = ", ".join([
            f"{r.get('type', '')}: {r.get('resource_name', '')}"
            for r in resources
        ])
        
        # Build direct log URL
        log_url = self._build_direct_log_url(result_id, result) or ''
        
        return {
            'test_result_id': result_id,
            'test_name': test_info.get('name', 'Unknown'),
            'status': result.get('status', 'Unknown'),
            'total_ops': custom_data.get('total_operations', 0),
            'successful_ops': custom_data.get('successful_operations', 0),
            'exception_summary': result.get('exception_summary', ''),
            'exception_full': result.get('exception', '')[:2000] if result.get('exception') else '',
            'duration_seconds': duration,
            'cluster_info': cluster_info,
            'cmd_executed': result.get('cmd_executed', ''),
            'log_url': log_url
        }
    
    def _extract_timeline_phases(self, result_id: str, result: Dict) -> List[Dict]:
        """Extract detailed timeline phases from test result and nutest logs."""
        phases = []
        test_info = result.get('test', {})
        test_name = test_info.get('name', 'Unknown')
        time_breakup = result.get('time_breakup', {})
        
        # Get log URLs
        plugin_logs = result.get('plugin_log_url', {})
        test_log_url = result.get('test_log_url', '')
        scheduler_log_url = result.get('scheduler_logs', '')
        
        # Overall test status
        overall_status = result.get('status', 'Unknown')
        error_stage = result.get('error_stage', '')
        
        # Try to fetch detailed timeline from nutest log
        nutest_timeline = self._fetch_nutest_timeline(result_id, result)
        
        if nutest_timeline:
            # Use detailed timeline from nutest
            phases = self._build_detailed_timeline(
                result_id, test_name, nutest_timeline, 
                overall_status, error_stage, test_log_url
            )
        else:
            # Fallback to time_breakup from JITA API
            phase_config = [
                ('test_scheduling', 'Scheduling', 1, scheduler_log_url),
                ('pre_run_plugin', 'Pre-Run Plugin', 2, plugin_logs.get('pre_run', '')),
                ('test_execution', 'Test Execution', 3, test_log_url),
                ('post_run_plugin', 'Post-Run Plugin', 4, plugin_logs.get('post_run', '')),
            ]
            
            for phase_key, phase_name, order, log_url in phase_config:
                phase_data = time_breakup.get(phase_key, {})
                if not phase_data:
                    continue
                
                start_ms = phase_data.get('start_time', {}).get('$date', 0)
                end_ms = phase_data.get('end_time', {}).get('$date', 0)
                
                status = overall_status if phase_key == 'test_execution' else 'Completed'
                
                phases.append({
                    'test_result_id': result_id,
                    'test_name': test_name,
                    'phase_name': phase_name,
                    'phase_order': order,
                    'start_time': start_ms // 1000 if start_ms else 0,
                    'end_time': end_ms // 1000 if end_ms else 0,
                    'duration_seconds': (end_ms - start_ms) // 1000 if start_ms and end_ms else 0,
                    'status': status,
                    'log_url': log_url
                })
        
        return phases
    
    def _fetch_nutest_timeline(self, result_id: str, result: Dict) -> Optional[Dict]:
        """Fetch detailed timeline from nutest test log."""
        try:
            test_log_url = result.get('test_log_url', '')
            if not test_log_url:
                return None
            
            # Resolve to direct URL
            direct_url = self._resolve_jita_log_url(test_log_url)
            if not direct_url:
                return None
            
            # Fetch first part of log to find timeline JSON
            response = requests.get(direct_url, timeout=30, stream=True)
            if response.status_code != 200:
                return None
            
            # Read first 50KB to find timeline
            content = ''
            for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
                    content += chunk
                    if len(content) > 50000:
                        break
            
            # Look for timeline JSON in the log
            import json
            timeline_match = re.search(r'"timeline":\s*(\{[^}]+(?:\{[^}]+\}[^}]*)*\})', content)
            if timeline_match:
                try:
                    timeline_str = timeline_match.group(1)
                    # Fix JSON (nutest uses single quotes sometimes)
                    timeline_str = timeline_str.replace("'", '"')
                    timeline = json.loads(timeline_str)
                    logger.info(f"Found nutest timeline with {len(timeline)} phases")
                    return timeline
                except:
                    pass
            
            return None
            
        except Exception as e:
            logger.warning(f"Error fetching nutest timeline: {e}")
            return None
    
    def _build_detailed_timeline(
        self, 
        result_id: str, 
        test_name: str, 
        timeline: Dict, 
        overall_status: str,
        error_stage: str,
        test_log_url: str
    ) -> List[Dict]:
        """Build detailed phases from nutest timeline."""
        phases = []
        order = 1
        
        # Define display names and order for nutest phases
        phase_display = {
            'class_resource_object_creation': 'Resource Creation',
            'class_prerun': 'Class Pre-Run',
            'class_setup': 'Class Setup',
            'test_resource_object_creation': 'Test Resource Creation',
            'setup': 'Test Setup',
            'test_body': 'Test Body',
            'teardown': 'Test Teardown',
            'test_post_run': 'Test Post-Run',
            'log_normalization': 'Log Normalization',
        }
        
        # Sub-phase display names
        sub_phase_display = {
            'update_start_time': 'Update Start Time',
            'check_esxi_license': 'Check ESXi License',
            'allow_unencrypted_login_for_hyperv': 'HyperV Login Config',
            'copy_yum_repos': 'Copy YUM Repos',
            'update_end_time': 'Update End Time',
            'log_analyser': 'Log Analysis',
            'log_collection': 'Log Collection',
            'scatter_logs': 'Scatter Logs',
        }
        
        def add_phase(name: str, data: Dict, parent: str = None):
            nonlocal order
            
            if not isinstance(data, dict):
                return
            
            start = data.get('start_time', 0)
            end = data.get('end_time', 0)
            duration = data.get('time_diff', 0)
            
            # Handle float timestamps (convert to int)
            if isinstance(start, float):
                start = int(start)
            if isinstance(end, float):
                end = int(end)
            if isinstance(duration, float):
                duration = int(duration)
            
            # Skip if no valid times
            if not start and not end:
                return
            
            # Determine display name
            display_name = phase_display.get(name) or sub_phase_display.get(name) or name.replace('_', ' ').title()
            if parent:
                display_name = f"  → {display_name}"  # Indent sub-phases
            
            # Determine status
            status = 'Completed'
            if error_stage and name.lower().replace('_', '') in error_stage.lower().replace('_', ''):
                status = 'Failed'
            elif name == 'test_body' and overall_status == 'Failed':
                status = 'Failed'
            
            phases.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'phase_name': display_name,
                'phase_order': order,
                'start_time': start,
                'end_time': end,
                'duration_seconds': duration,
                'status': status,
                'log_url': test_log_url if name == 'test_body' else ''
            })
            order += 1
        
        # Process phases in order
        phase_order = [
            'class_resource_object_creation',
            'class_prerun',
            'class_setup', 
            'test_resource_object_creation',
            'setup',
            'teardown',
            'test_post_run',
        ]
        
        for phase_key in phase_order:
            if phase_key in timeline:
                phase_data = timeline[phase_key]
                add_phase(phase_key, phase_data)
                
                # Check for sub-phases
                for sub_key, sub_data in phase_data.items():
                    if isinstance(sub_data, dict) and 'start_time' in sub_data:
                        add_phase(sub_key, sub_data, parent=phase_key)
        
        # Add test body phase (inferred from setup end to teardown start)
        if 'setup' in timeline and 'teardown' in timeline:
            setup_end = timeline['setup'].get('end_time', 0)
            teardown_start = timeline['teardown'].get('start_time', 0)
            if setup_end and teardown_start:
                phases.append({
                    'test_result_id': result_id,
                    'test_name': test_name,
                    'phase_name': 'Test Body (Execution)',
                    'phase_order': 5,  # After setup
                    'start_time': int(setup_end) if isinstance(setup_end, float) else setup_end,
                    'end_time': int(teardown_start) if isinstance(teardown_start, float) else teardown_start,
                    'duration_seconds': int(teardown_start - setup_end) if teardown_start > setup_end else 0,
                    'status': 'Failed' if overall_status == 'Failed' else 'Completed',
                    'log_url': test_log_url
                })
        
        # Sort by phase_order
        phases.sort(key=lambda p: p['phase_order'])
        
        # Re-number
        for i, p in enumerate(phases):
            p['phase_order'] = i + 1
        
        return phases
    
    def _insert_timeline(self, run_id: str, phases: List[Dict]):
        """Insert timeline phases into SQL."""
        if not phases:
            return
        
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        table = f"jita_{safe_id}_timeline"
        
        for phase in phases:
            def escape(val):
                if isinstance(val, str):
                    return val.replace("'", "''")
                return val or ''
            
            sql = f"""
                INSERT INTO {table} 
                (test_result_id, test_name, phase_name, phase_order, start_time, end_time, duration_seconds, status, log_url)
                VALUES (
                    '{phase['test_result_id']}',
                    '{escape(phase['test_name'])}',
                    '{escape(phase['phase_name'])}',
                    {phase['phase_order']},
                    {phase['start_time']},
                    {phase['end_time']},
                    {phase['duration_seconds']},
                    '{escape(phase['status'])}',
                    '{escape(phase['log_url'])}'
                )
            """
            execute_sql(sql)
    
    def _extract_events_from_result(self, result_id: str, result: Dict) -> List[Dict]:
        """Extract log events from test result metadata (exception, stack trace)."""
        events = []
        test_info = result.get('test', {})
        test_name = test_info.get('name', 'Unknown')
        
        # Extract from exception
        exception = result.get('exception', '')
        exception_summary = result.get('exception_summary', '')
        
        if exception:
            # Parse the exception to extract error type
            event_type = self._classify_exception(exception_summary or exception)
            message = exception_summary[:500] if exception_summary else exception[:500]
            
            # Main test exception is always P0
            priority = 'P0'
            
            end_time = result.get('end_time', {}).get('$date', 0)
            timestamp = end_time // 1000 if end_time else int(datetime.now().timestamp())
            
            events.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'log_source': 'exception',
                'timestamp': timestamp,
                'severity': 'ERROR',
                'event_type': event_type,
                'message': message,
                'stack_trace': exception[:2000],
                'line_number': 0,
                'priority': priority
            })
        
        # Check failure_analysis
        failure = result.get('failure_analysis', {})
        if failure.get('message'):
            message = failure.get('message', '')[:500]
            event_type = failure.get('category', 'UNKNOWN')
            priority = self._classify_priority('ERROR', event_type, message)
            
            events.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'log_source': 'failure_analysis',
                'timestamp': int(datetime.now().timestamp()),
                'severity': 'ERROR',
                'event_type': event_type,
                'message': message,
                'stack_trace': None,
                'line_number': 0,
                'priority': priority
            })
        
        return events
    
    def _fetch_and_parse_logs(self, result_id: str, result: Dict, timeline_phases: List[Dict] = None) -> List[Dict]:
        """Fetch logs from direct log server and parse for errors."""
        events = []
        test_info = result.get('test', {})
        test_name = test_info.get('name', 'Unknown')
        
        # Build direct log URL by resolving JITA redirect
        log_base_url = self._build_direct_log_url(result_id, result)
        
        if log_base_url:
            # Fetch and parse logs from direct server
            direct_events = self._fetch_logs_from_server(
                log_base_url, result_id, test_name
            )
            # Correlate with timeline phases
            if timeline_phases:
                direct_events = self._correlate_events_with_phases(direct_events, timeline_phases)
            events.extend(direct_events)
        
        # Also fetch scheduler logs if available
        scheduler_log_url = result.get('scheduler_logs')
        if scheduler_log_url:
            direct_scheduler_url = self._resolve_jita_log_url(scheduler_log_url)
            if direct_scheduler_url:
                content = self._fetch_log_file(direct_scheduler_url)
                if content:
                    parsed_events = self._parse_log_content(
                        content, 'scheduler', result_id, test_name
                    )
                    # Tag as Scheduling phase
                    for e in parsed_events:
                        e['phase'] = 'Scheduling'
                    events.extend(parsed_events)
                    logger.info(f"Parsed {len(parsed_events)} events from scheduler log")
        
        # Also fetch driver log if available
        driver_log_url = result.get('tester_log_url')
        if driver_log_url:
            direct_driver_url = self._resolve_jita_log_url(driver_log_url)
            if direct_driver_url:
                content = self._fetch_log_file(direct_driver_url)
                if content:
                    parsed_events = self._parse_log_content(
                        content, 'driver', result_id, test_name
                    )
                    # Tag as Test Execution phase
                    for e in parsed_events:
                        e['phase'] = 'Test Execution'
                    events.extend(parsed_events)
                    logger.info(f"Parsed {len(parsed_events)} events from driver log")
        
        # Fetch plugin logs
        plugin_logs = result.get('plugin_log_url', {})
        for plugin_type, plugin_url in plugin_logs.items():
            if plugin_url:
                direct_plugin_url = self._resolve_jita_log_url(plugin_url)
                if direct_plugin_url:
                    content = self._fetch_log_file(direct_plugin_url)
                    if content:
                        phase_name = 'Pre-Run Plugin' if 'pre' in plugin_type else 'Post-Run Plugin'
                        parsed_events = self._parse_log_content(
                            content, f'plugin_{plugin_type}', result_id, test_name
                        )
                        for e in parsed_events:
                            e['phase'] = phase_name
                        events.extend(parsed_events)
                        logger.info(f"Parsed {len(parsed_events)} events from {plugin_type} plugin log")
        
        return events
    
    def _correlate_events_with_phases(self, events: List[Dict], phases: List[Dict]) -> List[Dict]:
        """Correlate log events with timeline phases based on timestamp."""
        for event in events:
            event_ts = event.get('timestamp', 0)
            event['phase'] = 'Unknown'
            
            for phase in sorted(phases, key=lambda p: p['phase_order']):
                if phase['start_time'] <= event_ts <= phase['end_time']:
                    event['phase'] = phase['phase_name']
                    break
            
            # Default to Test Execution if no match
            if event['phase'] == 'Unknown':
                event['phase'] = 'Test Execution'
        
        return events
    
    def _build_direct_log_url(self, result_id: str, result: Dict) -> Optional[str]:
        """
        Build direct log server URL by resolving JITA API redirect.
        
        The JITA API's /log endpoint returns a 302 redirect to the actual log server.
        We capture that redirect to get the real log server URL dynamically.
        """
        try:
            # Get test_log_url from result
            test_log_url = result.get('test_log_url', '')
            
            if not test_log_url:
                logger.warning(f"No test_log_url for result {result_id}")
                return None
            
            # Resolve the JITA API URL to get actual log server URL
            direct_url = self._resolve_jita_log_url(test_log_url)
            
            if direct_url:
                # Ensure trailing slash for directory URLs
                if not direct_url.endswith('/') and not direct_url.endswith('.log'):
                    direct_url += '/'
                logger.info(f"Resolved log URL: {direct_url}")
                return direct_url
            
            return None
            
        except Exception as e:
            logger.warning(f"Error building direct log URL: {e}")
            return None
    
    def _resolve_jita_log_url(self, jita_url: str) -> Optional[str]:
        """
        Resolve JITA API log URL to get the actual log server URL.
        
        JITA's /api/v2/log endpoint returns a 302 redirect with the actual
        log server URL in the Location header. This dynamically determines
        the correct log server based on lab/infra configuration.
        
        Input: https://jita.eng.nutanix.com/api/v2/log?log_type=test_log&url=/logs/...&lab=phx1&infra=systest
        Output: http://10.46.1.200/logs/.../
        """
        # Check cache first
        if jita_url in self._log_url_cache:
            return self._log_url_cache[jita_url]
        
        try:
            # Make a HEAD request without following redirects
            response = self.session.head(
                jita_url, 
                allow_redirects=False, 
                timeout=10
            )
            
            # Check for redirect (302)
            if response.status_code in [301, 302, 303, 307, 308]:
                location = response.headers.get('Location', '')
                if location:
                    # Cache the resolved URL
                    self._log_url_cache[jita_url] = location
                    logger.info(f"JITA redirect resolved: {jita_url[:80]}... -> {location}")
                    return location
            
            # If no redirect, maybe JITA returns the content directly
            # In that case, parse the URL parameters to build direct URL
            logger.warning(f"No redirect from JITA log endpoint (status: {response.status_code})")
            return self._parse_jita_log_url_fallback(jita_url)
            
        except Exception as e:
            logger.warning(f"Error resolving JITA log URL: {e}")
            # Try fallback parsing
            return self._parse_jita_log_url_fallback(jita_url)
    
    def _parse_jita_log_url_fallback(self, jita_url: str) -> Optional[str]:
        """
        Fallback: Parse JITA API log URL when redirect doesn't work.
        
        Extracts the URL path and tries common log server patterns.
        """
        try:
            from urllib.parse import urlparse, parse_qs
            
            parsed = urlparse(jita_url)
            params = parse_qs(parsed.query)
            
            # Extract path from 'url' parameter
            log_path = params.get('url', [''])[0]
            if not log_path:
                return None
            
            # We don't know the exact server, but most are accessible via common IPs
            # This is a last resort fallback
            common_servers = [
                'http://10.46.1.200',  # PHX1 systest
                'http://10.47.1.200',  # PHX2 systest
            ]
            
            # Try the first server (most common)
            full_url = f"{common_servers[0]}{log_path}"
            logger.warning(f"Using fallback log server: {full_url}")
            return full_url
            
        except Exception as e:
            logger.warning(f"Error in fallback URL parsing: {e}")
            return None
    
    def _fetch_logs_from_server(
        self, 
        base_url: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Fetch and parse logs from direct log server."""
        events = []
        
        try:
            # Get directory listing
            response = requests.get(base_url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch log directory: {response.status_code}")
                return events
            
            # Parse directory listing for log files
            log_files = self._parse_directory_listing(response.text)
            logger.info(f"Found {len(log_files)} files in root log directory")
            
            # Fetch key log files at root level (nutest.log, etc.)
            for log_file in log_files:
                if log_file in ['nutest.log', 'nutest_webserver.log']:
                    log_url = f"{base_url}{log_file}"
                    content = self._fetch_log_file(log_url)
                    if content:
                        parsed_events = self._parse_log_content(
                            content, log_file.replace('.log', ''), result_id, test_name
                        )
                        events.extend(parsed_events)
                        logger.info(f"Parsed {len(parsed_events)} events from root {log_file}")
            
            # Find the test directory path (contains nutest_test.log)
            test_dir_path = None
            for f in log_files:
                if 'nutest_test.log' in f:
                    # Extract directory path from the file path
                    test_dir_path = '/'.join(f.split('/')[:-1]) + '/'
                    break
            
            if test_dir_path:
                test_dir_url = f"{base_url}{test_dir_path}"
                logger.info(f"Found test directory: {test_dir_path}")
                
                # Fetch test directory contents
                test_events = self._parse_test_directory(
                    test_dir_url, result_id, test_name
                )
                events.extend(test_events)
            
        except Exception as e:
            logger.error(f"Error fetching logs from server: {e}")
        
        return events
    
    def _parse_test_directory(
        self, 
        test_dir_url: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Parse logs from the test directory (contains nutest_test.log, logs/, etc.)."""
        events = []
        
        try:
            response = requests.get(test_dir_url, timeout=30)
            if response.status_code != 200:
                return events
            
            files = self._parse_directory_listing(response.text)
            logger.info(f"Found {len(files)} files in test directory")
            
            # Fetch key log files
            for log_file in files:
                is_key_log = log_file in self.KEY_LOG_FILES
                is_failure_log = any(
                    re.match(pattern, log_file) 
                    for pattern in self.FAILURE_LOG_PATTERNS
                )
                
                if is_key_log or is_failure_log:
                    log_url = f"{test_dir_url}{log_file}"
                    source = log_file.replace('.log', '')
                    
                    content = self._fetch_log_file(log_url)
                    if content:
                        parsed_events = self._parse_log_content(
                            content, source, result_id, test_name
                        )
                        events.extend(parsed_events)
                        logger.info(f"Parsed {len(parsed_events)} events from {log_file}")
            
            # Parse operation-specific logs in logs/ directory
            if 'logs/' in files:
                op_events = self._parse_operation_logs(
                    f"{test_dir_url}logs/", result_id, test_name
                )
                events.extend(op_events)
                logger.info(f"Parsed {len(op_events)} events from operation logs")
            
            # Also check for logbay directories
            logbay_dirs = [f for f in files if f.startswith('logbay_') and f.endswith('/')]
            for logbay_dir in logbay_dirs[:2]:  # Limit to 2 logbay dirs
                logbay_events = self._parse_logbay_directory(
                    f"{test_dir_url}{logbay_dir}", result_id, test_name
                )
                events.extend(logbay_events)
            
        except Exception as e:
            logger.warning(f"Error parsing test directory: {e}")
        
        return events
    
    def _parse_operation_logs(
        self, 
        logs_url: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Parse operation-specific logs in the logs/ directory."""
        events = []
        
        try:
            # Get listing of operation directories
            response = requests.get(logs_url, timeout=30)
            if response.status_code != 200:
                return events
            
            op_dirs = self._parse_directory_listing(response.text)
            # Filter to only directories (end with /)
            op_dirs = [d for d in op_dirs if d.endswith('/')]
            
            logger.info(f"Found {len(op_dirs)} operation directories")
            
            # Parse each operation's log file
            for op_dir in op_dirs:
                op_name = op_dir.rstrip('/')
                # The log file is usually named same as the directory
                log_file_name = f"{op_name}.log"
                log_url = f"{logs_url}{op_dir}{log_file_name}"
                
                content = self._fetch_log_file(log_url, max_size=5 * 1024 * 1024)  # 5MB limit per op
                if content:
                    parsed_events = self._parse_log_content(
                        content, f"op:{op_name}", result_id, test_name
                    )
                    events.extend(parsed_events)
                    if parsed_events:
                        logger.debug(f"Parsed {len(parsed_events)} events from {op_name}")
                
                # Also check for failed_tasks.json for more context
                failed_tasks_url = f"{logs_url}{op_dir}failed_tasks.json"
                try:
                    ft_response = requests.get(failed_tasks_url, timeout=10)
                    if ft_response.status_code == 200:
                        failed_tasks = ft_response.json()
                        if failed_tasks:
                            task_events = self._parse_failed_tasks(
                                failed_tasks, op_name, result_id, test_name
                            )
                            events.extend(task_events)
                except:
                    pass  # failed_tasks.json may not exist
            
        except Exception as e:
            logger.warning(f"Error parsing operation logs: {e}")
        
        return events
    
    def _parse_failed_tasks(
        self, 
        failed_tasks: Any, 
        op_name: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Parse failed_tasks.json for task failure details."""
        events = []
        
        try:
            tasks = failed_tasks if isinstance(failed_tasks, list) else [failed_tasks]
            
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                
                error_detail = task.get('error_detail', '')
                error_code = task.get('error_code', '')
                status = task.get('status', '')
                operation_type = task.get('operation_type', '')
                
                if status == 'FAILED' or error_detail:
                    message = error_detail or f"Task failed with code {error_code}"
                    
                    events.append({
                        'test_result_id': result_id,
                        'test_name': test_name,
                        'log_source': f"op:{op_name}/failed_tasks",
                        'timestamp': int(datetime.now().timestamp()),
                        'severity': 'ERROR',
                        'event_type': 'TASK_FAILED',
                        'message': f"[{operation_type}] {message}"[:500],
                        'stack_trace': None,
                        'line_number': 0,
                        'priority': 'P1'  # Task failures are important
                    })
        except Exception as e:
            logger.warning(f"Error parsing failed_tasks: {e}")
        
        return events
    
    def _parse_directory_listing(self, html: str) -> List[str]:
        """Parse Apache directory listing HTML to extract file names."""
        files = []
        # Match href="filename" in directory listing
        pattern = r'href="([^"?]+)"'
        matches = re.findall(pattern, html)
        
        for match in matches:
            # Skip parent directory and icon links
            if match.startswith('/') or match.startswith('?'):
                continue
            files.append(match)
        
        return files
    
    def _fetch_log_file(self, url: str, max_size: int = 10 * 1024 * 1024) -> str:
        """Fetch a log file with size limit."""
        try:
            # Stream to check size first
            response = requests.get(url, timeout=60, stream=True)
            if response.status_code != 200:
                return ""
            
            # Check content length
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > max_size:
                logger.warning(f"Log file too large ({content_length} bytes), fetching partial")
                # Fetch only the last portion for large files
                return self._fetch_log_tail(url, max_size // 2)
            
            return response.text
            
        except Exception as e:
            logger.warning(f"Error fetching log file {url}: {e}")
            return ""
    
    def _fetch_log_tail(self, url: str, size: int) -> str:
        """Fetch the tail of a large log file."""
        try:
            # Use Range header to get last N bytes
            headers = {'Range': f'bytes=-{size}'}
            response = requests.get(url, headers=headers, timeout=60)
            return response.text
        except:
            return ""
    
    def _parse_logbay_directory(
        self, 
        logbay_url: str, 
        result_id: str, 
        test_name: str,
        depth: int = 0
    ) -> List[Dict]:
        """Parse logbay directory for error logs (recursively)."""
        events = []
        
        # Limit recursion depth to avoid infinite loops
        if depth > 4:
            return events
        
        try:
            # Get logbay directory listing
            response = requests.get(logbay_url, timeout=30)
            if response.status_code != 200:
                return events
            
            files = self._parse_directory_listing(response.text)
            
            # Error file patterns to look for
            error_file_patterns = [
                '.FATAL',      # Service FATAL files (e.g., aplos.FATAL)
                '.ERROR',      # Service ERROR files
                'ERROR.',      # .log.ERROR files
                'FATAL.',      # .log.FATAL files
                'crash',       # Crash dumps
                'core.',       # Core dumps
                'panic',       # Panic logs
            ]
            
            # Key directories to search in logbay
            key_dirs = ['cvm_logs/', 'flowgateway_logs/', 'karbon/', 'msp/']
            
            for f in files:
                full_url = f"{logbay_url}{f}"
                
                # Check if it's a directory we should recurse into
                if f.endswith('/'):
                    # At depth 0, go into node directories (nutest_* directories)
                    if depth == 0 and f.startswith('nutest_'):
                        sub_events = self._parse_logbay_directory(
                            full_url, result_id, test_name, depth + 1
                        )
                        events.extend(sub_events)
                    # At depth 1, go into cvm_logs and other key directories
                    elif depth == 1 and f in key_dirs:
                        sub_events = self._parse_logbay_directory(
                            full_url, result_id, test_name, depth + 1
                        )
                        events.extend(sub_events)
                    continue
                
                # Check if it's an error-related file
                is_error_file = any(p.lower() in f.lower() for p in error_file_patterns)
                
                # Also include files that end with specific extensions
                is_log_file = f.endswith('.log') or f.endswith('.txt') or '.FATAL' in f or '.ERROR' in f
                
                if is_error_file and is_log_file:
                    content = self._fetch_log_file(full_url, max_size=2*1024*1024)  # 2MB limit per file
                    if content:
                        # Extract service name from filename
                        service_name = f.split('.')[0] if '.' in f else f
                        parsed = self._parse_log_content(
                            content, f'logbay:{service_name}', result_id, test_name
                        )
                        events.extend(parsed)
                        if parsed:
                            logger.info(f"Parsed {len(parsed)} events from logbay {f}")
            
        except Exception as e:
            logger.warning(f"Error parsing logbay directory: {e}")
        
        return events
    
    def _parse_log_content(
        self, 
        content: str, 
        source: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """
        Parse log content using the smart parser for reduced false positives.
        
        Uses evidence-based error detection:
        - Requires actual severity field in log format
        - Requires stack trace or exception class for high confidence
        - Deduplicates similar errors
        """
        try:
            from .smart_log_parser import get_smart_log_parser
            parser = get_smart_log_parser()
            
            # Use smart parser with minimum confidence threshold
            smart_events = parser.parse_log_content(
                content=content,
                log_source=source,
                test_result_id=result_id,
                test_name=test_name,
                min_confidence=0.4  # Require at least 40% confidence
            )
            
            # Convert SmartLogEvent to dict format
            events = []
            for evt in smart_events:
                events.append({
                    'test_result_id': evt.test_result_id,
                    'test_name': evt.test_name,
                    'log_source': evt.log_source,
                    'timestamp': evt.timestamp,
                    'severity': evt.severity,
                    'event_type': evt.event_type,
                    'message': evt.message,
                    'stack_trace': evt.stack_trace,
                    'line_number': evt.line_number,
                    'priority': evt.priority
                })
            
            return events
            
        except Exception as e:
            logger.warning(f"Smart parser failed, falling back to basic: {e}")
            return self._parse_log_content_basic(content, source, result_id, test_name)
    
    def _parse_log_content_basic(
        self, 
        content: str, 
        source: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Basic fallback parser using regex patterns."""
        events = []
        lines = content.split('\n')
        total_lines = len(lines)
        seen_messages = set()
        
        # Only match actual ERROR/FATAL at start of log format
        log_format_pattern = re.compile(
            r'^(?:\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}[^\s]*\s+)?'
            r'(ERROR|FATAL|CRITICAL)\s+',
            re.IGNORECASE
        )
        
        for line_num, line in enumerate(lines):
            match = log_format_pattern.match(line)
            if not match:
                continue
            
            severity = match.group(1).upper()
            if severity == 'CRITICAL':
                severity = 'FATAL'
            
            # Dedup
            msg_key = line[:100]
            if msg_key in seen_messages:
                continue
            seen_messages.add(msg_key)
            
            timestamp = self._extract_timestamp(line)
            event_type = self._classify_log_line(line)
            
            # Get context
            context_start = max(0, line_num - 10)
            context_end = min(total_lines, line_num + 11)
            context_lines = []
            for i in range(context_start, context_end):
                prefix = ">>> " if i == line_num else "    "
                context_lines.append(f"{prefix}[{i+1}] {lines[i].rstrip()[:200]}")
            
            stack_trace = "--- Context (±10 lines) ---\n" + '\n'.join(context_lines) if context_lines else None
            
            events.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'log_source': source,
                'timestamp': timestamp,
                'severity': severity,
                'event_type': event_type,
                'message': line[:500],
                'stack_trace': stack_trace,
                'line_number': line_num + 1,
                'priority': self._classify_priority(severity, event_type, line)
            })
        
        return events
    
    def _classify_exception(self, exception_text: str) -> str:
        """Classify exception type from exception text."""
        patterns = {
            'ASSERTION_ERROR': [r'AssertionError', r'assert.*fail'],
            'TIMEOUT': [r'TimeoutError', r'timeout', r'timed\s+out'],
            'CONNECTION_ERROR': [r'ConnectionError', r'connection.*fail', r'refused'],
            'INFRA_ERROR': [r'InfraError', r'infra.*fail', r'resource.*fail'],
            'ATTRIBUTE_ERROR': [r'AttributeError'],
            'KEY_ERROR': [r'KeyError'],
            'VALUE_ERROR': [r'ValueError'],
            'TYPE_ERROR': [r'TypeError'],
            'IMPORT_ERROR': [r'ImportError', r'ModuleNotFoundError'],
            'IO_ERROR': [r'IOError', r'FileNotFoundError'],
            'RUNTIME_ERROR': [r'RuntimeError'],
        }
        
        for event_type, regexes in patterns.items():
            for pattern in regexes:
                if re.search(pattern, exception_text, re.IGNORECASE):
                    return event_type
        
        return 'UNKNOWN_ERROR'
    
    def _classify_log_line(self, line: str) -> Optional[str]:
        """Classify error type from log line."""
        patterns = {
            'CONNECTION_ERROR': [r'connection.*fail', r'refused', r'reset'],
            'TIMEOUT': [r'timeout', r'timed\s+out', r'deadline'],
            'AUTH_FAIL': [r'auth.*fail', r'unauthorized', r'forbidden'],
            'NOT_FOUND': [r'not\s+found', r'does\s+not\s+exist', r'missing'],
            'PERMISSION_ERROR': [r'permission\s+denied', r'access\s+denied'],
            'CONFIG_ERROR': [r'config.*error', r'invalid.*config'],
            'RESOURCE_ERROR': [r'resource.*fail', r'allocation.*fail'],
            'VALIDATION_ERROR': [r'validation.*fail', r'invalid.*param'],
        }
        
        line_lower = line.lower()
        for event_type, regexes in patterns.items():
            for pattern in regexes:
                if re.search(pattern, line_lower):
                    return event_type
        
        return None
    
    def _classify_priority(self, severity: str, event_type: str, message: str) -> str:
        """
        Classify error priority based on severity, event type, and message.
        
        Priority Levels:
        - P0 (Critical): Test failures, fatal errors, assertion failures, infrastructure down
        - P1 (High): Timeouts, connection errors, authentication failures
        - P2 (Medium): Validation errors, resource issues, config errors
        - P3 (Low): Warnings, minor issues, cleanup failures
        """
        severity = (severity or '').upper()
        event_type = (event_type or '').upper()
        message_lower = (message or '').lower()
        
        # P0 - Critical: Test blocking issues
        p0_event_types = ['ASSERTION_ERROR', 'INFRA_ERROR', 'CLUSTER_ERROR', 'FATAL']
        p0_keywords = [
            r'test.*failed', r'assertion.*error', r'fatal', r'critical',
            r'panic', r'crash', r'cluster.*down', r'cvm.*down', r'node.*down',
            r'prism.*unreachable', r'infrastructure.*fail', r'deployment.*fail',
            r'imaging.*fail', r'test.*blocked', r'framework.*error'
        ]
        
        if severity == 'FATAL':
            return 'P0'
        if event_type in p0_event_types:
            return 'P0'
        for pattern in p0_keywords:
            if re.search(pattern, message_lower):
                return 'P0'
        
        # P1 - High: Significant errors that need attention
        p1_event_types = ['TIMEOUT', 'CONNECTION_ERROR', 'AUTH_FAIL', 'DATABASE_ERROR', 'HTTP_ERROR']
        p1_keywords = [
            r'timeout', r'timed\s*out', r'connection.*refuse', r'connection.*reset',
            r'authentication.*fail', r'unauthorized', r'forbidden', r'access.*denied',
            r'socket.*error', r'network.*unreachable', r'ssl.*error', r'certificate.*error',
            r'service.*unavailable', r'500\s+internal', r'502\s+bad\s+gateway'
        ]
        
        if event_type in p1_event_types:
            return 'P1'
        for pattern in p1_keywords:
            if re.search(pattern, message_lower):
                return 'P1'
        
        # P2 - Medium: Issues that should be investigated
        p2_event_types = ['VALIDATION_ERROR', 'RESOURCE_ERROR', 'CONFIG_ERROR', 'KEY_ERROR', 
                         'VALUE_ERROR', 'TYPE_ERROR', 'ATTRIBUTE_ERROR', 'IMPORT_ERROR']
        p2_keywords = [
            r'validation.*fail', r'invalid.*param', r'invalid.*value',
            r'resource.*not.*available', r'quota.*exceed', r'out\s+of\s+memory',
            r'disk.*full', r'config.*error', r'missing.*config', r'key.*error',
            r'attribute.*error', r'type.*error', r'import.*error', r'module.*not.*found',
            r'file.*not.*found', r'permission.*denied', r'not.*found', r'does.*not.*exist'
        ]
        
        if severity == 'ERROR' and event_type in p2_event_types:
            return 'P2'
        for pattern in p2_keywords:
            if re.search(pattern, message_lower):
                return 'P2'
        
        # P3 - Low: Warnings and minor issues
        p3_keywords = [
            r'warning', r'deprecat', r'retry', r'retrying', r'cleanup.*fail',
            r'teardown.*fail', r'skip', r'ignored', r'non.*critical'
        ]
        
        if severity == 'WARN':
            return 'P3'
        for pattern in p3_keywords:
            if re.search(pattern, message_lower):
                return 'P3'
        
        # Default based on severity
        if severity == 'ERROR':
            return 'P2'
        if severity == 'FATAL':
            return 'P0'
        
        return 'P3'
    
    def _extract_timestamp(self, line: str) -> int:
        """Extract timestamp from log line."""
        # Try various timestamp patterns
        patterns = [
            # ISO format: 2026-01-27T14:30:45
            r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})',
            # Standard format: 2026-01-27 14:30:45
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
            # Google glog: I20260127 14:30:45
            r'[IWEF](\d{8})\s+(\d{2}:\d{2}:\d{2})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                try:
                    if len(match.groups()) == 2:
                        # glog format
                        date_str = match.group(1)
                        time_str = match.group(2)
                        dt = datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H:%M:%S")
                    else:
                        ts_str = match.group(1).replace('T', ' ')
                        dt = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    return int(dt.timestamp())
                except:
                    pass
        
        return int(datetime.now().timestamp())
    
    def _is_stack_trace_line(self, line: str) -> bool:
        """Check if line is part of a stack trace."""
        stack_patterns = [
            r'^\s+at\s+',           # Java style
            r'^\s+File\s+"',        # Python style
            r'^\s+in\s+',           # Generic
            r'^Traceback',          # Python traceback header
            r'^\s+\d+:',            # Numbered stack frames
        ]
        
        for pattern in stack_patterns:
            if re.match(pattern, line):
                return True
        return False
    
    def _insert_summaries(self, run_id: str, summaries: List[Dict]):
        """Insert test summaries into SQL table."""
        if not summaries:
            return
        
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        table = f"jita_{safe_id}_summary"
        
        for summary in summaries:
            # Escape single quotes in strings
            def escape(val):
                if isinstance(val, str):
                    return val.replace("'", "''")
                return val
            
            sql = f"""
                INSERT OR REPLACE INTO {table} 
                (test_result_id, test_name, status, total_ops, successful_ops, 
                 exception_summary, exception_full, duration_seconds, cluster_info, cmd_executed, log_url)
                VALUES (
                    '{escape(summary["test_result_id"])}',
                    '{escape(summary["test_name"])}',
                    '{escape(summary["status"])}',
                    {summary["total_ops"]},
                    {summary["successful_ops"]},
                    '{escape(summary["exception_summary"])}',
                    '{escape(summary["exception_full"])}',
                    {summary["duration_seconds"]},
                    '{escape(summary["cluster_info"])}',
                    '{escape(summary["cmd_executed"])}',
                    '{escape(summary.get("log_url", ""))}'
                )
            """
            execute_sql(sql)
    
    def _insert_log_events(self, run_id: str, events: List[Dict]):
        """Insert log events into SQL table."""
        if not events:
            return
        
        safe_id = re.sub(r'[^a-zA-Z0-9]', '', run_id)
        table = f"jita_{safe_id}_logs"
        
        for event in events:
            def escape(val):
                if isinstance(val, str):
                    return val.replace("'", "''")
                return val if val is not None else ''
            
            sql = f"""
                INSERT INTO {table}
                (test_result_id, test_name, log_source, timestamp, severity, 
                 event_type, message, stack_trace, line_number, phase, priority)
                VALUES (
                    '{escape(event["test_result_id"])}',
                    '{escape(event["test_name"])}',
                    '{escape(event["log_source"])}',
                    {event["timestamp"]},
                    '{escape(event["severity"])}',
                    '{escape(event.get("event_type") or "")}',
                    '{escape(event["message"])}',
                    '{escape(event.get("stack_trace") or "")}',
                    {event.get("line_number", 0)},
                    '{escape(event.get("phase") or "Unknown")}',
                    '{escape(event.get("priority") or "P3")}'
                )
            """
            execute_sql(sql)
    
    def _build_analysis_response(
        self, 
        run_id: str, 
        task: Dict, 
        summaries: List[Dict],
        events: List[Dict]
    ) -> Dict[str, Any]:
        """Build the analysis response."""
        # Extract task info
        task_info = {
            'run_id': run_id,
            'label': task.get('label', ''),
            'service': task.get('service', ''),
            'created_by': task.get('created_by', ''),
            'status': task.get('status', ''),
        }
        
        # Test result counts
        result_counts = task.get('test_result_count', {})
        
        # Error summary
        error_counts = {}
        for event in events:
            sev = event.get('severity', 'UNKNOWN')
            error_counts[sev] = error_counts.get(sev, 0) + 1
        
        # Event type distribution
        event_types = {}
        for event in events:
            evt = event.get('event_type')
            if evt:
                event_types[evt] = event_types.get(evt, 0) + 1
        
        return {
            'task': task_info,
            'test_result_count': result_counts,
            'tests_analyzed': len(summaries),
            'log_events_found': len(events),
            'error_counts': error_counts,
            'event_types': event_types,
            'summaries': summaries
        }


# Singleton instance
_jita_service = None


def get_jita_service() -> JitaService:
    """Get or create the JITA service singleton."""
    global _jita_service
    if _jita_service is None:
        _jita_service = JitaService()
    return _jita_service
