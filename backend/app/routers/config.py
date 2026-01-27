"""
Configuration Router for NOVA Backend

Handles configuration management endpoints.
"""
import os
from fastapi import APIRouter, HTTPException

from ..models import (
    LLMConfig, PrismConfig, S3Config, SQLAgentConfig, 
    FullConfig, ConnectionTestResponse
)
from ..config import load_config, save_config
from ..tools.prism_tools import test_prism_connection, get_s3_endpoint_from_prism, auto_configure_s3_from_prism
from ..tools.s3_tools import get_s3_client

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_full_config():
    """Get full configuration (passwords masked)"""
    cfg = load_config()
    
    return {
        "llm": {
            "provider": cfg["llm"]["provider"],
            "hackathon_api_key": "***" if cfg["llm"]["hackathon_api_key"] else "",
            "base_url": cfg["llm"]["base_url"],
            "model": cfg["llm"]["model"]
        },
        "prism_central": {
            "ip": cfg["prism_central"]["ip"],
            "port": cfg["prism_central"]["port"],
            "username": cfg["prism_central"]["username"],
            "password": "***" if cfg["prism_central"]["password"] else ""
        },
        "s3": {
            "endpoint": cfg["s3"]["endpoint"],
            "access_key": cfg["s3"]["access_key"],
            "secret_key": "***" if cfg["s3"]["secret_key"] else "",
            "region": cfg["s3"]["region"]
        },
        "sql_agent": cfg["sql_agent"],
        "background": cfg.get("background", {})
    }


@router.post("")
async def update_full_config(config: FullConfig):
    """Update full configuration"""
    cfg = load_config()
    
    # Update LLM config
    if config.llm.hackathon_api_key and config.llm.hackathon_api_key != "***":
        cfg["llm"]["hackathon_api_key"] = config.llm.hackathon_api_key
    cfg["llm"]["provider"] = config.llm.provider
    cfg["llm"]["base_url"] = config.llm.base_url
    cfg["llm"]["model"] = config.llm.model
    
    # Update Prism Central config
    cfg["prism_central"]["ip"] = config.prism_central.ip
    cfg["prism_central"]["port"] = config.prism_central.port
    cfg["prism_central"]["username"] = config.prism_central.username
    if config.prism_central.password and config.prism_central.password != "***":
        cfg["prism_central"]["password"] = config.prism_central.password
    
    # Update S3 config
    cfg["s3"]["endpoint"] = config.s3.endpoint
    cfg["s3"]["access_key"] = config.s3.access_key
    if config.s3.secret_key and config.s3.secret_key != "***":
        cfg["s3"]["secret_key"] = config.s3.secret_key
    cfg["s3"]["region"] = config.s3.region
    
    # Update SQL Agent config
    cfg["sql_agent"]["url"] = config.sql_agent.url
    
    if save_config(cfg):
        return {"success": True, "message": "Configuration saved"}
    else:
        raise HTTPException(status_code=500, detail="Failed to save configuration")


# LLM Configuration
@router.get("/llm")
async def get_llm_config():
    """Get LLM configuration"""
    cfg = load_config()
    return {
        "provider": cfg["llm"]["provider"],
        "is_configured": bool(cfg["llm"]["hackathon_api_key"] or os.getenv("HACKATHON_API_KEY")),
        "base_url": cfg["llm"]["base_url"],
        "model": cfg["llm"]["model"]
    }


@router.post("/llm")
async def update_llm_config(config: LLMConfig):
    """Update LLM configuration"""
    cfg = load_config()
    
    if config.hackathon_api_key and config.hackathon_api_key != "***":
        cfg["llm"]["hackathon_api_key"] = config.hackathon_api_key
    cfg["llm"]["provider"] = config.provider
    cfg["llm"]["base_url"] = config.base_url
    cfg["llm"]["model"] = config.model
    
    if save_config(cfg):
        return {"success": True, "message": "LLM configuration saved"}
    raise HTTPException(status_code=500, detail="Failed to save configuration")


# Prism Central Configuration
@router.get("/prism")
async def get_prism_config():
    """Get Prism Central configuration"""
    cfg = load_config()
    return {
        "ip": cfg["prism_central"]["ip"] or os.getenv("PC_IP", ""),
        "port": cfg["prism_central"]["port"],
        "username": cfg["prism_central"]["username"] or os.getenv("PC_USERNAME", ""),
        "is_configured": bool(cfg["prism_central"]["ip"] or os.getenv("PC_IP"))
    }


@router.post("/prism")
async def update_prism_config(config: PrismConfig):
    """Update Prism Central configuration"""
    cfg = load_config()
    
    cfg["prism_central"]["ip"] = config.ip
    cfg["prism_central"]["port"] = config.port
    cfg["prism_central"]["username"] = config.username
    if config.password and config.password != "***":
        cfg["prism_central"]["password"] = config.password
    
    if save_config(cfg):
        return {"success": True, "message": "Prism Central configuration saved"}
    raise HTTPException(status_code=500, detail="Failed to save configuration")


