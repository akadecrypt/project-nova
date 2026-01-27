#!/usr/bin/env python3
"""
Logbay Upload Script for NOVA

Collects logs from a Nutanix cluster using logbay, compresses them,
uploads to S3, and triggers NOVA to process them.

Usage:
    python3 logbay_upload.py --cluster-ip 10.x.x.x --bucket nova-logs

Cron entry (run at minute 5 of every hour):
    5 * * * * /path/to/logbay_upload.py --cluster-ip 10.x.x.x --bucket nova-logs
"""
import os
import sys
import argparse
import subprocess
import tempfile
import tarfile
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

try:
    import boto3
    import requests
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install boto3 requests")
    sys.exit(1)


class LogbayUploader:
    """
    Collects logs via logbay and uploads to S3.
    """
    
    def __init__(
        self,
        cluster_ip: str,
        cluster_user: str = "nutanix",
        cluster_password: str = "nutanix/4u",
        s3_endpoint: str = None,
        s3_access_key: str = None,
        s3_secret_key: str = None,
        s3_bucket: str = "nova-logs",
        nova_api_url: str = None
    ):
        self.cluster_ip = cluster_ip
        self.cluster_user = cluster_user
        self.cluster_password = cluster_password
        self.s3_endpoint = s3_endpoint
        self.s3_access_key = s3_access_key
        self.s3_secret_key = s3_secret_key
        self.s3_bucket = s3_bucket
        self.nova_api_url = nova_api_url
    
    def _run_ssh_command(self, command: str, timeout: int = 300) -> tuple:
        """Run a command on the cluster via SSH"""
        ssh_cmd = [
            "sshpass", "-p", self.cluster_password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.cluster_user}@{self.cluster_ip}",
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
    
    def _scp_file(self, remote_path: str, local_path: str) -> bool:
        """Copy a file from the cluster via SCP"""
        scp_cmd = [
            "sshpass", "-p", self.cluster_password,
            "scp", "-o", "StrictHostKeyChecking=no",
            f"{self.cluster_user}@{self.cluster_ip}:{remote_path}",
            local_path
        ]
        
        try:
            result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=300)
            return result.returncode == 0
        except:
            return False
    
    def collect_logs(self, hours: int = 1) -> str:
        """
        Run logbay on the cluster to collect logs for the specified time period.
        
        Returns:
            Path to the downloaded log archive
        """
        # Calculate time range
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        # Create temp directory for logs
        temp_dir = tempfile.mkdtemp(prefix="nova_logs_")
        archive_name = f"cluster-logs-{end_time.strftime('%Y%m%d-%H%M')}.tar.gz"
        local_archive = os.path.join(temp_dir, archive_name)
        
        print(f"Collecting logs from {start_time} to {end_time}...")
        
        # Option 1: Run logbay if available
        # logbay_cmd = f"logbay collect -d {hours}h -o /tmp/logbay_output"
        # rc, stdout, stderr = self._run_ssh_command(logbay_cmd, timeout=600)
        
        # Option 2: Directly collect key log files
        remote_archive = f"/tmp/{archive_name}"
        
        # Create archive of important log files on the cluster
        collect_cmd = f"""
        cd /home/nutanix && tar -czf {remote_archive} \
            --ignore-failed-read \
            data/logs/oc*.log* \
            data/logs/ms*.log* \
            data/logs/atlas*.log* \
            data/logs/curator*.log* \
            data/logs/stargate*.log* \
            2>/dev/null || true
        """
        
        print("Creating log archive on cluster...")
        rc, stdout, stderr = self._run_ssh_command(collect_cmd.strip(), timeout=600)
        
        if rc != 0:
            print(f"Warning: Archive creation may have partial failures: {stderr}")
        
        # Download the archive
        print("Downloading log archive...")
        if not self._scp_file(remote_archive, local_archive):
            raise Exception("Failed to download log archive")
        
        # Clean up remote archive
        self._run_ssh_command(f"rm -f {remote_archive}")
        
        print(f"Logs collected: {local_archive}")
        return local_archive
    
    def upload_to_s3(self, local_path: str) -> tuple:
        """
        Upload the log archive to S3.
        
        Returns:
            Tuple of (s3_key, s3_url)
        """
        # Generate S3 key based on timestamp
        now = datetime.now()
        filename = os.path.basename(local_path)
        s3_key = f"{now.strftime('%Y/%m/%d/%H')}/{filename}"
        
        print(f"Uploading to S3: {self.s3_bucket}/{s3_key}...")
        
        s3 = boto3.client(
            's3',
            endpoint_url=self.s3_endpoint,
            aws_access_key_id=self.s3_access_key,
            aws_secret_access_key=self.s3_secret_key,
            verify=False
        )
        
        # Ensure bucket exists
        try:
            s3.head_bucket(Bucket=self.s3_bucket)
        except:
            print(f"Creating bucket: {self.s3_bucket}")
            s3.create_bucket(Bucket=self.s3_bucket)
        
        # Upload
        s3.upload_file(local_path, self.s3_bucket, s3_key)
        
        s3_url = f"s3://{self.s3_bucket}/{s3_key}"
        print(f"Uploaded: {s3_url}")
        
        return s3_key, s3_url
    
    def trigger_processing(self, s3_key: str, s3_url: str, hours: int = 1) -> dict:
        """
        Call NOVA API to process the uploaded logs.
        """
        if not self.nova_api_url:
            print("NOVA API URL not configured, skipping processing trigger")
            return {}
        
        # Calculate time period
        now = int(time.time())
        period_end = now
        period_start = now - (hours * 3600)
        
        payload = {
            "s3_key": s3_key,
            "s3_url": s3_url,
            "cluster_name": self.cluster_ip,
            "period_start": period_start,
            "period_end": period_end
        }
        
        print(f"Triggering NOVA processing: {self.nova_api_url}/api/logs/upload")
        
        try:
            response = requests.post(
                f"{self.nova_api_url}/api/logs/upload",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"Processing triggered: upload_id={result.get('upload_id')}")
                return result
            else:
                print(f"Error triggering processing: {response.status_code} - {response.text}")
                return {"error": response.text}
                
        except Exception as e:
            print(f"Error calling NOVA API: {e}")
            return {"error": str(e)}
    
    def run(self, hours: int = 1, cleanup: bool = True) -> dict:
        """
        Full workflow: collect, upload, trigger processing.
        """
        result = {
            "success": False,
            "s3_key": None,
            "s3_url": None,
            "upload_id": None
        }
        
        local_archive = None
        
        try:
            # Collect logs
            local_archive = self.collect_logs(hours)
            
            # Upload to S3
            s3_key, s3_url = self.upload_to_s3(local_archive)
            result["s3_key"] = s3_key
            result["s3_url"] = s3_url
            
            # Trigger processing
            proc_result = self.trigger_processing(s3_key, s3_url, hours)
            result["upload_id"] = proc_result.get("upload_id")
            
            result["success"] = True
            print("Log upload complete!")
            
        except Exception as e:
            print(f"Error: {e}")
            result["error"] = str(e)
        
        finally:
            # Cleanup
            if cleanup and local_archive and os.path.exists(local_archive):
                os.remove(local_archive)
                # Remove temp directory
                temp_dir = os.path.dirname(local_archive)
                if temp_dir.startswith(tempfile.gettempdir()):
                    try:
                        os.rmdir(temp_dir)
                    except:
                        pass
        
        return result


