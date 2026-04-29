#!/usr/bin/env python3
"""Gather consensus edits from learning-session plan.json files.

Walks ``<sessions_root>/<session_id>/plan.json`` (default
``~/.openjarvis/learning/sessions``), counts votes per
``(op, target, payload-value)`` tuple across every plan, applies a majority
threshold, and writes a single ``consensus_edits.json`` that the apply step
consumes.

Inputs (one of):
    --sessions-root <dir>   Walk plan.json files under this directory (default).
    --tallies-file <json>   Skip walking; read pre-aggregated tallies (the
                            shape produced by --emit-tallies). Useful when the
                            session directory is on another machine or when
                            reproducing a historical snapshot.

Output:
    <out>/consensus_edits.json   Final consensus edits (read by apply step).
                                 Includes a ``deferred_to_m3`` block listing
                                 free-text ops (prompt patches, few-shot
                                 exemplars, tool descriptions) that cannot be
                                 merged by majority voting and are recorded
                                 verbatim for the M3 hill-climber to consume
                                 as candidate seeds.
    <out>/raw_tallies.json       Full per-(op, target, value) vote counts plus
                                 an ``audit_tallies`` section for the deferred
                                 free-text ops.
    <out>/raw_edits.jsonl        One row per edit found (audit trail).

Why this exists: the consensus values used by m2 used to be hard-coded in
m2_create_distilled_configs.py (DISTILLED_TEMP, DISTILLED_MAX_TURNS,
REMOVE_TOOLS). That meant the analysis was off-tree and unreproducible. This
script makes the tally reproducible and the consensus edits a data artifact.
"""

from __future__ import annotations


# distill-streaming-fix
import logging as _logging
import sys as _sys
try:
    _sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except AttributeError:
    pass
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=_sys.stdout,
    force=True,
)

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SESSIONS_ROOT = Path.home() / ".openjarvis" / "learning" / "sessions"


@dataclass
class EditKey:
    """A (op, target, value) tuple identifying one distinct edit proposal."""

    op: str
    target: str
    value: str  # JSON-serialised payload value (or tool name for add/remove tool)

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.op, self.target, self.value)


@dataclass
class Tally:
    op: str
    target: str
    value: Any
    votes: int = 0
    sample_session_ids: list[str] = field(default_factory=list)


# ── Edit-row extraction ──────────────────────────────────────────────────────


def edit_to_key(edit: dict) -> EditKey | None:
    """Reduce an Edit dict to a vote key.

    Returns None for ops we don't tally (e.g. lora_finetune, prompt patches,
    where the value space is too sparse for plain majority voting).
    """
    op = edit.get("op")
    target = edit.get("target", "")
    payload = edit.get("payload") or {}

    if op in ("add_tool_to_agent", "remove_tool_from_agent"):
        tool = payload.get("tool_name") or payload.get("name") or payload.get("tool")
        if not tool:
            return None
        return EditKey(op=op, target=target, value=str(tool))

    if op == "set_agent_param":
        param = payload.get("param") or payload.get("name")
        value = payload.get("value")
        if param is None or value is None:
            return None
        # Bucket numeric temperature values (0.21 → "0.2") so close votes
        # collapse onto the same bin.
        if param == "temperature" and isinstance(value, (int, float)):
            value = round(float(value), 1)
        return EditKey(op=op, target=f"{target}.{param}", value=json.dumps(value))

    if op == "set_model_param":
        param = payload.get("param") or payload.get("name")
        value = payload.get("value")
        if param is None or value is None:
            return None
        return EditKey(op=op, target=f"{target}.{param}", value=json.dumps(value))

    if op == "set_agent_class":
        # Applier reads payload["new_class"]; target is the agent name.
        new_class = payload.get("new_class")
        if new_class is None:
            return None
        return EditKey(op=op, target=target, value=json.dumps(new_class))

    if op == "set_model_for_query_class":
        # Applier reads payload["query_class"] and payload["model"]; bucket as
        # (op, target=query_class, value=model) so the consensus row reads as
        # "for query class X, the consensus model is Y."
        query_class = payload.get("query_class")
        model = payload.get("model")
        if query_class is None or model is None:
            return None
        return EditKey(op=op, target=str(query_class), value=json.dumps(model))

    # Free-text ops (prompt patches, few-shot, tool descriptions) and lora are
    # handled by edit_to_audit_key / lora_finetune is excluded entirely.
    return None


