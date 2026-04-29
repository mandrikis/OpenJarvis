"""Tests for DistillationOrchestrator — full session with mocks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.learning.distillation.models import (
    AutonomyMode,
    BenchmarkSnapshot,
    FailureCluster,
    SessionStatus,
)
from openjarvis.learning.distillation.triggers import OnDemandTrigger


def _make_snapshot(overall: float = 0.6) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        benchmark_version="personal_v1",
        overall_score=overall,
        cluster_scores={"c1": overall},
        task_count=10,
        elapsed_seconds=5.0,
    )


def _make_diagnosis_result():
    from openjarvis.learning.distillation.diagnose.runner import DiagnosisResult

    return DiagnosisResult(
        diagnosis_md="## Diagnosis\nMath routing is broken.",
        clusters=[
            FailureCluster(
                id="c1",
                description="Math routing",
                sample_trace_ids=["t1", "t2", "t3"],
                student_failure_rate=0.8,
                teacher_success_rate=0.95,
                skill_gap="needs CoT",
            )
        ],
        cost_usd=0.05,
        tool_call_records=[],
    )


def _make_mock_engine():
    engine = MagicMock()
    engine.generate.return_value = {
        "content": json.dumps(
            {
                "edits": [
                    {
                        "id": "edit-001",
                        "pillar": "intelligence",
                        "op": "set_model_for_query_class",
                        "target": "routing.math",
                        "payload": {
                            "query_class": "math",
                            "model": "qwen2.5-coder:14b",
                        },
                        "rationale": "Route math to bigger model",
                        "expected_improvement": "c1",
                        "risk_tier": "auto",
                        "references": ["t1"],
                    }
                ]
            }
        ),
        "usage": {"total_tokens": 500},
        "cost_usd": 0.03,
        "finish_reason": "stop",
    }
    return engine


class TestDistillationOrchestrator:
    def test_full_session_completes(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.orchestrator import (
            DistillationOrchestrator,
        )

        orch = DistillationOrchestrator(
            teacher_engine=_make_mock_engine(),
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(count=MagicMock(return_value=30)),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_store=MagicMock(),
            checkpoint_store=MagicMock(
                current_sha=MagicMock(return_value="abc123"),
                begin_stage=MagicMock(return_value=MagicMock(pre_stage_sha="abc123")),
            ),
            openjarvis_home=tmp_path,
            autonomy_mode=AutonomyMode.AUTO,
            scorer=lambda **kw: _make_snapshot(0.65),
            benchmark_version="personal_v1",
        )

        with patch(
            "openjarvis.learning.distillation.orchestrator.DiagnosisRunner"
        ) as MockDiag:
            MockDiag.return_value.run.return_value = _make_diagnosis_result()
            session = orch.run(OnDemandTrigger())

        assert session.status in (
            SessionStatus.COMPLETED,
            SessionStatus.AWAITING_REVIEW,
        )
        assert session.teacher_cost_usd >= 0

    def test_cold_start_returns_failed(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.orchestrator import (
            DistillationOrchestrator,
        )

        trace_store = MagicMock()
        trace_store.count.return_value = 5  # Not enough

        orch = DistillationOrchestrator(
            teacher_engine=MagicMock(),
            teacher_model="claude-opus-4-6",
            trace_store=trace_store,
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_store=MagicMock(),
            checkpoint_store=MagicMock(
                current_sha=MagicMock(return_value="abc123"),
            ),
            openjarvis_home=tmp_path,
            autonomy_mode=AutonomyMode.TIERED,
            scorer=lambda **kw: _make_snapshot(),
            benchmark_version="personal_v1",
        )

        session = orch.run(OnDemandTrigger())
        assert session.status == SessionStatus.FAILED
        assert "not enough traces" in (session.error or "").lower()

    def test_session_persisted_to_store(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.orchestrator import (
            DistillationOrchestrator,
        )

        session_store = MagicMock()

        orch = DistillationOrchestrator(
            teacher_engine=_make_mock_engine(),
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(count=MagicMock(return_value=30)),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_store=session_store,
            checkpoint_store=MagicMock(
                current_sha=MagicMock(return_value="abc123"),
                begin_stage=MagicMock(return_value=MagicMock(pre_stage_sha="abc123")),
            ),
            openjarvis_home=tmp_path,
            autonomy_mode=AutonomyMode.AUTO,
            scorer=lambda **kw: _make_snapshot(0.65),
            benchmark_version="personal_v1",
        )

        with patch(
            "openjarvis.learning.distillation.orchestrator.DiagnosisRunner"
        ) as MockDiag:
            MockDiag.return_value.run.return_value = _make_diagnosis_result()
            orch.run(OnDemandTrigger())

        assert session_store.save_session.called

    def test_config_only_skips_prompt_and_few_shot_edits(
        self, tmp_path: Path
    ) -> None:
        """In config_only mode, prompt/few-shot edits are never applied."""
        from openjarvis.learning.distillation.orchestrator import (
            DistillationOrchestrator,
        )

        # Engine returns one allowed (intelligence) edit + one prompt edit
        # + one few-shot edit. Only the intelligence one should apply.
        engine = MagicMock()
        engine.generate.return_value = {
            "content": json.dumps(
                {
                    "edits": [
                        {
                            "id": "edit-allowed",
                            "pillar": "intelligence",
                            "op": "set_model_for_query_class",
                            "target": "routing.math",
                            "payload": {
                                "query_class": "math",
                                "model": "qwen2.5-coder:14b",
                            },
                            "rationale": "ok",
                            "expected_improvement": "c1",
                            "risk_tier": "auto",
                            "references": ["t1"],
                        },
                        {
                            "id": "edit-prompt",
                            "pillar": "agent",
                            "op": "replace_system_prompt",
                            "target": "agents.simple.system_prompt",
                            "payload": {"new_content": "hello"},
                            "rationale": "should be skipped",
                            "expected_improvement": "c1",
                            "risk_tier": "auto",
                            "references": ["t1"],
                        },
                        {
                            "id": "edit-fewshot",
                            "pillar": "agent",
                            "op": "edit_few_shot_exemplars",
                            "target": "agents.native_react.few_shot",
                            "payload": {
                                "agent": "native_react",
                                "exemplars": [{"input": "Q", "output": "A"}],
                            },
                            "rationale": "should be skipped",
                            "expected_improvement": "c1",
                            "risk_tier": "auto",
                            "references": ["t1"],
                        },
                    ]
                }
            ),
            "usage": {"total_tokens": 500},
            "cost_usd": 0.03,
            "finish_reason": "stop",
        }

        orch = DistillationOrchestrator(
            teacher_engine=engine,
            teacher_model="claude-opus-4-6",
            trace_store=MagicMock(count=MagicMock(return_value=30)),
            benchmark_samples=[],
            student_runner=MagicMock(),
            judge=MagicMock(),
            session_store=MagicMock(),
            checkpoint_store=MagicMock(
                current_sha=MagicMock(return_value="abc123"),
                begin_stage=MagicMock(
                    return_value=MagicMock(pre_stage_sha="abc123")
                ),
            ),
            openjarvis_home=tmp_path,
            autonomy_mode=AutonomyMode.AUTO,
            scorer=lambda **kw: _make_snapshot(0.65),
            benchmark_version="personal_v1",
            config_only=True,
        )

        with patch(
            "openjarvis.learning.distillation.orchestrator.DiagnosisRunner"
        ) as MockDiag:
            MockDiag.return_value.run.return_value = _make_diagnosis_result()
            session = orch.run(OnDemandTrigger())

        by_id = {o.edit_id: o for o in session.edit_outcomes}
        assert by_id["edit-prompt"].status == "skipped"
        assert "config_only" in (by_id["edit-prompt"].error or "")
        assert by_id["edit-fewshot"].status == "skipped"
        assert "config_only" in (by_id["edit-fewshot"].error or "")
        # The non-prompt edit should NOT have been blocked by config_only.
        assert by_id["edit-allowed"].status != "skipped" or "config_only" not in (
            by_id["edit-allowed"].error or ""
        )
