"""
JITA AI-Powered Log Analyzer

This service directly analyzes raw logs from JITA HTTP endpoints using AI.
No regex-based parsing - the AI identifies real issues, root causes, and fixes.

Flow:
1. Fetch raw log URLs from JITA test result
2. Download raw log content from log servers
3. Send to AI for intelligent analysis
4. Return structured error analysis with root cause and fixes
"""

import os
import json
import hashlib
import asyncio
import requests
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import logging
import re
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


@dataclass
class AIError:
    """Represents an AI-identified error from JITA logs."""
    error_id: str
    test_result_id: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    category: str  # Infrastructure, Network, Test Framework, etc.
    error_type: str  # Specific type like ConnectionTimeout, AssertionError
    title: str  # Short descriptive title (max 80 chars)
    summary: str  # What happened (1-2 sentences)
    root_cause: str  # Why it happened
    impact: str  # What is affected
    suggested_fix: str  # Actionable steps to fix
    confidence: float  # 0.0 to 1.0
    log_source: str  # Which log file
    log_snippet: str  # Relevant log excerpt
    line_range: str  # Line numbers in original log
    related_components: List[str] = field(default_factory=list)
    log_url: str = ""  # URL to raw log
    created_at: int = field(default_factory=lambda: int(datetime.now().timestamp()))
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def to_db_tuple(self) -> Tuple:
        """Convert to tuple for database insertion."""
        return (
            self.error_id,
            self.test_result_id,
            self.severity,
            self.category,
            self.error_type,
            self.title,
            self.summary,
            self.root_cause,
            self.impact,
            self.suggested_fix,
            self.confidence,
            self.log_source,
            self.log_snippet,
            self.line_range,
            json.dumps(self.related_components),
            self.log_url,
            self.created_at
        )