# Free-text ops that we record verbatim instead of merging by majority vote.
# M3 hill-climber consumes these as candidate seeds.
DEFERRED_OPS: tuple[str, ...] = (
    "patch_system_prompt",
    "replace_system_prompt",
    "edit_few_shot_exemplars",
    "edit_tool_description",
)


def edit_to_audit_key(edit: dict) -> EditKey | None:
    """Reduce a free-text edit to an audit key for exact-payload tallying.

    Returns None for ops not in DEFERRED_OPS. The value is the full payload
    JSON-serialised with sorted keys so identical payloads collapse onto a
    single row regardless of dict ordering.
    """
    op = edit.get("op")
    if op not in DEFERRED_OPS:
        return None
    target = edit.get("target", "")
    payload = edit.get("payload") or {}
    try:
        value = json.dumps(payload, sort_keys=True)
    except TypeError:
        value = repr(payload)
    return EditKey(op=op, target=target, value=value)


def walk_plans(sessions_root: Path) -> list[tuple[str, dict]]:
    """Return [(session_id, edit), ...] across every plan.json under root.

    Recurses into subdirectories so a parent dir containing multiple
    ensembles (each with its own ``sessions/`` subtree) walks them all.
    Symlinks are followed.
    """
    out: list[tuple[str, dict]] = []
    if not sessions_root.exists():
        print(f"WARN: sessions root does not exist: {sessions_root}", file=sys.stderr)
        return out

    seen: set[str] = set()
    for plan_path in sorted(sessions_root.rglob("plan.json")):
        try:
            real = str(plan_path.resolve())
        except OSError:
            real = str(plan_path)
        if real in seen:
            continue
        seen.add(real)
        session_id = plan_path.parent.name
        try:
            plan = json.loads(plan_path.read_text())
        except Exception as e:
            print(f"WARN: failed to read {plan_path}: {e}", file=sys.stderr)
            continue
        for edit in plan.get("edits", []):
            out.append((session_id, edit))
    return out


# ── Tally + threshold ────────────────────────────────────────────────────────


def tally_edits(edits: list[tuple[str, dict]]) -> dict[tuple[str, str, str], Tally]:
    tallies: dict[tuple[str, str, str], Tally] = {}
    for session_id, edit in edits:
        key = edit_to_key(edit)
        if key is None:
            continue
        try:
            value: Any = json.loads(key.value)
        except (json.JSONDecodeError, TypeError):
            value = key.value
        t = tallies.setdefault(
            key.as_tuple(),
            Tally(op=key.op, target=key.target, value=value),
        )
        t.votes += 1
        if len(t.sample_session_ids) < 5:
            t.sample_session_ids.append(session_id)
    return tallies


def audit_tally_edits(
    edits: list[tuple[str, dict]],
) -> dict[tuple[str, str, str], Tally]:
    """Tally exact-payload occurrences for free-text ops in DEFERRED_OPS."""
    tallies: dict[tuple[str, str, str], Tally] = {}
    for session_id, edit in edits:
        key = edit_to_audit_key(edit)
        if key is None:
            continue
        # Decode payload back to a dict for downstream consumers; fall back to
        # the raw string if it isn't JSON for any reason.
        try:
            payload: Any = json.loads(key.value)
        except (json.JSONDecodeError, TypeError):
            payload = key.value
        t = tallies.setdefault(
            key.as_tuple(),
            Tally(op=key.op, target=key.target, value=payload),
        )
        t.votes += 1
        if len(t.sample_session_ids) < 5:
            t.sample_session_ids.append(session_id)
    return tallies


