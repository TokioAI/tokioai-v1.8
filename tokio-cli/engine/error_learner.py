"""
Error Learner - OpenClaw Pattern
Records tool failures and learns to avoid repeating the same mistakes
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

class ErrorLearner:
    """
    Tracks tool execution failures and provides context to prevent repeated mistakes.

    OpenClaw Principle: Never repeat the same error twice.
    """

    def __init__(self):
        # Tool -> List of (error_message, timestamp, context)
        self.error_history: Dict[str, List[Dict]] = defaultdict(list)
        # Tool -> Count of failures
        self.failure_counts: Dict[str, int] = defaultdict(int)

    def record_error(
        self,
        tool_name: str,
        error_message: str,
        args: Optional[Dict] = None,
        context: Optional[str] = None
    ):
        """Record a tool execution failure"""
        error_entry = {
            "error": error_message,
            "timestamp": datetime.now().isoformat(),
            "args": args or {},
            "context": context or ""
        }

        self.error_history[tool_name].append(error_entry)
        self.failure_counts[tool_name] += 1

        logger.warning(f"⚠️ Error recorded for tool '{tool_name}': {error_message[:100]}")

    def get_tool_errors(self, tool_name: str) -> List[Dict]:
        """Get all recorded errors for a specific tool"""
        return self.error_history.get(tool_name, [])

    def has_failed_before(self, tool_name: str, args: Dict) -> bool:
        """
        Check if this exact tool+args combination has failed before.

        This helps prevent retrying the same failing operation.
        """
        errors = self.get_tool_errors(tool_name)

        for error in errors:
            if error["args"] == args:
                return True

        return False

    def get_failure_count(self, tool_name: str) -> int:
        """Get total failure count for a tool"""
        return self.failure_counts.get(tool_name, 0)

    def get_error_context_for_prompt(self, tool_name: Optional[str] = None) -> str:
        """
        Generate context string to include in prompt, warning about previous failures.

        If tool_name is provided, returns context specific to that tool.
        Otherwise, returns general failure summary.
        """
        if tool_name:
            errors = self.get_tool_errors(tool_name)

            if not errors:
                return ""

            # Get last 3 errors
            recent_errors = errors[-3:]

            context = f"\n⚠️ **Warning**: The tool '{tool_name}' has failed {len(errors)} time(s) before:\n"

            for i, error in enumerate(recent_errors, 1):
                context += f"\n{i}. Error: {error['error'][:150]}\n"
                if error['args']:
                    context += f"   Args: {error['args']}\n"

            context += "\n**Learn from these failures** and try a different approach.\n"

            return context

        else:
            # General summary
            if not self.failure_counts:
                return ""

            total_failures = sum(self.failure_counts.values())
            failing_tools = sorted(
                self.failure_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]  # Top 5 failing tools

            context = f"\n📊 **Error History**: {total_failures} total failures recorded.\n"
            context += "Top failing tools:\n"

            for tool, count in failing_tools:
                context += f"  - {tool}: {count} failures\n"

            return context

    def get_alternative_suggestion(self, tool_name: str, args: Dict) -> Optional[str]:
        """
        Suggest alternative approaches based on past failures.

        This is a simple heuristic - can be enhanced with LLM-based suggestions.
        """
        errors = self.get_tool_errors(tool_name)

        if not errors:
            return None

        # Common patterns and suggestions
        suggestions = []

        # Check for permission errors
        if any("permission" in e["error"].lower() for e in errors):
            suggestions.append("Try using sudo or checking file permissions")

        # Check for connection errors
        if any("connection" in e["error"].lower() for e in errors):
            suggestions.append("Verify service is running and network connectivity")

        # Check for invalid arguments
        if any("invalid" in e["error"].lower() or "argument" in e["error"].lower() for e in errors):
            suggestions.append("Double-check argument format and types")

        # Check for timeout
        if any("timeout" in e["error"].lower() for e in errors):
            suggestions.append("Consider increasing timeout or breaking into smaller operations")

        if suggestions:
            return " OR ".join(suggestions)

        # Generic suggestion
        return f"Tool '{tool_name}' has failed {len(errors)} times. Consider using a different tool or approach."

    def should_retry(self, tool_name: str, args: Dict, attempt: int, max_attempts: int = 3) -> bool:
        """
        Decide if a tool should be retried based on error history.

        Returns False if:
        - Already at max attempts
        - This exact combination has failed multiple times before
        """
        if attempt >= max_attempts:
            return False

        # Check if this exact operation has failed before
        if self.has_failed_before(tool_name, args):
            # Already tried this exact thing and it failed
            logger.info(f"🚫 Not retrying {tool_name} - exact args failed before")
            return False

        # Check if tool is consistently failing
        if self.get_failure_count(tool_name) > 10:
            logger.warning(f"⚠️ Tool {tool_name} has high failure rate ({self.get_failure_count(tool_name)} failures)")
            # Still allow retry but log warning

        return True

    def clear_tool_errors(self, tool_name: str):
        """Clear error history for a specific tool"""
        if tool_name in self.error_history:
            del self.error_history[tool_name]
        if tool_name in self.failure_counts:
            del self.failure_counts[tool_name]

        logger.info(f"🧹 Cleared error history for {tool_name}")

    def get_summary(self) -> Dict:
        """Get summary statistics of error history"""
        total_failures = sum(self.failure_counts.values())
        total_tools_failed = len(self.failure_counts)

        most_failed = None
        if self.failure_counts:
            most_failed = max(self.failure_counts.items(), key=lambda x: x[1])

        return {
            "total_failures": total_failures,
            "tools_failed": total_tools_failed,
            "most_failed_tool": most_failed[0] if most_failed else None,
            "most_failed_count": most_failed[1] if most_failed else 0,
            "tool_failure_counts": dict(self.failure_counts)
        }
