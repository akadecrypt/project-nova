"""
JITA Log Parser for NOVA Backend

Specialized parser for nutest and JITA log formats.
Extends patterns from log_parser.py with JITA-specific patterns.
"""
import re
from typing import List, Dict, Optional, Iterator
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class JitaLogEvent:
    """Represents a parsed JITA/nutest log event."""
    test_result_id: str
    test_name: str
    log_source: str                     # scheduler, driver, test, plugin_pre, plugin_post
    timestamp: int                      # Unix epoch seconds
    severity: str                       # INFO, WARN, ERROR, FATAL
    event_type: Optional[str] = None    # Classified error type
    message: str = ""                   # Log message (truncated)
    stack_trace: Optional[str] = None   # Full stack trace
    line_number: int = 0


class JitaLogParser:
    """
    Parser for JITA/nutest log formats.
    
    Handles:
    - Nutest test output logs
    - Python stack traces/exceptions
    - Scheduler logs
    - Plugin logs
    """
    
    # Severity patterns
    SEVERITY_PATTERNS = {
        'FATAL': [
            r'\bFATAL\b', r'\bCRITICAL\b', r'\bPANIC\b',
            r'FAILED.*FATAL', r'Test\s+FAILED'
        ],
        'ERROR': [
            r'\bERROR\b', r'\bERR\b', r'\bFAILED\b', r'\bFAILURE\b',
            r'Exception\b', r'Error:', r'failed:', r'Traceback'
        ],
        'WARN': [
            r'\bWARN\b', r'\bWARNING\b'
        ],
        'INFO': [
            r'\bINFO\b', r'\bDEBUG\b'
        ],
    }
    
    # Exception type patterns (Python/nutest specific)
    EXCEPTION_PATTERNS = {
        'ASSERTION_ERROR': [
            r'AssertionError', r'assert\s+False', r'assert.*fail',
            r'Test\s+FAILED', r'Test\s+assertion\s+failed'
        ],
        'TIMEOUT_ERROR': [
            r'TimeoutError', r'TimeoutException', r'timeout\s+expired',
            r'timed\s+out', r'deadline\s+exceeded', r'operation.*timeout'
        ],
        'CONNECTION_ERROR': [
            r'ConnectionError', r'ConnectionRefusedError', r'ConnectionResetError',
            r'connection\s+refused', r'connection\s+reset', r'socket.*error',
            r'network.*unreachable', r'host.*unreachable'
        ],
        'INFRA_ERROR': [
            r'InfraError', r'INFRA_ERROR', r'infrastructure.*fail',
            r'resource.*allocation.*fail', r'cluster.*unavailable',
            r'node.*down', r'service.*unavailable'
        ],
        'ATTRIBUTE_ERROR': [
            r'AttributeError', r"has\s+no\s+attribute", r"object.*no\s+attribute"
        ],
        'KEY_ERROR': [
            r'KeyError', r'key.*not\s+found', r'missing\s+key'
        ],
        'VALUE_ERROR': [
            r'ValueError', r'invalid.*value', r'value.*out\s+of\s+range'
        ],
        'TYPE_ERROR': [
            r'TypeError', r'unexpected\s+type', r'type.*mismatch'
        ],
        'IMPORT_ERROR': [
            r'ImportError', r'ModuleNotFoundError', r'No\s+module\s+named',
            r'cannot\s+import'
        ],
        'IO_ERROR': [
            r'IOError', r'FileNotFoundError', r'PermissionError',
            r'file.*not\s+found', r'permission\s+denied', r'read.*error'
        ],
        'HTTP_ERROR': [
            r'HTTPError', r'HTTP\s+\d{3}', r'status\s+code.*[45]\d{2}',
            r'request.*failed', r'api.*error'
        ],
        'RUNTIME_ERROR': [
            r'RuntimeError', r'runtime.*error'
        ],
        'SETUP_ERROR': [
            r'SetupError', r'setup.*failed', r'initialization.*failed',
            r'test.*setup.*error'
        ],
        'TEARDOWN_ERROR': [
            r'TeardownError', r'teardown.*failed', r'cleanup.*failed'
        ],
        'RESOURCE_ERROR': [
            r'ResourceError', r'resource.*not\s+available',
            r'quota.*exceeded', r'out\s+of\s+memory', r'disk.*full'
        ],
        'VALIDATION_ERROR': [
            r'ValidationError', r'validation.*failed', r'invalid.*input',
            r'schema.*error', r'format.*error'
        ],
        'AUTHENTICATION_ERROR': [
            r'AuthenticationError', r'auth.*failed', r'unauthorized',
            r'invalid.*credentials', r'access.*denied'
        ],
        'DATABASE_ERROR': [
            r'DatabaseError', r'db.*error', r'query.*failed',
            r'transaction.*failed', r'deadlock'
        ],
        'NUTEST_ERROR': [
            r'NutestError', r'nutest.*exception', r'framework.*error'
        ],
        'WORKFLOW_ERROR': [
            r'WorkflowError', r'workflow.*failed', r'operation.*failed',
            r'step.*failed'
        ],
        'CLUSTER_ERROR': [
            r'ClusterError', r'cluster.*not\s+ready', r'cvm.*down',
            r'prism.*error', r'nos.*error'
        ],
    }
    
    # Nutest-specific log patterns
    NUTEST_PATTERNS = {
        'TEST_START': r'(Running\s+test|Test\s+started|Starting\s+test)\s*:?\s*(\S+)',
        'TEST_END': r'(Test\s+(PASSED|FAILED|SKIPPED)|test.*completed)',
        'OPERATION': r'(Operation|Step|Phase)\s*:?\s*(\S+)\s*-\s*(PASSED|FAILED|SKIPPED)',
        'WORKFLOW': r'(Workflow|Scenario)\s*:?\s*(\S+)',
    }
    
    # Timestamp patterns
    TIMESTAMP_PATTERNS = [
        # ISO format: 2026-01-27T14:30:45.123Z
        (r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)', '%Y-%m-%dT%H:%M:%S'),
        # Standard format: 2026-01-27 14:30:45
        (r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', '%Y-%m-%d %H:%M:%S'),
        # Google glog: E20260127 14:30:45
        (r'[IWEF](\d{4})(\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', 'glog'),
        # Nutest format: [2026-01-27 14:30:45]
        (r'\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]', '%Y-%m-%d %H:%M:%S'),
        # Python logging: 2026-01-27 14:30:45,123
        (r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}),\d+', '%Y-%m-%d %H:%M:%S'),
    ]
    
    def __init__(self, max_message_length: int = 500, max_stack_trace_length: int = 2000):
        self.max_message_length = max_message_length
        self.max_stack_trace_length = max_stack_trace_length
        
        # Compile patterns for efficiency
        self._severity_compiled = {
            sev: [re.compile(p, re.IGNORECASE) for p in patterns]
            for sev, patterns in self.SEVERITY_PATTERNS.items()
        }
        self._exception_compiled = {
            exc: [re.compile(p, re.IGNORECASE) for p in patterns]
            for exc, patterns in self.EXCEPTION_PATTERNS.items()
        }
    
    def parse_log_content(
        self,
        content: str,
        log_source: str,
        test_result_id: str,
        test_name: str,
        severity_filter: List[str] = None
    ) -> Iterator[JitaLogEvent]:
        """
        Parse log content and yield events matching severity filter.
        
        Args:
            content: Raw log content
            log_source: Source of log (scheduler, driver, test, etc.)
            test_result_id: JITA test result ID
            test_name: Name of the test
            severity_filter: List of severities to include (default: ERROR, FATAL)
            
        Yields:
            JitaLogEvent objects for matching log entries
        """
        if severity_filter is None:
            severity_filter = ['ERROR', 'FATAL']
        
        severity_filter = [s.upper() for s in severity_filter]
        
        lines = content.split('\n')
        current_event = None
        stack_lines = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.rstrip()
            if not line:
                continue
            
            # Check if this is a new log entry
            is_new_entry = self._is_new_log_entry(line)
            
            if is_new_entry:
                # Yield previous event if exists and matches filter
                if current_event and current_event.severity in severity_filter:
                    if stack_lines:
                        current_event.stack_trace = '\n'.join(stack_lines)[:self.max_stack_trace_length]
                    yield current_event
                
                # Detect severity
                severity = self._detect_severity(line)
                
                if severity in severity_filter:
                    timestamp = self._extract_timestamp(line)
                    event_type = self._classify_error(line)
                    
                    current_event = JitaLogEvent(
                        test_result_id=test_result_id,
                        test_name=test_name,
                        log_source=log_source,
                        timestamp=timestamp,
                        severity=severity,
                        event_type=event_type,
                        message=line[:self.max_message_length],
                        line_number=line_num
                    )
                    stack_lines = []
                else:
                    current_event = None
                    stack_lines = []
            
            elif current_event:
                # Continuation line (possibly stack trace)
                if self._is_stack_trace_line(line) and len(stack_lines) < 100:
                    stack_lines.append(line)
                elif line.strip() and len(stack_lines) < 100:
                    # Could be part of multi-line message or stack trace
                    stack_lines.append(line)
        
        # Yield last event
        if current_event and current_event.severity in severity_filter:
            if stack_lines:
                current_event.stack_trace = '\n'.join(stack_lines)[:self.max_stack_trace_length]
            yield current_event
    
    def parse_exception(
        self,
        exception_text: str,
        test_result_id: str,
        test_name: str,
        timestamp: int = None
    ) -> JitaLogEvent:
        """
        Parse an exception/stack trace from JITA result.
        
        Args:
            exception_text: Full exception text with stack trace
            test_result_id: JITA test result ID
            test_name: Name of the test
            timestamp: Unix timestamp (defaults to now)
            
        Returns:
            JitaLogEvent representing the exception
        """
        if timestamp is None:
            timestamp = int(datetime.now().timestamp())
        
        # Extract first line as message
        lines = exception_text.strip().split('\n')
        message = lines[-1] if lines else exception_text[:self.max_message_length]
        
        # Classify the exception
        event_type = self._classify_error(exception_text)
        
        # Determine severity
        severity = 'ERROR'
        if any(p in exception_text.lower() for p in ['fatal', 'critical', 'panic']):
            severity = 'FATAL'
        
        return JitaLogEvent(
            test_result_id=test_result_id,
            test_name=test_name,
            log_source='exception',
            timestamp=timestamp,
            severity=severity,
            event_type=event_type,
            message=message[:self.max_message_length],
            stack_trace=exception_text[:self.max_stack_trace_length],
            line_number=0
        )
    
    def _detect_severity(self, line: str) -> str:
        """Detect log severity from a line."""
        # Check for explicit severity markers at start
        line_upper = line.upper()
        
        # Google glog format: first char
        if re.match(r'^[IWEF]\d{4,8}\s', line):
            first_char = line[0].upper()
            return {'F': 'FATAL', 'E': 'ERROR', 'W': 'WARN', 'I': 'INFO'}.get(first_char, 'INFO')
        
        # Standard patterns
        for severity in ['FATAL', 'ERROR', 'WARN', 'INFO']:
            for pattern in self._severity_compiled[severity]:
                if pattern.search(line):
                    return severity
        
        return 'INFO'
    
    def _classify_error(self, text: str) -> Optional[str]:
        """Classify error type from text."""
        for event_type, patterns in self._exception_compiled.items():
            for pattern in patterns:
                if pattern.search(text):
                    return event_type
        return None
    
    def _extract_timestamp(self, line: str) -> int:
        """Extract timestamp from log line."""
        for pattern, fmt in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                try:
                    if fmt == 'glog':
                        # Google glog: groups are year, month, day, hour, min, sec
                        year, month, day = match.group(1), match.group(2), match.group(3)
                        hour, minute, second = match.group(4), match.group(5), match.group(6)
                        dt = datetime(int(year), int(month), int(day), 
                                     int(hour), int(minute), int(second))
                    else:
                        ts_str = match.group(1)
                        # Clean up for parsing
                        ts_str = ts_str.replace('T', ' ').replace('Z', '')[:19]
                        dt = datetime.strptime(ts_str, fmt.replace('T', ' ')[:19])
                    return int(dt.timestamp())
                except (ValueError, IndexError):
                    continue
        
        return int(datetime.now().timestamp())
    
    def _is_new_log_entry(self, line: str) -> bool:
        """Check if a line is the start of a new log entry."""
        # Google glog format
        if re.match(r'^[IWEF]\d{4,8}\s', line):
            return True
        
        # Standard timestamp at start
        if re.match(r'^\d{4}-\d{2}-\d{2}[\sT]', line):
            return True
        
        # Bracketed timestamp
        if re.match(r'^\[\d{4}-\d{2}-\d{2}', line):
            return True
        
        # Severity at start
        if re.match(r'^(FATAL|ERROR|WARN|WARNING|INFO|DEBUG)\s*[:\[]', line, re.IGNORECASE):
            return True
        
        # Traceback start
        if line.strip() == 'Traceback (most recent call last):':
            return True
        
        return False
    
    def _is_stack_trace_line(self, line: str) -> bool:
        """Check if line is part of a stack trace."""
        stripped = line.lstrip()
        
        # Python stack trace patterns
        if stripped.startswith('File "'):
            return True
        if stripped.startswith('at '):
            return True
        if stripped.startswith('in '):
            return True
        if re.match(r'^\d+:', stripped):  # Numbered frames
            return True
        if stripped.startswith('...'):  # Truncation indicator
            return True
        
        # Exception continuation
        if re.match(r'^[A-Z][a-zA-Z]+Error:', stripped):
            return True
        if re.match(r'^[A-Z][a-zA-Z]+Exception:', stripped):
            return True
        
        return False
    
    def extract_test_operations(self, content: str) -> List[Dict]:
        """
        Extract test operation results from nutest log.
        
        Returns list of dicts with operation name and status.
        """
        operations = []
        
        for match in re.finditer(self.NUTEST_PATTERNS['OPERATION'], content, re.IGNORECASE):
            operations.append({
                'type': match.group(1),
                'name': match.group(2),
                'status': match.group(3)
            })
        
        return operations


# Singleton instance
_parser = None


def get_jita_log_parser() -> JitaLogParser:
    """Get or create the JITA log parser singleton."""
    global _parser
    if _parser is None:
        _parser = JitaLogParser()
    return _parser