def pick_consensus(
    tallies: dict[tuple[str, str, str], Tally],
    *,
    min_votes: int,
    min_majority: float,
) -> dict[str, Any]:
    """Pick the majority value per (op, target) group.

    For numeric/scalar ops (set_agent_param, set_model_param): the value with
    the most votes wins, provided it has both >= min_votes votes AND
    >= min_majority share among all votes for that (op, target) group.

    For tool ops (add/remove): every (op, target, tool) tuple with >= min_votes
    is included independently (you can remove multiple tools).
    """
    # Group by (op, target)
    by_group: dict[tuple[str, str], list[Tally]] = defaultdict(list)
    for t in tallies.values():
        by_group[(t.op, t.target)].append(t)

    consensus_scalar: list[dict] = []
    consensus_tools: dict[str, list[dict]] = {
        "add_tool_to_agent": [],
        "remove_tool_from_agent": [],
    }

    for (op, target), group in by_group.items():
        total = sum(t.votes for t in group)
        if op in consensus_tools:
            for t in group:
                if t.votes >= min_votes:
                    consensus_tools[op].append(
                        {
                            "target": target,
                            "tool_name": t.value,
                            "votes": t.votes,
                            "total_votes_in_group": total,
                        }
                    )
        else:
            winner = max(group, key=lambda t: t.votes)
            share = winner.votes / total if total else 0.0
            if winner.votes >= min_votes and share >= min_majority:
                consensus_scalar.append(
                    {
                        "op": op,
                        "target": target,
                        "value": winner.value,
                        "votes": winner.votes,
                        "total_votes_in_group": total,
                        "majority_share": round(share, 3),
                    }
                )

    return {
        "scalar_edits": consensus_scalar,
        "add_tools": consensus_tools["add_tool_to_agent"],
        "remove_tools": consensus_tools["remove_tool_from_agent"],
    }


# ── LLM-select best deferred-text candidate ──────────────────────────────────


_LLM_SELECT_SYSTEM = """You are given N candidate edits, all proposed
independently by different teacher models for the SAME target (e.g. a
system prompt for one agent, a description for one tool, a few-shot set
for one agent).

Your job: identify the consensus — what most candidates agree on — and
pick the single candidate that best represents that consensus. Think of
it as the median, not the most opinionated outlier.

Look for ideas / instructions / structures that recur across candidates;
pick the candidate that captures the most of those recurring ideas with
the least idiosyncratic content.

Output ONLY a JSON object on its own line:
{"selected_idx": <int>, "reason": "<one short sentence>"}
"""


def _summarize_payload(op: str, payload: dict) -> str:
    """Truncate large payloads for inclusion in the LLM-select prompt."""
    if op == "replace_system_prompt":
        s = (payload or {}).get("new_content", "") or ""
        return s if len(s) < 2000 else s[:2000] + " …[truncated]"
    if op == "edit_few_shot_exemplars":
        ex = (payload or {}).get("exemplars") or []
        if not ex:
            return "(empty)"
        first = ex[0]
        inp = (first.get("input") or "")[:200]
        out = (first.get("output") or "")[:600]
        n = len(ex)
        return f"[{n} exemplar(s)] input: {inp!r}\\noutput: {out!r}"
    if op == "edit_tool_description":
        return ((payload or {}).get("new_description") or "")[:1500]
    return json.dumps(payload, ensure_ascii=False)[:1500]


_LLM_SYNTHESIZE_SYSTEM_PROMPT = """You are given N candidate system prompts,
each proposed independently by a different teacher model for the SAME agent.
Your job is to write ONE new system prompt that synthesizes the recurring
themes across the candidates.

Rules:
- Combine ideas, instructions, and structure that recur across multiple
  candidates. The more candidates a theme appears in, the more weight it
  carries.
- Drop idiosyncratic content that only appears in one or two candidates,
  unless it directly resolves a failure mode the rest hint at.
- Do not invent constraints that no candidate proposed (e.g. arbitrary turn
  caps, search limits) — only carry forward constraints that have consensus
  support.
- Keep the prompt clear and self-consistent. No contradictions.
- Match the candidates' general length and tone.

Output ONLY a JSON object on its own line:
{"new_content": "<the synthesized system prompt>", "reason": "<one short sentence on what you combined>"}
"""


