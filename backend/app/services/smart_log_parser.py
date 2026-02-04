"""
Smart Log Parser for NOVA Backend

Improved log parsing with:
1. Structured log format detection (extracts actual severity field)
2. Evidence-based error detection (requires stack trace or exception)
3. Priority scoring based on multiple factors
4. Smart deduplication
"""
import re
import hashlib
from typing import List, Dict, Optional, Iterator, Tuple
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParsedLogEntry:
    """A parsed log entry with metadata."""
    line_number: int
    raw_line: str
    timestamp: Optional[int] = None
    severity: str = "INFO"  # Actual severity from log format
    source: str = ""        # Log source/module
    message: str = ""       # The actual message content
    is_continuation: bool = False


@dataclass 
class SmartLogEvent:
    """Represents an identified error event with priority scoring."""
    test_result_id: str
    test_name: str
    log_source: str
    timestamp: int
    severity: str                      # INFO, WARN, ERROR, FATAL
    event_type: Optional[str] = None   # Classified error type
    message: str = ""
    stack_trace: Optional[str] = None
    line_number: int = 0
    priority: str = "P3"               # P0 (critical) to P3 (low)
    confidence: float = 0.0            # 0.0 to 1.0
    evidence: List[str] = field(default_factory=list)
    context_lines: List[str] = field(default_factory=list)
    dedup_hash: str = ""