class JitaAIAnalyzer:
    """
    AI-powered JITA log analyzer that fetches and analyzes raw logs.
    
    Key features:
    1. Direct log fetching from JITA HTTP endpoints
    2. AI-based error detection (no regex)
    3. Root cause analysis
    4. Impact assessment
    5. Fix suggestions
    """
    
    # Log files to analyze (in priority order)
    KEY_LOG_FILES = [
        'nutest_test.log',      # Main test log - highest priority
        'nutest.log',           # NuTest framework log
        'nutest_webserver.log', # Web server log
        'setup.log',            # Setup phase log
        'teardown.log',         # Teardown phase log
    ]
    
    # Subdirectories that might contain useful logs
    LOG_SUBDIRS = ['logs/', 'logbay/']
    
    # Maximum log content size to send to AI (in characters)
    MAX_LOG_SIZE = 50000
    
    # Maximum number of log files to analyze per test
    MAX_LOG_FILES = 8
    
    def __init__(self):
        """Initialize the JITA AI analyzer."""
        self._config = self._load_config()
        self._log_url_cache: Dict[str, str] = {}
        self._session = requests.Session()
        self._session.auth = ("agave_bot", "admin")
        self._session.headers.update({
            "User-Agent": "NOVA-AI-Analyzer/1.0"
        })
    
    def _load_config(self) -> Dict:
        """Load config from config.json"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.json')
            if os.path.exists(config_path):
                with open(config_path) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load config: {e}")
        return {}
    
    async def analyze_test(
        self,
        run_id: str,
        test_result: Dict,
        include_raw_logs: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze a test result using AI.
        
        Args:
            run_id: JITA run ID
            test_result: Test result data from JITA API
            include_raw_logs: Whether to include raw log URLs in response
            
        Returns:
            Analysis result with AI-identified errors
        """
        test_result_id = test_result.get('_id', test_result.get('id', 'unknown'))
        test_name = test_result.get('testcase', test_result.get('test_name', 'Unknown'))
        
        logger.info(f"AI analyzing test: {test_name} ({test_result_id})")
        
        # Build context from test result
        context = self._build_test_context(test_result)
        
        # Get log URLs
        log_urls = self._extract_log_urls(test_result)
        logger.info(f"Found {len(log_urls)} log URLs for test")
        
        # Fetch and analyze logs
        all_errors: List[AIError] = []
        analyzed_logs: List[Dict] = []
        
        # First, analyze the test exception directly if present
        exception_errors = await self._analyze_test_exception(
            run_id, test_result_id, test_result, context
        )
        all_errors.extend(exception_errors)
        
        # Then analyze each log source
        for log_type, log_url in log_urls.items():
            try:
                resolved_url = self._resolve_jita_log_url(log_url)
                if not resolved_url:
                    continue
                
                # Fetch log content
                log_content = self._fetch_log_content(resolved_url)
                if not log_content:
                    continue
                
                analyzed_logs.append({
                    "log_type": log_type,
                    "log_url": log_url,
                    "resolved_url": resolved_url,
                    "content_size": len(log_content)
                })
                
                # Analyze with AI
                errors = await self._analyze_log_content(
                    run_id=run_id,
                    test_result_id=test_result_id,
                    content=log_content,
                    log_source=log_type,
                    log_url=resolved_url,
                    test_name=test_name,
                    context=context
                )
                all_errors.extend(errors)
                
            except Exception as e:
                logger.error(f"Error analyzing {log_type}: {e}")
        
        # Deduplicate errors
        unique_errors = self._deduplicate_errors(all_errors)
        
        # Sort by severity and confidence
        unique_errors.sort(key=lambda e: (
            {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}.get(e.severity, 4),
            -e.confidence
        ))
        
        # Build summary
        summary = self._build_summary(unique_errors)
        
        result = {
            "status": "success",
            "run_id": run_id,
            "test_result_id": test_result_id,
            "test_name": test_name,
            "test_status": test_result.get('status', 'Unknown'),
            "errors": [e.to_dict() for e in unique_errors],
            "total_errors": len(unique_errors),
            "summary": summary,
            "analyzed_logs": analyzed_logs if include_raw_logs else len(analyzed_logs)
        }
        
        return result
    
    def _build_test_context(self, test_result: Dict) -> Dict[str, Any]:
        """Build context information from test result."""
        # Handle exception which can be string or dict
        exception = test_result.get('exception', {})
        if isinstance(exception, str):
            exception_summary = exception
        elif isinstance(exception, dict):
            exception_summary = exception.get('message', '') or exception.get('msg', '')
        else:
            exception_summary = str(exception) if exception else ''
        
        return {
            "test_status": test_result.get('status', 'Unknown'),
            "test_name": test_result.get('testcase', ''),
            "cluster_info": test_result.get('cluster_name', ''),
            "duration": test_result.get('duration', 0),
            "exception_summary": exception_summary,
            "total_ops": test_result.get('total_ops', 0),
            "successful_ops": test_result.get('successful_ops', 0),
        }
    
    def _extract_log_urls(self, test_result: Dict) -> Dict[str, str]:
        """Extract log URLs from test result."""
        urls = {}
        
        # Main test log
        if test_result.get('test_log_url'):
            urls['test_log'] = test_result['test_log_url']
        
        # Scheduler logs
        if test_result.get('scheduler_logs'):
            urls['scheduler_log'] = test_result['scheduler_logs']
        
        # Tester log
        if test_result.get('tester_log_url'):
            urls['tester_log'] = test_result['tester_log_url']
        
        # Plugin logs
        if test_result.get('plugin_log_url'):
            urls['plugin_log'] = test_result['plugin_log_url']
        
        return urls
    
    def _resolve_jita_log_url(self, jita_url: str) -> Optional[str]:
        """Resolve JITA API log URL to get the actual log server URL."""
        if jita_url in self._log_url_cache:
            return self._log_url_cache[jita_url]
        
        try:
            response = self._session.head(jita_url, allow_redirects=False, timeout=10)
            
            if response.status_code in [301, 302, 303, 307, 308]:
                location = response.headers.get('Location', '')
                if location:
                    self._log_url_cache[jita_url] = location
                    return location
            
            # Fallback: parse URL parameters
            return self._parse_jita_url_fallback(jita_url)
            
        except Exception as e:
            logger.warning(f"Error resolving JITA URL: {e}")
            return self._parse_jita_url_fallback(jita_url)
    
    def _parse_jita_url_fallback(self, jita_url: str) -> Optional[str]:
        """Fallback URL parsing when redirect doesn't work."""
        try:
            parsed = urlparse(jita_url)
            params = parse_qs(parsed.query)
            log_path = params.get('url', [''])[0]
            
            if log_path:
                return f"http://10.46.1.200{log_path}"
            return None
        except Exception:
            return None
    
    def _fetch_log_content(self, url: str, max_size: int = None) -> Optional[str]:
        """Fetch raw log content from URL."""
        max_size = max_size or self.MAX_LOG_SIZE
        
        try:
            response = self._session.get(url, timeout=60, stream=True)
            if response.status_code != 200:
                return None
            
            # Read with size limit
            content = ""
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                if chunk:
                    content += chunk
                    if len(content) >= max_size:
                        # Get last portion for large files (tail)
                        content = content[-max_size:]
                        break
            
            return content
            
        except Exception as e:
            logger.error(f"Error fetching log from {url}: {e}")
            return None
    
    async def _analyze_test_exception(
        self,
        run_id: str,
        test_result_id: str,
        test_result: Dict,
        context: Dict
    ) -> List[AIError]:
        """Analyze the test exception directly from test result."""
        errors = []
        
        # Handle exception which can be string or dict
        exception = test_result.get('exception', {})
        if isinstance(exception, str):
            exception_message = exception
            exception_trace = ''
        elif isinstance(exception, dict):
            exception_message = exception.get('message', '') or exception.get('msg', '')
            exception_trace = exception.get('stack_trace', '') or exception.get('stackTrace', '') or exception.get('traceback', '')
        else:
            exception_message = str(exception) if exception else ''
            exception_trace = ''
        
        if not exception_message and not exception_trace:
            return errors
        
        # Build exception content
        content = f"""=== TEST RESULT ===
Status: {test_result.get('status', 'Unknown')}
Test: {test_result.get('testcase', 'Unknown')}

=== EXCEPTION ===
Message: {exception_message}

Stack Trace:
{exception_trace or 'No stack trace available'}
"""
        
        # Analyze with AI
        ai_errors = await self._analyze_log_content(
            run_id=run_id,
            test_result_id=test_result_id,
            content=content,
            log_source="test_exception",
            log_url="",
            test_name=test_result.get('testcase', ''),
            context=context
        )
        
        return ai_errors
    
    async def _analyze_log_content(
        self,
        run_id: str,
        test_result_id: str,
        content: str,
        log_source: str,
        log_url: str,
        test_name: str,
        context: Dict
    ) -> List[AIError]:
        """Analyze log content using AI."""
        if not content or len(content.strip()) < 20:
            return []
        
        # Build the AI prompt
        prompt = self._build_analysis_prompt(content, log_source, test_name, context)
        
        # Call the AI
        response = await self._call_ai(prompt)
        if not response:
            return []
        
        # Parse the response
        errors = self._parse_ai_response(
            response=response,
            run_id=run_id,
            test_result_id=test_result_id,
            log_source=log_source,
            log_url=log_url,
            content=content
        )
        
        return errors
    
    def _build_analysis_prompt(
        self,
        content: str,
        log_source: str,
        test_name: str,
        context: Dict
    ) -> str:
        """Build the prompt for AI analysis."""
        
        prompt = f"""You are an expert log analyzer for Nutanix distributed systems test automation (NuTest).
Analyze the following raw log content and identify ALL real errors that caused or indicate test failures.

CONTEXT:
- Log Source: {log_source}
- Test Name: {test_name}
- Test Status: {context.get('test_status', 'Unknown')}
- Cluster: {context.get('cluster_info', 'Unknown')}
- Duration: {context.get('duration', 0)} seconds
- Operations: {context.get('successful_ops', 0)}/{context.get('total_ops', 0)} successful

INSTRUCTIONS:
1. Identify REAL errors that caused problems (not false positives like "error_count=0")
2. For each error found, provide detailed analysis
3. Focus on actionable issues that explain why the test failed
4. Group similar errors together - don't repeat the same error type multiple times

RAW LOG CONTENT:
```
{content[:self.MAX_LOG_SIZE]}
```

Respond with a JSON object containing an array of errors:

{{
    "errors": [
        {{
            "severity": "CRITICAL|HIGH|MEDIUM|LOW",
            "category": "Infrastructure|Network|Test Framework|Configuration|Resource|Authentication|Database|Application",
            "error_type": "specific error type name (e.g., AssertionError, ConnectionTimeout)",
            "title": "short descriptive title (max 80 chars)",
            "summary": "what happened in 1-2 sentences",
            "root_cause": "detailed explanation of why this happened",
            "impact": "what systems/tests are affected",
            "suggested_fix": "specific actionable steps to resolve",
            "confidence": 0.0-1.0,
            "related_components": ["list", "of", "affected", "components"],
            "log_snippet": "relevant excerpt from the log (max 500 chars)",
            "line_hint": "approximate location in log (e.g., 'near line 150' or 'at start')"
        }}
    ],
    "summary": {{
        "total_issues": number,
        "primary_cause": "main reason for test failure in one sentence",
        "recommended_action": "most important thing to do first"
    }}
}}

If no real errors are found, return {{"errors": [], "summary": {{"total_issues": 0, "primary_cause": "No issues detected", "recommended_action": "None"}}}}

Respond ONLY with the JSON object, no other text."""

        return prompt
    
    async def _call_ai(self, prompt: str) -> Optional[str]:
        """Call the AI service for analysis."""
        try:
            import httpx
            
            llm_config = self._config.get('llm', {})
            api_key = llm_config.get('hackathon_api_key')
            base_url = llm_config.get('base_url', 'https://hkn12.ai.nutanix.com/enterpriseai/v1/')
            model = llm_config.get('model', 'hack-reason')
            
            if not api_key:
                logger.error("No AI API key configured")
                return None
            
            url = f"{base_url.rstrip('/')}/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert log analyzer. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 4000
            }
            
            logger.info(f"Calling AI service at {url}")
            
            async with httpx.AsyncClient(timeout=180.0, verify=False) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"AI service error: {response.status_code}")
                    return None
                
                data = response.json()
                result = data.get('choices', [{}])[0].get('message', {}).get('content', '')
                logger.info(f"AI response received ({len(result)} chars)")
                return result
                
        except Exception as e:
            logger.error(f"AI service error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _parse_ai_response(
        self,
        response: str,
        run_id: str,
        test_result_id: str,
        log_source: str,
        log_url: str,
        content: str
    ) -> List[AIError]:
        """Parse AI response into AIError objects."""
        errors = []
        
        try:
            # Clean response
            json_str = response.strip()
            if json_str.startswith('```'):
                json_str = re.sub(r'^```(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*```$', '', json_str)
            
            data = json.loads(json_str)
            
            for i, error_data in enumerate(data.get('errors', [])):
                error_id = hashlib.md5(
                    f"{run_id}:{test_result_id}:{log_source}:{i}:{error_data.get('title', '')}".encode()
                ).hexdigest()[:12]
                
                error = AIError(
                    error_id=error_id,
                    test_result_id=test_result_id,
                    severity=error_data.get('severity', 'MEDIUM'),
                    category=error_data.get('category', 'Unknown'),
                    error_type=error_data.get('error_type', 'Unknown'),
                    title=error_data.get('title', 'Unknown Error')[:80],
                    summary=error_data.get('summary', ''),
                    root_cause=error_data.get('root_cause', 'Unknown'),
                    impact=error_data.get('impact', 'Unknown'),
                    suggested_fix=error_data.get('suggested_fix', 'Review logs'),
                    confidence=float(error_data.get('confidence', 0.5)),
                    log_source=log_source,
                    log_snippet=error_data.get('log_snippet', '')[:1000],
                    line_range=error_data.get('line_hint', ''),
                    related_components=error_data.get('related_components', []),
                    log_url=log_url
                )
                errors.append(error)
                
                logger.info(f"AI found: [{error.severity}] {error.title}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            logger.debug(f"Response: {response[:500]}")
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
        
        return errors
    
    def _deduplicate_errors(self, errors: List[AIError]) -> List[AIError]:
        """Deduplicate similar errors."""
        seen_hashes = set()
        unique = []
        
        for error in errors:
            # Create hash from title and error type
            hash_content = f"{error.error_type}:{error.title}:{error.category}"
            content_hash = hashlib.md5(hash_content.encode()).hexdigest()[:16]
            
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique.append(error)
        
        return unique
    
    def _build_summary(self, errors: List[AIError]) -> Dict[str, Any]:
        """Build analysis summary."""
        if not errors:
            return {
                "total": 0,
                "by_severity": {},
                "by_category": {},
                "primary_cause": "No issues detected",
                "top_issues": []
            }
        
        by_severity = {}
        by_category = {}
        
        for error in errors:
            by_severity[error.severity] = by_severity.get(error.severity, 0) + 1
            by_category[error.category] = by_category.get(error.category, 0) + 1
        
        # Primary cause is the first (highest severity) error
        primary = errors[0] if errors else None
        
        return {
            "total": len(errors),
            "by_severity": by_severity,
            "by_category": by_category,
            "primary_cause": primary.summary if primary else "Unknown",
            "top_issues": [
                {
                    "title": e.title,
                    "severity": e.severity,
                    "category": e.category,
                    "root_cause": e.root_cause,
                    "suggested_fix": e.suggested_fix
                }
                for e in errors[:5]
            ]
        }


# Singleton instance
_jita_ai_analyzer = None


def get_jita_ai_analyzer() -> JitaAIAnalyzer:
    """Get or create the JITA AI analyzer singleton."""
    global _jita_ai_analyzer
    if _jita_ai_analyzer is None:
        _jita_ai_analyzer = JitaAIAnalyzer()
    return _jita_ai_analyzer
