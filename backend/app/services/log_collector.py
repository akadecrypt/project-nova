"""
Log Collector Service for NOVA Backend

Automatically collects logs from Nutanix Object Store clusters discovered
via Prism Central and uploads them to S3 for analysis.
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
    get_pods_to_scan
)
from ..tools.prism_tools import get_object_store_clusters


class LogCollector:
    """
    Automated log collector for Nutanix Object Store clusters.
    
    Discovers clusters from Prism Central, collects logs via SSH,
    uploads to S3, and triggers NOVA processing.
    """
    
    def __init__(self):
        self.enabled = is_auto_collect_enabled()
        self.interval_hours = get_collection_interval_hours()
        self.initial_delay_minutes = get_initial_delay_minutes()
        self.cluster_user = get_cluster_username()
        self.cluster_password = get_cluster_password()
        self.logs_bucket = get_logs_bucket()
        self.pods_to_scan = get_pods_to_scan()
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
    
    def _run_ssh_command(self, host: str, command: str, timeout: int = 300) -> tuple:
        """
        Run a command on a remote host via SSH.
        
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if not self.has_sshpass:
            return -1, "", "sshpass not available"
        
        ssh_cmd = [
            "sshpass", "-p", self.cluster_password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.cluster_user}@{host}",
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
    
    def _scp_file(self, host: str, remote_path: str, local_path: str, timeout: int = 300) -> bool:
        """Copy a file from remote host via SCP"""
        if not self.has_sshpass:
            return False
        
        scp_cmd = [
            "sshpass", "-p", self.cluster_password,
            "scp", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{self.cluster_user}@{host}:{remote_path}",
            local_path
        ]
        
        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0
        except:
            return False
    
    def collect_logs_from_cluster(
        self,
        cluster_ip: str,
        object_store_name: str,
        hours: int = 1
    ) -> Optional[str]:
        """
        Collect logs from a single cluster.
        
        Args:
            cluster_ip: IP address of the cluster to collect from
            object_store_name: Name of the object store
            hours: Hours of logs to collect
            
        Returns:
            Path to local archive file, or None if failed
        """
        if not self.has_sshpass:
            print(f"⚠️ sshpass not available, cannot collect logs from {cluster_ip}")
            return None
        
        # Create temp directory for this collection
        temp_dir = tempfile.mkdtemp(prefix=f"nova_logs_{object_store_name}_")
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        archive_name = f"{object_store_name}-{cluster_ip}-{timestamp}.tar.gz"
        local_archive = os.path.join(temp_dir, archive_name)
        remote_archive = f"/tmp/{archive_name}"
        
        print(f"📦 Collecting logs from {object_store_name} ({cluster_ip})...")
        
        # Build log file patterns for tar
        log_patterns = []
        for pod in self.pods_to_scan:
            pod_lower = pod.lower()
            log_patterns.extend([
                f"data/logs/{pod_lower}*.log*",
                f"data/logs/{pod_lower.upper()}*.log*"
            ])
        
        patterns_str = " ".join(log_patterns)
        
        # Create archive of log files on the cluster
        collect_cmd = f"""
        cd /home/nutanix && tar -czf {remote_archive} \
            --ignore-failed-read \
            {patterns_str} \
            2>/dev/null || true
        """
        
        rc, stdout, stderr = self._run_ssh_command(cluster_ip, collect_cmd.strip(), timeout=600)
        
        if rc != 0 and "No such file" not in stderr:
            print(f"⚠️ Warning creating archive on {cluster_ip}: {stderr}")
        
        # Check if archive was created
        check_cmd = f"ls -la {remote_archive} 2>/dev/null"
        rc, stdout, stderr = self._run_ssh_command(cluster_ip, check_cmd, timeout=30)
        
        if rc != 0:
            print(f"❌ No logs found on {cluster_ip}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        # Download the archive
        print(f"📥 Downloading log archive from {cluster_ip}...")
        if not self._scp_file(cluster_ip, remote_archive, local_archive):
            print(f"❌ Failed to download archive from {cluster_ip}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        # Clean up remote archive
        self._run_ssh_command(cluster_ip, f"rm -f {remote_archive}", timeout=30)
        
        # Verify local file exists and has content
        if not os.path.exists(local_archive) or os.path.getsize(local_archive) < 100:
            print(f"❌ Archive from {cluster_ip} is empty or missing")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        
        print(f"✅ Collected logs from {cluster_ip}: {os.path.getsize(local_archive)} bytes")
        return local_archive
    
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
            
            s3_url = f"s3://{self.logs_bucket}/{s3_key}"
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
            
            upload_id = await processor.create_upload_record(
                s3_key=s3_key,
                s3_url=s3_url,
                cluster_name=cluster_name,
                period_start=now - (hours * 3600),
                period_end=now
            )
            
            if upload_id:
                # Process in background
                asyncio.create_task(processor.process_upload(upload_id))
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
        
        # Collect from each cluster
        for cluster in clusters:
            object_store_name = cluster.get("object_store_name", "unknown")
            cluster_ip = cluster.get("primary_ip")
            
            if not cluster_ip:
                print(f"⚠️ No IP found for {object_store_name}, trying alternative IPs...")
                cluster_ips = cluster.get("cluster_ips", [])
                if cluster_ips:
                    cluster_ip = cluster_ips[0]
                else:
                    print(f"❌ No IPs available for {object_store_name}")
                    results["clusters_failed"] += 1
                    results["details"].append({
                        "object_store": object_store_name,
                        "status": "failed",
                        "error": "No cluster IP available"
                    })
                    continue
            
            detail = {
                "object_store": object_store_name,
                "cluster_ip": cluster_ip,
                "status": "pending"
            }
            
            try:
                # Collect logs
                local_archive = self.collect_logs_from_cluster(
                    cluster_ip,
                    object_store_name,
                    hours
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
                    cluster_ip,
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
