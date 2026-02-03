"""
JITA Service for NOVA Backend

Integrates with JITA (Jita Is a Test Automation) to analyze test runs,
fetch logs, parse errors, and store results in SQL tables.
"""
import re
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from ..logging_config import get_logger
from ..tools.sql_tools import execute_sql

disable_warnings(InsecureRequestWarning)

logger = get_logger(__name__)


class JitaService:
    """
    Service for analyzing JITA test runs.
    
    Fetches task details, test results, and logs from JITA API,
    parses them for errors, and stores in run-specific SQL tables.
    """
    
    JITA_BASE_URL = "https://jita.eng.nutanix.com/api/v2"
    AUTH = ("agave_bot", "admin")
    
    # Log source types
    LOG_SOURCES = {
        'scheduler': 'scheduler_logs',
        'driver': 'tester_log_url',
        'test': 'test_log_url',
        'plugin_pre': 'plugin_log_url.pre_run',
        'plugin_post': 'plugin_log_url.post_run',
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.auth = self.AUTH
    
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
            
            # Extract log events from exception/stack trace
            events = self._extract_events_from_result(result_id, result)
            all_log_events.extend(events)
            
            # Fetch and parse logs
            log_events = self._fetch_and_parse_logs(result_id, result)
            all_log_events.extend(log_events)
        
        # 5. Insert data into SQL
        self._insert_summaries(run_id, test_summaries)
        self._insert_log_events(run_id, all_log_events)
        
        # 6. Return analysis summary
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
    
    def create_run_tables(self, run_id: str):
        """Create SQL tables for storing run analysis."""
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
            line_number INTEGER
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
            cmd_executed TEXT
        )
        """
        execute_sql(create_summary_sql)
        
        logger.info(f"Created tables: {logs_table}, {summary_table}")
    
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
            'cmd_executed': result.get('cmd_executed', '')
        }
    
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
            
            end_time = result.get('end_time', {}).get('$date', 0)
            timestamp = end_time // 1000 if end_time else int(datetime.now().timestamp())
            
            events.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'log_source': 'exception',
                'timestamp': timestamp,
                'severity': 'ERROR',
                'event_type': event_type,
                'message': exception_summary[:500] if exception_summary else exception[:500],
                'stack_trace': exception[:2000],
                'line_number': 0
            })
        
        # Check failure_analysis
        failure = result.get('failure_analysis', {})
        if failure.get('message'):
            events.append({
                'test_result_id': result_id,
                'test_name': test_name,
                'log_source': 'failure_analysis',
                'timestamp': int(datetime.now().timestamp()),
                'severity': 'ERROR',
                'event_type': failure.get('category', 'UNKNOWN'),
                'message': failure.get('message', '')[:500],
                'stack_trace': None,
                'line_number': 0
            })
        
        return events
    
    def _fetch_and_parse_logs(self, result_id: str, result: Dict) -> List[Dict]:
        """Fetch logs from JITA and parse for errors."""
        events = []
        test_info = result.get('test', {})
        test_name = test_info.get('name', 'Unknown')
        
        # Collect all log URLs
        log_urls = {
            'scheduler': result.get('scheduler_logs'),
            'driver': result.get('tester_log_url'),
            'test': result.get('test_log_url'),
        }
        
        # Plugin logs
        plugin_logs = result.get('plugin_log_url', {})
        if isinstance(plugin_logs, dict):
            log_urls['plugin_pre'] = plugin_logs.get('pre_run')
            log_urls['plugin_post'] = plugin_logs.get('post_run')
        
        # Fetch and parse each log
        for source, url in log_urls.items():
            if not url:
                continue
            
            content = self.fetch_log_content(url)
            if not content:
                continue
            
            # Parse log content for errors
            parsed_events = self._parse_log_content(
                content, source, result_id, test_name
            )
            events.extend(parsed_events)
        
        return events
    
    def _parse_log_content(
        self, 
        content: str, 
        source: str, 
        result_id: str, 
        test_name: str
    ) -> List[Dict]:
        """Parse log content and extract error events."""
        events = []
        lines = content.split('\n')
        
        # Patterns for severity detection
        severity_patterns = {
            'FATAL': [r'\bFATAL\b', r'\bCRITICAL\b', r'\bPANIC\b'],
            'ERROR': [r'\bERROR\b', r'\bERR\b', r'\bFAILED\b', r'\bFAILURE\b', r'\bException\b'],
            'WARN': [r'\bWARN\b', r'\bWARNING\b'],
        }
        
        current_event = None
        stack_lines = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Detect severity
            severity = None
            for sev, patterns in severity_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        severity = sev
                        break
                if severity:
                    break
            
            # Only capture ERROR and FATAL
            if severity in ['ERROR', 'FATAL']:
                # Save previous event
                if current_event:
                    if stack_lines:
                        current_event['stack_trace'] = '\n'.join(stack_lines)[:2000]
                    events.append(current_event)
                
                # Start new event
                timestamp = self._extract_timestamp(line)
                event_type = self._classify_log_line(line)
                
                current_event = {
                    'test_result_id': result_id,
                    'test_name': test_name,
                    'log_source': source,
                    'timestamp': timestamp,
                    'severity': severity,
                    'event_type': event_type,
                    'message': line[:500],
                    'stack_trace': None,
                    'line_number': line_num
                }
                stack_lines = []
            
            elif current_event and self._is_stack_trace_line(line):
                stack_lines.append(line)
        
        # Don't forget the last event
        if current_event:
            if stack_lines:
                current_event['stack_trace'] = '\n'.join(stack_lines)[:2000]
            events.append(current_event)
        
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
                 exception_summary, exception_full, duration_seconds, cluster_info, cmd_executed)
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
                    '{escape(summary["cmd_executed"])}'
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
                 event_type, message, stack_trace, line_number)
                VALUES (
                    '{escape(event["test_result_id"])}',
                    '{escape(event["test_name"])}',
                    '{escape(event["log_source"])}',
                    {event["timestamp"]},
                    '{escape(event["severity"])}',
                    '{escape(event.get("event_type") or "")}',
                    '{escape(event["message"])}',
                    '{escape(event.get("stack_trace") or "")}',
                    {event.get("line_number", 0)}
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
