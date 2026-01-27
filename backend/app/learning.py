"""
Learning Module for NOVA Backend

Captures successful interactions and uses them as few-shot examples
to improve AI responses over time.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

from .config import BASE_DIR


LEARNING_FILE = BASE_DIR / "learned_examples.json"
MAX_EXAMPLES_PER_CATEGORY = 10
MAX_TOTAL_EXAMPLES = 50


class LearningManager:
    """
    Manages learning from user interactions.
    
    Stores successful query patterns and tool usages to improve
    future responses through few-shot learning.
    """
    
    def __init__(self):
        self.examples: Dict[str, List[dict]] = defaultdict(list)
        self.query_patterns: Dict[str, str] = {}  # natural query -> SQL pattern
        self.load()
    
    def load(self):
        """Load learned examples from disk"""
        if LEARNING_FILE.exists():
            try:
                with open(LEARNING_FILE, 'r') as f:
                    data = json.load(f)
                    self.examples = defaultdict(list, data.get("examples", {}))
                    self.query_patterns = data.get("query_patterns", {})
                    print(f"📚 Loaded {sum(len(v) for v in self.examples.values())} learned examples")
            except Exception as e:
                print(f"⚠️ Failed to load learned examples: {e}")
    
    def save(self):
        """Save learned examples to disk"""
        try:
            data = {
                "examples": dict(self.examples),
                "query_patterns": self.query_patterns,
                "last_updated": datetime.now().isoformat()
            }
            with open(LEARNING_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save learned examples: {e}")
    
    def learn_from_interaction(
        self,
        user_query: str,
        tool_name: str,
        tool_args: dict,
        tool_result: dict,
        was_successful: bool = True
    ):
        """
        Learn from a successful tool interaction.
        
        Args:
            user_query: What the user asked
            tool_name: Which tool was used
            tool_args: Arguments passed to the tool
            tool_result: Result from the tool
            was_successful: Whether the interaction was successful
        """
        if not was_successful:
            return
        
        # Skip if result was an error
        if tool_result.get("status") == "error":
            return
        
        # Determine category based on tool
        category = self._categorize_tool(tool_name)
        
        # Create example
        example = {
            "query": user_query,
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        }
        
        # For SQL queries, store the query pattern
        if tool_name == "execute_sql" and tool_args.get("query"):
            sql_query = tool_args["query"]
            example["sql"] = sql_query
            
            # Store as a query pattern (normalize the user query)
            normalized = self._normalize_query(user_query)
            self.query_patterns[normalized] = sql_query
        
        # For other tools, store the args
        elif tool_args:
            example["args"] = tool_args
        
        # Add to examples, keeping only recent ones
        self.examples[category].append(example)
        self.examples[category] = self.examples[category][-MAX_EXAMPLES_PER_CATEGORY:]
        
        # Trim total examples if needed
        self._trim_examples()
        
        # Save periodically (every 5 new examples)
        total = sum(len(v) for v in self.examples.values())
        if total % 5 == 0:
            self.save()
    
    def _categorize_tool(self, tool_name: str) -> str:
        """Categorize tool for organizing examples"""
        if tool_name == "execute_sql":
            return "sql_queries"
        elif "bucket" in tool_name.lower():
            return "bucket_operations"
        elif "object" in tool_name.lower():
            return "object_operations"
        elif "prism" in tool_name.lower() or "cluster" in tool_name.lower():
            return "prism_operations"
        else:
            return "other"
    
    def _normalize_query(self, query: str) -> str:
        """Normalize a query for pattern matching"""
        # Lowercase and remove extra whitespace
        normalized = " ".join(query.lower().split())
        # Remove common filler words
        for word in ["please", "can you", "could you", "show me", "get me", "i want"]:
            normalized = normalized.replace(word, "")
        return normalized.strip()
    
    def _trim_examples(self):
        """Trim total examples to max limit"""
        total = sum(len(v) for v in self.examples.values())
        while total > MAX_TOTAL_EXAMPLES:
            # Remove oldest from largest category
            largest = max(self.examples.keys(), key=lambda k: len(self.examples[k]))
            if self.examples[largest]:
                self.examples[largest].pop(0)
            total = sum(len(v) for v in self.examples.values())
    
    def get_relevant_examples(self, user_query: str, limit: int = 5) -> List[dict]:
        """
        Get examples relevant to the user's query.
        
        Uses simple keyword matching to find relevant past interactions.
        """
        normalized = self._normalize_query(user_query)
        keywords = set(normalized.split())
        
        scored_examples = []
        
        for category, examples in self.examples.items():
            for ex in examples:
                ex_normalized = self._normalize_query(ex.get("query", ""))
                ex_keywords = set(ex_normalized.split())
                
                # Score by keyword overlap
                overlap = len(keywords & ex_keywords)
                if overlap > 0:
                    scored_examples.append((overlap, ex))
        
        # Sort by score (descending) and return top N
        scored_examples.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored_examples[:limit]]
    
    def get_sql_pattern(self, user_query: str) -> Optional[str]:
        """
        Get a SQL pattern for a similar past query.
        """
        normalized = self._normalize_query(user_query)
        
        # Exact match
        if normalized in self.query_patterns:
            return self.query_patterns[normalized]
        
        # Fuzzy match - find most similar
        best_match = None
        best_score = 0
        
        query_words = set(normalized.split())
        for pattern_query, sql in self.query_patterns.items():
            pattern_words = set(pattern_query.split())
            overlap = len(query_words & pattern_words)
            similarity = overlap / max(len(query_words), len(pattern_words), 1)
            
            if similarity > best_score and similarity > 0.5:
                best_score = similarity
                best_match = sql
        
        return best_match
    
    def build_learning_context(self, user_query: str = None) -> str:
        """
        Build a context string with learned examples.
        
        This is included in the system prompt to provide few-shot learning.
        """
        lines = []
        
        # Get relevant examples if query provided
        if user_query:
            relevant = self.get_relevant_examples(user_query)
            if relevant:
                lines.append("## Relevant Past Interactions")
                lines.append("")
                for ex in relevant:
                    lines.append(f"**User asked:** {ex.get('query', 'N/A')}")
                    if ex.get("sql"):
                        lines.append(f"**SQL used:** `{ex['sql']}`")
                    elif ex.get("tool"):
                        lines.append(f"**Tool used:** {ex['tool']}")
                    lines.append("")
        
        # Add general patterns
        if self.examples.get("sql_queries"):
            lines.append("## Learned SQL Patterns")
            lines.append("")
            for ex in self.examples["sql_queries"][-5:]:
                if ex.get("sql"):
                    query_preview = ex.get("query", "")[:50]
                    lines.append(f"- \"{query_preview}...\" → `{ex['sql']}`")
            lines.append("")
        
        return "\n".join(lines) if lines else ""
    
    def get_stats(self) -> dict:
        """Get learning statistics"""
        return {
            "total_examples": sum(len(v) for v in self.examples.values()),
            "categories": {k: len(v) for k, v in self.examples.items()},
            "query_patterns": len(self.query_patterns)
        }
    
    def clear(self):
        """Clear all learned examples"""
        self.examples = defaultdict(list)
        self.query_patterns = {}
        self.save()


# Global singleton instance
_learning_manager: Optional[LearningManager] = None


def get_learning_manager() -> LearningManager:
    """Get or create the global learning manager instance"""
    global _learning_manager
    if _learning_manager is None:
        _learning_manager = LearningManager()
    return _learning_manager