_LLM_SYNTHESIZE_TOOL_DESC = """You are given N candidate descriptions for the
SAME tool, each proposed independently by a different teacher model. Write
ONE new description that synthesizes the recurring guidance.

Rules:
- Capture what the tool does, when to use it, and any usage cautions that
  recur across candidates.
- Drop idiosyncratic phrasing that appears only in one candidate.
- Keep it concise — match the candidates' typical length.

Output ONLY a JSON object on its own line:
{"new_description": "<the synthesized tool description>", "reason": "<one short sentence>"}
"""


_LLM_SYNTHESIZE_FEW_SHOT = """You are given N candidate few-shot exemplar
sets for the SAME agent, each proposed independently by a different teacher
model. Write ONE new set of exemplars that synthesizes the recurring
patterns.

Rules:
- Identify the patterns that recur across candidates: input shape, expected
  reasoning structure, output format, tool-use cadence.
- Write NEW exemplars (input + output pairs) that exhibit those recurring
  patterns. Do not copy verbatim from any single candidate; synthesize.
- Match the typical number of exemplars across candidates (round to the
  median if they vary).
- Keep exemplars realistic — inputs the agent would plausibly receive,
  outputs that demonstrate the consensus reasoning style.
- Do not invent factual claims; if the candidate exemplars use placeholder
  facts, your exemplars may do the same.

Output ONLY a JSON object on its own line:
{"exemplars": [{"input": "<>", "output": "<>"}, ...], "reason": "<one short sentence>"}
"""


def _build_synthesis_prompt(op: str, target: str, candidates: list[dict]) -> str:
    """Render the candidate list into a user prompt for the synthesizer."""
    blocks: list[str] = []
    for i, c in enumerate(candidates):
        summary = _summarize_payload(op, c.get("payload") or {})
        votes = c.get("votes", 1)
        sids = (c.get("sample_session_ids") or [])[:3]
        blocks.append(
            f"--- candidate {i} (votes={votes}, sessions={sids}) ---\n{summary}"
        )
    return (
        f"OP: {op}\nTARGET: {target}\nN_CANDIDATES: {len(candidates)}\n\n"
        + "\n\n".join(blocks)
    )


def _parse_synthesis_response(op: str, content: str) -> tuple[dict | None, str]:
    """Parse the LLM's synthesis response into a payload dict + reason string.

    Returns (payload, reason). On parse failure returns (None, error_msg) so
    the caller can fall back to the highest-voted candidate.
    """
    if not content:
        return None, "(empty response)"
    try:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None, "(no JSON object found)"
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f"(JSON parse error: {e})"
    reason = str(obj.get("reason", ""))[:300]
    if op == "replace_system_prompt":
        new_content = obj.get("new_content")
        if not isinstance(new_content, str) or not new_content.strip():
            return None, "(missing or empty new_content)"
        return {"new_content": new_content}, reason
    if op == "edit_tool_description":
        new_desc = obj.get("new_description")
        if not isinstance(new_desc, str) or not new_desc.strip():
            return None, "(missing or empty new_description)"
        return {"new_description": new_desc}, reason
    if op == "edit_few_shot_exemplars":
        exemplars = obj.get("exemplars")
        if not isinstance(exemplars, list) or not exemplars:
            return None, "(missing or empty exemplars list)"
        # Sanity-check shape: each entry must have string input + output.
        clean: list[dict] = []
        for ex in exemplars:
            if not isinstance(ex, dict):
                continue
            inp = ex.get("input")
            out = ex.get("output")
            if isinstance(inp, str) and isinstance(out, str) and inp and out:
                clean.append({"input": inp, "output": out})
        if not clean:
            return None, "(no valid input/output pairs)"
        return {"exemplars": clean}, reason
    return None, f"(unsupported op: {op})"


