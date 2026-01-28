"""
Centralized logging configuration for NOVA backend.
Logs are stored in backend/logs/ directory with rotation.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

# Log directory
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Log format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Log levels
LOG_LEVEL = logging.INFO

# Max log file size (10 MB)
MAX_LOG_SIZE = 10 * 1024 * 1024
# Keep 5 backup files
BACKUP_COUNT = 5


def setup_logging():
    """Initialize logging configuration for the application."""
    
    # Create formatters
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Main application log
    app_handler = RotatingFileHandler(
        LOG_DIR / "nova.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    app_handler.setLevel(LOG_LEVEL)
    app_handler.setFormatter(formatter)
    root_logger.addHandler(app_handler)
    
    # Error log (only errors and above)
    error_handler = RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    # Chat-specific log
    chat_logger = logging.getLogger("nova.chat")
    chat_handler = RotatingFileHandler(
        LOG_DIR / "chat.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    chat_handler.setFormatter(formatter)
    chat_logger.addHandler(chat_handler)
    
    # Tools/SQL log
    tools_logger = logging.getLogger("nova.tools")
    tools_handler = RotatingFileHandler(
        LOG_DIR / "tools.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    tools_handler.setFormatter(formatter)
    tools_logger.addHandler(tools_handler)
    
    # Log collector log
    collector_logger = logging.getLogger("nova.collector")
    collector_handler = RotatingFileHandler(
        LOG_DIR / "collector.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    collector_handler.setFormatter(formatter)
    collector_logger.addHandler(collector_handler)
    
    # API access log
    api_logger = logging.getLogger("nova.api")
    api_handler = RotatingFileHandler(
        LOG_DIR / "api.log",
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT
    )
    api_handler.setFormatter(formatter)
    api_logger.addHandler(api_handler)
    
    logging.info("🚀 NOVA logging initialized")
    logging.info(f"📁 Log directory: {LOG_DIR}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(f"nova.{name}")


# Convenience loggers
def get_chat_logger() -> logging.Logger:
    return logging.getLogger("nova.chat")


def get_tools_logger() -> logging.Logger:
    return logging.getLogger("nova.tools")


def get_collector_logger() -> logging.Logger:
    return logging.getLogger("nova.collector")


def get_api_logger() -> logging.Logger:
    return logging.getLogger("nova.api")


# Utility functions for structured logging
def log_chat_message(user_message: str, response: str = None, error: str = None):
    """Log a chat interaction."""
    logger = get_chat_logger()
    logger.info(f"USER: {user_message[:200]}{'...' if len(user_message) > 200 else ''}")
    if response:
        logger.info(f"ASSISTANT: {response[:200]}{'...' if len(response) > 200 else ''}")
    if error:
        logger.error(f"CHAT_ERROR: {error}")


def log_tool_call(tool_name: str, args: dict = None, result: str = None, error: str = None):
    """Log a tool execution."""
    logger = get_tools_logger()
    args_str = str(args)[:100] if args else "None"
    logger.info(f"TOOL_CALL: {tool_name} | Args: {args_str}")
    if result:
        result_str = str(result)[:200]
        logger.info(f"TOOL_RESULT: {tool_name} | {result_str}")
    if error:
        logger.error(f"TOOL_ERROR: {tool_name} | {error}")


def log_sql_query(query: str, result_count: int = None, error: str = None):
    """Log a SQL query execution."""
    logger = get_tools_logger()
    query_str = query[:150] if query else "None"
    logger.info(f"SQL_QUERY: {query_str}")
    if result_count is not None:
        logger.info(f"SQL_RESULT: {result_count} rows")
    if error:
        logger.error(f"SQL_ERROR: {error}")


def log_api_request(method: str, path: str, status_code: int = None, duration_ms: float = None):
    """Log an API request."""
    logger = get_api_logger()
    log_msg = f"{method} {path}"
    if status_code:
        log_msg += f" | {status_code}"
    if duration_ms:
        log_msg += f" | {duration_ms:.0f}ms"
    logger.info(log_msg)
