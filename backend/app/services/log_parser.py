"""
Log Parser Service for NOVA Backend

Parses Nutanix logbay archives and extracts ERROR/WARN/FATAL events.
Only extracts metadata - does not store full log content.
"""
import re
import gzip
import tarfile
import tempfile
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Iterator, Tuple
from pathlib import Path


@dataclass
class LogEvent:
    """Represents a parsed log event (metadata only)"""
    timestamp: int                      # Unix epoch seconds
    pod: str                            # OC, MS, Atlas, Curator, Stargate
    node_name: Optional[str] = None
    object_store_uuid: Optional[str] = None
    object_store_name: Optional[str] = None
    bucket_name: Optional[str] = None
    severity: str = "INFO"              # INFO, WARN, ERROR, FATAL
    event_type: Optional[str] = None    # REPLICATION_FAIL, IO_ERROR, etc.
    message: str = ""                   # First 500 chars
    stack_trace: Optional[str] = None   # First 1000 chars
    raw_log_file: str = ""              # S3 URL to archive
    raw_file_path: str = ""             # Path within archive
    raw_line_number: int = 0


class LogParser:
    """
    Parses Nutanix logbay archives and extracts important log events.
    
    Supported log formats:
    - OC (Object Controller): oc.log, oc.ERROR, oc.FATAL
    - MS (Metadata Service): ms.log, ms.ERROR  
    - Atlas: atlas.log
    - Curator: curator.log
    - Stargate: stargate.log
    """
    
    # Log file patterns to scan
    # Matches actual Nutanix Object Store log file naming conventions
    LOG_FILE_PATTERNS = {
        'OC': [
            'oc.log', 'oc.ERROR', 'oc.FATAL', 'oc.WARNING', 
            'object_controller.log', 'object_store.', 'object-controller',
            'poseidon', 'hermes', 'federation_controller',
        ],
        'MS': [
            'ms.log', 'ms.ERROR', 'ms.FATAL', 
            'metadata_service.log', 'metadata-service', 'ms-',
        ],
        'Atlas': ['atlas.log', 'atlas.ERROR', 'atlas.FATAL', 'atlas-'],
        'Curator': ['curator.log', 'curator.ERROR', 'curator.FATAL'],
        'Stargate': ['stargate.log', 'stargate.ERROR', 'stargate.FATAL'],
        'Zookeeper': ['zookeeper', 'zk-'],
        'Buckets': ['bucket', 'bucketstools'],
    }
    
    # Also match files by severity in filename (common Nutanix pattern)
    SEVERITY_FILE_PATTERNS = ['.ERROR.', '.FATAL.', '.WARNING.', '.WARN.']
    
    # Severity patterns
    SEVERITY_PATTERNS = {
        'FATAL': [r'\bFATAL\b', r'\bCRITICAL\b', r'\bPANIC\b'],
        'ERROR': [r'\bERROR\b', r'\bERR\b', r'\bFAILED\b', r'\bFAILURE\b'],
        'WARN': [r'\bWARN\b', r'\bWARNING\b'],
        'INFO': [r'\bINFO\b'],
    }
    
    # Event type patterns (for classification)
    EVENT_TYPE_PATTERNS = {
        'FILE_NOT_FOUND': [
            r'no\s+such\s+file', r'file.*not\s+exist', r'file\s+not\s+found',
            r'not\s+a\s+regular\s+file', r'cannot\s+open\s+file'
        ],
        'CONNECTION_ERROR': [
            r'unable\s+to\s+create.*connection', r'connection\s+failed', r'connect\s+error',
            r'connection\s+refused', r'connection\s+reset', r'failed\s+to\s+connect',
            r'transport\s+error', r'rpc.*error', r'http\s+connection\s+error'
        ],
        'REPLICATION_FAIL': [
            r'replication\s+fail', r'sync\s+error', r'replication\s+error',
            r'failed\s+to\s+replicate', r'replication\s+lag'
        ],
        'IO_ERROR': [
            r'i/o\s+error', r'disk\s+read\s+fail', r'write\s+error', r'read\s+error',
            r'failed\s+to\s+read', r'failed\s+to\s+write'
        ],
        'AUTH_FAIL': [
            r'auth.*fail', r'access\s+denied', r'permission\s+denied', r'unauthorized',
            r'authentication\s+failed', r'invalid.*credentials'
        ],
        'DISK_FULL': [r'no\s+space\s+left', r'disk\s+full', r'out\s+of\s+space'],
        'OOM': [r'out\s+of\s+memory', r'oom\s+killer', r'memory\s+allocation\s+fail'],
        'TIMEOUT': [r'timeout', r'timed\s+out', r'deadline\s+exceeded'],
        'SESSION_ERROR': [
            r'session.*error', r'failed\s+to\s+read\s+session', r'session\s+expired',
            r'invalid\s+session'
        ],
        'CONFIG_ERROR': [
            r'configuration\s+error', r'invalid\s+config', r'missing\s+config',
            r'thread\s+name.*maximum'
        ],
        'ZOOKEEPER_ERROR': [
            r'zookeeper.*error', r'zk.*error', r'znode.*error', r'zeus.*error'
        ],
        'CORRUPTION': [r'checksum\s+mismatch', r'data\s+corruption', r'corrupt'],
        'QUOTA_EXCEEDED': [r'quota\s+exceeded', r'limit\s+reached', r'quota\s+limit'],
        'SERVICE_DOWN': [r'service\s+unavailable', r'failed\s+to\s+start', r'service\s+down'],
        'OBJECT_ERROR': [
            r'object\s+lookup.*fail', r'invalid\s*object', r'kInvalidObject',
            r'object.*not\s+found', r'empty\s+value', r'object\s+error',
            r'failed.*object', r'object.*empty'
        ],
        'METADATA_ERROR': [
            r'metadata.*error', r'metadata.*fail', r'invalid\s+metadata',
            r'metadata.*corrupt', r'metadata.*missing'
        ],
        'RPC_ERROR': [
            r'rpc\s+fail', r'rpc\s+error', r'grpc.*error', r'grpc.*fail'
        ],
        'VALIDATION_ERROR': [
            r'validation\s+fail', r'invalid\s+request', r'invalid\s+param',
            r'validation\s+error', r'malformed'
        ],
        'SSL_ERROR': [
            r'ssl_error', r'ssl\s+error', r'tls\s+error', r'certificate\s+error',
            r'handshake\s+fail'
        ],
        'SEND_FAIL': [
            r'failed\s+to\s+send', r'send.*fail', r'syscall\s+fail',
            r'internal\s+error.*syscall'
        ],
        'SCAN_FAIL': [
            r'scan\s*fail', r'CuratorScanFailure', r'scan.*error'
        ],
        'CLIENT_UNAVAILABLE': [
            r'client\s+is\s+unavailable', r'client\s+unavailable',
            r'notification.*unavailable', r'service.*unavailable'
        ],
        'BUCKET_ERROR': [
            r'kInvalidBucket', r'invalid\s*bucket', r'bucket.*lookup\s+fail',
            r'bucket\s+info.*fail', r'bucket.*not\s+found', r'bucket.*error'
        ],
        'REGISTRATION_ERROR': [
            r'registration\s+fail', r'entity\s+registration\s+fail',
            r'kDBUpdateInProgress', r'db\s+update\s+in\s+progress'
        ],
        'IAM_ERROR': [
            r'could\s+not\s+retrieve.*iam', r'iam.*fail', r'iam.*error',
            r'could\s+not\s+retrieve.*user\s+info', r'could\s+not\s+retrieve.*keys'
        ],
        'CONFIG_NOT_FOUND': [
            r'config.*not\s+found', r'metadata\s+not\s+found',
            r'feature\s+config.*not\s+found', r'not\s+found\s+for'
        ],
        'S3_OP_ERROR': [
            r's3_base_op.*:\d+\]', r's3.*op.*error', r'request_id=.*op_id=.*error'
        ],
        'NOT_FOUND': [
            r'non\s*exist', r'non\s*existent', r'no\s+replication\s+configuration',
            r'no\s+entities\s+found', r'missing\s+uuid', r'website.*non\s*exist',
            r'cors.*non\s*exist'
        ],
        'PARSE_ERROR': [
            r'parsing.*fail', r'parse\s+error', r'failed\s+to\s+parse'
        ],
        'PUBLISH_ERROR': [
            r'failed\s+to\s+publish', r'publish.*fail', r'publish.*error'
        ],
        'USER_ERROR': [
            r'failed\s+to\s+get\s+user', r'user.*not\s+found', r'missing.*user'
        ],
        'PIPE_ERROR': [
            r'broken\s+pipe', r'error\s+while\s+writing\s+to\s+socket'
        ],
        'PROTOCOL_ERROR': [
            r'only\s+https.*allowed', r'protocol\s+error', r'invalid\s+protocol'
        ],
        'NOT_INITIALIZED': [
            r'not\s+initialized', r'not\s+been\s+populated', r'not\s+handled\s+yet',
            r'instance.*not\s+initialized'
        ],
        'STATE_NOT_FOUND': [
            r'state\s+not\s+found', r'no.*member\s+state\s+found', r'state.*missing'
        ],
        'DNS_ERROR': [
            r'getaddrinfo\s+fail', r'name.*service.*not\s+known', r'dns.*fail'
        ],
        'COMMAND_ERROR': [
            r'exited\s+with\s+status', r'command.*fail', r'exit\s+code'
        ],
        'DISK_ERROR': [
            r'failed\s+to\s+check\s+disk', r'disk.*error', r'disk.*fail'
        ],
        'INVALID_NAME': [
            r'bucket\s+name\s+can\s+only\s+contain', r'invalid.*name', r'illegal.*name'
        ],
        'NOT_READY': [
            r'not\s+yet.*ready', r'not\s+in\s+a\s+running\s+state', r'not\s+ready'
        ],
        'RAFT_ERROR': [
            r'failed\s+to\s+get\s+raft', r'raft.*error', r'raft.*fail', r'illegal\s+state'
        ],
    }
    
    # Timestamp patterns commonly found in Nutanix logs
    TIMESTAMP_PATTERNS = [
        # Google glog format: E20260107 18:56:50.225841Z (yyyymmdd hh:mm:ss)
        r'[IWEF](\d{8})\s+(\d{2}:\d{2}:\d{2})',
        # ISO format: 2026-01-27T14:30:45.123Z
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)',
        # Standard format: 2026-01-27 14:30:45
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
        # Syslog format: Jan 27 14:30:45
        r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        # Epoch in brackets: [1706363445]
        r'\[(\d{10,13})\]',
    ]
    
    def __init__(self, max_message_length: int = 500, max_stack_trace_length: int = 1000):
        self.max_message_length = max_message_length
        self.max_stack_trace_length = max_stack_trace_length
        
        # Compile patterns for efficiency
        self._severity_compiled = {
            sev: [re.compile(p, re.IGNORECASE) for p in patterns]
            for sev, patterns in self.SEVERITY_PATTERNS.items()
        }
        self._event_type_compiled = {
            evt: [re.compile(p, re.IGNORECASE) for p in patterns]
            for evt, patterns in self.EVENT_TYPE_PATTERNS.items()
        }
        self._timestamp_compiled = [re.compile(p) for p in self.TIMESTAMP_PATTERNS]
    
    def parse_archive(
        self,
        archive_path: str,
        s3_url: str,
        severity_filter: List[str] = None
    ) -> Iterator[LogEvent]:
        """
        Parse a logbay archive and yield log events.
        
        Args:
            archive_path: Local path to the .tar.gz archive
            s3_url: S3 URL where the archive is stored (for reference)
            severity_filter: List of severities to include (default: ERROR, WARN, FATAL)
        
        Yields:
            LogEvent objects for matching log lines
        """
        if severity_filter is None:
            severity_filter = ['ERROR', 'FATAL']  # Only errors and fatals, not warnings
        
        severity_filter = [s.upper() for s in severity_filter]
        
        try:
            with tarfile.open(archive_path, 'r:gz') as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    
                    # Check if this is a log file we care about
                    pod, log_type = self._identify_log_file(member.name)
                    if pod is None:
                        continue
                    
                    # Extract and parse the file
                    try:
                        f = tar.extractfile(member)
                        if f is None:
                            continue
                        
                        content = f.read()
                        
                        # Handle gzipped files within the archive
                        if member.name.endswith('.gz'):
                            try:
                                content = gzip.decompress(content)
                            except:
                                pass
                        
                        # Decode content
                        try:
                            text = content.decode('utf-8', errors='replace')
                        except:
                            text = content.decode('latin-1', errors='replace')
                        
                        # Parse lines
                        for event in self._parse_log_content(
                            text, pod, member.name, s3_url, severity_filter
                        ):
                            yield event
                            
                    except Exception as e:
                        print(f"Error parsing {member.name}: {e}")
                        continue
                        
        except Exception as e:
            print(f"Error opening archive {archive_path}: {e}")
            raise
    
    def _identify_log_file(self, filepath: str) -> Tuple[Optional[str], Optional[str]]:
        """Identify the pod and log type from a file path"""
        filename = os.path.basename(filepath).lower()
        filepath_lower = filepath.lower()
        
        # First, check if the file has severity in name (common Nutanix pattern)
        # Only process ERROR and FATAL files
        has_error_severity = any(sev in filename for sev in ['.error.', '.fatal.'])
        
        # FIRST: Identify component from directory path (most reliable)
        # This prevents misidentification (e.g., poseidon_atlas being tagged as OC)
        component_from_path = None
        if '/atlas/' in filepath_lower:
            component_from_path = 'Atlas'
        elif '/ms/' in filepath_lower:
            component_from_path = 'MS'
        elif '/oc/' in filepath_lower:
            component_from_path = 'OC'
        elif '/zookeeper/' in filepath_lower:
            component_from_path = 'Zookeeper'
        elif '/bucketstools/' in filepath_lower:
            component_from_path = 'Buckets'
        elif '/objectsbrowser/' in filepath_lower:
            component_from_path = 'ObjectsBrowser'
        
        # If we identified component from path and file has error severity, return it
        if component_from_path and has_error_severity:
            return component_from_path, 'error_file'
        
        # SECOND: Check filename patterns for .ERROR or .FATAL files
        if has_error_severity:
            # Use path-based component if available
            if component_from_path:
                return component_from_path, 'error_file'
            # Otherwise try to identify from filename
            for pod, patterns in self.LOG_FILE_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in filename:
                        return pod, pattern
            return 'Unknown', 'error_file'
        
        # THIRD: Check for explicit log files (*.log, *.ERROR, *.FATAL)
        if filename.endswith('.error') or filename.endswith('.fatal'):
            return component_from_path or 'Unknown', 'severity_file'
        
        # FOURTH: Process .out files which often contain important logs
        if filename.endswith('.out') and component_from_path:
            return component_from_path, 'out_file'
        
        return None, None
    
    def _parse_log_content(
        self,
        content: str,
        pod: str,
        file_path: str,
        s3_url: str,
        severity_filter: List[str]
    ) -> Iterator[LogEvent]:
        """Parse log file content and yield matching events"""
        
        lines = content.split('\n')
        current_event = None
        stack_trace_lines = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Detect severity
            severity = self._detect_severity(line)
            
            # Check if this is a new log entry or continuation (stack trace)
            is_new_entry = self._is_new_log_entry(line)
            
            if is_new_entry:
                # Yield previous event if exists
                if current_event and current_event.severity in severity_filter:
                    if stack_trace_lines:
                        current_event.stack_trace = '\n'.join(stack_trace_lines)[:self.max_stack_trace_length]
                    yield current_event
                
                # Start new event
                if severity in severity_filter:
                    timestamp = self._extract_timestamp(line)
                    event_type = self._detect_event_type(line)
                    node_name = self._extract_node_name(line, file_path)
                    bucket_name = self._extract_bucket_name(line)
                    
                    current_event = LogEvent(
                        timestamp=timestamp,
                        pod=pod,
                        node_name=node_name,
                        bucket_name=bucket_name,
                        severity=severity,
                        event_type=event_type,
                        message=line[:self.max_message_length],
                        raw_log_file=s3_url,
                        raw_file_path=file_path,
                        raw_line_number=line_num
                    )
                    stack_trace_lines = []
                else:
                    current_event = None
                    stack_trace_lines = []
            else:
                # Continuation line (possibly stack trace)
                if current_event and len(stack_trace_lines) < 50:
                    stack_trace_lines.append(line)
        
        # Yield last event
        if current_event and current_event.severity in severity_filter:
            if stack_trace_lines:
                current_event.stack_trace = '\n'.join(stack_trace_lines)[:self.max_stack_trace_length]
            yield current_event
    
    def _detect_severity(self, line: str) -> str:
        """Detect log severity from a line"""
        # Google glog format: first char is severity (I, W, E, F)
        if re.match(r'^[IWEF]\d{8}\s', line):
            first_char = line[0]
            if first_char == 'F':
                return 'FATAL'
            elif first_char == 'E':
                return 'ERROR'
            elif first_char == 'W':
                return 'WARN'
            else:
                return 'INFO'
        
        # Standard severity patterns
        for severity in ['FATAL', 'ERROR', 'WARN', 'INFO']:
            for pattern in self._severity_compiled[severity]:
                if pattern.search(line):
                    return severity
        return 'INFO'
    
    def _detect_event_type(self, line: str) -> Optional[str]:
        """Detect event type from a line"""
        line_lower = line.lower()
        for event_type, patterns in self._event_type_compiled.items():
            for pattern in patterns:
                if pattern.search(line_lower):
                    return event_type
        return None
    
    def _extract_timestamp(self, line: str) -> int:
        """Extract timestamp from a log line, return as epoch seconds"""
        # Google glog format: E20260107 18:56:50.225841Z
        glog_match = re.match(r'^[IWEF](\d{4})(\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', line)
        if glog_match:
            try:
                year, month, day = glog_match.group(1), glog_match.group(2), glog_match.group(3)
                hour, minute, second = glog_match.group(4), glog_match.group(5), glog_match.group(6)
                dt = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
                return int(dt.timestamp())
            except:
                pass
        
        for pattern in self._timestamp_compiled:
            match = pattern.search(line)
            if match:
                ts_str = match.group(1)
                
                # Try to parse the timestamp
                try:
                    # Already epoch
                    if ts_str.isdigit():
                        ts = int(ts_str)
                        # Convert milliseconds to seconds if needed
                        if ts > 10000000000:
                            ts = ts // 1000
                        return ts
                    
                    # ISO format
                    if 'T' in ts_str:
                        ts_str = ts_str.replace('Z', '+00:00')
                        dt = datetime.fromisoformat(ts_str.replace('Z', ''))
                        return int(dt.timestamp())
                    
                    # Standard format
                    dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                    return int(dt.timestamp())
                    
                except:
                    continue
        
        # Default to current time if no timestamp found
        return int(datetime.now().timestamp())
    
    def _is_new_log_entry(self, line: str) -> bool:
        """Check if a line is the start of a new log entry"""
        # Google glog format: E20260107 18:56:50 (starts with IWEF + 8 digit date)
        if re.match(r'^[IWEF]\d{8}\s', line):
            return True
        
        # Lines starting with timestamp or severity indicator
        for pattern in self._timestamp_compiled:
            if pattern.match(line):
                return True
        
        # Lines starting with common log prefixes
        if re.match(r'^[IWEF]\d{4}\s', line):  # Google-style short: I0127 14:30:45
            return True
        if re.match(r'^\[\d{4}-\d{2}-\d{2}', line):  # [2026-01-27 ...
            return True
        if re.match(r'^\d{4}-\d{2}-\d{2}', line):  # 2026-01-27 ...
            return True
        
        return False
    
    def _extract_node_name(self, line: str, file_path: str = "") -> Optional[str]:
        """Extract node name from log line or file path"""
        # First try to extract from file path (most reliable)
        # Pattern: object-controller-0, poseidon-atlas-0, zk-1, metadata-service-0
        path_patterns = [
            r'(object-controller-\d+)',
            r'(poseidon-atlas-\d+)',
            r'(metadata-service-\d+)',
            r'(ms-server-\d+)',  # MS pods use ms-server-0 naming
            r'(zk-\d+)',
        ]
        for pattern in path_patterns:
            match = re.search(pattern, file_path, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Then try from line content
        line_patterns = [
            r'\b(object-controller-\d+)\b',
            r'\b(poseidon-atlas-\d+)\b',
            r'\b(metadata-service-\d+)\b',
            r'\b(ms-server-\d+)\b',  # MS pods
            r'\b(zk-\d+)\b',
            r'\b(node-\d+)\b',
            r'\b(atlas-\d+)\b',
            r'\b(ms-\d+)\b',
            r'\b(oc-\d+)\b',
        ]
        for pattern in line_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def _extract_bucket_name(self, line: str) -> Optional[str]:
        """Extract bucket name from log line"""
        # Pattern: bucket=xxx or bucket: xxx or "bucket_name" or bucket_id
        patterns = [
            r'bucket[=:]\s*["\']?([a-zA-Z0-9_-]+)["\']?',
            r'bucket_name[=:]\s*["\']?([a-zA-Z0-9_-]+)["\']?',
            r'bucket_id[=:]\s*["\']?([a-zA-Z0-9_-]+)["\']?',
            r'"bucket"\s*:\s*"([^"]+)"',
            r'Bucket:\s*([a-zA-Z0-9_-]+)',
            r'bucket\s+([a-zA-Z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    def _extract_object_store_uuid(self, line: str) -> Optional[str]:
        """Extract object store UUID from log line"""
        # UUID pattern
        uuid_pattern = r'object_store[_-]?(?:uuid|id)?[=:]\s*([a-f0-9-]{36})'
        match = re.search(uuid_pattern, line, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
