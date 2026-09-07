"""Fixture phase policy and references to native stage owners.

The existing receipt chain persists decisions and dispatch claims. This module
does not create native sessions, store conversations, or execute model calls.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any

from hoh.protocol import (
    BindingError, ProtocolError, _require_exact_keys, _require_hash,
    validate_evidence_record, validate_role_request, validate_role_result,
    validate_stage_binding,
)


WORKFLOW_SCHEMA = "vivary.hoh-workflow/v1"
GATE_SCHEMA = "vivary.hoh-phase-gate/v1"
HANDOFF_SCHEMA = "vivary.hoh-handoff/v1"
PHASE_POLICY = "vivary.hoh-fixture-gates/v1"
ROLE_ORDER = ("planner", "developer", "qa")
REQUIREMENT_IDS = frozenset({
    "test_links.LinkCheckTests.test_reports_missing_relative_target",
    "test_links.LinkCheckTests.test_rejects_parent_escape",
    "test_links.LinkCheckTests.test_ignores_anchor_only_target",
    "test_links.LinkCheckTests.test_accepts_existing_relative_target",
})


def record_hash(value: object) -> str:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class Workflow:
    """An explicit assignment for every stage, bound to one fixed phase policy."""

    def __init__(self, value: object, *, run_id: str, iterations: int, adapters: dict[str, Any]):
        if not isinstance(value, dict):
            raise BindingError("workflow configuration must be an object")
        _require_exact_keys(value, {"schema", "policy", "run_id", "iterations", "stages"}, "workflow")
        if value["schema"] != WORKFLOW_SCHEMA or value["policy"] != PHASE_POLICY:
            raise BindingError("workflow schema or phase policy differs")
        if value["run_id"] != run_id or type(value["iterations"]) is not int or value["iterations"] != iterations:
            raise BindingError("workflow run or iteration policy differs")
        if not isinstance(value["stages"], list):
            raise BindingError("workflow stages must be a list")
        stages = [validate_stage_binding(item) for item in value["stages"]]
        expected = [(iteration, role) for iteration in range(1, iterations + 1) for role in ROLE_ORDER]
        if [(item["iteration"], item["role"]) for item in stages] != expected or any(item["run_id"] != run_id for item in stages):
            raise BindingError("workflow must assign every stage exactly once in order")
        role_agents: dict[str, str] = {}
        sessions: set[tuple[str, str]] = set()
        for item in stages:
            role, agent, runtime = item["role"], item["agent_id"], item["runtime"]
            if role in role_agents and role_agents[role] != agent:
                raise BindingError("assigned agent changes between iterations")
            role_agents[role] = agent
            session = (runtime, item["session_id"])
            if session in sessions:
                raise BindingError("native session is reused by another stage")
            sessions.add(session)
            if runtime not in adapters or getattr(adapters[runtime], "runtime_id", None) != runtime:
                raise BindingError(f"stage runtime is unsupported or mismatched: {runtime}")
        if len(set(role_agents.values())) != len(ROLE_ORDER):
            raise BindingError("planner, developer, and QA require distinct agents")
        self.value = {**value, "stages": stages}
        self.sha256 = record_hash(self.value)
        self.adapters = dict(adapters)
        self._stages = {(item["iteration"], item["role"]): item for item in stages}

    def binding(self, iteration: int, role: str) -> dict[str, Any]:
        return dict(self._stages[iteration, role])

    def adapter(self, iteration: int, role: str) -> Any:
        runtime = self.binding(iteration, role)["runtime"]
        adapter = self.adapters[runtime]
        if getattr(adapter, "runtime_id", None) != runtime:
            raise BindingError("registered runtime identity changed")
        return adapter

    def handoff(self, gate: dict[str, Any], artifacts: dict[str, str]) -> dict[str, Any]:
        predecessor = self.binding(gate["iteration"], gate["role"])
        successor = None
        if gate["decision"] in {"advance", "rework"}:
            if gate["role"] == "qa":
                successor = self.binding(gate["iteration"] + 1, "planner")
            else:
                successor = self.binding(gate["iteration"], ROLE_ORDER[ROLE_ORDER.index(gate["role"]) + 1])
        record = {
            "schema": HANDOFF_SCHEMA, "workflow_sha256": self.sha256,
            "predecessor": predecessor, "successor": successor,
            "attempt": gate["attempt"], "gate": gate, "artifacts": dict(artifacts),
        }
        self.validate_handoff(record)
        return record

    def validate_handoff(self, record: object) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ProtocolError("handoff must be an object")
        _require_exact_keys(record, {
            "schema", "workflow_sha256", "predecessor", "successor", "attempt", "gate", "artifacts",
        }, "handoff")
        if record["schema"] != HANDOFF_SCHEMA or record["workflow_sha256"] != self.sha256:
            raise BindingError("handoff workflow differs")
        source = validate_stage_binding(record["predecessor"])
        if source != self.binding(source["iteration"], source["role"]):
            raise BindingError("handoff predecessor differs")
        gate = record["gate"]
        if not isinstance(gate, dict):
            raise ProtocolError("handoff gate must be an object")
        _require_exact_keys(gate, {
            "schema", "policy", "iteration", "role", "stage_id", "attempt", "decision", "checks", "reasons",
        }, "phase gate")
        if gate["schema"] != GATE_SCHEMA or gate["policy"] != PHASE_POLICY:
            raise ProtocolError("phase gate policy differs")
        if any(gate[key] != source[key] for key in ("iteration", "role", "stage_id")):
            raise BindingError("phase gate predecessor differs")
        if type(record["attempt"]) is not int or record["attempt"] not in (1, 2) or type(gate["attempt"]) is not int or gate["attempt"] != record["attempt"]:
            raise BindingError("handoff attempt differs")
        if gate["decision"] not in {"advance", "rework", "complete", "blocked"}:
            raise ProtocolError("unknown phase gate decision")
        checks = gate["checks"]
        expected_checks = {"response_and_usage", "requirements", "report_sections", "candidate_unchanged"}
        if source["role"] == "developer":
            expected_checks |= {"candidate_file_set", "candidate_syntax"}
        if source["role"] == "qa":
            expected_checks |= {"evidence_bound", "no_regression", "verdict_consistent", "progress_allowed"}
        if not isinstance(checks, dict) or set(checks) != expected_checks or any(type(v) is not bool for v in checks.values()):
            raise ProtocolError("phase gate checks differ")
        if not isinstance(gate["reasons"], list) or any(not isinstance(x, str) or not x for x in gate["reasons"]):
            raise ProtocolError("phase gate reasons differ")
        if gate["decision"] != "blocked" and (not all(checks.values()) or gate["reasons"]):
            raise ProtocolError("rejected checks cannot authorize a handoff")
        iteration, role = source["iteration"], source["role"]
        expected_successor = None
        if gate["decision"] in {"advance", "rework"}:
            if role != "qa":
                if gate["decision"] != "advance":
                    raise ProtocolError("only QA can request bounded rework")
                expected_successor = self.binding(iteration, ROLE_ORDER[ROLE_ORDER.index(role) + 1])
            elif iteration < self.value["iterations"]:
                expected_successor = self.binding(iteration + 1, "planner")
            else:
                raise ProtocolError("handoff exceeds the iteration bound")
        if gate["decision"] == "complete" and (role != "qa" or iteration != self.value["iterations"]):
            raise ProtocolError("only final QA can complete the workflow")
        if record["successor"] != expected_successor:
            raise BindingError("handoff successor differs from its route")
        artifacts = record["artifacts"]
        expected_artifacts = {"candidate_sha256", "checkpoint_commit", "development_document_sha256"}
        if role in {"developer", "qa"}:
            expected_artifacts.add("developer_report_sha256")
        if role == "qa":
            expected_artifacts |= {"qa_evidence_report_sha256", "test_evidence_sha256"}
        if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
            raise ProtocolError("handoff artifact set differs")
        for key, value in artifacts.items():
            if key == "checkpoint_commit":
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
                    raise ProtocolError("handoff checkpoint must be a Git revision")
            else:
                _require_hash(value, key)
        return record


def _sections(text: str, headings: tuple[str, ...]) -> bool:
    for heading in headings:
        match = re.search(r"(?m)^" + re.escape(heading) + r"\n([^#][\s\S]*?)(?=^#{1,3} |\Z)", text)
        if match is None or not match.group(1).strip():
            return False
    return True


def evaluate_phase(
    request: dict[str, Any], result: dict[str, Any], *, iterations: int,
    candidate_unchanged: bool, developer_source: str | None = None,
    developer_files: set[str] | None = None, evidence: dict[str, Any] | None = None,
    lost_passing: tuple[str, ...] = (),
    progress_allowed: bool = True,
) -> dict[str, Any]:
    """Decide a route from explicit submissions and coordinator observations."""
    request = validate_role_request(request)
    result = validate_role_result({key: value for key, value in result.items() if not key.startswith("_")}, request=request)
    if result["request_sha256"] != record_hash(request) or result["output_sha256"] != "sha256:" + hashlib.sha256(result["output_text"].encode()).hexdigest():
        raise BindingError("phase result does not bind its request and output")
    role, iteration = request["role"], request["iteration"]
    submission = result["submission"]
    headings = {
        "planner": ("### Priority Order", "### Preservation Gate", "### Acceptance Gate"),
        "developer": ("## Changes", "## Validation"),
        "qa": ("## Status", "## Evidence", "## Gaps", "## Next action"),
    }[role]
    checks = {
        "response_and_usage": result["complete"] and result["usage"]["complete"],
        "requirements": set(submission["requirements"]) == REQUIREMENT_IDS,
        "report_sections": _sections(result["output_text"], headings),
        "candidate_unchanged": candidate_unchanged,
    }
    if role == "planner":
        priorities = re.findall(r"(?m)^[1-3]\. \S.+$", result["output_text"])
        checks["report_sections"] &= 1 <= len(priorities) <= 3
    if role == "developer":
        checks["candidate_file_set"] = developer_files == {"linkcheck.py"}
        try:
            tree = ast.parse(developer_source or "")
            checks["candidate_syntax"] = any(isinstance(node, ast.FunctionDef) and node.name == "check_tree" for node in tree.body)
        except SyntaxError:
            checks["candidate_syntax"] = False
    if role == "qa":
        valid_evidence = False
        if evidence is not None:
            evidence = validate_evidence_record(evidence, run_id=request["run_id"], iteration=iteration)
            valid_evidence = evidence["complete"] and record_hash(evidence) == request["test_evidence_sha256"]
        checks["evidence_bound"] = valid_evidence
        checks["no_regression"] = not lost_passing
        checks["progress_allowed"] = progress_allowed
        green = valid_evidence and evidence["returncode"] == 0 and not evidence["observations"]
        checks["verdict_consistent"] = submission["decision"] != "ready" or bool(green)
    reasons = [name for name, passed in checks.items() if not passed]
    decision = "blocked"
    if submission["decision"] == "blocked":
        reasons.append("agent-blocked")
    elif role != "qa" and submission["decision"] != "ready":
        reasons.append("rework-requires-next-iteration")
    elif not reasons:
        if role != "qa":
            decision = "advance"
        elif iteration < iterations:
            decision = "rework" if submission["decision"] == "rework" else "advance"
        elif submission["decision"] == "ready":
            decision = "complete"
        else:
            reasons.append("rework-limit-reached")
    return {
        "schema": GATE_SCHEMA, "policy": PHASE_POLICY, "iteration": iteration, "role": role,
        "stage_id": request["binding"]["stage_id"], "attempt": request["attempt"],
        "decision": decision, "checks": checks, "reasons": reasons,
    }
