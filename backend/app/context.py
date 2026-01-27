"""
Context Manager for NOVA Backend

Handles loading, combining, and managing context from markdown files.
Supports dynamic SQL summary updates.

Context files are automatically loaded from the context/ directory.
Use numeric prefixes to control order: 01_system_prompt.md, 02_product.md, etc.
Or configure order in context_order.json.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .config import CONTEXT_DIR


class ContextManager:
    """
    Manages loading and combining context from markdown files.
    
    All .md files in the context directory are automatically loaded.
    
    Ordering:
    1. If context_order.json exists, uses that order
    2. Otherwise, sorts alphabetically (use numeric prefixes like 01_, 02_)
    3. Files not in order config are appended at the end
    """
    
    def __init__(self, context_dir: Path = None):
        self.context_dir = context_dir or CONTEXT_DIR
        self.contexts: Dict[str, str] = {}
        self.context_order: List[str] = []
        self.sql_summary: str = ""
        self.last_sql_refresh: Optional[datetime] = None
    
    def _load_order_config(self) -> List[str]:
        """Load context order from config file if it exists"""
        order_file = self.context_dir / "context_order.json"
        
        if order_file.exists():
            try:
                with open(order_file, 'r') as f:
                    config = json.load(f)
                    return config.get("order", [])
            except Exception as e:
                print(f"⚠️ Failed to load context_order.json: {e}")
        
        return []
    
    def _save_order_config(self) -> bool:
        """Save current context order to config file"""
        order_file = self.context_dir / "context_order.json"
        
        try:
            config = {
                "description": "Order in which context files are included in the system prompt",
                "order": self.context_order
            }
            with open(order_file, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"⚠️ Failed to save context_order.json: {e}")
            return False
    
    def load_all(self) -> int:
        """
        Load all markdown files from context directory.
        
        Returns:
            Number of files loaded
        """
        if not self.context_dir.exists():
            print(f"⚠️ Context directory not found: {self.context_dir}")
            return 0
        
        # Load order configuration
        configured_order = self._load_order_config()
        
        # Find all markdown files
        md_files = sorted(self.context_dir.glob("*.md"))
        
        loaded = 0
        loaded_names = []
        
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                name = md_file.stem
                self.contexts[name] = content
                loaded_names.append(name)
                print(f"📄 Loaded context: {md_file.name}")
                loaded += 1
            except Exception as e:
                print(f"⚠️ Failed to load {md_file.name}: {e}")
        
        # Determine final order
        if configured_order:
            # Use configured order, append any new files
            self.context_order = [n for n in configured_order if n in loaded_names]
            for name in loaded_names:
                if name not in self.context_order:
                    self.context_order.append(name)
        else:
            # Use alphabetical order (numeric prefixes will sort correctly)
            self.context_order = loaded_names
        
        return loaded
    
    def get_context(self, name: str) -> str:
        """Get a specific context by name (without .md extension)"""
        return self.contexts.get(name, "")
    
    def set_context(self, name: str, content: str) -> None:
        """Set a context programmatically"""
        self.contexts[name] = content
        if name not in self.context_order:
            self.context_order.append(name)
    
    def save_context(self, name: str, content: str) -> bool:
        """Save a context to disk and update in-memory"""
        file_path = self.context_dir / f"{name}.md"
        try:
            file_path.write_text(content, encoding="utf-8")
            self.contexts[name] = content
            if name not in self.context_order:
                self.context_order.append(name)
            return True
        except Exception as e:
            print(f"⚠️ Failed to save context {name}: {e}")
            return False
    
    def delete_context(self, name: str) -> bool:
        """Delete a context file"""
        file_path = self.context_dir / f"{name}.md"
        try:
            if file_path.exists():
                file_path.unlink()
            if name in self.contexts:
                del self.contexts[name]
            if name in self.context_order:
                self.context_order.remove(name)
            return True
        except Exception as e:
            print(f"⚠️ Failed to delete context {name}: {e}")
            return False
    
    def list_contexts(self) -> list:
        """List all loaded context names in order"""
        return self.context_order.copy()
    
    def set_order(self, order: List[str]) -> bool:
        """
        Set the context order.
        
        Args:
            order: List of context names in desired order
            
        Returns:
            True if order was saved successfully
        """
        # Validate all names exist
        valid_order = [n for n in order if n in self.contexts]
        
        # Add any missing contexts at the end
        for name in self.contexts:
            if name not in valid_order:
                valid_order.append(name)
        
        self.context_order = valid_order
        return self._save_order_config()
    
    def build_system_prompt(self) -> str:
        """
        Build complete system prompt from all contexts.
        
        Contexts are included in the configured order.
        SQL summary is appended at the end if available.
        """
        parts = []
        
        # Add contexts in order
        for name in self.context_order:
            if name in self.contexts:
                parts.append(self.contexts[name])
        
        # Add any contexts not in order (shouldn't happen, but safety)
        for name, content in self.contexts.items():
            if name not in self.context_order:
                # Format name nicely for title
                title = name.replace('_', ' ').replace('-', ' ').title()
                parts.append(f"# {title}\n\n{content}")
        
        # Add dynamic SQL summary if available
        if self.sql_summary:
            parts.append(f"# Current Data Summary (Auto-refreshed)\n\n{self.sql_summary}")
        
        return "\n\n---\n\n".join(parts)
    
    def update_sql_summary(self, summary: str) -> None:
        """Update the SQL data summary"""
        self.sql_summary = summary
        self.last_sql_refresh = datetime.now()
    
    def clear_sql_summary(self) -> None:
        """Clear the SQL summary"""
        self.sql_summary = ""
        self.last_sql_refresh = None
    
    def reload(self) -> int:
        """Reload all contexts from disk"""
        self.contexts.clear()
        self.context_order.clear()
        return self.load_all()
    
    def get_stats(self) -> dict:
        """Get statistics about loaded contexts"""
        total_chars = sum(len(c) for c in self.contexts.values())
        return {
            "count": len(self.contexts),
            "names": self.context_order,
            "total_characters": total_chars,
            "sql_summary_available": bool(self.sql_summary),
            "last_sql_refresh": self.last_sql_refresh.isoformat() if self.last_sql_refresh else None
        }


# Global singleton instance
_context_manager: Optional[ContextManager] = None


def get_context_manager() -> ContextManager:
    """Get or create the global context manager instance"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager


def initialize_context_manager() -> ContextManager:
    """Initialize and load the context manager"""
    manager = get_context_manager()
    manager.load_all()
    return manager
