"""
Tool Manager for NOVA Backend

Manages loading tools from JSON and converting to OpenAI function format.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from ..config import TOOLS_FILE


class ToolManager:
    """
    Manages loading tools from JSON configuration.
    
    Tool definitions are stored in tools/tools.json and converted
    to OpenAI function calling format at runtime.
    """
    
    def __init__(self, tools_file: Path = None):
        self.tools_file = tools_file or TOOLS_FILE
        self.tools_config: Dict = {}
        self.openai_tools: List[Dict] = []
    
    def load(self) -> int:
        """
        Load tools from JSON file.
        
        Returns:
            Number of tools loaded
        """
        if not self.tools_file.exists():
            print(f"⚠️ Tools file not found: {self.tools_file}")
            return 0
        
        try:
            with open(self.tools_file, 'r') as f:
                self.tools_config = json.load(f)
            
            # Convert to OpenAI format
            self.openai_tools = []
            for tool in self.tools_config.get("tools", []):
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}})
                    }
                }
                self.openai_tools.append(openai_tool)
            
            print(f"🔧 Loaded {len(self.openai_tools)} tools")
            return len(self.openai_tools)
            
        except Exception as e:
            print(f"⚠️ Failed to load tools: {e}")
            return 0
    
    def get_tools(self) -> List[Dict]:
        """Get tools in OpenAI function calling format"""
        return self.openai_tools
    
    def get_tool_info(self, name: str) -> Optional[Dict]:
        """Get detailed info about a specific tool"""
        for tool in self.tools_config.get("tools", []):
            if tool["name"] == name:
                return tool
        return None
    
    def get_tool_names(self) -> List[str]:
        """Get list of all tool names"""
        return [t["function"]["name"] for t in self.openai_tools]
    
    def get_categories(self) -> Dict:
        """Get tool categories"""
        return self.tools_config.get("categories", {})
    
    def get_tools_by_category(self, category: str) -> List[Dict]:
        """Get all tools in a specific category"""
        return [
            tool for tool in self.tools_config.get("tools", [])
            if tool.get("category") == category
        ]
    
    def reload(self) -> int:
        """Reload tools from disk"""
        self.tools_config = {}
        self.openai_tools = []
        return self.load()


# Global singleton instance
_tool_manager: Optional[ToolManager] = None


def get_tool_manager() -> ToolManager:
    """Get or create the global tool manager instance"""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = ToolManager()
    return _tool_manager


def initialize_tool_manager() -> ToolManager:
    """Initialize and load the tool manager"""
    manager = get_tool_manager()
    manager.load()
    return manager