class SmartLogParser:
    """
    Intelligent log parser that reduces false positives.
    
    Key improvements:
    1. Parses actual log format to extract severity field
    2. Only flags lines with severity=ERROR/FATAL in the log format
    3. Adds evidence requirements (stack trace, exception class)
    4. Assigns priority scores based on multiple factors
    5. Deduplicates similar errors
    """
    
    # Log format patterns - extract severity from log structure
    LOG_FORMAT_PATTERNS = [
        # Python logging: "2026-01-27 14:30:45 ERROR module.name: message"
        re.compile(
            r'^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[\s,\d]*'
            r'(?P<sev>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\s+'
            r'(?P<src>[\w\.\-]+)\s*[:\|]\s*'
            r'(?P<msg>.*)$',
            re.IGNORECASE
        ),
        # Google glog: "E20260127 14:30:45.123456 12345 file.cc:123] message"
        re.compile(
            r'^(?P<sev>[IWEF])(?P<ts>\d{8}\s+\d{2}:\d{2}:\d{2})\.\d+\s+'
            r'\d+\s+(?P<src>\S+):?\d*\]\s*(?P<msg>.*)$'
        ),
        # Nutest format: "2026-01-27 14:30:45 ERROR module (source:body) message"
        re.compile(
            r'^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+'
            r'(?P<sev>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\s+'
            r'(?P<src>[\w\.\-]+)\s*\([^)]+\)\s*'
            r'(?P<msg>.*)$',
            re.IGNORECASE
        ),
        # Simple: "[ERROR] message" or "ERROR: message"
        re.compile(
            r'^\[?(?P<sev>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]?\s*[:\-]\s*'
            r'(?P<msg>.*)$',
            re.IGNORECASE
        ),
    ]
    
    # Patterns that MUST be present for high-confidence error detection
    STRONG_ERROR_INDICATORS = [
        re.compile(r'^Traceback \(most recent call last\):', re.MULTILINE),
        re.compile(r'^\s*File ".*", line \d+', re.MULTILINE),
        re.compile(r'^[A-Z][a-zA-Z]*Error:', re.MULTILINE),
        re.compile(r'^[A-Z][a-zA-Z]*Exception:', re.MULTILINE),
        re.compile(r'raise\s+[A-Z][a-zA-Z]*(Error|Exception)', re.MULTILINE),
        re.compile(r'Test\s+FAILED', re.IGNORECASE),
        re.compile(r'FATAL ERROR', re.IGNORECASE),
        re.compile(r'ASSERTION FAILED', re.IGNORECASE),
    ]
    
    # Exception class names that indicate real errors
    EXCEPTION_CLASSES = [
        # Python built-in
        'AssertionError', 'RuntimeError', 'ValueError', 'TypeError', 'KeyError',
        'AttributeError', 'IndexError', 'ImportError', 'IOError', 'OSError',
        'FileNotFoundError', 'PermissionError', 'ConnectionError', 'TimeoutError',
        'MemoryError', 'OverflowError', 'ZeroDivisionError', 'UnicodeError',
        'UnicodeDecodeError', 'UnicodeEncodeError', 'SyntaxError', 'IndentationError',
        'NameError', 'UnboundLocalError', 'StopIteration', 'GeneratorExit',
        'RecursionError', 'NotImplementedError', 'SystemError', 'SystemExit',
        'KeyboardInterrupt', 'BrokenPipeError', 'ConnectionRefusedError',
        'ConnectionResetError', 'ConnectionAbortedError', 'InterruptedError',
        'ChildProcessError', 'ProcessLookupError', 'BlockingIOError',
        
        # HTTP/Network
        'HTTPError', 'URLError', 'RequestException', 'ConnectionException',
        'SSLError', 'ProxyError', 'InvalidURL', 'ChunkedEncodingError',
        'ContentDecodingError', 'TooManyRedirects', 'MissingSchema',
        'InvalidSchema', 'InvalidHeader', 'StreamConsumedError',
        
        # Auth
        'AuthenticationError', 'AuthorizationError', 'CredentialsError',
        'TokenError', 'InvalidTokenError', 'ExpiredTokenError',
        
        # Database
        'DatabaseError', 'IntegrityError', 'OperationalError', 'ProgrammingError',
        'InterfaceError', 'InternalError', 'DataError', 'NotSupportedError',
        
        # Validation
        'ValidationError', 'SchemaError', 'ParseError', 'SerializationError',
        
        # Nutanix/Test Framework
        'NuTestError', 'InfraError', 'ClusterError', 'WorkflowError', 'SetupError',
        'NuTestInterfaceTransportError', 'NuTestSSHTimeoutError', 'NuTestSSHError',
        'NuTestTimeoutError', 'NuTestResourceError', 'TestError', 'TestFailure',
        'ConfigurationError', 'DeploymentError', 'ProvisioningError',
        
        # API/Service
        'APIError', 'ServiceError', 'EndpointError', 'RateLimitError',
        'QuotaExceededError', 'ResourceNotFoundError', 'ConflictError',
    ]
    
    # False positive patterns - skip these even if they contain "ERROR"
    FALSE_POSITIVE_PATTERNS = [
        re.compile(r'error_count\s*[=:]\s*\d+', re.IGNORECASE),
        re.compile(r'errors?\s*:\s*0', re.IGNORECASE),
        re.compile(r'no\s+errors?', re.IGNORECASE),
        re.compile(r'error.*rate\s*[=:]\s*0', re.IGNORECASE),
        re.compile(r'/error/', re.IGNORECASE),  # URLs with /error/
        re.compile(r'_error_', re.IGNORECASE),   # Variable names
        re.compile(r'\.error\.', re.IGNORECASE), # Package names
        re.compile(r'error_handler', re.IGNORECASE),
        re.compile(r'on_error', re.IGNORECASE),
        re.compile(r'stderr', re.IGNORECASE),
        re.compile(r'Successfully', re.IGNORECASE),  # Success messages
    ]
    
    # Event type classification (comprehensive patterns for actual errors)
    ERROR_TYPES = {
        # Python/Framework Errors
        'ASSERTION_ERROR': [r'AssertionError', r'assert\s+False', r'ASSERTION FAILED', r'assertion.*failed'],
        'KEY_ERROR': [r'KeyError', r'KeyError:', r"KeyError:.*'[^']+'"],
        'VALUE_ERROR': [r'ValueError', r'ValueError:', r'invalid.*value', r'value.*invalid'],
        'TYPE_ERROR': [r'TypeError', r'TypeError:', r'type.*error', r'wrong.*type'],
        'ATTRIBUTE_ERROR': [r'AttributeError', r'AttributeError:', r'has no attribute'],
        'INDEX_ERROR': [r'IndexError', r'IndexError:', r'index out of', r'list index out'],
        'RUNTIME_ERROR': [r'RuntimeError', r'RuntimeError:'],
        'IMPORT_ERROR': [r'ImportError', r'ModuleNotFoundError', r'No module named'],
        'NAME_ERROR': [r'NameError', r'NameError:', r'name.*is not defined'],
        
        # Network/Connection Errors
        'TIMEOUT': [r'TimeoutError', r'Timeout', r'timed\s+out', r'deadline\s+exceeded', r'connection.*timed', r'socket.*timeout', r'read.*timeout', r'request.*timeout'],
        'CONNECTION_ERROR': [r'ConnectionError', r'ConnectionRefused', r'connection\s+reset', r'Connection refused', r'Connection reset', r'ECONNREFUSED', r'ECONNRESET', r'network.*unreachable', r'host.*unreachable', r'no route to host'],
        'SOCKET_ERROR': [r'SocketError', r'socket\.error', r'socket\.timeout', r'broken pipe', r'EPIPE'],
        'SSL_ERROR': [r'SSLError', r'SSL.*error', r'certificate.*error', r'ssl.*handshake', r'CERTIFICATE_VERIFY_FAILED'],
        'DNS_ERROR': [r'DNSError', r'getaddrinfo', r'Name or service not known', r'DNS.*failed', r'resolution.*failed'],
        
        # HTTP Errors
        'HTTP_400': [r'HTTP.*400', r'Bad Request', r'status.*400'],
        'HTTP_401': [r'HTTP.*401', r'Unauthorized', r'status.*401'],
        'HTTP_403': [r'HTTP.*403', r'Forbidden', r'status.*403', r'access.*denied'],
        'HTTP_404': [r'HTTP.*404', r'Not Found', r'status.*404', r'resource.*not found'],
        'HTTP_500': [r'HTTP.*500', r'Internal Server Error', r'status.*500'],
        'HTTP_502': [r'HTTP.*502', r'Bad Gateway', r'status.*502'],
        'HTTP_503': [r'HTTP.*503', r'Service Unavailable', r'status.*503'],
        'HTTP_ERROR': [r'HTTPError', r'status\s+code.*[45]\d{2}', r'HTTP\s+[45]\d{2}', r'requests\.exceptions\.HTTPError'],
        
        # Authentication/Authorization
        'AUTH_ERROR': [r'AuthenticationError', r'AuthError', r'authentication.*failed', r'invalid.*credentials', r'login.*failed'],
        'PERMISSION_ERROR': [r'PermissionError', r'Permission denied', r'access.*denied', r'not authorized', r'forbidden'],
        
        # File/IO Errors
        'FILE_NOT_FOUND': [r'FileNotFoundError', r'No such file', r'file not found', r'path.*does not exist'],
        'IO_ERROR': [r'IOError', r'I/O error', r'read.*failed', r'write.*failed', r'disk.*error'],
        'DISK_FULL': [r'No space left', r'disk.*full', r'ENOSPC', r'quota.*exceeded'],
        
        # Resource/Memory Errors
        'MEMORY_ERROR': [r'MemoryError', r'out of memory', r'OOM', r'cannot allocate', r'malloc.*failed'],
        'RESOURCE_ERROR': [r'ResourceError', r'resource.*unavailable', r'resource.*exhausted', r'too many open files'],
        
        # Database Errors
        'DATABASE_ERROR': [r'DatabaseError', r'DBError', r'SQL.*error', r'query.*failed', r'database.*error', r'connection.*database'],
        'CONSTRAINT_ERROR': [r'IntegrityError', r'constraint.*violation', r'duplicate.*key', r'foreign key'],
        
        # Nutanix/Infrastructure Specific
        'INFRA_ERROR': [r'InfraError', r'INFRA_ERROR', r'cluster.*unavailable', r'infrastructure.*error'],
        'CLUSTER_ERROR': [r'ClusterError', r'cluster.*error', r'cluster.*failed', r'cvm.*error', r'prism.*error'],
        'WORKFLOW_ERROR': [r'WorkflowError', r'workflow.*failed', r'workflow.*error'],
        'TASK_FAILED': [r'TASK_FAILED', r'task.*failed', r'operation.*failed', r'task.*error'],
        'API_ERROR': [r'APIError', r'API.*error', r'api.*failed', r'REST.*error'],
        
        # SSH/Remote Errors  
        'SSH_ERROR': [r'SSHError', r'SSH.*failed', r'NuTestSSH', r'ssh.*error', r'paramiko.*error', r'connection.*ssh'],
        'TRANSPORT_ERROR': [r'TransportError', r'InterfaceTransportError', r'transport.*failed'],
        
        # Test Framework Errors
        'SETUP_ERROR': [r'SetupError', r'setup.*failed', r'setUp.*error', r'initialization.*failed'],
        'TEARDOWN_ERROR': [r'TeardownError', r'teardown.*failed', r'cleanup.*failed'],
        'TEST_FAILED': [r'TestFailed', r'test.*failed', r'FAILED', r'test.*error'],
        'SKIP_ERROR': [r'SkipTest', r'test.*skipped', r'skip.*reason'],
        
        # Validation/Data Errors
        'VALIDATION_ERROR': [r'ValidationError', r'validation.*failed', r'invalid.*data', r'schema.*error'],
        'PARSING_ERROR': [r'ParseError', r'JSON.*error', r'XML.*error', r'parse.*failed', r'syntax.*error'],
        'ENCODING_ERROR': [r'UnicodeError', r'encoding.*error', r'decode.*error', r'utf-8.*error'],
        
        # Configuration Errors
        'CONFIG_ERROR': [r'ConfigError', r'configuration.*error', r'config.*invalid', r'missing.*config'],
        
        # Concurrency Errors
        'DEADLOCK': [r'Deadlock', r'deadlock.*detected', r'circular.*wait'],
        'RACE_CONDITION': [r'race.*condition', r'concurrent.*modification'],
        'LOCK_ERROR': [r'LockError', r'lock.*timeout', r'unable to acquire'],
    }
    
    def __init__(self, context_window: int = 10):
        """
        Initialize parser.
        
        Args:
            context_window: Number of lines to capture around errors
        """
        self.context_window = context_window
        self._error_type_patterns = {
            k: [re.compile(p, re.IGNORECASE) for p in v]
            for k, v in self.ERROR_TYPES.items()
        }
    
    def parse_log_content(
        self,
        content: str,
        log_source: str,
        test_result_id: str,
        test_name: str,
        min_confidence: float = 0.5
    ) -> List[SmartLogEvent]:
        """
        Parse log content and return high-confidence error events.
        
        Args:
            content: Raw log content
            log_source: Source identifier
            test_result_id: Test result ID
            test_name: Test name
            min_confidence: Minimum confidence threshold (0.0-1.0)
            
        Returns:
            List of SmartLogEvent with confidence >= min_confidence
        """
        lines = content.split('\n')
        events = []
        seen_hashes = set()
        
        # First pass: parse all lines and detect structure
        parsed_lines = self._parse_lines(lines)
        
        # Second pass: find error regions with context
        error_regions = self._find_error_regions(parsed_lines, lines)
        
        # Third pass: create events from regions
        for region in error_regions:
            event = self._create_event_from_region(
                region, log_source, test_result_id, test_name
            )
            
            if event and event.confidence >= min_confidence:
                # Deduplicate
                if event.dedup_hash not in seen_hashes:
                    seen_hashes.add(event.dedup_hash)
                    events.append(event)
        
        # Sort by priority and confidence
        events.sort(key=lambda e: (
            {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}.get(e.priority, 3),
            -e.confidence
        ))
        
        return events
    
    def _parse_lines(self, lines: List[str]) -> List[ParsedLogEntry]:
        """Parse each line to extract structure."""
        parsed = []
        
        for i, line in enumerate(lines, 1):
            entry = ParsedLogEntry(
                line_number=i,
                raw_line=line,
                is_continuation=self._is_continuation(line)
            )
            
            # Try to match log format patterns
            for pattern in self.LOG_FORMAT_PATTERNS:
                match = pattern.match(line)
                if match:
                    groups = match.groupdict()
                    entry.severity = self._normalize_severity(groups.get('sev', 'INFO'))
                    entry.source = groups.get('src', '')
                    entry.message = groups.get('msg', line)
                    entry.timestamp = self._parse_timestamp(groups.get('ts', ''))
                    break
            else:
                # No format match - check for severity keywords at start
                entry.severity = self._detect_line_severity(line)
                entry.message = line
            
            parsed.append(entry)
        
        return parsed
    
    def _find_error_regions(
        self, 
        parsed: List[ParsedLogEntry], 
        raw_lines: List[str]
    ) -> List[Dict]:
        """Find error regions with context."""
        regions = []
        i = 0
        
        while i < len(parsed):
            entry = parsed[i]
            
            # Only consider actual ERROR/FATAL from log format
            if entry.severity in ('ERROR', 'FATAL') and not entry.is_continuation:
                # Check for false positives
                if self._is_false_positive(entry.raw_line):
                    i += 1
                    continue
                
                # Collect this error region
                region = {
                    'start_line': i,
                    'primary_entry': entry,
                    'continuation_lines': [],
                    'context_before': [],
                    'context_after': [],
                    'has_stack_trace': False,
                    'exception_class': None,
                }
                
                # Get context before
                start = max(0, i - self.context_window)
                region['context_before'] = raw_lines[start:i]
                
                # Collect continuation lines (stack trace, multi-line message)
                j = i + 1
                while j < len(parsed) and self._should_continue(parsed[j], entry):
                    region['continuation_lines'].append(parsed[j].raw_line)
                    
                    # Check for stack trace indicators
                    if self._is_stack_trace_line(parsed[j].raw_line):
                        region['has_stack_trace'] = True
                    
                    # Check for exception class
                    exc = self._extract_exception_class(parsed[j].raw_line)
                    if exc:
                        region['exception_class'] = exc
                    
                    j += 1
                
                # Get context after
                end = min(len(raw_lines), j + self.context_window)
                region['context_after'] = raw_lines[j:end]
                region['end_line'] = j
                
                # Also check primary line for exception class
                if not region['exception_class']:
                    region['exception_class'] = self._extract_exception_class(entry.raw_line)
                
                regions.append(region)
                i = j
            else:
                i += 1
        
        return regions
    
    def _create_event_from_region(
        self,
        region: Dict,
        log_source: str,
        test_result_id: str,
        test_name: str
    ) -> Optional[SmartLogEvent]:
        """Create a SmartLogEvent from an error region."""
        entry = region['primary_entry']
        
        # Calculate confidence score
        confidence, evidence = self._calculate_confidence(region)
        
        # Skip very low confidence
        if confidence < 0.3:
            return None
        
        # Determine priority
        priority = self._determine_priority(region, confidence)
        
        # Classify error type
        full_text = entry.raw_line + '\n' + '\n'.join(region['continuation_lines'])
        event_type = self._classify_error_type(full_text)
        
        # Build stack trace
        stack_trace = None
        if region['continuation_lines']:
            # Add context around the error
            context = []
            if region['context_before']:
                context.append("--- Context (±{} lines) ---".format(self.context_window))
                for line in region['context_before'][-5:]:
                    context.append(f"    {line}")
            
            context.append(f">>> {entry.raw_line}")
            
            for line in region['continuation_lines'][:50]:
                context.append(f"    {line}")
            
            stack_trace = '\n'.join(context)
        
        # Create dedup hash
        dedup_hash = self._create_dedup_hash(entry, region)
        
        return SmartLogEvent(
            test_result_id=test_result_id,
            test_name=test_name,
            log_source=log_source,
            timestamp=entry.timestamp or int(datetime.now().timestamp()),
            severity=entry.severity,
            event_type=event_type,
            message=entry.message[:500],
            stack_trace=stack_trace,
            line_number=entry.line_number,
            priority=priority,
            confidence=confidence,
            evidence=evidence,
            dedup_hash=dedup_hash
        )
    
    def _calculate_confidence(self, region: Dict) -> Tuple[float, List[str]]:
        """Calculate confidence score for error region."""
        score = 0.0
        evidence = []
        
        entry = region['primary_entry']
        full_text = entry.raw_line + '\n' + '\n'.join(region['continuation_lines'])
        
        # Base score for having ERROR/FATAL in log format
        if entry.severity == 'FATAL':
            score += 0.4
            evidence.append("FATAL severity in log format")
        elif entry.severity == 'ERROR':
            score += 0.3
            evidence.append("ERROR severity in log format")
        
        # Has stack trace (+0.3)
        if region['has_stack_trace']:
            score += 0.3
            evidence.append("Contains stack trace")
        
        # Has known exception class (+0.2)
        if region['exception_class']:
            score += 0.2
            evidence.append(f"Exception: {region['exception_class']}")
        
        # Check for strong error indicators
        for pattern in self.STRONG_ERROR_INDICATORS:
            if pattern.search(full_text):
                score += 0.15
                evidence.append(f"Strong indicator: {pattern.pattern[:30]}...")
                break
        
        # Has continuation lines (likely a real error with details)
        if len(region['continuation_lines']) > 2:
            score += 0.1
            evidence.append("Multi-line error details")
        
        # Penalty for very short message (might be noise)
        if len(entry.message) < 20:
            score -= 0.1
        
        return min(1.0, score), evidence
    
    def _determine_priority(self, region: Dict, confidence: float) -> str:
        """Determine error priority."""
        entry = region['primary_entry']
        
        # P0: FATAL or very high confidence with stack trace
        if entry.severity == 'FATAL':
            return 'P0'
        if confidence >= 0.9 and region['has_stack_trace']:
            return 'P0'
        
        # P1: High confidence errors with evidence
        if confidence >= 0.7 and (region['has_stack_trace'] or region['exception_class']):
            return 'P1'
        
        # P2: Medium confidence
        if confidence >= 0.5:
            return 'P2'
        
        # P3: Low confidence
        return 'P3'
    
    def _classify_error_type(self, text: str) -> Optional[str]:
        """Classify the error type."""
        for error_type, patterns in self._error_type_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    return error_type
        return None
    
    def _create_dedup_hash(self, entry: ParsedLogEntry, region: Dict) -> str:
        """Create a hash for deduplication."""
        # Hash based on: exception class, first 50 chars of message, source
        key_parts = [
            region.get('exception_class', ''),
            entry.message[:50] if entry.message else '',
            entry.source or '',
        ]
        key = '|'.join(key_parts)
        return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def _normalize_severity(self, sev: str) -> str:
        """Normalize severity string."""
        sev = sev.upper()
        mapping = {
            'WARNING': 'WARN',
            'CRITICAL': 'FATAL',
            'I': 'INFO',
            'W': 'WARN',
            'E': 'ERROR',
            'F': 'FATAL',
        }
        return mapping.get(sev, sev)
    
    def _detect_line_severity(self, line: str) -> str:
        """Detect severity from unstructured line."""
        line_start = line[:50].upper()
        
        if 'FATAL' in line_start or 'CRITICAL' in line_start:
            return 'FATAL'
        if line_start.startswith('ERROR') or ' ERROR ' in line_start:
            return 'ERROR'
        if 'WARN' in line_start:
            return 'WARN'
        return 'INFO'
    
    def _parse_timestamp(self, ts_str: str) -> Optional[int]:
        """Parse timestamp string to unix epoch."""
        if not ts_str:
            return None
        
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y%m%d %H:%M:%S',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(ts_str[:19], fmt)
                return int(dt.timestamp())
            except ValueError:
                continue
        
        return None
    
    def _is_continuation(self, line: str) -> bool:
        """Check if line is a continuation (not a new log entry)."""
        stripped = line.lstrip()
        
        # Empty or whitespace-only
        if not stripped:
            return True
        
        # Starts with whitespace (indented)
        if line and line[0] in ' \t':
            return True
        
        # Stack trace patterns
        if stripped.startswith('File "'):
            return True
        if stripped.startswith('at '):
            return True
        if stripped.startswith('^'):
            return True
        
        return False
    
    def _should_continue(self, entry: ParsedLogEntry, primary: ParsedLogEntry) -> bool:
        """Check if entry should be included in the error region."""
        # Include continuations
        if entry.is_continuation:
            return True
        
        # Include if same source and lower/equal severity
        if entry.source == primary.source:
            sev_order = {'INFO': 0, 'WARN': 1, 'ERROR': 2, 'FATAL': 3}
            if sev_order.get(entry.severity, 0) <= sev_order.get(primary.severity, 0):
                return True
        
        # Stop on new ERROR/FATAL from different source
        if entry.severity in ('ERROR', 'FATAL'):
            return False
        
        return False
    
    def _is_stack_trace_line(self, line: str) -> bool:
        """Check if line is part of a stack trace."""
        stripped = line.strip()
        
        if stripped.startswith('File "'):
            return True
        if stripped.startswith('at '):
            return True
        if re.match(r'^\s+\d+:', stripped):
            return True
        if 'Traceback' in stripped:
            return True
        if re.match(r'^[A-Z][a-zA-Z]+(Error|Exception):', stripped):
            return True
        
        return False
    
    def _is_false_positive(self, line: str) -> bool:
        """Check if line is a false positive."""
        for pattern in self.FALSE_POSITIVE_PATTERNS:
            if pattern.search(line):
                return True
        return False
    
    def _extract_exception_class(self, line: str) -> Optional[str]:
        """Extract exception class name from line."""
        for exc_class in self.EXCEPTION_CLASSES:
            if exc_class in line:
                return exc_class
        
        # Generic pattern
        match = re.search(r'([A-Z][a-zA-Z]*(Error|Exception)):', line)
        if match:
            return match.group(1)
        
        return None


# Singleton instance
_smart_parser = None


def get_smart_log_parser() -> SmartLogParser:
    """Get or create the smart log parser singleton."""
    global _smart_parser
    if _smart_parser is None:
        _smart_parser = SmartLogParser()
    return _smart_parser