# Ops that have a synthesis prompt; anything else falls back to selection.
SYNTHESIZE_OPS: tuple[str, ...] = (
    "replace_system_prompt",
    "edit_tool_description",
    "edit_few_shot_exemplars",
)


def _synthesis_system_prompt(op: str) -> str | None:
    if op == "replace_system_prompt":
        return _LLM_SYNTHESIZE_SYSTEM_PROMPT
    if op == "edit_tool_description":
        return _LLM_SYNTHESIZE_TOOL_DESC
    if op == "edit_few_shot_exemplars":
        return _LLM_SYNTHESIZE_FEW_SHOT
    return None


def llm_synthesize_best(
    deferred: dict[str, list[dict]],
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
) -> dict[str, list[dict]]:
    """For each (op, target) group with multiple candidates, ask an LLM to
    synthesize ONE new payload that combines recurring themes across the
    candidates. Returns {op: [chosen, ...]} mirroring the deferred dict
    structure but with a single synthesized entry per target.

    Each entry gains:
      - ``llm_synthesized: True`` (or False if we fell back to selection)
      - ``llm_reason: str`` — one-sentence explanation
      - ``llm_n_candidates: int`` — how many candidates fed the synthesis
      - the synthesized payload replaces ``payload``

    Falls back to the highest-voted candidate (with ``llm_synthesized: False``
    and a ``llm_fallback_reason``) if synthesis fails to parse, the LLM
    errors, or the op is not in SYNTHESIZE_OPS.
    """
    try:
        from openjarvis.core.types import Message, Role
        from openjarvis.engine.cloud import CloudEngine
    except ImportError as e:
        print(f"WARN: LLM-synthesize unavailable ({e}); skipping.", file=sys.stderr)
        return {op: [] for op in DEFERRED_OPS}

    ce = CloudEngine()
    synthesized: dict[str, list[dict]] = {op: [] for op in DEFERRED_OPS}

    for op, items in deferred.items():
        # Group candidates by target
        by_target: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            by_target[it["target"]].append(it)

        for target, candidates in by_target.items():
            if not candidates:
                continue

            # Always-applicable shortcut: if there's only one candidate, no
            # synthesis is needed (and synthesizing on n=1 just rewrites it).
            if len(candidates) == 1:
                only = dict(candidates[0])
                only["llm_synthesized"] = False
                only["llm_reason"] = "only candidate"
                only["llm_n_candidates"] = 1
                synthesized[op].append(only)
                continue

            sys_prompt = _synthesis_system_prompt(op)
            highest_voted = max(candidates, key=lambda c: c.get("votes", 0))

            if sys_prompt is None:
                # Op has no synthesis prompt — fall back to highest-voted.
                fallback = dict(highest_voted)
                fallback["llm_synthesized"] = False
                fallback["llm_reason"] = f"op {op} not in SYNTHESIZE_OPS; using highest-voted"
                fallback["llm_n_candidates"] = len(candidates)
                synthesized[op].append(fallback)
                continue

            user_prompt = _build_synthesis_prompt(op, target, candidates)

            try:
                resp = ce.generate(
                    messages=[
                        Message(role=Role.SYSTEM, content=sys_prompt),
                        Message(role=Role.USER, content=user_prompt),
                    ],
                    model=model,
                    max_tokens=max_tokens,
                    temperature=0.0,
                )
                content = resp.get("content", "") or ""
                payload, reason = _parse_synthesis_response(op, content)
            except Exception as e:
                payload, reason = None, f"(LLM error: {e})"

            if payload is None:
                # Synthesis failed; fall back to highest-voted candidate.
                fallback = dict(highest_voted)
                fallback["llm_synthesized"] = False
                fallback["llm_fallback_reason"] = reason
                fallback["llm_n_candidates"] = len(candidates)
                synthesized[op].append(fallback)
                print(
                    f"  [llm-synth] {op} {target}: FALLBACK to highest-voted "
                    f"({len(candidates)} candidates) — {reason[:120]}"
                )
                continue

            entry = {
                "target": target,
                "payload": payload,
                "votes": sum(c.get("votes", 1) for c in candidates),
                "total_votes_in_group": sum(c.get("votes", 1) for c in candidates),
                "sample_session_ids": [
                    sid
                    for c in candidates
                    for sid in (c.get("sample_session_ids") or [])
                ][:5],
                "llm_synthesized": True,
                "llm_reason": reason,
                "llm_n_candidates": len(candidates),
                "llm_source_session_ids": [
                    (c.get("sample_session_ids") or [None])[0] for c in candidates
                ],
            }
            synthesized[op].append(entry)
            print(
                f"  [llm-synth] {op} {target}: synthesized from "
                f"{len(candidates)} candidates — {reason[:120]}"
            )
    return synthesized