def load_config_from_nova(nova_api_url: str) -> dict:
    """Load S3 configuration from NOVA backend"""
    try:
        response = requests.get(f"{nova_api_url}/api/config/s3", timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Upload Nutanix cluster logs to S3 and trigger NOVA analysis"
    )
    
    parser.add_argument(
        "--cluster-ip", "-c",
        required=True,
        help="Nutanix cluster IP address"
    )
    parser.add_argument(
        "--cluster-user",
        default="nutanix",
        help="SSH username for cluster (default: nutanix)"
    )
    parser.add_argument(
        "--cluster-password",
        default="nutanix/4u",
        help="SSH password for cluster"
    )
    parser.add_argument(
        "--bucket", "-b",
        default="nova-logs",
        help="S3 bucket for logs (default: nova-logs)"
    )
    parser.add_argument(
        "--s3-endpoint",
        help="S3 endpoint URL (or set S3_ENDPOINT env var)"
    )
    parser.add_argument(
        "--s3-access-key",
        help="S3 access key (or set S3_ACCESS_KEY env var)"
    )
    parser.add_argument(
        "--s3-secret-key",
        help="S3 secret key (or set S3_SECRET_KEY env var)"
    )
    parser.add_argument(
        "--nova-api",
        help="NOVA backend API URL (e.g., http://10.x.x.x:9360)"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Hours of logs to collect (default: 1)"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't delete local files after upload"
    )
    
    args = parser.parse_args()
    
    # Get S3 config from environment or args
    s3_endpoint = args.s3_endpoint or os.environ.get("S3_ENDPOINT")
    s3_access_key = args.s3_access_key or os.environ.get("S3_ACCESS_KEY")
    s3_secret_key = args.s3_secret_key or os.environ.get("S3_SECRET_KEY")
    
    # Try to load from NOVA if not provided
    if args.nova_api and (not s3_endpoint or not s3_access_key):
        print("Loading S3 config from NOVA backend...")
        config = load_config_from_nova(args.nova_api)
        s3_endpoint = s3_endpoint or config.get("endpoint")
        s3_access_key = s3_access_key or config.get("access_key")
    
    if not s3_endpoint or not s3_access_key or not s3_secret_key:
        print("Error: S3 configuration required.")
        print("Provide --s3-endpoint, --s3-access-key, --s3-secret-key")
        print("Or set S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY environment variables")
        print("Or provide --nova-api to load from NOVA backend")
        sys.exit(1)
    
    # Create uploader and run
    uploader = LogbayUploader(
        cluster_ip=args.cluster_ip,
        cluster_user=args.cluster_user,
        cluster_password=args.cluster_password,
        s3_endpoint=s3_endpoint,
        s3_access_key=s3_access_key,
        s3_secret_key=s3_secret_key,
        s3_bucket=args.bucket,
        nova_api_url=args.nova_api
    )
    
    result = uploader.run(hours=args.hours, cleanup=not args.no_cleanup)
    
    # Print result as JSON for scripting
    print(json.dumps(result, indent=2))
    
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
