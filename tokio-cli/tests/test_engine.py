"""
Unit tests for OpenClaw CLI Engine

Run with: pytest tests/test_engine.py -v
"""
import pytest
import asyncio
from datetime import datetime

# Mock imports for testing
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.workspace import Workspace
from engine.error_learner import ErrorLearner
from engine.context_builder import ContextBuilder
from engine.tool_executor import ToolRegistry, ToolResult

# ============================================================================
# Test Workspace
# ============================================================================

def test_workspace_initialization(tmp_path):
    """Test workspace creates required files"""
    workspace = Workspace(workspace_path=str(tmp_path))

    assert workspace.soul_path.exists()
    assert workspace.memory_path.exists()
    assert workspace.config_path.exists()
    assert workspace.tools_path.exists()
    assert workspace.sessions_path.exists()

def test_workspace_read_soul(tmp_path):
    """Test reading SOUL.md"""
    workspace = Workspace(workspace_path=str(tmp_path))

    soul = workspace.read_soul()

    assert "Tokio CLI Agent" in soul
    assert "OpenClaw" in soul

def test_workspace_update_memory(tmp_path):
    """Test updating MEMORY.md"""
    workspace = Workspace(workspace_path=str(tmp_path))

    workspace.update_memory("Test Learning", "This is a test memory entry")

    memory = workspace.read_memory()

    assert "Test Learning" in memory
    assert "This is a test memory entry" in memory

def test_workspace_save_generated_tool(tmp_path):
    """Test saving generated tool"""
    workspace = Workspace(workspace_path=str(tmp_path))

    tool_code = """
def execute(arg1, arg2):
    return f"Result: {arg1} {arg2}"
"""

    workspace.save_generated_tool("test_tool", tool_code)

    assert (workspace.tools_path / "test_tool.py").exists()

# ============================================================================
# Test Error Learner
# ============================================================================

def test_error_learner_record():
    """Test recording errors"""
    learner = ErrorLearner()

    learner.record_error("bash", "Command not found", {"command": "invalid"})

    errors = learner.get_tool_errors("bash")

    assert len(errors) == 1
    assert errors[0]["error"] == "Command not found"

def test_error_learner_failure_count():
    """Test failure counting"""
    learner = ErrorLearner()

    learner.record_error("bash", "Error 1", {})
    learner.record_error("bash", "Error 2", {})

    count = learner.get_failure_count("bash")

    assert count == 2

def test_error_learner_should_retry():
    """Test retry logic"""
    learner = ErrorLearner()

    # First attempt - should retry
    assert learner.should_retry("bash", {"command": "ls"}, 1, 3)

    # Record failure
    learner.record_error("bash", "Failed", {"command": "ls"})

    # Same args failed before - should not retry
    assert not learner.should_retry("bash", {"command": "ls"}, 2, 3)

# ============================================================================
# Test Tool Registry
# ============================================================================

def test_tool_registry_register():
    """Test registering tools"""
    registry = ToolRegistry()

    def test_executor(arg):
        return f"Result: {arg}"

    registry.register_tool(
        name="test_tool",
        description="Test tool",
        category="Test",
        parameters=["arg"],
        executor_func=test_executor
    )

    assert registry.has_tool("test_tool")

    tool = registry.get_tool("test_tool")

    assert tool["name"] == "test_tool"
    assert tool["description"] == "Test tool"

def test_tool_registry_list():
    """Test listing tools"""
    registry = ToolRegistry()

    def test_executor():
        pass

    registry.register_tool("tool1", "Tool 1", "Cat1", [], test_executor)
    registry.register_tool("tool2", "Tool 2", "Cat2", [], test_executor)

    tools = registry.list_tools()

    assert len(tools) == 2
    assert tools[0]["name"] == "tool1"

# ============================================================================
# Test Context Builder
# ============================================================================

@pytest.fixture
def mock_workspace(tmp_path):
    """Mock workspace for testing"""
    return Workspace(workspace_path=str(tmp_path))

@pytest.fixture
def mock_registry():
    """Mock tool registry"""
    registry = ToolRegistry()

    def bash_executor(command):
        return "output"

    registry.register_tool("bash", "Execute bash", "System", ["command"], bash_executor)

    return registry

@pytest.fixture
def mock_error_learner():
    """Mock error learner"""
    return ErrorLearner()

def test_context_builder_system_prompt(mock_workspace, mock_registry, mock_error_learner):
    """Test building system prompt"""
    builder = ContextBuilder(mock_workspace, mock_registry, mock_error_learner)

    prompt = builder.build_system_prompt()

    assert "IDENTITY" in prompt
    assert "MEMORY" in prompt
    assert "TOOLS" in prompt
    assert "bash" in prompt

def test_context_builder_conversation_history(mock_workspace, mock_registry, mock_error_learner):
    """Test building conversation history"""
    builder = ContextBuilder(mock_workspace, mock_registry, mock_error_learner)

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]

    history = builder.build_conversation_context(messages)

    assert "Hello" in history
    assert "Hi there" in history

# ============================================================================
# Test Tool Result
# ============================================================================

def test_tool_result_success():
    """Test successful tool result"""
    result = ToolResult(
        tool_name="bash",
        success=True,
        output="success output",
        execution_time=1.5
    )

    assert result.tool_name == "bash"
    assert result.success is True
    assert result.output == "success output"
    assert result.error is None

def test_tool_result_failure():
    """Test failed tool result"""
    result = ToolResult(
        tool_name="bash",
        success=False,
        output="",
        error="Command failed",
        execution_time=0.5
    )

    assert result.success is False
    assert result.error == "Command failed"

# ============================================================================
# Integration Tests (Async)
# ============================================================================

@pytest.mark.asyncio
async def test_tool_executor_execute_bash():
    """Test executing bash tool"""
    from engine.mcp_client import MCPClient
    from engine.tool_executor import ToolExecutor

    # Mock MCP client
    class MockMCPClient:
        async def list_tools(self):
            return []

        async def find_tool(self, name):
            return None

        def is_connected(self):
            return False

    workspace = Workspace(workspace_path="/tmp/test_workspace")
    mcp_client = MockMCPClient()
    executor = ToolExecutor(workspace, mcp_client)

    # Execute bash tool (should work even without real bash)
    # result = await executor.execute("bash", {"command": "echo test"})

    # For now, just test that executor initializes
    assert executor.registry.has_tool("bash")

# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