def llm_select_best(
    deferred: dict[str, list[dict]],
    *,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 600,
) -> dict[str, list[dict]]:
    """For each (op, target) group with multiple unique candidates, ask an
    LLM to pick the best one. Returns {op: [chosen, ...]} mirroring the
    deferred dict structure but with a single chosen entry per target.
    Each chosen entry gains ``llm_selected: True`` and ``llm_reason: str``.
    """
    try:
        from openjarvis.core.types import Message, Role
        from openjarvis.engine.cloud import CloudEngine
    except ImportError as e:
        print(f"WARN: LLM-select unavailable ({e}); skipping.", file=sys.stderr)
        return {op: [] for op in DEFERRED_OPS}

    ce = CloudEngine()
    selected: dict[str, list[dict]] = {op: [] for op in DEFERRED_OPS}

    for op, items in deferred.items():
        # Group candidates by target
        by_target: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            by_target[it["target"]].append(it)

        for target, candidates in by_target.items():
            if not candidates:
                continue
            if len(candidates) == 1:
                # Trivial: only one candidate, no choice needed.
                only = dict(candidates[0])
                only["llm_selected"] = True
                only["llm_reason"] = "only candidate"
                selected[op].append(only)
                continue

            # Build a numbered prompt
            blocks: list[str] = []
            for i, c in enumerate(candidates):
                summary = _summarize_payload(op, c.get("payload") or {})
                votes = c.get("votes", 1)
                sids = (c.get("sample_session_ids") or [])[:3]
                blocks.append(
                    f"--- candidate {i} (votes={votes}, sessions={sids}) ---\\n{summary}"
                )
            prompt = (
                f"OP: {op}\\nTARGET: {target}\\nN_CANDIDATES: {len(candidates)}\\n\\n"
                + "\\n\\n".join(blocks)
            )

            try:
                resp = ce.generate(
                    messages=[
                        Message(role=Role.SYSTEM, content=_LLM_SELECT_SYSTEM),
                        Message(role=Role.USER, content=prompt),
                    ],
                    model=model,
                    max_tokens=max_tokens,
                    temperature=0.0,
                )
                content = resp.get("content", "") or ""
                # Find a JSON object in the response
                m = re.search(r"\{[^{}]*\"selected_idx\"[^{}]*\}", content, re.S)
                if m:
                    obj = json.loads(m.group(0))
                    idx = int(obj.get("selected_idx", 0))
                    reason = str(obj.get("reason", ""))[:300]
                else:
                    idx, reason = 0, "(parse failed; defaulted to candidate 0)"
            except Exception as e:
                idx, reason = 0, f"(LLM error: {e}; defaulted to candidate 0)"

            idx = max(0, min(idx, len(candidates) - 1))
            chosen = dict(candidates[idx])
            chosen["llm_selected"] = True
            chosen["llm_reason"] = reason
            chosen["llm_n_candidates"] = len(candidates)
            chosen["llm_chosen_idx"] = idx
            selected[op].append(chosen)
            print(
                f"  [llm-select] {op} {target}: "
                f"{len(candidates)} candidates → idx {idx} "
                f"(session {chosen.get('sample_session_ids') or '?'}) "
                f"— {reason[:120]}"
            )
    return selected


