"""
Log Processor Service for NOVA Backend

Orchestrates log processing: downloads archives from S3, parses them,
and stores event metadata in the database.
"""
import os
import time
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from .log_parser import LogParser, LogEvent
from ..config import load_config
from ..tools.sql_tools import execute_sql


class LogProcessor:
    """
    Processes log uploads: downloads from S3, parses, stores metadata.
    """
    
    def __init__(self):
        self.parser = LogParser()
        self.config = load_config()
    
    def _get_s3_client(self):
        """Get configured S3 client"""
        s3_config = self.config.get('s3', {})
        
        return boto3.client(
            's3',
            endpoint_url=s3_config.get('endpoint'),
            aws_access_key_id=s3_config.get('access_key'),
            aws_secret_access_key=s3_config.get('secret_key'),
            region_name=s3_config.get('region', 'us-east-1'),
            verify=False
        )
    
    def create_upload_record(
        self,
        s3_key: str,
        s3_url: str,
        cluster_name: str,
        period_start: int,
        period_end: int
    ) -> Optional[int]:
        """
        Create a log_uploads record and return the upload_id.
        """
        now = int(time.time())
        
        result = execute_sql(f"""
            INSERT INTO log_uploads 
            (s3_key, s3_url, cluster_name, period_start, period_end, status, uploaded_at)
            VALUES 
            ('{s3_key}', '{s3_url}', '{cluster_name}', {period_start}, {period_end}, 'PENDING', {now})
        """)
        
        # SQL agent returns {"type":"write","rows_affected":1} on success
        # or {"error":"..."} on failure
        if result.get('error') or result.get('status') == 'error':
            print(f"Error creating upload record: {result.get('error', result)}")
            return None
        
        # Get the last inserted ID by querying for max upload_id with matching s3_key
        # (last_insert_rowid doesn't work across separate HTTP requests)
        id_result = execute_sql(f"SELECT MAX(upload_id) FROM log_uploads WHERE s3_key = '{s3_key}'")
        if id_result.get('rows'):
            row = id_result['rows'][0]
            if isinstance(row, dict):
                return list(row.values())[0]
            return row[0]
        
        return None
    
    def update_upload_status(
        self,
        upload_id: int,
        status: str,
        stats: Dict[str, int] = None,
        error_message: str = None
    ):
        """Update the status of a log upload record"""
        now = int(time.time())
        
        updates = [f"status='{status}'", f"processed_at={now}"]
        
        if stats:
            if 'total_files' in stats:
                updates.append(f"total_files={stats['total_files']}")
            if 'total_lines' in stats:
                updates.append(f"total_lines={stats['total_lines']}")
            if 'errors_found' in stats:
                updates.append(f"errors_found={stats['errors_found']}")
            if 'warnings_found' in stats:
                updates.append(f"warnings_found={stats['warnings_found']}")
            if 'fatals_found' in stats:
                updates.append(f"fatals_found={stats['fatals_found']}")
        
        if error_message:
            # Escape single quotes
            error_message = error_message.replace("'", "''")
            updates.append(f"error_message='{error_message}'")
        
        sql = f"UPDATE log_uploads SET {', '.join(updates)} WHERE upload_id={upload_id}"
        execute_sql(sql)
    
    def store_log_event(self, event: LogEvent, upload_id: int) -> bool:
        """Store a log event in the database"""
        # Escape single quotes in text fields
        message = event.message.replace("'", "''") if event.message else ""
        stack_trace = event.stack_trace.replace("'", "''") if event.stack_trace else None
        raw_file_path = event.raw_file_path.replace("'", "''") if event.raw_file_path else ""
        raw_log_file = event.raw_log_file.replace("'", "''") if event.raw_log_file else ""
        
        now = int(time.time())
        
        # Build INSERT statement
        columns = [
            'timestamp', 'pod', 'severity', 'message',
            'raw_log_file', 'raw_file_path', 'raw_line_number',
            'upload_id', 'ingested_at'
        ]
        values = [
            str(event.timestamp),
            f"'{event.pod}'",
            f"'{event.severity}'",
            f"'{message}'",
            f"'{raw_log_file}'",
            f"'{raw_file_path}'",
            str(event.raw_line_number),
            str(upload_id),
            str(now)
        ]
        
        # Optional fields
        if event.node_name:
            columns.append('node_name')
            values.append(f"'{event.node_name}'")
        
        if event.object_store_uuid:
            columns.append('object_store_uuid')
            values.append(f"'{event.object_store_uuid}'")
        
        if event.object_store_name:
            columns.append('object_store_name')
            values.append(f"'{event.object_store_name}'")
        
        if event.bucket_name:
            columns.append('bucket_name')
            values.append(f"'{event.bucket_name}'")
        
        if event.event_type:
            columns.append('event_type')
            values.append(f"'{event.event_type}'")
        
        if stack_trace:
            columns.append('stack_trace')
            values.append(f"'{stack_trace}'")
        
        sql = f"INSERT INTO logs ({', '.join(columns)}) VALUES ({', '.join(values)})"
        result = execute_sql(sql)
        
        return result.get('status') != 'error'
    
    def process_upload(
        self,
        upload_id: int,
        s3_key: str,
        s3_url: str,
        object_store_name: str = None,
        severity_filter: List[str] = None
    ) -> Dict[str, Any]:
        """
        Process a log upload: download, parse, store.
        
        Args:
            upload_id: The log_uploads record ID
            s3_key: S3 key of the archive
            s3_url: Full S3 URL
            object_store_name: Name of the object store (for context)
            severity_filter: Severities to include
        
        Returns:
            Processing statistics
        """
        if severity_filter is None:
            log_config = self.config.get('log_analysis', {})
            severity_filter = log_config.get('severity_filter', ['ERROR', 'WARN', 'FATAL'])
        
        stats = {
            'total_files': 0,
            'total_lines': 0,
            'errors_found': 0,
            'warnings_found': 0,
            'fatals_found': 0,
            'events_stored': 0
        }
        
        try:
            # Update status to PROCESSING
            self.update_upload_status(upload_id, 'PROCESSING')
            
            # Get bucket name from config
            log_config = self.config.get('log_analysis', {})
            bucket_name = log_config.get('logs_bucket', 'nova-logs')
            
            # Download archive from S3
            s3 = self._get_s3_client()
            
            with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                print(f"Downloading {s3_key} from bucket {bucket_name}...")
                s3.download_file(bucket_name, s3_key, tmp_path)
                
                # Parse the archive
                print(f"Parsing archive...")
                for event in self.parser.parse_archive(tmp_path, s3_url, severity_filter):
                    # Add object store context
                    if object_store_name:
                        event.object_store_name = object_store_name
                    
                    # Store the event
                    if self.store_log_event(event, upload_id):
                        stats['events_stored'] += 1
                        
                        # Count by severity
                        if event.severity == 'ERROR':
                            stats['errors_found'] += 1
                        elif event.severity == 'WARN':
                            stats['warnings_found'] += 1
                        elif event.severity == 'FATAL':
                            stats['fatals_found'] += 1
                
                # Update with final stats
                self.update_upload_status(upload_id, 'COMPLETED', stats)
                print(f"Processing complete: {stats}")
                
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            
            return stats
            
        except ClientError as e:
            error_msg = f"S3 error: {str(e)}"
            print(error_msg)
            self.update_upload_status(upload_id, 'FAILED', error_message=error_msg)
            return {'error': error_msg}
            
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            print(error_msg)
            self.update_upload_status(upload_id, 'FAILED', error_message=error_msg)
            return {'error': error_msg}
    
    def get_upload_status(self, upload_id: int) -> Optional[Dict[str, Any]]:
        """Get the status of a log upload"""
        result = execute_sql(f"SELECT * FROM log_uploads WHERE upload_id={upload_id}")
        
        if result.get('status') == 'error' or not result.get('rows'):
            return None
        
        row = result['rows'][0]
        if isinstance(row, dict):
            return row
        
        # Convert list to dict based on column order
        columns = [
            'upload_id', 's3_key', 's3_url', 'cluster_name',
            'period_start', 'period_end', 'total_files', 'total_lines',
            'errors_found', 'warnings_found', 'fatals_found',
            'status', 'error_message', 'uploaded_at', 'processed_at'
        ]
        return dict(zip(columns, row))
    
    def list_uploads(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent log uploads"""
        result = execute_sql(f"""
            SELECT * FROM log_uploads 
            ORDER BY uploaded_at DESC 
            LIMIT {limit}
        """)
        
        if result.get('status') == 'error':
            return []
        
        uploads = []
        for row in result.get('rows', []):
            if isinstance(row, dict):
                uploads.append(row)
            else:
                columns = [
                    'upload_id', 's3_key', 's3_url', 'cluster_name',
                    'period_start', 'period_end', 'total_files', 'total_lines',
                    'errors_found', 'warnings_found', 'fatals_found',
                    'status', 'error_message', 'uploaded_at', 'processed_at'
                ]
                uploads.append(dict(zip(columns, row)))
        
        return uploads


# Singleton instance
_processor: Optional[LogProcessor] = None


def get_log_processor() -> LogProcessor:
    """Get or create the log processor instance"""
    global _processor
    if _processor is None:
        _processor = LogProcessor()
    return _processor
