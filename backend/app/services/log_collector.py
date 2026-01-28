"""
Log Collector Service for NOVA Backend

Automatically collects logs from Nutanix Object Store clusters discovered
via Prism Central and uploads them to S3 for analysis.

Uses the recommended approach:
1. SSH to Prism Central VM
2. Use 'mspctl cls ssh <cluster_name>' to access object store cluster
3. Use 'allssh' to collect logs from all nodes
"""
import os
import subprocess
import tempfile
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
import shutil

try:
    import boto3
    from botocore.exceptions import ClientError
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from ..config import (
    get_s3_endpoint, get_s3_access_key, get_s3_secret_key, get_s3_region,
    get_logs_bucket, get_collection_interval_hours, is_auto_collect_enabled,
    get_cluster_username, get_cluster_password, get_initial_delay_minutes,
    get_pods_to_scan, get_pc_ip
)
from ..tools.prism_tools import get_object_store_clusters
from ..logging_config import get_collector_logger

logger = get_collector_logger()


class LogCollector:
    """
    Automated log collector for Nutanix Object Store clusters.
    
    Uses mspctl cls ssh to access object store clusters through Prism Central,
    then uses allssh to collect logs from all nodes.
    """
    
    # Full path to mspctl on PCVM (not in default PATH)
    MSPCTL = "/usr/local/nutanix/cluster/bin/mspctl"
    
    def __init__(self):
        self.enabled = is_auto_collect_enabled()
        self.interval_hours = get_collection_interval_hours()
        self.initial_delay_minutes = get_initial_delay_minutes()
        self.cluster_user = get_cluster_username()
        self.cluster_password = get_cluster_password()
        self.logs_bucket = get_logs_bucket()
        self.pods_to_scan = get_pods_to_scan()
        self.prism_ip = get_pc_ip()
        self._running = False
        self._last_collection = {}
        
        # Check for sshpass availability
        self.has_sshpass = self._check_sshpass()
        
    def _check_sshpass(self) -> bool:
        """Check if sshpass is available for password-based SSH"""
        try:
            result = subprocess.run(
                ["which", "sshpass"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def _get_s3_client(self):
        """Get boto3 S3 client"""
        if not HAS_BOTO3:
            raise RuntimeError("boto3 not installed")
        
        return boto3.client(
            's3',
            endpoint_url=get_s3_endpoint(),
            aws_access_key_id=get_s3_access_key(),
            aws_secret_access_key=get_s3_secret_key(),
            region_name=get_s3_region(),
            verify=False
        )
    
    def _run_prism_ssh_command(self, command: str, timeout: int = 300) -> tuple:
        """
        Run a command on Prism Central VM via SSH.
        
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if not self.has_sshpass:
            return -1, "", "sshpass not available"
        
        ssh_cmd = [
            "sshpass", "-p", self.cluster_password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=30",
            "-o", "ServerAliveInterval=60",
            f"{self.cluster_user}@{self.prism_ip}",
            command
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)
    
    def _scp_from_prism(self, remote_path: str, local_path: str, timeout: int = 300) -> bool:
        """Copy a file from Prism Central via SSH + cat (SCP/SFTP not supported on PCVM)"""
        if not self.has_sshpass:
            return False
        
        # Use ssh + cat instead of scp since PCVM doesn't support sftp subsystem
        ssh_cmd = [
            "sshpass", "-p", self.cluster_password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=30",
            f"{self.cluster_user}@{self.prism_ip}",
            f"cat {remote_path}"
        ]
        
        try:
            with open(local_path, 'wb') as f:
                result = subprocess.run(
                    ssh_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=timeout
                )
            return result.returncode == 0 and os.path.getsize(local_path) > 0
        except Exception as e:
            print(f"⚠️ Download error: {e}")
            return False
    
    def _get_msp_cluster_name(self, object_store_name: str) -> Optional[str]:
        """
        Get the MSP cluster name for an object store.
        Uses 'mspctl cls ls' on Prism Central to find the cluster.
        """
        print(f"🔍 Looking up MSP cluster name for {object_store_name}...")
        
        rc, stdout, stderr = self._run_prism_ssh_command(f"{self.MSPCTL} cls ls", timeout=60)
        
        if rc != 0:
            print(f"❌ Failed to list MSP clusters: {stderr}")
            return None
        
        # Parse the output to find the cluster
        # mspctl cls ls output format varies, look for the object store name
        lines = stdout.strip().split('\n')
        for line in lines:
            # Look for lines containing the object store name
            if object_store_name.lower() in line.lower():
                # Extract the cluster name (usually first column)
                parts = line.split()
                if parts:
                    cluster_name = parts[0]
                    print(f"✅ Found MSP cluster: {cluster_name}")
                    return cluster_name
        
        # If exact match not found, try to find any objects cluster
        for line in lines:
            if 'object' in line.lower() or 'oss' in line.lower():
                parts = line.split()
                if parts:
                    cluster_name = parts[0]
                    print(f"✅ Found MSP cluster (fuzzy match): {cluster_name}")
                    return cluster_name
        
        print(f"⚠️ Could not find MSP cluster for {object_store_name}")
        return None
    
    def collect_logs_from_cluster(
        self,
        object_store_name: str,
        object_store_uuid: str = None,
        hours: int = 1
    ) -> Optional[str]:
        """
        Collect logs from an object store cluster using mspctl and allssh.
        
        This method:
        1. SSHs to Prism Central
        2. Uses 'mspctl cls ssh <cluster>' to access the object store
        3. Uses 'allssh' to collect logs from all nodes
        4. Creates and downloads a tar archive
        
        Args:
            object_store_name: Name of the object store
            object_store_uuid: UUID of the object store (optional)
            hours: Hours of logs to collect
            
        Returns:
            Path to local archive file, or None if failed
        """
        if not self.has_sshpass:
            print(f"⚠️ sshpass not available, cannot collect logs")
            return None
        
        if not self.prism_ip:
            print(f"❌ Prism Central IP not configured")
            return None
        
        # Get MSP cluster name
        msp_cluster = self._get_msp_cluster_name(object_store_name)
        if not msp_cluster:
            print(f"⚠️ Could not find MSP cluster, trying with object store name...")
            msp_cluster = object_store_name
        
        # Create temp directory for this collection
        temp_dir = tempfile.mkdtemp(prefix=f"nova_logs_{object_store_name}_")
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        archive_name = f"{object_store_name}-{timestamp}.tar.gz"
        local_archive = os.path.join(temp_dir, archive_name)
        # Use home directory on PCVM instead of /tmp (which is only 238MB)
        remote_archive = f"/home/nutanix/{archive_name}"
        
        print(f"📦 Collecting logs from {object_store_name} via mspctl...")
        
        # Object store logs are in /var/log/ctrlog/default/
        # Components: oc (Object Controller), ms (Metadata Service), atlas, zookeeper, etc.
        log_dirs = [
            "/var/log/ctrlog/default/oc",
            "/var/log/ctrlog/default/ms", 
            "/var/log/ctrlog/default/atlas",
            "/var/log/ctrlog/default/zookeeper",
            "/var/log/ctrlog/default/bucketstools"
        ]
        log_dirs_str = " ".join(log_dirs)
        
        print(f"🔗 Connecting to {msp_cluster} via Prism Central...")
        
        # Create tar archive of logs on the object store node
        # Logs are in /var/log/ctrlog/default/<component>/
        tar_cmd = f"tar -czf /tmp/nova_logs_{timestamp}.tar.gz {log_dirs_str} 2>/dev/null"
        
        print(f"📥 Creating log archive on object store node...")
        rc, stdout, stderr = self._run_prism_ssh_command(
            f'{self.MSPCTL} cls ssh {msp_cluster} --cmd "{tar_cmd}"',
            timeout=300
        )
        
        # Check if archive was created
        check_cmd = f'{self.MSPCTL} cls ssh {msp_cluster} --cmd "ls -la /tmp/nova_logs_{timestamp}.tar.gz"'
        rc, stdout, stderr = self._run_prism_ssh_command(check_cmd, timeout=30)
        
        if "nova_logs_" not in stdout:
            print(f"⚠️ Archive not created on node: {stderr[:200]}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        print(f"✅ Archive created on node")
        
        # Copy archive from object store node to PCVM using cat + redirect
        # Must wrap in bash -c to get proper redirect behavior
        print(f"📥 Copying archive to PCVM...")
        copy_cmd = f'bash -c "{self.MSPCTL} cls ssh {msp_cluster} --cmd \\"cat /tmp/nova_logs_{timestamp}.tar.gz\\" > {remote_archive} 2>/dev/null"'
        rc, stdout, stderr = self._run_prism_ssh_command(copy_cmd, timeout=600)
        
        # Cleanup temp file on object store node
        cleanup_cmd = f'{self.MSPCTL} cls ssh {msp_cluster} --cmd "rm -f /tmp/nova_logs_{timestamp}.tar.gz"'
        self._run_prism_ssh_command(cleanup_cmd, timeout=30)
        
        # Check if archive exists on Prism
        check_cmd = f"ls -la {remote_archive} 2>/dev/null"
        rc, stdout, stderr = self._run_prism_ssh_command(check_cmd, timeout=30)
        
        if rc != 0 or remote_archive not in stdout:
            print(f"❌ No logs archive found on Prism Central")
            print(f"   stdout: {stdout[:200]}")
            print(f"   stderr: {stderr[:200]}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        # Download the archive from Prism Central
        print(f"📥 Downloading log archive from Prism Central...")
        if not self._scp_from_prism(remote_archive, local_archive):
            print(f"❌ Failed to download archive from Prism Central")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        # Clean up remote archive on Prism
        self._run_prism_ssh_command(f"rm -f {remote_archive}", timeout=30)
        
        # Verify local file exists and has content
        if not os.path.exists(local_archive) or os.path.getsize(local_archive) < 100:
            print(f"❌ Archive is empty or missing")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        # Strip mspctl header from the file (it adds "======= IP =======" before content)
        # The gzip magic bytes are \x1f\x8b
        self._strip_mspctl_header(local_archive)
        
        print(f"✅ Collected logs from {object_store_name}: {os.path.getsize(local_archive)} bytes")
        return local_archive
    
    def _strip_mspctl_header(self, filepath: str) -> bool:
        """
        Strip mspctl SSH header from file if present.
        mspctl adds '================== IP ==================\n' before command output.
        """
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            
            # Find gzip magic bytes (\x1f\x8b)
            gzip_start = data.find(b'\x1f\x8b')
            
            if gzip_start == -1:
                print(f"⚠️ No gzip content found in file")
                return False
            
            if gzip_start > 0:
                print(f"🔧 Stripping {gzip_start} bytes of mspctl header")
                with open(filepath, 'wb') as f:
                    f.write(data[gzip_start:])
            
            return True
        except Exception as e:
            print(f"⚠️ Error stripping header: {e}")
            return False
    
    def upload_to_s3(self, local_path: str, object_store_name: str) -> Optional[Dict]:
        """
        Upload log archive to S3.
        
        Returns:
            Dict with s3_key and s3_url, or None if failed
        """
        if not HAS_BOTO3:
            print("❌ boto3 not available for S3 upload")
            return None
        
        try:
            s3 = self._get_s3_client()
            
            # Generate S3 key with date hierarchy
            now = datetime.now()
            filename = os.path.basename(local_path)
            s3_key = f"logs/{object_store_name}/{now.strftime('%Y/%m/%d/%H')}/{filename}"
            
            print(f"📤 Uploading to S3: {self.logs_bucket}/{s3_key}...")
            
            # Ensure bucket exists
            try:
                s3.head_bucket(Bucket=self.logs_bucket)
            except ClientError:
                print(f"📁 Creating bucket: {self.logs_bucket}")
                s3.create_bucket(Bucket=self.logs_bucket)
            
            # Upload
            s3.upload_file(local_path, self.logs_bucket, s3_key)
            
            # Construct full HTTP URL with S3 endpoint
            endpoint = get_s3_endpoint().rstrip('/')
            s3_url = f"{endpoint}/{self.logs_bucket}/{s3_key}"
            print(f"✅ Uploaded: {s3_url}")
            
            return {
                "s3_key": s3_key,
                "s3_url": s3_url
            }
            
        except Exception as e:
            print(f"❌ S3 upload failed: {e}")
            return None
    
    async def trigger_processing(
        self,
        s3_key: str,
        s3_url: str,
        cluster_name: str,
        hours: int = 1
    ) -> Optional[int]:
        """
        Trigger NOVA to process the uploaded logs.
        
        This calls the log processor directly instead of via HTTP.
        
        Returns:
            upload_id if successful, None otherwise
        """
        try:
            from .log_processor import LogProcessor
            
            processor = LogProcessor()
            now = int(time.time())
            
            upload_id = processor.create_upload_record(
                s3_key=s3_key,
                s3_url=s3_url,
                cluster_name=cluster_name,
                period_start=now - (hours * 3600),
                period_end=now
            )
            
            if upload_id:
                # Process in background - process_upload is not async, run in executor
                import concurrent.futures
                loop = asyncio.get_event_loop()
                loop.run_in_executor(
                    None,
                    processor.process_upload,
                    upload_id,
                    s3_key,
                    s3_url,
                    cluster_name
                )
                print(f"✅ Processing triggered: upload_id={upload_id}")
                return upload_id
            else:
                print("❌ Failed to create upload record")
                return None
                
        except Exception as e:
            print(f"❌ Error triggering processing: {e}")
            return None
    
    async def collect_from_all_clusters(self, hours: int = 1) -> Dict:
        """
        Discover and collect logs from all object store clusters.
        
        Uses mspctl cls ssh via Prism Central to access clusters.
        
        Returns:
            Summary of collection results
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "clusters_discovered": 0,
            "clusters_collected": 0,
            "clusters_failed": 0,
            "total_uploads": 0,
            "details": []
        }
        
        if not self.enabled:
            print("⏸️ Log collection is disabled")
            results["message"] = "Log collection disabled"
            return results
        
        if not self.has_sshpass:
            print("⚠️ sshpass not available - install it for automated log collection")
            results["message"] = "sshpass not installed"
            return results
        
        if not self.prism_ip:
            print("❌ Prism Central IP not configured")
            results["message"] = "Prism Central IP not configured"
            return results
        
        # Discover clusters from Prism Central
        print("🔍 Discovering object store clusters from Prism Central...")
        clusters_result = get_object_store_clusters()
        
        if not clusters_result.get("success"):
            print(f"❌ Failed to discover clusters: {clusters_result.get('message')}")
            results["message"] = clusters_result.get("message")
            return results
        
        clusters = clusters_result.get("clusters", [])
        results["clusters_discovered"] = len(clusters)
        
        if not clusters:
            print("⚠️ No active object store clusters found")
            results["message"] = "No clusters found"
            return results
        
        print(f"📊 Found {len(clusters)} active object store cluster(s)")
        print(f"🔗 Will use Prism Central ({self.prism_ip}) with mspctl for log collection")
        
        # Collect from each cluster using mspctl
        for cluster in clusters:
            object_store_name = cluster.get("object_store_name", "unknown")
            object_store_uuid = cluster.get("object_store_uuid")
            
            detail = {
                "object_store": object_store_name,
                "method": "mspctl_ssh",
                "status": "pending"
            }
            
            # Check if we've already collected this hour for this cluster
            current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
            current_hour_epoch = int(current_hour.timestamp())
            
            # First check in-memory cache
            last_collection = self._last_collection.get(object_store_name)
            if last_collection and last_collection >= current_hour:
                logger.info(f"⏭️ Skipping {object_store_name} - already collected this hour (memory)")
                print(f"⏭️ Skipping {object_store_name} - already collected at {last_collection.strftime('%H:%M')}")
                detail["status"] = "skipped"
                detail["reason"] = "Already collected this hour"
                results["details"].append(detail)
                continue
            
            # Also check database for persistence across restarts
            try:
                from ..tools.sql_tools import execute_sql
                check_result = execute_sql(
                    f"SELECT upload_id FROM log_uploads WHERE cluster_name = '{object_store_name}' "
                    f"AND uploaded_at >= {current_hour_epoch} LIMIT 1"
                )
                if check_result.get("rows") and len(check_result["rows"]) > 0:
                    logger.info(f"⏭️ Skipping {object_store_name} - already collected this hour (DB)")
                    print(f"⏭️ Skipping {object_store_name} - already collected this hour (found in DB)")
                    detail["status"] = "skipped"
                    detail["reason"] = "Already collected this hour (DB check)"
                    results["details"].append(detail)
                    # Update memory cache
                    self._last_collection[object_store_name] = datetime.now()
                    continue
            except Exception as e:
                logger.warning(f"Could not check DB for prior collection: {e}")
            
            try:
                # Collect logs via mspctl cls ssh
                local_archive = self.collect_logs_from_cluster(
                    object_store_name=object_store_name,
                    object_store_uuid=object_store_uuid,
                    hours=hours
                )
                
                if not local_archive:
                    detail["status"] = "failed"
                    detail["error"] = "Collection failed"
                    results["clusters_failed"] += 1
                    results["details"].append(detail)
                    continue
                
                # Upload to S3
                upload_result = self.upload_to_s3(local_archive, object_store_name)
                
                # Clean up local file
                temp_dir = os.path.dirname(local_archive)
                shutil.rmtree(temp_dir, ignore_errors=True)
                
                if not upload_result:
                    detail["status"] = "failed"
                    detail["error"] = "S3 upload failed"
                    results["clusters_failed"] += 1
                    results["details"].append(detail)
                    continue
                
                # Trigger processing
                upload_id = await self.trigger_processing(
                    upload_result["s3_key"],
                    upload_result["s3_url"],
                    object_store_name,
                    hours
                )
                
                detail["status"] = "success"
                detail["s3_url"] = upload_result["s3_url"]
                detail["upload_id"] = upload_id
                results["clusters_collected"] += 1
                results["total_uploads"] += 1
                
                # Update last collection time
                self._last_collection[object_store_name] = datetime.now()
                
            except Exception as e:
                detail["status"] = "failed"
                detail["error"] = str(e)
                results["clusters_failed"] += 1
            
            results["details"].append(detail)
        
        print(f"\n📊 Collection Summary:")
        print(f"   Discovered: {results['clusters_discovered']}")
        print(f"   Collected:  {results['clusters_collected']}")
        print(f"   Failed:     {results['clusters_failed']}")
        
        return results
    
    def get_status(self) -> Dict:
        """Get current collector status"""
        return {
            "enabled": self.enabled,
            "running": self._running,
            "has_sshpass": self.has_sshpass,
            "has_boto3": HAS_BOTO3,
            "prism_ip": self.prism_ip,
            "collection_method": "mspctl_ssh",
            "interval_hours": self.interval_hours,
            "logs_bucket": self.logs_bucket,
            "last_collections": {
                name: ts.isoformat() 
                for name, ts in self._last_collection.items()
            }
        }


# Global collector instance
_collector: Optional[LogCollector] = None


def get_log_collector() -> LogCollector:
    """Get or create the global LogCollector instance"""
    global _collector
    if _collector is None:
        _collector = LogCollector()
    return _collector


async def run_log_collection(hours: int = 1) -> Dict:
    """Run a single log collection cycle"""
    collector = get_log_collector()
    return await collector.collect_from_all_clusters(hours)