@router.post("/prism/test", response_model=ConnectionTestResponse)
async def test_prism():
    """Test Prism Central connection"""
    return test_prism_connection()


# S3 Configuration
@router.get("/s3")
async def get_s3_config():
    """Get S3 configuration"""
    cfg = load_config()
    return {
        "endpoint": cfg["s3"]["endpoint"] or os.getenv("NUTANIX_S3_ENDPOINT", ""),
        "access_key": cfg["s3"]["access_key"] or os.getenv("NUTANIX_ACCESS_KEY", ""),
        "region": cfg["s3"]["region"],
        "is_configured": bool(cfg["s3"]["endpoint"] or os.getenv("NUTANIX_S3_ENDPOINT"))
    }


@router.post("/s3")
async def update_s3_config(config: S3Config):
    """Update S3 configuration"""
    cfg = load_config()
    
    cfg["s3"]["endpoint"] = config.endpoint
    cfg["s3"]["access_key"] = config.access_key
    if config.secret_key and config.secret_key != "***":
        cfg["s3"]["secret_key"] = config.secret_key
    cfg["s3"]["region"] = config.region
    
    if save_config(cfg):
        return {"success": True, "message": "S3 configuration saved"}
    raise HTTPException(status_code=500, detail="Failed to save configuration")


@router.post("/s3/test", response_model=ConnectionTestResponse)
async def test_s3():
    """Test S3 connection"""
    try:
        s3 = get_s3_client()
        s3.list_buckets()
        return {"success": True, "message": "Connected to S3"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/s3/detect")
async def detect_s3_from_prism():
    """
    Auto-detect S3 endpoint from Prism Central Object Stores.
    Requires Prism Central to be configured first.
    """
    result = get_s3_endpoint_from_prism()
    
    if result.get("success"):
        # Optionally auto-save the detected endpoint
        cfg = load_config()
        cfg["s3"]["endpoint"] = result.get("endpoint", "")
        cfg["s3"]["region"] = result.get("region", "us-east-1")
        save_config(cfg)
        
        return {
            "success": True,
            "endpoint": result.get("endpoint"),
            "object_store_name": result.get("object_store_name"),
            "region": result.get("region"),
            "message": f"Detected endpoint from Object Store: {result.get('object_store_name')}",
            "all_stores": result.get("all_stores", [])
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "Failed to detect S3 endpoint")
        }


@router.post("/s3/auto-configure")
async def auto_configure_s3():
    """
    Auto-configure S3 completely from Prism Central.
    - Detects Object Store endpoint
    - Creates IAM service account
    - Generates access keys
    - Saves all configuration
    """
    result = auto_configure_s3_from_prism()
    
    if result.get("success"):
        # Save all S3 configuration
        cfg = load_config()
        cfg["s3"]["endpoint"] = result.get("endpoint", "")
        cfg["s3"]["access_key"] = result.get("access_key", "")
        cfg["s3"]["secret_key"] = result.get("secret_key", "")
        cfg["s3"]["region"] = result.get("region", "us-east-1")
        save_config(cfg)
        
        return {
            "success": True,
            "endpoint": result.get("endpoint"),
            "access_key": result.get("access_key"),
            "object_store_name": result.get("object_store_name"),
            "iam_username": result.get("iam_username"),
            "message": result.get("message")
        }
    else:
        return {
            "success": False,
            "message": result.get("message", "Failed to auto-configure S3"),
            "endpoint": result.get("endpoint")  # May have endpoint even if IAM failed
        }


# SQL Agent Configuration
@router.get("/sql")
async def get_sql_config():
    """Get SQL Agent configuration"""
    cfg = load_config()
    return {
        "url": cfg["sql_agent"]["url"],
        "is_configured": bool(cfg["sql_agent"]["url"])
    }


@router.post("/sql")
async def update_sql_config(config: SQLAgentConfig):
    """Update SQL Agent configuration"""
    cfg = load_config()
    cfg["sql_agent"]["url"] = config.url
    
    if save_config(cfg):
        return {"success": True, "message": "SQL Agent configuration saved"}
    raise HTTPException(status_code=500, detail="Failed to save configuration")


@router.post("/sql/test", response_model=ConnectionTestResponse)
async def test_sql():
    """Test SQL Agent connection"""
    from ..tools.sql_tools import list_tables
    
    result = list_tables()
    
    if result.get("status") == "error":
        return {"success": False, "message": result.get("error", "Connection failed")}
    
    tables = result.get("tables", [])
    return {
        "success": True, 
        "message": f"Connected! Found {len(tables)} tables"
    }
