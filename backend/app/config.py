"""
Configuration Management for NOVA Backend

Handles loading/saving configuration from JSON file.
"""
import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
CONTEXT_DIR = BASE_DIR / "context"
TOOLS_DIR = BASE_DIR / "tools"
TOOLS_FILE = TOOLS_DIR / "tools.json"


def get_default_config() -> dict:
    """Return default configuration structure"""
    return {
        "llm": {
            "provider": "nutanix-ai",
            "hackathon_api_key": "",
            "base_url": "https://hkn12.ai.nutanix.com/enterpriseai/v1/",
            "model": "hack-reason"
        },
        "prism_central": {
            "ip": "",
            "port": 9440,
            "username": "",
            "password": ""
        },
        "s3": {
            "endpoint": "",
            "access_key": "",
            "secret_key": "",
            "region": "us-east-1"
        },
        "sql_agent": {
            "url": ""
        },
        "background": {
            "sql_refresh_interval_seconds": 300,
            "enable_background_refresh": True
        },
        "log_analysis": {
            "logs_bucket": "nova-logs",
            "retention_days": 30,
            "max_message_length": 500,
            "max_stack_trace_length": 1000,
            "severity_filter": ["ERROR", "WARN", "FATAL"],
            "pods_to_scan": ["OC", "MS", "Atlas", "Curator", "Stargate"],
            "collection_interval_hours": 1,
            "auto_collect": False,
            "cluster_credentials": {
                "username": "nutanix",
                "password": "nutanix/4u"
            },
            "initial_delay_minutes": 5
        }
    }


def load_config() -> dict:
    """Load configuration from JSON file with defaults"""
    config = get_default_config()
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                for key in config:
                    if key in saved:
                        if isinstance(config[key], dict):
                            config[key].update(saved[key])
                        else:
                            config[key] = saved[key]
        except Exception as e:
            print(f"Error loading config: {e}")
    
    return config


def save_config(config: dict) -> bool:
    """Save configuration to JSON file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False


def get_config_value(section: str, key: str) -> str:
    """Get a config value from the loaded configuration"""
    config = load_config()
    return config.get(section, {}).get(key, "")


# Convenience getters for common values
def get_llm_api_key() -> str:
    return get_config_value("llm", "hackathon_api_key")

def get_llm_base_url() -> str:
    return get_config_value("llm", "base_url") or "https://hkn12.ai.nutanix.com/enterpriseai/v1/"

def get_llm_model() -> str:
    return get_config_value("llm", "model") or "hack-reason"

def get_pc_ip() -> str:
    return get_config_value("prism_central", "ip")

def get_pc_port() -> int:
    config = load_config()
    return config.get("prism_central", {}).get("port", 9440)

def get_pc_username() -> str:
    return get_config_value("prism_central", "username")

def get_pc_password() -> str:
    return get_config_value("prism_central", "password")

def get_s3_endpoint() -> str:
    return get_config_value("s3", "endpoint")

def get_s3_access_key() -> str:
    return get_config_value("s3", "access_key")

def get_s3_secret_key() -> str:
    return get_config_value("s3", "secret_key")

def get_s3_region() -> str:
    return get_config_value("s3", "region") or "us-east-1"

def get_sql_agent_url() -> str:
    return get_config_value("sql_agent", "url")

def get_background_refresh_interval() -> int:
    config = load_config()
    return config.get("background", {}).get("sql_refresh_interval_seconds", 300)

def is_background_refresh_enabled() -> bool:
    config = load_config()
    return config.get("background", {}).get("enable_background_refresh", True)


# Log Analysis configuration getters
def get_log_analysis_config() -> dict:
    """Get complete log analysis configuration"""
    config = load_config()
    return config.get("log_analysis", {})

def get_logs_bucket() -> str:
    return get_log_analysis_config().get("logs_bucket", "nova-logs")

def get_log_retention_days() -> int:
    return get_log_analysis_config().get("retention_days", 30)

def get_collection_interval_hours() -> int:
    return get_log_analysis_config().get("collection_interval_hours", 1)

def is_auto_collect_enabled() -> bool:
    return get_log_analysis_config().get("auto_collect", False)

def get_cluster_username() -> str:
    creds = get_log_analysis_config().get("cluster_credentials", {})
    return creds.get("username", "nutanix")

def get_cluster_password() -> str:
    creds = get_log_analysis_config().get("cluster_credentials", {})
    return creds.get("password", "nutanix/4u")

def get_initial_delay_minutes() -> int:
    return get_log_analysis_config().get("initial_delay_minutes", 5)

def get_pods_to_scan() -> list:
    return get_log_analysis_config().get("pods_to_scan", ["OC", "MS", "Atlas", "Curator", "Stargate"])

def get_severity_filter() -> list:
    return get_log_analysis_config().get("severity_filter", ["ERROR", "WARN", "FATAL"])