def build_deferred_to_m3(
    audit_tallies: dict[tuple[str, str, str], Tally],
) -> dict[str, list[dict]]:
    """Group audit-tally rows by op into the deferred_to_m3 block.

    No min_votes / min_majority filtering — singletons are kept so the M3
    hill-climber can decide what's worth pursuing. Rows are sorted by votes
    descending within each op.
    """
    by_op: dict[str, list[dict]] = {op: [] for op in DEFERRED_OPS}
    by_group_total: dict[tuple[str, str], int] = defaultdict(int)
    for t in audit_tallies.values():
        by_group_total[(t.op, t.target)] += t.votes
    for t in audit_tallies.values():
        if t.op not in by_op:
            continue
        by_op[t.op].append(
            {
                "target": t.target,
                "payload": t.value,
                "votes": t.votes,
                "total_votes_in_group": by_group_total[(t.op, t.target)],
                "sample_session_ids": list(t.sample_session_ids),
            }
        )
    for op, rows in by_op.items():
        rows.sort(key=lambda r: (-r["votes"], r["target"]))
    return by_op


# ── I/O helpers ──────────────────────────────────────────────────────────────


def write_raw_edits(edits: list[tuple[str, dict]], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for session_id, edit in edits:
            f.write(json.dumps({"session_id": session_id, **edit}) + "\n")


def serialise_tallies(tallies: dict[tuple[str, str, str], Tally]) -> list[dict]:
    return [
        {
            "op": t.op,
            "target": t.target,
            "value": t.value,
            "votes": t.votes,
            "sample_session_ids": t.sample_session_ids,
        }
        for t in sorted(tallies.values(), key=lambda x: (-x.votes, x.op, x.target))
    ]


def deserialise_tallies(rows: list[dict]) -> dict[tuple[str, str, str], Tally]:
    out: dict[tuple[str, str, str], Tally] = {}
    for row in rows:
        key = (row["op"], row["target"], json.dumps(row["value"]))
        out[key] = Tally(
            op=row["op"],
            target=row["target"],
            value=row["value"],
            votes=int(row["votes"]),
            sample_session_ids=list(row.get("sample_session_ids", [])),
        )
    return out


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_SESSIONS_ROOT,
        help=f"Walk plan.json files under this dir (default: {DEFAULT_SESSIONS_ROOT})",
    )
    src.add_argument(
        "--tallies-file",
        type=Path,
        help="Skip walking; load pre-aggregated tallies from this JSON.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("results/neurips-2026/distillation-m2/consensus"),
        help="Output directory (default: results/.../distillation-m2/consensus)",
    )
    p.add_argument(
        "--min-votes",
        type=int,
        default=5,
        help="Minimum votes for a value to qualify as consensus (default: 5)",
    )
    p.add_argument(
        "--min-majority",
        type=float,
        default=0.4,
        help=(
            "For scalar ops: winning value must hold this share of group "
            "votes. M1 used plurality (~0.4), not strict majority (default: 0.4)."
        ),
    )
    p.add_argument(
        "--llm-select",
        action="store_true",
        help=(
            "For each (op, target) in deferred_to_m3 with multiple unique "
            "candidates, ask an LLM to pick the best one (rather than "
            "deferring to step 5's lexicographic tiebreak)."
        ),
    )
    p.add_argument(
        "--llm-select-model",
        default="claude-sonnet-4-6",
        help="Model used for --llm-select (default: claude-sonnet-4-6).",
    )
    p.add_argument(
        "--llm-synthesize",
        action="store_true",
        help=(
            "For each (op, target) in deferred_to_m3 with multiple candidates, "
            "ask an LLM to synthesize ONE new payload that combines recurring "
            "themes across the candidates. Applies to replace_system_prompt, "
            "edit_few_shot_exemplars, and edit_tool_description. Step 5 "
            "consumes this in preference to --llm-select output."
        ),
    )
    p.add_argument(
        "--llm-synthesize-model",
        default="claude-sonnet-4-6",
        help="Model used for --llm-synthesize (default: claude-sonnet-4-6).",
    )
    args = p.parse_args(argv)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.tallies_file:
        tallies_doc = json.loads(args.tallies_file.read_text())
        tallies = deserialise_tallies(tallies_doc.get("tallies", tallies_doc))
        audit_tallies = deserialise_tallies(tallies_doc.get("audit_tallies", []))
        n_edits = sum(t.votes for t in tallies.values()) + sum(
            t.votes for t in audit_tallies.values()
        )
        n_sessions = tallies_doc.get("n_sessions")
        source = str(args.tallies_file)
        print(f"Loaded {len(tallies)} distinct edits ({n_edits} votes) from {source}")
    else:
        edits = walk_plans(args.sessions_root)
        n_edits = len(edits)
        n_sessions = len({sid for sid, _ in edits})
        print(f"Walked {args.sessions_root}: {n_sessions} sessions, {n_edits} edits")
        if n_edits == 0:
            print("No edits found — nothing to tally.", file=sys.stderr)
            return 1
        write_raw_edits(edits, out_dir / "raw_edits.jsonl")
        tallies = tally_edits(edits)
        audit_tallies = audit_tally_edits(edits)
        source = str(args.sessions_root)

    raw_tallies_path = out_dir / "raw_tallies.json"
    raw_tallies_path.write_text(
        json.dumps(
            {
                "n_sessions": n_sessions,
                "n_edits": n_edits,
                "source": source,
                "tallies": serialise_tallies(tallies),
                "audit_tallies": serialise_tallies(audit_tallies),
            },
            indent=2,
        )
    )

    consensus = pick_consensus(
        tallies,
        min_votes=args.min_votes,
        min_majority=args.min_majority,
    )
    consensus["deferred_to_m3"] = build_deferred_to_m3(audit_tallies)

    if args.llm_select:
        print()
        print("LLM-selecting best candidate per target for deferred-text edits...")
        consensus["llm_selected"] = llm_select_best(
            consensus["deferred_to_m3"],
            model=args.llm_select_model,
        )
    if args.llm_synthesize:
        print()
        print("LLM-synthesizing one payload per target from all candidates...")
        consensus["llm_synthesized"] = llm_synthesize_best(
            consensus["deferred_to_m3"],
            model=args.llm_synthesize_model,
        )
    consensus_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "n_sessions": n_sessions,
        "n_edits": n_edits,
        "thresholds": {
            "min_votes": args.min_votes,
            "min_majority": args.min_majority,
        },
        "consensus": consensus,
    }
    consensus_path = out_dir / "consensus_edits.json"
    consensus_path.write_text(json.dumps(consensus_doc, indent=2))

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(f"Raw tallies → {raw_tallies_path}")
    print(f"Consensus   → {consensus_path}")
    print()
    print(f"Scalar consensus edits ({len(consensus['scalar_edits'])}):")
    for e in consensus["scalar_edits"]:
        print(
            f"  {e['op']:20} {e['target']:30} = {e['value']!r:10}  "
            f"({e['votes']}/{e['total_votes_in_group']} votes, "
            f"{e['majority_share']:.0%} share)"
        )
    if consensus["remove_tools"]:
        print(f"Tools to remove ({len(consensus['remove_tools'])}):")
        for t in consensus["remove_tools"]:
            print(f"  {t['tool_name']:20} ({t['votes']} votes)")
    if consensus["add_tools"]:
        print(f"Tools to add ({len(consensus['add_tools'])}):")
        for t in consensus["add_tools"]:
            print(f"  {t['tool_name']:20} ({t['votes']} votes)")
    deferred = consensus["deferred_to_m3"]
    print(
        f"Deferred to M3: {len(deferred['patch_system_prompt'])} prompt patches / "
        f"{len(deferred['replace_system_prompt'])} replace_prompts / "
        f"{len(deferred['edit_few_shot_exemplars'])} few_shot / "
        f"{len(deferred['edit_tool_description'])} tool_descs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
