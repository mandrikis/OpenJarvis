"""Integration tests for LearningOrchestrator agent_id scoping."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.learning.learning_orchestrator import LearningOrchestrator


def test_learning_orchestrator_run_with_agent_id(tmp_path):
    """run(agent_id=...) filters traces to that agent."""
    mock_store = MagicMock()
    mock_store.list_traces.return_value = []

    orchestrator = LearningOrchestrator(
        trace_store=mock_store,
        config_dir=str(tmp_path),
    )

    result = orchestrator.run(agent_id="agent-123")
    assert result["status"] == "skipped"
    # Verify list_traces was called with agent="agent-123"
    calls = mock_store.list_traces.call_args_list
    assert any(call.kwargs.get("agent") == "agent-123" for call in calls)


def test_learning_orchestrator_run_without_agent_id(tmp_path):
    """run() without agent_id uses all traces (backwards compat)."""
    mock_store = MagicMock()
    mock_store.list_traces.return_value = []

    orchestrator = LearningOrchestrator(
        trace_store=mock_store,
        config_dir=str(tmp_path),
    )

    result = orchestrator.run()
    assert result["status"] == "skipped"
