"""
AI-Powered Log Analyzer for NOVA

Uses LLM to intelligently analyze logs and identify real issues:
1. Structural analysis to find potential error regions
2. LLM-based classification to filter false positives
3. Embedding-based deduplication to avoid redundant analysis
4. Root cause analysis and fix suggestions
"""

import os
import json
import hashlib
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)


@dataclass
class AnalyzedError:
    """Represents an AI-analyzed error from logs."""
    id: str
    is_real_error: bool
    confidence: float  # 0.0 to 1.0
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str  # e.g., "Infrastructure", "Network", "Application", "Test Framework"
    error_type: str  # Specific type like "ConnectionTimeout", "AssertionFailure"
    title: str  # Short descriptive title
    summary: str  # What happened
    root_cause: str  # Why it happened
    impact: str  # What's affected
    suggested_fix: str  # How to fix
    related_components: List[str] = field(default_factory=list)
    log_snippet: str = ""
    line_numbers: Tuple[int, int] = (0, 0)
    source_file: str = ""
    timestamp: Optional[int] = None
    dedup_hash: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class AILogAnalyzer:
    """
    AI-powered log analyzer that uses LLM for intelligent error detection.
    
    Key features:
    1. Structural analysis - finds potential error regions without naive regex
    2. LLM classification - determines if something is a real error
    3. Deduplication - uses embeddings to group similar errors
    4. Root cause analysis - explains why errors occurred
    5. Fix suggestions - provides actionable remediation steps
    """
    
    # Structural patterns that indicate potential error regions (not content matching)
    ERROR_REGION_INDICATORS = [
        # Stack trace structure
        r'^Traceback \(most recent call last\):',
        r'^\s+File ".*", line \d+',
        r'^[A-Z][a-zA-Z]*(?:Error|Exception|Failure):',
        
        # Log level markers (structural, not content)
        r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}.*\b(ERROR|FATAL|CRITICAL)\b',
        r'^\[?(ERROR|FATAL|CRITICAL)\]?\s*[-:]\s*\S',
        
        # Test failure markers
        r'^={3,}\s*(FAILURES|ERRORS)\s*={3,}',
        r'^FAILED\s+\S+',
        r'^E\s+\w+Error:',
    ]
    
    # Maximum tokens to send to LLM per chunk
    MAX_CHUNK_TOKENS = 2000
    
    def __init__(self, llm_provider: str = "openai"):
        """
        Initialize the AI log analyzer.
        
        Args:
            llm_provider: "openai" or "gemini"
        """
        self.llm_provider = llm_provider
        self._compiled_patterns = [re.compile(p, re.MULTILINE) for p in self.ERROR_REGION_INDICATORS]
        self._analysis_cache: Dict[str, AnalyzedError] = {}
        self._embedding_cache: Dict[str, List[float]] = {}
    
    async def analyze_log_content(
        self,
        content: str,
        source_file: str,
        test_name: str = "",
        context: Dict[str, Any] = None
    ) -> List[AnalyzedError]:
        """
        Analyze log content using AI to identify real errors.
        
        Args:
            content: Raw log content
            source_file: Source file name for reference
            test_name: Associated test name
            context: Additional context (cluster info, test type, etc.)
            
        Returns:
            List of analyzed errors (only real issues, not false positives)
        """
        if not content or len(content.strip()) < 10:
            return []
        
        # Step 1: Find potential error regions using structural analysis
        error_regions = self._find_error_regions(content)
        
        if not error_regions:
            logger.info(f"No potential error regions found in {source_file}")
            return []
        
        logger.info(f"Found {len(error_regions)} potential error regions in {source_file}")
        
        # Step 2: Deduplicate similar regions before sending to LLM
        unique_regions = self._deduplicate_regions(error_regions)
        logger.info(f"After deduplication: {len(unique_regions)} unique regions")
        
        # Step 3: Analyze each unique region with LLM
        analyzed_errors = []
        for region in unique_regions:
            # Check cache first
            cache_key = self._get_cache_key(region['content'])
            if cache_key in self._analysis_cache:
                cached = self._analysis_cache[cache_key]
                if cached.is_real_error:
                    analyzed_errors.append(cached)
                continue
            
            # Analyze with LLM
            analysis = await self._analyze_with_llm(
                region['content'],
                source_file,
                test_name,
                region['start_line'],
                region['end_line'],
                context
            )
            
            if analysis:
                # Cache the result
                self._analysis_cache[cache_key] = analysis
                
                if analysis.is_real_error:
                    analyzed_errors.append(analysis)
        
        # Step 4: Sort by severity and confidence
        analyzed_errors.sort(key=lambda e: (
            {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(e.severity, 4),
            -e.confidence
        ))
        
        return analyzed_errors
    
    def _find_error_regions(self, content: str) -> List[Dict]:
        """
        Find potential error regions using structural analysis.
        
        This is NOT regex matching for "ERROR" - it's looking for
        structural patterns that indicate error regions (stack traces,
        log format boundaries, etc.)
        """
        lines = content.split('\n')
        regions = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this line starts a potential error region
            is_error_start = False
            for pattern in self._compiled_patterns:
                if pattern.match(line):
                    is_error_start = True
                    break
            
            if is_error_start:
                # Collect the error region with context
                start_line = max(0, i - 3)  # 3 lines before
                end_line = i + 1
                
                # Expand to include continuation lines (stack trace, etc.)
                while end_line < len(lines):
                    next_line = lines[end_line]
                    
                    # Continue if indented (stack trace continuation)
                    if next_line.startswith(' ') or next_line.startswith('\t'):
                        end_line += 1
                        continue
                    
                    # Continue if it's a "Caused by" or similar
                    if next_line.startswith('Caused by:') or next_line.startswith('... '):
                        end_line += 1
                        continue
                    
                    # Continue if it looks like exception details
                    if re.match(r'^[A-Z][a-zA-Z]*(?:Error|Exception):', next_line):
                        end_line += 1
                        continue
                    
                    # Stop at next structured log line or empty line after content
                    if self._is_new_log_entry(next_line) or (not next_line.strip() and end_line > i + 5):
                        break
                    
                    end_line += 1
                    
                    # Don't collect too much
                    if end_line - i > 50:
                        break
                
                # Add a few lines of context after
                end_line = min(len(lines), end_line + 3)
                
                region_content = '\n'.join(lines[start_line:end_line])
                
                # Only add if it has meaningful content
                if len(region_content.strip()) > 20:
                    regions.append({
                        'start_line': start_line + 1,  # 1-indexed
                        'end_line': end_line,
                        'content': region_content,
                        'trigger_line': line
                    })
                
                i = end_line
            else:
                i += 1
        
        return regions
    
    def _is_new_log_entry(self, line: str) -> bool:
        """Check if a line starts a new log entry."""
        # Common log format patterns
        patterns = [
            r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}',  # ISO timestamp
            r'^\[\d{4}-\d{2}-\d{2}',  # Bracketed timestamp
            r'^[IWEF]\d{8}\s+\d{2}:',  # Google glog
            r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}',  # Syslog
        ]
        
        for pattern in patterns:
            if re.match(pattern, line):
                return True
        return False
    
    def _deduplicate_regions(self, regions: List[Dict]) -> List[Dict]:
        """
        Deduplicate similar error regions to avoid redundant LLM calls.
        
        Uses a simple content hash for now. Could be enhanced with embeddings.
        """
        seen_hashes = set()
        unique = []
        
        for region in regions:
            # Create a normalized hash of the content
            normalized = self._normalize_for_hash(region['content'])
            content_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
            
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique.append(region)
        
        return unique
    
    def _normalize_for_hash(self, content: str) -> str:
        """Normalize content for hashing (remove variable parts)."""
        # Remove timestamps
        content = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[.\d]*', 'TIMESTAMP', content)
        # Remove line numbers in stack traces
        content = re.sub(r'line \d+', 'line N', content)
        # Remove hex addresses
        content = re.sub(r'0x[0-9a-fA-F]+', 'ADDR', content)
        # Remove UUIDs
        content = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', content)
        # Collapse whitespace
        content = re.sub(r'\s+', ' ', content)
        return content.strip()[:500]
    
    def _get_cache_key(self, content: str) -> str:
        """Generate a cache key for the content."""
        normalized = self._normalize_for_hash(content)
        return hashlib.md5(normalized.encode()).hexdigest()
    
    async def _analyze_with_llm(
        self,
        content: str,
        source_file: str,
        test_name: str,
        start_line: int,
        end_line: int,
        context: Dict[str, Any] = None
    ) -> Optional[AnalyzedError]:
        """
        Analyze a log region using LLM to determine if it's a real error.
        """
        try:
            # Prepare the prompt
            prompt = self._build_analysis_prompt(content, source_file, test_name, context)
            
            # Call LLM
            if self.llm_provider == "gemini":
                response = await self._call_gemini(prompt)
            else:
                response = await self._call_openai(prompt)
            
            if not response:
                return None
            
            # Parse the response
            analysis = self._parse_llm_response(response, content, source_file, start_line, end_line)
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing with LLM: {e}")
            return None
    
    def _build_analysis_prompt(
        self,
        content: str,
        source_file: str,
        test_name: str,
        context: Dict[str, Any] = None
    ) -> str:
        """Build the prompt for LLM analysis."""
        
        context_info = ""
        if context:
            context_info = f"""
Additional Context:
- Test Name: {test_name or 'Unknown'}
- Cluster Info: {context.get('cluster_info', 'Not available')}
- Test Status: {context.get('test_status', 'Unknown')}
"""
        
        prompt = f"""You are an expert log analyzer for a distributed systems test framework (Nutanix NuTest).
Analyze the following log snippet and determine if it represents a REAL ERROR that needs attention.

IMPORTANT: Many logs contain the word "error" but are NOT actual errors (e.g., "error_count=0", "no errors found", error handling code paths, etc.)
You must distinguish between:
1. REAL ERRORS - Actual failures, exceptions, or issues that caused problems
2. FALSE POSITIVES - Mentions of "error" that don't indicate actual problems

Source File: {source_file}
{context_info}

LOG SNIPPET:
```
{content[:3000]}
```

Analyze this log snippet and respond with a JSON object:

{{
    "is_real_error": true/false,
    "confidence": 0.0-1.0,
    "severity": "CRITICAL|HIGH|MEDIUM|LOW",
    "category": "Infrastructure|Network|Application|Test Framework|Configuration|Resource|Authentication|Database|Unknown",
    "error_type": "specific error type name",
    "title": "short descriptive title (max 80 chars)",
    "summary": "what happened in 1-2 sentences",
    "root_cause": "why it happened based on the logs",
    "impact": "what is affected by this error",
    "suggested_fix": "actionable steps to fix or investigate",
    "related_components": ["list", "of", "affected", "components"],
    "reasoning": "explain why you classified this as real error or false positive"
}}

Be conservative - if unsure, mark as not a real error. Only flag issues that clearly indicate failures.
Respond ONLY with the JSON object, no other text."""

        return prompt
    
    async def _call_openai(self, prompt: str) -> Optional[str]:
        """Call OpenAI API for analysis."""
        try:
            import openai
            
            # Get API key from environment or config
            api_key = os.environ.get('OPENAI_API_KEY')
            if not api_key:
                # Try to load from config
                config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.json')
                if os.path.exists(config_path):
                    with open(config_path) as f:
                        config = json.load(f)
                        api_key = config.get('openai', {}).get('api_key')
            
            if not api_key:
                logger.warning("No OpenAI API key found, using fallback analysis")
                return None
            
            client = openai.AsyncOpenAI(api_key=api_key)
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert log analyzer. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
    
    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini API for analysis."""
        try:
            import google.generativeai as genai
            
            # Get API key
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
            if not api_key:
                config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.json')
                if os.path.exists(config_path):
                    with open(config_path) as f:
                        config = json.load(f)
                        api_key = config.get('gemini', {}).get('api_key')
            
            if not api_key:
                logger.warning("No Gemini API key found, using fallback analysis")
                return None
            
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=1000
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
    
    def _parse_llm_response(
        self,
        response: str,
        content: str,
        source_file: str,
        start_line: int,
        end_line: int
    ) -> Optional[AnalyzedError]:
        """Parse the LLM response into an AnalyzedError object."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = response.strip()
            if json_str.startswith('```'):
                json_str = re.sub(r'^```(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*```$', '', json_str)
            
            data = json.loads(json_str)
            
            # Generate unique ID
            error_id = hashlib.md5(f"{source_file}:{start_line}:{content[:100]}".encode()).hexdigest()[:12]
            
            # Generate dedup hash
            dedup_hash = self._get_cache_key(content)
            
            return AnalyzedError(
                id=error_id,
                is_real_error=data.get('is_real_error', False),
                confidence=float(data.get('confidence', 0.5)),
                severity=data.get('severity', 'MEDIUM'),
                category=data.get('category', 'Unknown'),
                error_type=data.get('error_type', 'Unknown'),
                title=data.get('title', 'Unknown Error')[:80],
                summary=data.get('summary', ''),
                root_cause=data.get('root_cause', 'Unknown'),
                impact=data.get('impact', 'Unknown'),
                suggested_fix=data.get('suggested_fix', 'Review the logs for more details'),
                related_components=data.get('related_components', []),
                log_snippet=content[:1000],
                line_numbers=(start_line, end_line),
                source_file=source_file,
                timestamp=int(datetime.now().timestamp()),
                dedup_hash=dedup_hash
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")
            return None
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return None
    
    def clear_cache(self):
        """Clear the analysis cache."""
        self._analysis_cache.clear()
        self._embedding_cache.clear()


class AILogAnalyzerService:
    """
    Service wrapper for AI log analysis with batch processing and result storage.
    """
    
    def __init__(self, llm_provider: str = "openai"):
        self.analyzer = AILogAnalyzer(llm_provider=llm_provider)
        self._results_cache: Dict[str, List[AnalyzedError]] = {}
    
    async def analyze_test_logs(
        self,
        run_id: str,
        test_result_id: str,
        log_contents: Dict[str, str],
        test_name: str = "",
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Analyze all logs for a test result.
        
        Args:
            run_id: JITA run ID
            test_result_id: Test result ID
            log_contents: Dict of {source_file: content}
            test_name: Test name
            context: Additional context
            
        Returns:
            Analysis results with all identified errors
        """
        cache_key = f"{run_id}:{test_result_id}"
        
        # Check cache
        if cache_key in self._results_cache:
            cached = self._results_cache[cache_key]
            return {
                "status": "success",
                "cached": True,
                "run_id": run_id,
                "test_result_id": test_result_id,
                "errors": [e.to_dict() for e in cached],
                "total_errors": len(cached)
            }
        
        all_errors = []
        
        # Analyze each log file
        for source_file, content in log_contents.items():
            if not content:
                continue
            
            try:
                errors = await self.analyzer.analyze_log_content(
                    content=content,
                    source_file=source_file,
                    test_name=test_name,
                    context=context
                )
                all_errors.extend(errors)
            except Exception as e:
                logger.error(f"Error analyzing {source_file}: {e}")
        
        # Deduplicate across all files
        unique_errors = self._deduplicate_errors(all_errors)
        
        # Cache results
        self._results_cache[cache_key] = unique_errors
        
        # Build summary
        summary = self._build_summary(unique_errors)
        
        return {
            "status": "success",
            "cached": False,
            "run_id": run_id,
            "test_result_id": test_result_id,
            "errors": [e.to_dict() for e in unique_errors],
            "total_errors": len(unique_errors),
            "summary": summary
        }
    
    def _deduplicate_errors(self, errors: List[AnalyzedError]) -> List[AnalyzedError]:
        """Deduplicate errors based on their dedup_hash."""
        seen = set()
        unique = []
        
        for error in errors:
            if error.dedup_hash not in seen:
                seen.add(error.dedup_hash)
                unique.append(error)
        
        return unique
    
    def _build_summary(self, errors: List[AnalyzedError]) -> Dict[str, Any]:
        """Build a summary of the analysis results."""
        if not errors:
            return {
                "total": 0,
                "by_severity": {},
                "by_category": {},
                "top_issues": []
            }
        
        by_severity = {}
        by_category = {}
        
        for error in errors:
            by_severity[error.severity] = by_severity.get(error.severity, 0) + 1
            by_category[error.category] = by_category.get(error.category, 0) + 1
        
        # Top 5 issues
        top_issues = [
            {
                "title": e.title,
                "severity": e.severity,
                "category": e.category,
                "suggested_fix": e.suggested_fix
            }
            for e in errors[:5]
        ]
        
        return {
            "total": len(errors),
            "by_severity": by_severity,
            "by_category": by_category,
            "top_issues": top_issues
        }
    
    def clear_cache(self, run_id: str = None, test_result_id: str = None):
        """Clear cached results."""
        if run_id and test_result_id:
            cache_key = f"{run_id}:{test_result_id}"
            self._results_cache.pop(cache_key, None)
        elif run_id:
            # Clear all for this run
            keys_to_remove = [k for k in self._results_cache if k.startswith(f"{run_id}:")]
            for key in keys_to_remove:
                del self._results_cache[key]
        else:
            self._results_cache.clear()
        
        self.analyzer.clear_cache()


# Singleton instance
_ai_analyzer_service = None


def get_ai_analyzer_service(llm_provider: str = "openai") -> AILogAnalyzerService:
    """Get or create the AI analyzer service singleton."""
    global _ai_analyzer_service
    if _ai_analyzer_service is None:
        _ai_analyzer_service = AILogAnalyzerService(llm_provider=llm_provider)
    return _ai_analyzer_service
