"""
NOVA Task Manager - Centralized background task tracking

Tracks all background tasks across the application for monitoring.
"""
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import threading
import time


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    JITA_ANALYSIS = "jita_analysis"
    LOG_UPLOAD = "log_upload"
    DATA_SYNC = "data_sync"
    SCHEMA_REFRESH = "schema_refresh"
    OTHER = "other"


class Task:
    """Represents a background task"""
    
    def __init__(
        self,
        task_id: str,
        task_type: TaskType,
        name: str,
        description: str = "",
        metadata: Dict = None
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.name = name
        self.description = description
        self.metadata = metadata or {}
        
        self.status = TaskStatus.PENDING
        self.progress = 0  # 0-100
        self.progress_message = ""
        
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        
        self.result: Any = None
        self.error: Optional[str] = None
    
    def start(self):
        """Mark task as started"""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()
    
    def update_progress(self, progress: int, message: str = ""):
        """Update task progress"""
        self.progress = min(100, max(0, progress))
        self.progress_message = message
    
    def complete(self, result: Any = None):
        """Mark task as completed"""
        self.status = TaskStatus.COMPLETED
        self.progress = 100
        self.completed_at = datetime.now()
        self.result = result
    
    def fail(self, error: str):
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error = error
    
    def cancel(self):
        """Mark task as cancelled"""
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.now()
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get task duration in seconds"""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API response"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "error": self.error
        }


class TaskManager:
    """Centralized task manager singleton"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: Dict[str, Task] = {}
        self._task_lock = threading.Lock()
        self._max_completed_tasks = 100  # Keep last N completed tasks
    
    def create_task(
        self,
        task_id: str,
        task_type: TaskType,
        name: str,
        description: str = "",
        metadata: Dict = None
    ) -> Task:
        """Create and register a new task"""
        task = Task(task_id, task_type, name, description, metadata)
        with self._task_lock:
            self._tasks[task_id] = task
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        return self._tasks.get(task_id)
    
    def list_tasks(
        self,
        task_type: Optional[TaskType] = None,
        status: Optional[TaskStatus] = None,
        include_completed: bool = True
    ) -> List[Task]:
        """List tasks with optional filters"""
        tasks = list(self._tasks.values())
        
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        elif not include_completed:
            tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
        
        # Sort by created_at descending (newest first)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks
    
    def get_running_tasks(self) -> List[Task]:
        """Get all currently running tasks"""
        return self.list_tasks(status=TaskStatus.RUNNING)
    
    def get_active_tasks(self) -> List[Task]:
        """Get all pending and running tasks"""
        return [t for t in self._tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
    
    def cleanup_old_tasks(self):
        """Remove old completed tasks to prevent memory growth"""
        with self._task_lock:
            completed = [t for t in self._tasks.values() 
                        if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)]
            completed.sort(key=lambda t: t.completed_at or datetime.min)
            
            # Remove oldest completed tasks beyond limit
            to_remove = len(completed) - self._max_completed_tasks
            if to_remove > 0:
                for task in completed[:to_remove]:
                    del self._tasks[task.task_id]
    
    def get_summary(self) -> Dict:
        """Get summary of all tasks"""
        tasks = list(self._tasks.values())
        
        running = [t for t in tasks if t.status == TaskStatus.RUNNING]
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]
        
        return {
            "total": len(tasks),
            "running": len(running),
            "pending": len(pending),
            "completed": len(completed),
            "failed": len(failed),
            "running_tasks": [t.to_dict() for t in running],
            "pending_tasks": [t.to_dict() for t in pending]
        }


# Global instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get the global task manager instance"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
