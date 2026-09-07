"""Behavior tests for the deterministic headless-loop preparation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
TEST_BOOT_ID = "00000000-0000-4000-8000-000000000001"

from hoh.protocol import (  # noqa: E402
    BindingError,
    BudgetError,
    ClockError,
    DeadlineError,
    IterationDeadline,
    ProtocolError,
    UsageLedger,
    validate_role_request,
    validate_role_result,
    validate_evidence_record,
    validate_transition_record,
    validate_usage_record,
)
from hoh.workflow import (  # noqa: E402
    PHASE_POLICY, REQUIREMENT_IDS, WORKFLOW_SCHEMA, Workflow, evaluate_phase, record_hash,
)
from hoh.claude import (  # noqa: E402
    ClaudeAdapter,
    ClaudePreflightError,
    normalize_claude_usage,
)
from hoh_loop import (  # noqa: E402
    EXPECTED_ORACLE_TEST_IDS,
    HeadlessLoop,
    HarnessError,
    ReceiptStore,
    RoleView,
    RunFault,
    canonical_json_bytes,
    hash_tree,
    run_owned_process,
    run_product_tests,
    sha256_bytes,
    sha256_file,
    verify_expected_red,
)


def preserved_test_dir(prefix: str) -> Path:
    root = Path("/tmp/hoh-test-artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))


def test_workflow(run_id, iterations, runtimes=("double", "double", "double")):
    return {
        "schema": WORKFLOW_SCHEMA, "policy": PHASE_POLICY,
        "run_id": run_id, "iterations": iterations,
        "stages": [
            {
                "stage_id": f"{run_id}-i{iteration}-{role}", "run_id": run_id,
                "iteration": iteration, "role": role, "runtime": runtime,
                "agent_id": f"{role}-agent", "session_id": f"fake-session-{run_id}-{iteration}-{role}",
            }
            for iteration in range(1, iterations + 1)
            for role, runtime in zip(("planner", "developer", "qa"), runtimes)
        ],
    }


def make_test_loop(*, adapter, **values):
    return HeadlessLoop(
        **values, workflow=test_workflow(values["run_id"], values["iterations"]),
        adapters={"double": adapter},
    )


def submission(request, decision="ready"):
    return {
        "decision": decision, "candidate_sha256": request["candidate_sha256"],
        "test_evidence_sha256": request["test_evidence_sha256"],
        "requirements": sorted(REQUIREMENT_IDS),
    }


class ProtocolTests(unittest.TestCase):
    def test_role_request_accepts_only_the_versioned_runtime_neutral_shape(self) -> None:
        request = {
            "schema": "vivary.hoh-role-request/v2",
            "run_id": "run-001",
            "iteration": 1,
            "role": "planner",
            "binding": test_workflow("run-001", 1)["stages"][0],
            "attempt": 1, "handoff_sha256": None, "test_evidence_sha256": None,
            "prompt_bytes": 128,
            "prompt_sha256": "sha256:" + "a" * 64,
            "baseline_sha256": "sha256:" + "b" * 64,
            "candidate_sha256": "sha256:" + "c" * 64,
            "receipt_chain_head": None,
            "deadline_unix_ns": 2_000_000_000,
            "read_roots": ["specification", "public-evidence"],
            "write_root": None,
        }

        parsed = validate_role_request(request)

        self.assertEqual(parsed["role"], "planner")
        for mutation in (
            {**request, "vendor": "claude"},
            {**request, "iteration": True},
            {**request, "role": "reviewer"},
            {**request, "prompt_sha256": "not-a-hash"},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ProtocolError):
                    validate_role_request(mutation)

    def test_result_evidence_and_transition_reject_stale_or_cross_run_fields(self) -> None:
        request = {
            "schema": "vivary.hoh-role-request/v2",
            "run_id": "run-001",
            "iteration": 1,
            "role": "qa",
            "binding": test_workflow("run-001", 1)["stages"][2],
            "attempt": 1, "handoff_sha256": "sha256:" + "d" * 64,
            "test_evidence_sha256": "sha256:" + "e" * 64,
            "prompt_bytes": 10,
            "prompt_sha256": "sha256:" + "a" * 64,
            "baseline_sha256": "sha256:" + "b" * 64,
            "candidate_sha256": "sha256:" + "c" * 64,
            "receipt_chain_head": None,
            "deadline_unix_ns": 2_000_000_000,
            "read_roots": ["candidate"],
            "write_root": None,
        }
        output = "# Evidence\n"
        usage = {
            "schema": "vivary.hoh-usage/v1",
            "vendor_usage_raw": {"source": "test-double"},
            "aggregate_input_tokens": 1,
            "aggregate_output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "budget_counted_tokens": 2,
            "claude_agentic_turns": 1,
            "codex_top_level_turns": None,
            "complete": True,
        }
        result = {
            "schema": "vivary.hoh-role-result/v2",
            "run_id": "run-001",
            "iteration": 1,
            "role": "qa",
            "binding": request["binding"], "attempt": request["attempt"],
            "submission": submission(request),
            "request_sha256": sha256_bytes(canonical_json_bytes(request)),
            "output_kind": "evidence_report",
            "output_text": output,
            "output_sha256": sha256_bytes(output.encode()),
            "usage": usage,
            "complete": True,
        }
        self.assertEqual(validate_role_result(result, request=request)["role"], "qa")
        with self.assertRaises(ProtocolError):
            validate_role_result({**result, "run_id": "run-002"}, request=request)
        with self.assertRaises(ProtocolError):
            validate_role_result({**result, "unexpected": True}, request=request)

        evidence = {
            "schema": "vivary.hoh-evidence/v1",
            "run_id": "run-001",
            "iteration": 1,
            "candidate_sha256": request["candidate_sha256"],
            "command": ["python3", "-m", "unittest"],
            "returncode": 0,
            "output_sha256": "sha256:" + "d" * 64,
            "observations": [],
            "complete": True,
        }
        validate_evidence_record(evidence, run_id="run-001", iteration=1)
        with self.assertRaises(ProtocolError):
            validate_evidence_record(evidence, candidate_sha256="sha256:" + "e" * 64)

        transition = {
            "schema": "vivary.hoh-transition/v1",
            "run_id": "run-001",
            "iteration": 1,
            "from_stage": "planner",
            "to_stage": "developer",
            "candidate_before_sha256": "sha256:" + "a" * 64,
            "candidate_after_sha256": "sha256:" + "b" * 64,
            "prior_receipt_sha256": None,
        }
        validate_transition_record(transition)
        with self.assertRaises(ProtocolError):
            validate_transition_record({**transition, "to_stage": "qa"})

    def test_usage_ledger_refuses_unknown_or_exhausting_maxima_without_reset(self) -> None:
        ledger_path = preserved_test_dir("usage-refusal-") / "usage.json"
        ledger = UsageLedger(ledger_path, packet_budget=100)

        with self.assertRaises(BudgetError):
            ledger.reserve("unknown", None)
        first = ledger.reserve("call-1", 60)
        self.assertEqual(first["remaining"], 40)

        probe = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import json,sys; from hoh.protocol import UsageLedger; "
                "print(json.dumps(UsageLedger(sys.argv[1], 100).snapshot()))",
                str(ledger_path),
            ],
            env={**os.environ, "PYTHONPATH": str(ROOT / "tools")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["remaining"], 40)

        reopened = UsageLedger(ledger_path, packet_budget=100)
        self.assertEqual(reopened.snapshot()["remaining"], 40)
        with self.assertRaises(BudgetError):
            reopened.reserve("call-2", 41)
        self.assertNotIn("call-2", reopened.snapshot()["reservations"])

    def test_usage_settlement_counts_cache_once_and_retains_incomplete_reservation(self) -> None:
        ledger_path = preserved_test_dir("usage-settle-") / "usage.json"
        ledger = UsageLedger(ledger_path, packet_budget=100)
        ledger.reserve("complete", 40)
        complete = validate_usage_record(
            {
                "schema": "vivary.hoh-usage/v1",
                "vendor_usage_raw": {"source": "test-double"},
                "aggregate_input_tokens": 15,
                "aggregate_output_tokens": 5,
                "cache_read_input_tokens": 2,
                "cache_write_input_tokens": 3,
                "budget_counted_tokens": 20,
                "claude_agentic_turns": None,
                "codex_top_level_turns": None,
                "complete": True,
            }
        )
        ledger.settle("complete", complete)
        self.assertEqual(ledger.snapshot()["remaining"], 80)

        ledger.reserve("incomplete", 50)
        incomplete = {
            **complete,
            "aggregate_input_tokens": None,
            "aggregate_output_tokens": None,
            "budget_counted_tokens": None,
            "complete": False,
        }
        ledger.settle("incomplete", incomplete)
        snapshot = UsageLedger(ledger_path, packet_budget=100).snapshot()
        self.assertEqual(snapshot["remaining"], 30)
        self.assertEqual(snapshot["reservations"]["incomplete"]["charged"], 50)
        self.assertEqual(snapshot["reservations"]["incomplete"]["status"], "incomplete")

    def test_usage_ledger_rejects_malformed_persisted_reservations(self) -> None:
        root = preserved_test_dir("usage-corrupt-")
        valid_usage = {
            "schema": "vivary.hoh-usage/v1",
            "vendor_usage_raw": {"source": "test-double"},
            "aggregate_input_tokens": 5,
            "aggregate_output_tokens": 4,
            "cache_read_input_tokens": None,
            "cache_write_input_tokens": None,
            "budget_counted_tokens": 9,
            "claude_agentic_turns": None,
            "codex_top_level_turns": None,
            "complete": True,
        }
        invalid_reservations = {
            "negative charged": {"maximum": 10, "charged": -1, "status": "reserved", "usage": None},
            "boolean maximum": {"maximum": True, "charged": 1, "status": "reserved", "usage": None},
            "unknown field": {
                "maximum": 10,
                "charged": 10,
                "status": "reserved",
                "usage": None,
                "release": 10,
            },
            "unknown status": {"maximum": 10, "charged": 10, "status": "lost", "usage": None},
            "settled mismatch": {
                "maximum": 10,
                "charged": 8,
                "status": "settled",
                "usage": valid_usage,
            },
            "incomplete released": {
                "maximum": 10,
                "charged": 1,
                "status": "incomplete",
                "usage": {**valid_usage, "complete": False, "budget_counted_tokens": 9},
            },
        }
        for index, (label, reservation) in enumerate(invalid_reservations.items()):
            with self.subTest(label=label):
                path = root / f"usage-{index}.json"
                path.write_text(
                    json.dumps(
                        {
                            "schema": "vivary.hoh-ledger/v1",
                            "packet_budget": 100,
                            "reservations": {"call-1": reservation},
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(BudgetError):
                    UsageLedger(path, packet_budget=100).snapshot()

        path = root / "malformed-settlement.json"
        ledger = UsageLedger(path, packet_budget=100)
        ledger.reserve("call-1", 50)
        with self.assertRaises(ProtocolError):
            ledger.settle("call-1", {**valid_usage, "budget_counted_tokens": 8})
        self.assertEqual(ledger.snapshot()["remaining"], 50)

    def test_iteration_deadline_persists_expiry_and_refuses_clock_reversal(self) -> None:
        path = preserved_test_dir("deadline-state-") / "deadline.json"
        deadline = IterationDeadline.create(
            path,
            run_id="run-001",
            iteration=2,
            duration_seconds=3600,
            now_unix_ns=1_000_000_000,
            now_monotonic_ns=10_000_000_000,
            boot_id=TEST_BOOT_ID,
        )
        self.assertEqual(
            deadline.remaining(
                now_unix_ns=2_000_000_000,
                now_monotonic_ns=11_000_000_000,
                boot_id=TEST_BOOT_ID,
            ),
            3599.0,
        )

        resumed = IterationDeadline.resume(
            path, run_id="run-001", iteration=2, boot_id=TEST_BOOT_ID
        )
        self.assertEqual(resumed.expires_unix_ns, 3_601_000_000_000)
        with self.assertRaises(ClockError):
            resumed.remaining(
                now_unix_ns=1_999_999_999,
                now_monotonic_ns=12_000_000_000,
                boot_id=TEST_BOOT_ID,
            )
        with self.assertRaises(DeadlineError):
            IterationDeadline.create(
                path,
                run_id="run-001",
                iteration=2,
                duration_seconds=3600,
                now_unix_ns=2_000_000_000,
                now_monotonic_ns=12_000_000_000,
                boot_id=TEST_BOOT_ID,
            )

    def test_iteration_deadline_detects_masked_wall_rollback_and_boot_change(self) -> None:
        root = preserved_test_dir("deadline-clock-continuity-")
        path = root / "deadline.json"
        deadline = IterationDeadline.create(
            path,
            run_id="clock-001",
            iteration=1,
            duration_seconds=3600,
            now_unix_ns=3_600_000_000_000,
            now_monotonic_ns=10_000_000_000,
            boot_id=TEST_BOOT_ID,
        )
        with self.assertRaisesRegex(ClockError, "elapsed less time"):
            deadline.remaining(
                now_unix_ns=4_500_000_000_000,
                now_monotonic_ns=2_710_000_000_000,
                boot_id=TEST_BOOT_ID,
            )

        changed_boot = "00000000-0000-4000-8000-000000000002"
        with self.assertRaisesRegex(ClockError, "system boot"):
            IterationDeadline.resume(
                path, run_id="clock-001", iteration=1, boot_id=changed_boot
            )

    @unittest.skipIf(os.name == "nt", "process-group evidence runs in Habitat Linux")
    def test_deadline_stops_stalled_process_group_after_five_second_grace(self) -> None:
        root = preserved_test_dir("deadline-process-")
        script = root / "stall.py"
        pids = root / "pids.json"
        script.write_text(
            """\
import json, os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([
    sys.executable, "-c",
    "import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "open(os.environ['GRANDCHILD_PID'], 'w').write(str(os.getpid())); time.sleep(60)",
], env={**os.environ, "GRANDCHILD_PID": sys.argv[2]})
open(sys.argv[1], "w").write(json.dumps({"parent": os.getpid(), "child": child.pid}))
time.sleep(60)
""",
            encoding="utf-8",
        )
        grandchild_pid = root / "grandchild.pid"
        deadline = IterationDeadline.create(
            root / "deadline.json",
            run_id="stall-001",
            iteration=1,
            duration_seconds=0.2,
        )
        started = time.monotonic()

        result = run_owned_process(
            [sys.executable, str(script), str(pids), str(grandchild_pid)],
            cwd=root,
            deadline=deadline,
        )

        elapsed = time.monotonic() - started
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["forced_after_grace"])
        self.assertGreaterEqual(elapsed, 4.5)
        self.assertLess(elapsed, 6.0)
        recorded = json.loads(pids.read_text(encoding="utf-8"))
        recorded["grandchild"] = int(grandchild_pid.read_text(encoding="utf-8"))
        for pid in recorded.values():
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"pid {pid} was not reaped")

    @unittest.skipIf(os.name == "nt", "process-group evidence runs in Habitat Linux")
    def test_closed_pipe_descendant_is_detected_killed_and_reaped(self) -> None:
        root = preserved_test_dir("closed-pipe-descendant-")
        script = root / "spawn-and-exit.py"
        child_pid = root / "child.pid"
        child_ready = root / "child.ready"
        script.write_text(
            """\
import os, subprocess, sys, time
child = subprocess.Popen(
    [sys.executable, "-c", "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(sys.argv[1], 'w').write('ready'); time.sleep(60)", sys.argv[2]],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
)
stop = time.monotonic() + 2
while not os.path.exists(sys.argv[2]) and time.monotonic() < stop:
    time.sleep(0.01)
if not os.path.exists(sys.argv[2]):
    raise RuntimeError("child did not become ready")
open(sys.argv[1], "w").write(str(child.pid))
""",
            encoding="utf-8",
        )
        deadline = IterationDeadline.create(
            root / "deadline.json",
            run_id="closed-pipe-001",
            iteration=1,
            duration_seconds=30,
        )
        started = time.monotonic()

        result = run_owned_process(
            [sys.executable, str(script), str(child_pid), str(child_ready)],
            cwd=root,
            deadline=deadline,
        )

        elapsed = time.monotonic() - started
        pid = int(child_pid.read_text(encoding="utf-8"))
        self.assertFalse(result["timed_out"])
        self.assertTrue(result["orphaned_descendants"])
        self.assertTrue(result["forced_after_grace"])
        self.assertFalse(result["accepted"])
        self.assertGreaterEqual(elapsed, 4.5)
        self.assertLess(elapsed, 5.5)
        self.assertFalse(Path(f"/proc/{pid}").exists())


class FixtureContractTests(unittest.TestCase):
    EXPECTED_RED = {
        "test_links.LinkCheckTests.test_reports_missing_relative_target":
            "observation=missing-target-was-not-reported",
        "test_links.LinkCheckTests.test_rejects_parent_escape":
            "observation=parent-escape-was-accepted",
        "test_links.LinkCheckTests.test_ignores_anchor_only_target":
            "observation=anchor-only-target-was-read",
    }

    def test_starter_is_exactly_red_and_completed_copy_is_green(self) -> None:
        fixture = ROOT / "docs/product/multi-project/fixtures/hoh-loop"
        artifacts = preserved_test_dir("fixture-contract-")
        starter = artifacts / "starter"

        red = verify_expected_red(fixture, starter, self.EXPECTED_RED, timeout_seconds=10)

        self.assertEqual(set(red["failed_test_ids"]), set(self.EXPECTED_RED))
        self.assertTrue(starter.exists())
        completed = artifacts / "completed"
        completed_source = """\
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import unquote
LINK = re.compile(r"\\[[^\\]]*\\]\\(([^)]+)\\)")
def check_tree(root: Path) -> list[dict[str, str]]:
    findings = []
    root = root.resolve()
    for source in sorted(root.rglob("*.md")):
        for raw_target in LINK.findall(source.read_text(encoding="utf-8")):
            target = unquote(raw_target.strip())
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_target = target.split("#", 1)[0]
            if not file_target:
                continue
            resolved = (source.parent / file_target).resolve()
            record = {"source": source.relative_to(root).as_posix(), "target": target}
            if not resolved.is_relative_to(root):
                findings.append({**record, "code": "path_escape"})
            elif not resolved.is_file():
                findings.append({**record, "code": "missing_target"})
    return sorted(findings, key=lambda item: (item["source"], item["target"]))
"""
        verify_expected_red(fixture, completed, self.EXPECTED_RED, timeout_seconds=10)
        (completed / "linkcheck.py").write_text(completed_source, encoding="utf-8")

        green = run_product_tests(completed, timeout_seconds=10)

        self.assertEqual(green["returncode"], 0, green["output"])
        self.assertTrue(green["oracle_accepted"])
        self.assertTrue(completed.exists())

    def test_exit_zero_without_declared_test_ids_is_not_oracle_green(self) -> None:
        fixture = ROOT / "docs/product/multi-project/fixtures/hoh-loop"
        project = preserved_test_dir("fixture-exit-zero-") / "project"
        shutil.copytree(fixture, project)
        for path in project.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        project.chmod(0o755)
        forged = "\n".join(
            f"forged ({test_id}) ... ok" for test_id in sorted(EXPECTED_ORACLE_TEST_IDS)
        )
        (project / "linkcheck.py").write_text(
            f"import os\nprint({forged!r}, flush=True)\nos._exit(0)\n", encoding="utf-8"
        )

        result = run_product_tests(project, timeout_seconds=10)

        self.assertNotEqual(result["returncode"], 0)
        self.assertEqual(set(result["executed_test_ids"]), EXPECTED_ORACLE_TEST_IDS)
        self.assertTrue(
            result["oracle_complete"],
            {key: result.get(key) for key in ("returncode", "executed_test_ids", "timed_out", "deadline_error", "deadline_state")},
        )
        self.assertFalse(result["oracle_accepted"])

    def test_candidate_unittest_shadow_cannot_replace_trusted_parent(self) -> None:
        fixture = ROOT / "docs/product/multi-project/fixtures/hoh-loop"
        project = preserved_test_dir("fixture-unittest-shadow-") / "project"
        shutil.copytree(fixture, project)
        for path in project.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        project.chmod(0o755)
        (project / "linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        forged = "\n".join(
            f"forged ({test_id}) ... ok" for test_id in sorted(EXPECTED_ORACLE_TEST_IDS)
        )
        (project / "unittest.py").write_text(
            f"import os\nprint({forged!r}, flush=True)\nos._exit(0)\n", encoding="utf-8"
        )

        result = run_product_tests(project, timeout_seconds=10)

        self.assertEqual(result["returncode"], 0, result["output"])
        self.assertEqual(set(result["executed_test_ids"]), EXPECTED_ORACLE_TEST_IDS)
        self.assertTrue(result["oracle_accepted"])

    @unittest.skipIf(os.name == "nt", "process-group evidence runs in Habitat Linux")
    def test_timeout_mode_reaps_a_stalled_candidate_child(self) -> None:
        fixture = ROOT / "docs/product/multi-project/fixtures/hoh-loop"
        project = preserved_test_dir("fixture-stalled-child-") / "project"
        shutil.copytree(fixture, project)
        for path in project.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        candidate_pid = project.parent / "candidate.pid"
        (project / "linkcheck.py").write_text(
            """\
import os
import signal
import time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(os.environ["HOH_STALL_PID"]).write_text(str(os.getpid()), encoding="utf-8")
time.sleep(60)
""",
            encoding="utf-8",
        )
        prior = os.environ.get("HOH_STALL_PID")
        os.environ["HOH_STALL_PID"] = str(candidate_pid)
        started = time.monotonic()
        try:
            result = run_product_tests(project, timeout_seconds=1.0)
        finally:
            if prior is None:
                os.environ.pop("HOH_STALL_PID", None)
            else:
                os.environ["HOH_STALL_PID"] = prior

        elapsed = time.monotonic() - started
        pid = int(candidate_pid.read_text(encoding="utf-8"))
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup_confirmed"])
        self.assertTrue(result["forced_after_grace"])
        self.assertFalse(result["oracle_accepted"])
        self.assertGreaterEqual(elapsed, 4.5)
        self.assertLess(elapsed, 6.0)
        self.assertFalse(Path(f"/proc/{pid}").exists())


class RoleViewAndReceiptTests(unittest.TestCase):
    def test_role_views_refuse_undeclared_paths_links_processes_shell_and_writes(self) -> None:
        root = preserved_test_dir("role-view-")
        public = root / "public"
        public.mkdir()
        (public / "spec.md").write_text("# Public\n", encoding="utf-8")
        candidate = root / "candidate.py"
        candidate.write_text("VALUE = 1\n", encoding="utf-8")
        canary = root / "credential-canary"
        canary.write_text("never-visible\n", encoding="utf-8")

        planner = RoleView.materialize(
            root / "planner",
            role="planner",
            sources={"specification": public},
            writable_root=None,
        )
        self.assertEqual(planner.read_text("specification/spec.md"), "# Public\n")
        for operation in (
            lambda: planner.read_text("candidate/candidate.py"),
            lambda: planner.read_text("../credential-canary"),
            lambda: planner.write_text("specification/spec.md", "changed"),
            lambda: planner.environment("SECRET"),
            lambda: planner.process_file("self/environ"),
            lambda: planner.shell("cat /proc/self/environ"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises((PermissionError, FileNotFoundError)):
                    operation()

        qa = RoleView.materialize(
            root / "qa",
            role="qa",
            sources={"candidate": candidate},
            writable_root=None,
        )
        with self.assertRaises(PermissionError):
            qa.write_text("candidate/candidate.py", "VALUE = 2\n")

        linked = root / "linked"
        linked.mkdir()
        try:
            (linked / "canary-link").symlink_to(canary)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaises(HarnessError):
            RoleView.materialize(
                root / "linked-view",
                role="planner",
                sources={"specification": linked},
                writable_root=None,
            )

    def test_receipts_are_immutable_hash_chained_and_reopenable(self) -> None:
        root = preserved_test_dir("receipt-chain-")
        bindings = {
            "baseline_sha256": "sha256:" + "a" * 64,
            "baseline_commit": "a" * 40,
            "baseline_tree": "b" * 40,
            "specification_sha256": "sha256:" + "b" * 64,
            "oracle_sha256": "sha256:" + "c" * 64,
            "prompt_sha256": {
                "planner": "sha256:" + "d" * 64,
                "developer": "sha256:" + "e" * 64,
                "qa": "sha256:" + "f" * 64,
            },
            "iteration": 1,
            "candidate_sha256": "sha256:" + "1" * 64,
            "prior_receipt_sha256": None,
        }
        store = ReceiptStore(root, "run-001")
        first = store.append(
            {
                "run_id": "run-001",
                "iteration": 1,
                "stage": "planner",
                "status": "complete",
                "bindings": bindings,
                "details": {"observation": "planned"},
            }
        )
        second = store.append(
            {
                "run_id": "run-001",
                "iteration": 1,
                "stage": "developer",
                "status": "complete",
                "bindings": {**bindings, "prior_receipt_sha256": first["sha256"]},
                "details": {"observation": "changed"},
            }
        )
        self.assertEqual(second["record"]["prior_receipt_sha256"], first["sha256"])
        self.assertIn(second["sha256"], (root / "index.md").read_text(encoding="utf-8"))
        self.assertEqual(ReceiptStore(root, "run-001").head, second["sha256"])

        first["path"].chmod(0o644)
        first["path"].write_text("{}\n", encoding="utf-8")
        with self.assertRaises(HarnessError):
            ReceiptStore(root, "run-001")

    def test_interrupted_receipt_write_keeps_last_committed_head(self) -> None:
        root = preserved_test_dir("receipt-interrupted-")
        bindings = {
            "baseline_sha256": "sha256:" + "a" * 64,
            "baseline_commit": "a" * 40,
            "baseline_tree": "b" * 40,
            "specification_sha256": "sha256:" + "b" * 64,
            "oracle_sha256": "sha256:" + "c" * 64,
            "prompt_sha256": {
                "planner": "sha256:" + "d" * 64,
                "developer": "sha256:" + "e" * 64,
                "qa": "sha256:" + "f" * 64,
            },
            "iteration": 1,
            "candidate_sha256": "sha256:" + "1" * 64,
            "prior_receipt_sha256": None,
        }
        store = ReceiptStore(root, "run-001")
        first = store.append(
            {
                "run_id": "run-001",
                "iteration": 1,
                "stage": "planner",
                "status": "complete",
                "bindings": bindings,
                "details": {"observation": "planned"},
            }
        )

        def interrupted(path: Path, raw: bytes) -> None:
            path.write_bytes(raw[:9])
            raise OSError("simulated interrupted write")

        store._write_receipt_temporary = interrupted
        with self.assertRaisesRegex(OSError, "simulated interrupted write"):
            store.append(
                {
                    "run_id": "run-001",
                    "iteration": 1,
                    "stage": "developer",
                    "status": "complete",
                    "bindings": {**bindings, "prior_receipt_sha256": first["sha256"]},
                    "details": {"observation": "changed"},
                }
            )
        unrelated = root / "details/.receipt-unrelated.tmp"
        unrelated.write_text("unrelated", encoding="utf-8")

        reopened = ReceiptStore(root, "run-001")

        self.assertEqual(reopened.head, first["sha256"])
        self.assertEqual(len(list((root / "details").glob("*.json"))), 1)
        self.assertTrue(unrelated.is_file())

    def test_interrupted_index_write_is_rebuilt_from_committed_receipts(self) -> None:
        root = preserved_test_dir("index-interrupted-")
        bindings = {
            "baseline_sha256": "sha256:" + "a" * 64,
            "baseline_commit": "a" * 40,
            "baseline_tree": "b" * 40,
            "specification_sha256": "sha256:" + "b" * 64,
            "oracle_sha256": "sha256:" + "c" * 64,
            "prompt_sha256": {
                "planner": "sha256:" + "d" * 64,
                "developer": "sha256:" + "e" * 64,
                "qa": "sha256:" + "f" * 64,
            },
            "iteration": 1,
            "candidate_sha256": "sha256:" + "1" * 64,
            "prior_receipt_sha256": None,
        }
        store = ReceiptStore(root, "run-001")
        first = store.append(
            {
                "run_id": "run-001",
                "iteration": 1,
                "stage": "planner",
                "status": "complete",
                "bindings": bindings,
                "details": {"observation": "planned"},
            }
        )

        def interrupted(path: Path, raw: bytes) -> None:
            path.write_bytes(raw[:9])
            raise OSError("simulated interrupted index write")

        store._write_index_temporary = interrupted
        with self.assertRaisesRegex(OSError, "simulated interrupted index write"):
            store.append(
                {
                    "run_id": "run-001",
                    "iteration": 1,
                    "stage": "developer",
                    "status": "complete",
                    "bindings": {**bindings, "prior_receipt_sha256": first["sha256"]},
                    "details": {"observation": "changed"},
                }
            )
        unrelated = root / ".index.md-unrelated.tmp"
        unrelated.write_text("unrelated", encoding="utf-8")
        committed = sorted((root / "details").glob("*.json"))[-1]
        committed_head = sha256_bytes(committed.read_bytes())

        reopened = ReceiptStore(root, "run-001")

        self.assertEqual(reopened.head, committed_head)
        self.assertIn(committed_head, (root / "index.md").read_text(encoding="utf-8"))
        self.assertTrue(unrelated.is_file())


class DeterministicRoleAdapter:
    runtime_id = "double"

    def __init__(self, *, completed_developer: bool = False, runtime_id: str = "double"):
        self.calls: list[tuple[int, str]] = []
        self.completed_developer = completed_developer
        self.runtime_id = runtime_id
        self.requests = []

    def maximum_charge(self, _role: str) -> int:
        return 10

    def invoke(self, request, _prompt, view, _deadline):
        role = request["role"]
        iteration = request["iteration"]
        self.calls.append((iteration, role))
        self.requests.append(deepcopy(request))
        decision = "ready"
        if role == "planner":
            with self._must_refuse():
                view.read_text("candidate/linkcheck.py")
            output = (
                f"## Project Planner Priorities\nIteration {iteration}\n"
                "### Priority Order\n1. Repair the next observed fixture gap.\n"
                "### Preservation Gate\nPreserve every passing requirement.\n"
                "### Acceptance Gate\nRun the fixed oracle and report all observations.\n"
            )
        elif role == "developer":
            current = view.read_text("candidate/linkcheck.py")
            if self.completed_developer:
                output_source = current + f"\n# verified iteration {iteration}\n"
            else:
                output_source = self._source_for_iteration(iteration)
            view.write_text("candidate/linkcheck.py", output_source)
            output = f"## Changes\nChanged fixture behavior for iteration {iteration}.\n## Validation\nCoordinator runs the fixed oracle.\n"
        else:
            with self._must_refuse():
                view.write_text("candidate/linkcheck.py", "changed")
            view.read_text(f"developer-report/iteration-{iteration}-developer.md")
            decision = "rework" if "FAILED" in _prompt else "ready"
            output = (
                f"## Status\n{decision}\n## Evidence\nIteration {iteration} deterministic output.\n"
                "## Gaps\nSee named failed tests, if any.\n## Next action\nFollow the coordinator gate.\n"
            )
        usage = {
            "schema": "vivary.hoh-usage/v1",
            "vendor_usage_raw": {"source": "deterministic-role-double"},
            "aggregate_input_tokens": 1,
            "aggregate_output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_write_input_tokens": 0,
            "budget_counted_tokens": 2,
            "claude_agentic_turns": None,
            "codex_top_level_turns": None,
            "complete": True,
        }
        return {
            "schema": "vivary.hoh-role-result/v2",
            "run_id": request["run_id"],
            "iteration": iteration,
            "role": role,
            "binding": deepcopy(request["binding"]), "attempt": request["attempt"],
            "submission": submission(request, decision),
            "request_sha256": sha256_bytes(canonical_json_bytes(request)),
            "output_kind": {
                "planner": "development_document",
                "developer": "developer_report",
                "qa": "evidence_report",
            }[role],
            "output_text": output,
            "output_sha256": sha256_bytes(output.encode()),
            "usage": usage,
            "complete": True,
        }

    class _must_refuse:
        def __enter__(self):
            return self

        def __exit__(self, error_type, _error, _traceback):
            if error_type is None or not issubclass(error_type, (PermissionError, FileNotFoundError)):
                raise AssertionError("role view unexpectedly allowed forbidden operation")
            return True

    @staticmethod
    def _source_for_iteration(iteration: int) -> str:
        common = """\
from __future__ import annotations
import re
from pathlib import Path
from urllib.parse import unquote
LINK = re.compile(r"\\[[^\\]]*\\]\\(([^)]+)\\)")
def check_tree(root: Path) -> list[dict[str, str]]:
    findings = []
    root = root.resolve()
    for source in sorted(root.rglob("*.md")):
        for raw_target in LINK.findall(source.read_text(encoding="utf-8")):
            target = unquote(raw_target.strip())
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            file_target = target.split("#", 1)[0]
"""
        anchor = "" if iteration >= 3 else """\
            if not file_target:
                findings.append({"source": source.relative_to(root).as_posix(), "target": target, "code": "missing_target"})
                continue
"""
        missing = """\
            if not file_target:
                continue
            resolved = (source.parent / file_target).resolve()
            record = {"source": source.relative_to(root).as_posix(), "target": target}
"""
        escape = (
            """\
            if not resolved.is_relative_to(root):
                findings.append({**record, "code": "path_escape"})
            elif not resolved.is_file():
                findings.append({**record, "code": "missing_target"})
"""
            if iteration >= 2
            else """\
            if resolved.is_relative_to(root) and not resolved.is_file():
                findings.append({**record, "code": "missing_target"})
"""
        )
        return common + anchor + missing + escape + "    return sorted(findings, key=lambda item: (item['source'], item['target']))\n"


class RetryOnceAdapter(DeterministicRoleAdapter):
    def __init__(self, *, completed_developer: bool = False):
        super().__init__(completed_developer=completed_developer)
        self.retried = False

    def invoke(self, request, prompt, view, deadline):
        result = super().invoke(request, prompt, view, deadline)
        if request["role"] == "planner" and not self.retried:
            self.retried = True
            return {**result, "unknown": "schema violation"}
        return result


class StaleResultAdapter(DeterministicRoleAdapter):
    def invoke(self, request, prompt, view, deadline):
        result = super().invoke(request, prompt, view, deadline)
        if request["role"] == "planner":
            return {**result, "run_id": "stale-run"}
        return result


class InvalidMutatingDeveloperAdapter(DeterministicRoleAdapter):
    def invoke(self, request, prompt, view, deadline):
        result = super().invoke(request, prompt, view, deadline)
        if request["role"] == "developer":
            return {**result, "unexpected": "invalid after mutation"}
        return result


class UnknownMaximumAdapter:
    runtime_id = "double"

    def __init__(self):
        self.invoked = False

    def maximum_charge(self, _role):
        return None

    def invoke(self, *_args):
        self.invoked = True
        raise AssertionError("unknown maximum must refuse before adapter invocation")


class StallingPlannerAdapter(DeterministicRoleAdapter):
    def __init__(self):
        super().__init__()
        self.recorded_pids: list[int] = []

    def invoke(self, request, _prompt, view, deadline):
        self.calls.append((request["iteration"], request["role"]))
        if request["role"] != "planner":
            raise AssertionError("deadline failure must prevent the next role")
        root = preserved_test_dir("sequencer-stall-child-")
        script = root / "stall.py"
        pids = root / "pids.json"
        grandchild = root / "grandchild.pid"
        script.write_text(
            """\
import json, os, signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([
    sys.executable, "-c",
    "import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "open(os.environ['GRANDCHILD_PID'], 'w').write(str(os.getpid())); time.sleep(60)",
], env={**os.environ, "GRANDCHILD_PID": sys.argv[2]})
open(sys.argv[1], "w").write(json.dumps({"parent": os.getpid(), "child": child.pid}))
time.sleep(60)
""",
            encoding="utf-8",
        )
        process = run_owned_process(
            [sys.executable, str(script), str(pids), str(grandchild)],
            cwd=view.root,
            deadline=deadline,
        )
        recorded = json.loads(pids.read_text(encoding="utf-8"))
        self.recorded_pids = [*recorded.values(), int(grandchild.read_text(encoding="utf-8"))]
        output = "late planner output"
        usage = {
            "schema": "vivary.hoh-usage/v1",
            "vendor_usage_raw": {"source": "stalled-double", "process": process},
            "aggregate_input_tokens": None,
            "aggregate_output_tokens": None,
            "cache_read_input_tokens": None,
            "cache_write_input_tokens": None,
            "budget_counted_tokens": None,
            "claude_agentic_turns": None,
            "codex_top_level_turns": None,
            "complete": False,
        }
        return {
            "schema": "vivary.hoh-role-result/v2",
            "run_id": request["run_id"],
            "iteration": request["iteration"],
            "role": request["role"],
            "binding": request["binding"], "attempt": request["attempt"],
            "submission": submission(request),
            "request_sha256": sha256_bytes(canonical_json_bytes(request)),
            "output_kind": "development_document",
            "output_text": output,
            "output_sha256": sha256_bytes(output.encode()),
            "usage": usage,
            "complete": False,
        }


class OverrunAdapter(DeterministicRoleAdapter):
    def invoke(self, request, prompt, view, deadline):
        result = super().invoke(request, prompt, view, deadline)
        result["usage"] = {
            **result["usage"],
            "aggregate_input_tokens": 6,
            "aggregate_output_tokens": 5,
            "budget_counted_tokens": 11,
        }
        return result


class OrdinaryRegressionAdapter(DeterministicRoleAdapter):
    def __init__(self):
        super().__init__(completed_developer=True)

    def invoke(self, request, prompt, view, deadline):
        if request["role"] == "developer" and request["iteration"] == 2:
            self.completed_developer = False
            result = super().invoke(request, prompt, view, deadline)
            self.completed_developer = True
            return result
        return super().invoke(request, prompt, view, deadline)


class FixedInputMutationAdapter(DeterministicRoleAdapter):
    def __init__(self, specification: Path):
        super().__init__()
        self.specification = specification

    def invoke(self, request, prompt, view, deadline):
        result = super().invoke(request, prompt, view, deadline)
        if request["role"] == "planner":
            self.specification.write_text("# Mutated specification\n", encoding="utf-8")
        return result


class NoProgressAdapter(DeterministicRoleAdapter):
    def __init__(self):
        super().__init__(completed_developer=True)

    def invoke(self, request, prompt, view, deadline):
        if request["role"] != "developer":
            return super().invoke(request, prompt, view, deadline)
        original = view.read_text("candidate/linkcheck.py")
        result = super().invoke(request, prompt, view, deadline)
        view.write_text("candidate/linkcheck.py", original)
        return result


class SequencerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = preserved_test_dir("sequencer-")
        self.fixture = ROOT / "docs/product/multi-project/fixtures/hoh-loop"
        self.prompts = ROOT / "tools/hoh/prompts"

    def _project(self, name: str) -> Path:
        destination = self.root / name
        shutil.copytree(self.fixture, destination)
        for path in destination.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        destination.chmod(0o755)
        return destination

    def _loop(self, name: str, project: Path, adapter: DeterministicRoleAdapter, iterations: int = 1) -> HeadlessLoop:
        return make_test_loop(
            project=project,
            receipt_dir=self.root / f"{name}-receipts",
            prompt_dir=self.prompts,
            run_id=name,
            iterations=iterations,
            iteration_timeout_seconds=60,
            reported_token_budget=1000,
            usage_ledger=self.root / f"{name}-usage.json",
            adapter=adapter,
        )

    def _interrupted_after_developer(self, name: str) -> tuple[Path, Path, Path]:
        project = self._project(f"{name}-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = DeterministicRoleAdapter(completed_developer=True)
        loop = self._loop(name, project, adapter)
        result = loop.run(RunFault(interrupt_after_developer=True))
        self.assertEqual(result["status"], "interrupted")
        return project, self.root / f"{name}-receipts", self.root / f"{name}-usage.json"

    def test_resume_after_accepted_developer_receipt_before_state_write(self) -> None:
        project = self._project("receipt-gap-project")
        project.joinpath("linkcheck.py").write_text(DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8")
        first = self._loop("receipt-gap", project, DeterministicRoleAdapter(completed_developer=True))
        result = first.run(RunFault(interrupt_before_developer_state=True))
        self.assertEqual(result["status"], "interrupted")
        stale = json.loads(first.state_path.read_text(encoding="utf-8"))
        self.assertEqual(stale["stage"], "iteration_started")
        deadline = json.loads(Path(stale["deadline_path"]).read_text(encoding="utf-8"))
        ledger_before = first.ledger.snapshot()
        adapter = DeterministicRoleAdapter(completed_developer=True)
        reopened = self._loop("receipt-gap", project, adapter)
        self.assertEqual(reopened.run()["status"], "complete")
        self.assertEqual(adapter.calls, [(1, "qa")])
        self.assertEqual(reopened.ledger.snapshot()["charged"], ledger_before["charged"] + 2)
        resumed_deadline = json.loads(Path(stale["deadline_path"]).read_text(encoding="utf-8"))
        for field in ("expires_unix_ns", "started_monotonic_ns", "boot_id", "duration_seconds"):
            self.assertEqual(resumed_deadline[field], deadline[field])
        self.assertEqual(reopened.run()["status"], "complete")
        self.assertEqual(adapter.calls, [(1, "qa")])

    def test_three_iterations_preserve_order_bindings_and_reach_green(self) -> None:
        project = self._project("healthy-project")
        adapter = DeterministicRoleAdapter()
        loop = self._loop("healthy", project, adapter, iterations=3)

        result = loop.run()

        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            adapter.calls,
            [(1, "planner"), (1, "developer"), (1, "qa"),
             (2, "planner"), (2, "developer"), (2, "qa"),
             (3, "planner"), (3, "developer"), (3, "qa")],
        )
        self.assertEqual(run_product_tests(project, timeout_seconds=10)["returncode"], 0)
        details = sorted((self.root / "healthy-receipts/details").glob("*.json"))
        self.assertGreaterEqual(len(details), 12)
        for path in details:
            payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
            self.assertEqual(payload["bindings"]["baseline_sha256"], loop.baseline_sha256)
            self.assertEqual(payload["bindings"]["baseline_commit"], loop.baseline_commit)
            self.assertEqual(payload["bindings"]["baseline_tree"], loop.baseline_tree)
            self.assertEqual(payload["bindings"]["specification_sha256"], loop.common["specification_sha256"])
            self.assertEqual(payload["bindings"]["oracle_sha256"], loop.common["oracle_sha256"])
            if payload["stage"] in {"planner", "developer", "qa"} and payload["status"] == "complete":
                request = payload["details"]["role_request"]
                self.assertGreater(request["prompt_bytes"], 0)
                self.assertTrue(request["prompt_sha256"].startswith("sha256:"))
                opened = payload["details"]["opened_receipt_files"]
                self.assertIn("receipts/index.md", opened)
                self.assertTrue(any(name.startswith("receipts/details/") for name in opened))

    def test_new_baseline_refuses_dirty_staged_untracked_and_ignored_files(self) -> None:
        for kind in ("dirty", "staged", "untracked", "ignored"):
            with self.subTest(kind=kind):
                project = self._project(f"baseline-{kind}-project")
                if kind == "ignored":
                    project.joinpath(".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
                subprocess.run(["git", "init", "-q"], cwd=project, check=True)
                subprocess.run(["git", "add", "-A"], cwd=project, check=True)
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=baseline-test",
                        "-c",
                        "user.email=baseline@example.invalid",
                        "commit",
                        "-q",
                        "-m",
                        "baseline",
                    ],
                    cwd=project,
                    check=True,
                )
                if kind in {"dirty", "staged"}:
                    project.joinpath("linkcheck.py").write_text("changed\n", encoding="utf-8")
                    if kind == "staged":
                        subprocess.run(["git", "add", "linkcheck.py"], cwd=project, check=True)
                elif kind == "untracked":
                    project.joinpath("untracked.txt").write_text("untracked\n", encoding="utf-8")
                else:
                    project.joinpath("ignored.tmp").write_text("ignored\n", encoding="utf-8")
                adapter = DeterministicRoleAdapter()
                loop = self._loop(f"baseline-{kind}", project, adapter)

                with self.assertRaisesRegex(HarnessError, "clean Git worktree"):
                    loop.run()

                self.assertEqual(adapter.calls, [])
                self.assertFalse(loop.baseline_path.exists())

    def test_one_schema_retry_is_allowed_and_a_maximum_is_required_before_invocation(self) -> None:
        retry_project = self._project("retry-project")
        (retry_project / "linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        retry = RetryOnceAdapter(completed_developer=True)
        result = self._loop("retry", retry_project, retry).run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(retry.calls[:2], [(1, "planner"), (1, "planner")])
        self.assertEqual(len(retry.calls), 4)

        refusal_project = self._project("refusal-project")
        refusal = UnknownMaximumAdapter()
        with self.assertRaises(BudgetError):
            self._loop("refusal", refusal_project, refusal).run()
        self.assertFalse(refusal.invoked)
        self.assertEqual(
            UsageLedger(self.root / "refusal-usage.json", packet_budget=1000).snapshot()["charged"],
            0,
        )

    def test_stale_identity_retains_reservation_without_a_schema_retry(self) -> None:
        project = self._project("stale-result-project")
        adapter = StaleResultAdapter()
        ledger_path = self.root / "stale-result-usage.json"
        loop = make_test_loop(
            project=project,
            receipt_dir=self.root / "stale-result-receipts",
            prompt_dir=self.prompts,
            run_id="stale-result",
            iterations=1,
            iteration_timeout_seconds=60,
            reported_token_budget=10,
            usage_ledger=ledger_path,
            adapter=adapter,
        )

        with self.assertRaisesRegex(HarnessError, "identity mismatch"):
            loop.run()

        self.assertEqual(adapter.calls, [(1, "planner")])
        reservation = UsageLedger(ledger_path, packet_budget=10).snapshot()["reservations"][
            "stale-result-1-planner-1"
        ]
        self.assertEqual(reservation["status"], "incomplete")
        self.assertEqual(reservation["charged"], reservation["maximum"])

    def test_invalid_mutating_developer_attempt_is_not_retried_or_exported(self) -> None:
        project = self._project("invalid-developer-project")
        original = project.joinpath("linkcheck.py").read_bytes()
        adapter = InvalidMutatingDeveloperAdapter()
        ledger_path = self.root / "invalid-developer-usage.json"

        with self.assertRaisesRegex(HarnessError, "mutated its writable projection"):
            self._loop("invalid-developer", project, adapter).run()

        self.assertEqual(adapter.calls, [(1, "planner"), (1, "developer")])
        self.assertEqual(project.joinpath("linkcheck.py").read_bytes(), original)
        reservation = UsageLedger(ledger_path, packet_budget=1000).snapshot()["reservations"][
            "invalid-developer-1-developer-1"
        ]
        self.assertEqual(reservation["status"], "incomplete")
        self.assertEqual(reservation["charged"], reservation["maximum"])

    def test_overrun_stops_before_next_role_and_final_red_stays_failed_after_reopen(self) -> None:
        overrun_project = self._project("overrun-project")
        overrun = OverrunAdapter()
        with self.assertRaisesRegex(HarnessError, "exceeded or corrupted"):
            self._loop("overrun", overrun_project, overrun).run()
        self.assertEqual(overrun.calls, [(1, "planner")])
        reservation = UsageLedger(
            self.root / "overrun-usage.json", packet_budget=1000
        ).snapshot()["reservations"]["overrun-1-planner-1"]
        self.assertEqual(reservation["status"], "overrun")
        self.assertEqual(reservation["charged"], 11)

        red_project = self._project("final-red-project")
        red_adapter = DeterministicRoleAdapter()
        with self.assertRaisesRegex(HarnessError, "completion gate rejected"):
            self._loop("final-red", red_project, red_adapter).run()
        first_calls = list(red_adapter.calls)
        self.assertEqual(first_calls, [(1, "planner"), (1, "developer"), (1, "qa")])
        reopened = DeterministicRoleAdapter()
        with self.assertRaisesRegex(HarnessError, "terminal failed run"):
            self._loop("final-red", red_project, reopened).run()
        self.assertEqual(reopened.calls, [])

    def test_ordinary_loss_of_previously_passing_behavior_stops_as_regression(self) -> None:
        project = self._project("ordinary-regression-project")
        (project / "linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = OrdinaryRegressionAdapter()

        result = self._loop("ordinary-regression", project, adapter, iterations=2).run()

        self.assertEqual(result["status"], "regressed")
        self.assertIn(
            "test_links.LinkCheckTests.test_ignores_anchor_only_target",
            result["lost_passing_test_ids"],
        )
        self.assertEqual(adapter.calls[-1], (2, "developer"))
        self.assertNotIn((2, "qa"), adapter.calls)
        ledger = UsageLedger(self.root / "ordinary-regression-usage.json", packet_budget=1000).snapshot()
        self.assertNotIn("ordinary-regression-2-qa-1", ledger["reservations"])
        receipts = [
            json.loads(path.read_text(encoding="utf-8"))["payload"]
            for path in sorted((self.root / "ordinary-regression-receipts/details").glob("*.json"))
        ]
        terminal = receipts[-1]
        self.assertEqual((terminal["stage"], terminal["status"]), ("test", "regressed"))
        self.assertEqual(terminal["details"]["lost_passing_test_ids"], result["lost_passing_test_ids"])
        self.assertEqual(terminal["details"]["healthy_candidate_sha256"], result["healthy_candidate_sha256"])
        self.assertEqual(
            terminal["details"]["evidence"]["candidate_sha256"],
            terminal["bindings"]["frozen_candidate_sha256"],
        )
        self.assertNotIn("handoff", terminal["details"])

    def test_partial_oracle_after_prior_green_is_incomplete_and_terminal(self) -> None:
        project = self._project("partial-later-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = OrdinaryRegressionAdapter()

        def partial_later(candidate, **kwargs):
            result = run_product_tests(candidate, **kwargs)
            if candidate.name == "iteration-2":
                result["oracle_complete"] = False
                result["passed_test_ids"] = []
            return result

        with patch("hoh_loop.run_product_tests", side_effect=partial_later):
            with self.assertRaisesRegex(HarnessError, "did not execute every declared test"):
                self._loop("partial-later", project, adapter, iterations=2).run()

        receipts = self.root / "partial-later-receipts"
        terminal = json.loads(sorted((receipts / "details").glob("*.json"))[-1].read_text())["payload"]
        self.assertEqual((terminal["stage"], terminal["status"]), ("test", "incomplete"))
        self.assertFalse(terminal["details"]["evidence"]["complete"])
        self.assertTrue(terminal["details"]["lost_passing_test_ids"])
        self.assertIn("output", terminal["details"])
        self.assertEqual(json.loads((receipts / "state.json").read_text())["stage"], "failed")
        self.assertNotIn((2, "qa"), adapter.calls)
        ledger = self.root / "partial-later-usage.json"
        original_ledger = ledger.read_bytes()
        self.assertNotIn("partial-later-2-qa-1", json.loads(original_ledger)["reservations"])
        reopened = OrdinaryRegressionAdapter()
        with self.assertRaisesRegex(HarnessError, "terminal failed run"):
            self._loop("partial-later", project, reopened, iterations=2).run()
        self.assertEqual(reopened.calls, [])
        self.assertEqual(ledger.read_bytes(), original_ledger)

    def test_regression_refuses_project_changed_during_oracle(self) -> None:
        project = self._project("moving-regression-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = OrdinaryRegressionAdapter()

        def mutate_later(candidate, **kwargs):
            result = run_product_tests(candidate, **kwargs)
            if candidate.name == "iteration-2":
                with project.joinpath("linkcheck.py").open("a", encoding="utf-8") as handle:
                    handle.write("# concurrent project change\n")
            return result

        with patch("hoh_loop.run_product_tests", side_effect=mutate_later):
            with self.assertRaisesRegex(HarnessError, "candidate changed during oracle execution"):
                self._loop("moving-regression", project, adapter, iterations=2).run()

        receipts = self.root / "moving-regression-receipts"
        terminal = json.loads(sorted((receipts / "details").glob("*.json"))[-1].read_text())["payload"]
        self.assertEqual((terminal["stage"], terminal["status"]), ("test", "incomplete"))
        self.assertEqual(terminal["details"]["observation"], "project-candidate-changed-during-oracle")
        self.assertEqual(terminal["bindings"]["candidate_sha256"], hash_tree(project))
        self.assertNotEqual(terminal["details"]["project_candidate_before_sha256"], hash_tree(project))
        self.assertNotIn((2, "qa"), adapter.calls)
        reopened = OrdinaryRegressionAdapter()
        with self.assertRaisesRegex(HarnessError, "terminal failed run"):
            self._loop("moving-regression", project, reopened, iterations=2).run()
        self.assertEqual(reopened.calls, [])

    def test_incomplete_pre_regression_oracle_stops_before_injection_and_qa(self) -> None:
        project = self._project("pre-regression-partial-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = DeterministicRoleAdapter(completed_developer=True)
        injections = []

        def partial(candidate, **kwargs):
            result = run_product_tests(candidate, **kwargs)
            if candidate.name.endswith("pre-regression"):
                result["oracle_complete"] = False
            return result

        with patch("hoh_loop.run_product_tests", side_effect=partial):
            with self.assertRaisesRegex(HarnessError, "pre-regression oracle execution was incomplete"):
                self._loop("pre-regression-partial", project, adapter).run(
                    RunFault(regress_before_qa=lambda candidate: injections.append(candidate))
                )
        self.assertEqual(injections, [])
        self.assertEqual(adapter.calls, [(1, "planner"), (1, "developer")])
        receipts = self.root / "pre-regression-partial-receipts"
        terminal = json.loads(sorted((receipts / "details").glob("*.json"))[-1].read_text())["payload"]
        self.assertEqual((terminal["stage"], terminal["status"]), ("test", "incomplete"))
        self.assertEqual(terminal["details"]["observation"], "pre-regression-oracle-incomplete")
        self.assertIn("process_evidence", terminal["details"])
        ledger = self.root / "pre-regression-partial-usage.json"
        original_ledger = ledger.read_bytes()
        deadline_path = receipts / "iteration-1-deadline.json"
        original_deadline = deadline_path.read_bytes()
        reopened = DeterministicRoleAdapter(completed_developer=True)
        with self.assertRaisesRegex(HarnessError, "terminal failed run"):
            self._loop("pre-regression-partial", project, reopened).run()
        self.assertEqual(reopened.calls, [])
        self.assertEqual(ledger.read_bytes(), original_ledger)
        self.assertEqual(deadline_path.read_bytes(), original_deadline)

    def test_regression_deadline_expiry_after_receipt_stops_without_qa(self) -> None:
        project = self._project("late-regression-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = OrdinaryRegressionAdapter()
        loop = self._loop("late-regression", project, adapter, iterations=2)
        original_append = loop._append
        original_remaining = IterationDeadline.remaining
        expired = False

        def append_then_expire(iteration, stage, status, *args, **kwargs):
            nonlocal expired
            result = original_append(iteration, stage, status, *args, **kwargs)
            if (stage, status) == ("test", "regressed"):
                expired = True
            return result

        def remaining(deadline):
            if expired:
                raise DeadlineError("test expiry after regression receipt")
            return original_remaining(deadline)

        with patch.object(loop, "_append", side_effect=append_then_expire):
            with patch.object(IterationDeadline, "remaining", remaining):
                with self.assertRaisesRegex(DeadlineError, "test expiry"):
                    loop.run()

        receipts = self.root / "late-regression-receipts"
        terminal = json.loads(sorted((receipts / "details").glob("*.json"))[-1].read_text())["payload"]
        self.assertEqual((terminal["stage"], terminal["status"]), ("test", "incomplete"))
        self.assertEqual(terminal["details"]["observation"], "deadline-expired-before-regression-stop")
        self.assertNotIn((2, "qa"), adapter.calls)
        original_expiry = json.loads((receipts / "iteration-2-deadline.json").read_text())["expires_unix_ns"]
        reopened = OrdinaryRegressionAdapter()
        with self.assertRaisesRegex(HarnessError, "terminal failed run"):
            self._loop("late-regression", project, reopened, iterations=2).run()
        self.assertEqual(reopened.calls, [])
        self.assertEqual(json.loads((receipts / "iteration-2-deadline.json").read_text())["expires_unix_ns"], original_expiry)

    def test_fixed_inputs_are_rechecked_after_each_role_before_settlement(self) -> None:
        project = self._project("fixed-input-project")
        adapter = FixedInputMutationAdapter(project / "spec.md")

        with self.assertRaisesRegex(HarnessError, "specification, oracle, or role prompt"):
            self._loop("fixed-input", project, adapter).run()

        self.assertEqual(adapter.calls, [(1, "planner")])
        ledger = UsageLedger(self.root / "fixed-input-usage.json", packet_budget=1000).snapshot()
        reservation = ledger["reservations"]["fixed-input-1-planner-1"]
        self.assertEqual(reservation["status"], "incomplete")
        self.assertEqual(reservation["charged"], reservation["maximum"])

    def test_two_consecutive_iterations_without_candidate_progress_stop(self) -> None:
        project = self._project("no-progress-project")
        (project / "linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        adapter = NoProgressAdapter()

        with self.assertRaisesRegex(HarnessError, "progress_allowed"):
            self._loop("no-progress", project, adapter, iterations=3).run()

        self.assertEqual(adapter.calls[-1], (3, "qa"))

    @unittest.skipIf(os.name == "nt", "process-group evidence runs in Habitat Linux")
    def test_stalled_role_retains_reservation_writes_incomplete_receipt_and_deadline_on_restart(self) -> None:
        project = self._project("stalled-project")
        adapter = StallingPlannerAdapter()
        loop = make_test_loop(
            project=project,
            receipt_dir=self.root / "stalled-receipts",
            prompt_dir=self.prompts,
            run_id="stalled",
            iterations=1,
            iteration_timeout_seconds=1.5,
            reported_token_budget=100,
            usage_ledger=self.root / "stalled-usage.json",
            adapter=adapter,
        )
        with self.assertRaisesRegex(HarnessError, "after the iteration deadline"):
            loop.run()
        self.assertEqual(adapter.calls, [(1, "planner")])
        self.assertEqual(len(adapter.recorded_pids), 3)
        for pid in adapter.recorded_pids:
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"pid {pid} was not reaped")
        ledger = UsageLedger(self.root / "stalled-usage.json", packet_budget=100).snapshot()
        self.assertEqual(ledger["charged"], 10)
        reservation = ledger["reservations"]["stalled-1-planner-1"]
        self.assertEqual(reservation["status"], "incomplete")
        self.assertEqual(reservation["charged"], reservation["maximum"])
        receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((self.root / "stalled-receipts/details").glob("*.json"))]
        self.assertEqual(receipts[-1]["payload"]["status"], "incomplete")
        deadline_path = self.root / "stalled-receipts/iteration-1-deadline.json"
        original_expiry = json.loads(deadline_path.read_text(encoding="utf-8"))["expires_unix_ns"]

        restarted = StallingPlannerAdapter()
        with self.assertRaises(DeadlineError):
            make_test_loop(
                project=project,
                receipt_dir=self.root / "stalled-receipts",
                prompt_dir=self.prompts,
                run_id="stalled",
                iterations=1,
                iteration_timeout_seconds=1.5,
                reported_token_budget=100,
                usage_ledger=self.root / "stalled-usage.json",
                adapter=restarted,
            ).run()
        self.assertEqual(restarted.calls, [])
        self.assertEqual(json.loads(deadline_path.read_text(encoding="utf-8"))["expires_unix_ns"], original_expiry)

    def test_resume_after_developer_checkpoint_does_not_rerun_developer(self) -> None:
        project = self._project("resume-project")
        (project / "linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        first_adapter = DeterministicRoleAdapter(completed_developer=True)
        first = self._loop("resume", project, first_adapter)
        interrupted = first.run(RunFault(interrupt_after_developer=True))
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(first_adapter.calls, [(1, "planner"), (1, "developer")])
        original_expiry = json.loads(
            (self.root / "resume-receipts/iteration-1-deadline.json").read_text(encoding="utf-8")
        )["expires_unix_ns"]

        resumed_adapter = DeterministicRoleAdapter(completed_developer=True)
        resumed = self._loop("resume", project, resumed_adapter).run()

        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(resumed_adapter.calls, [(1, "qa")])
        self.assertEqual(
            json.loads((self.root / "resume-receipts/iteration-1-deadline.json").read_text(encoding="utf-8"))["expires_unix_ns"],
            original_expiry,
        )

    def test_resume_refuses_changed_or_missing_developer_artifacts(self) -> None:
        cases = (
            ("changed-development", "iteration-1-development.md", "change"),
            ("missing-development", "iteration-1-development.md", "remove"),
            ("changed-report", "iteration-1-developer.md", "change"),
            ("missing-report", "iteration-1-developer.md", "remove"),
        )
        for suffix, name, operation in cases:
            with self.subTest(artifact=suffix):
                run_id = f"resume-artifact-{suffix}"
                project, receipts, _ledger = self._interrupted_after_developer(run_id)
                artifact = receipts / "documents" / name
                if operation == "change":
                    artifact.write_text("altered after checkpoint\n", encoding="utf-8")
                else:
                    artifact.unlink()
                adapter = DeterministicRoleAdapter(completed_developer=True)

                with self.assertRaisesRegex(HarnessError, "development document|developer report"):
                    self._loop(run_id, project, adapter).run()

                self.assertEqual(adapter.calls, [])

    def test_regressed_state_is_terminal_even_without_derived_role_views(self) -> None:
        project = self._project("terminal-regression-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )

        def inject(candidate: Path) -> None:
            source = candidate / "linkcheck.py"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "elif not resolved.is_file():", "elif False and not resolved.is_file():"
                ),
                encoding="utf-8",
            )

        first_adapter = DeterministicRoleAdapter(completed_developer=True)
        result = self._loop("terminal-regression", project, first_adapter).run(
            RunFault(regress_before_qa=inject)
        )
        self.assertEqual(result["status"], "regressed")
        self.assertEqual(first_adapter.calls, [(1, "planner"), (1, "developer")])
        ledger_path = self.root / "terminal-regression-usage.json"
        ledger_before = ledger_path.read_bytes()
        receipts = self.root / "terminal-regression-receipts"
        for derived in (receipts / "role-views", receipts / "role-receipt-projections"):
            derived.rename(receipts / f"retained-{derived.name}")

        reopened_adapter = DeterministicRoleAdapter(completed_developer=True)
        with self.assertRaisesRegex(HarnessError, "terminal regressed run"):
            self._loop("terminal-regression", project, reopened_adapter).run()
        self.assertEqual(reopened_adapter.calls, [])
        self.assertEqual(ledger_path.read_bytes(), ledger_before)

    def test_resume_refuses_changed_or_missing_ledger_and_changed_policy(self) -> None:
        project, receipts, ledger = self._interrupted_after_developer("resume-ledger-missing")
        ledger.unlink()
        adapter = DeterministicRoleAdapter(completed_developer=True)
        with self.assertRaisesRegex(HarnessError, "ledger"):
            self._loop("resume-ledger-missing", project, adapter).run()
        self.assertEqual(adapter.calls, [])

        project, receipts, ledger = self._interrupted_after_developer("resume-ledger-path")
        adapter = DeterministicRoleAdapter(completed_developer=True)
        changed_path = self.root / "other-usage.json"
        changed = make_test_loop(
            project=project,
            receipt_dir=receipts,
            prompt_dir=self.prompts,
            run_id="resume-ledger-path",
            iterations=1,
            iteration_timeout_seconds=60,
            reported_token_budget=1000,
            usage_ledger=changed_path,
            adapter=adapter,
        )
        with self.assertRaisesRegex(HarnessError, "baseline binding"):
            changed.run()
        self.assertEqual(adapter.calls, [])

        project, receipts, ledger = self._interrupted_after_developer("resume-policy")
        adapter = DeterministicRoleAdapter(completed_developer=True)
        changed = make_test_loop(
            project=project,
            receipt_dir=receipts,
            prompt_dir=self.prompts,
            run_id="resume-policy",
            iterations=1,
            iteration_timeout_seconds=59,
            reported_token_budget=1000,
            usage_ledger=ledger,
            adapter=adapter,
        )
        with self.assertRaisesRegex(HarnessError, "baseline binding"):
            changed.run()
        self.assertEqual(adapter.calls, [])

    def test_resume_refuses_changed_checkpoint_receipt_head_stage_and_deadline_path(self) -> None:
        for suffix, mutate in (
            ("head", lambda state: state.update(receipt_chain_head="sha256:" + "0" * 64)),
            ("stage", lambda state: state.update(stage="iteration_complete")),
            ("deadline", lambda state: state.update(deadline_path="/tmp/other-deadline.json")),
        ):
            with self.subTest(binding=suffix):
                name = f"resume-{suffix}"
                project, receipts, _ledger = self._interrupted_after_developer(name)
                state_path = receipts / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                mutate(state)
                state_path.write_text(json.dumps(state), encoding="utf-8")
                adapter = DeterministicRoleAdapter(completed_developer=True)
                with self.assertRaises(HarnessError):
                    self._loop(name, project, adapter).run()
                self.assertEqual(adapter.calls, [])

        project, _receipts, _ledger = self._interrupted_after_developer("resume-git")
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=resume-test",
                "-c",
                "user.email=resume@example.invalid",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "unexpected checkpoint",
            ],
            cwd=project,
            check=True,
        )
        adapter = DeterministicRoleAdapter(completed_developer=True)
        with self.assertRaisesRegex(HarnessError, "Git checkpoint"):
            self._loop("resume-git", project, adapter).run()
        self.assertEqual(adapter.calls, [])

    def test_resume_refuses_a_rebound_baseline_commit_and_tree(self) -> None:
        project, receipts, _ledger = self._interrupted_after_developer("resume-baseline")
        baseline_path = receipts / "baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["baseline_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        baseline["baseline_tree"] = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        adapter = DeterministicRoleAdapter(completed_developer=True)

        with self.assertRaisesRegex(HarnessError, "receipt baseline binding differs"):
            self._loop("resume-baseline", project, adapter).run()

        self.assertEqual(adapter.calls, [])

    def test_no_progress_count_survives_restart(self) -> None:
        project = self._project("no-progress-resume-project")
        project.joinpath("linkcheck.py").write_text(
            DeterministicRoleAdapter._source_for_iteration(3), encoding="utf-8"
        )
        first_adapter = NoProgressAdapter()
        first = self._loop("no-progress-resume", project, first_adapter, iterations=3)

        interrupted = first.run(RunFault(interrupt_after_iteration=2))

        self.assertEqual(interrupted["status"], "interrupted")
        state = json.loads(
            (self.root / "no-progress-resume-receipts/state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["no_progress_count"], 1)
        resumed_adapter = NoProgressAdapter()
        with self.assertRaisesRegex(HarnessError, "progress_allowed"):
            self._loop(
                "no-progress-resume", project, resumed_adapter, iterations=3
            ).run()
        self.assertEqual(resumed_adapter.calls, [(3, "planner"), (3, "developer"), (3, "qa")])

    def test_regression_stops_acceptance_and_preserves_healthy_binding(self) -> None:
        project = self._project("regression-project")
        completed = DeterministicRoleAdapter._source_for_iteration(3)
        (project / "linkcheck.py").write_text(completed, encoding="utf-8")
        spec_before = (project / "spec.md").read_bytes()
        oracle_before = hash_tree(project / "tests")
        prompts_before = hash_tree(self.prompts)

        def inject(candidate: Path) -> None:
            source = candidate / "linkcheck.py"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "elif not resolved.is_file():", "elif False and not resolved.is_file():"
                ),
                encoding="utf-8",
            )

        adapter = DeterministicRoleAdapter(completed_developer=True)
        result = self._loop("regression", project, adapter).run(RunFault(regress_before_qa=inject))

        self.assertEqual(result["status"], "regressed")
        self.assertIn("test_links.LinkCheckTests.test_reports_missing_relative_target", result["observations"])
        self.assertNotEqual(result["healthy_candidate_sha256"], result["injected_candidate_sha256"])
        self.assertEqual((project / "spec.md").read_bytes(), spec_before)
        self.assertEqual(hash_tree(project / "tests"), oracle_before)
        self.assertEqual(hash_tree(self.prompts), prompts_before)
        self.assertEqual(adapter.calls, [(1, "planner"), (1, "developer")])
        ledger = UsageLedger(self.root / "regression-usage.json", packet_budget=1000).snapshot()
        self.assertNotIn("regression-1-qa-1", ledger["reservations"])
        receipts = [
            json.loads(path.read_text(encoding="utf-8"))["payload"]
            for path in sorted((self.root / "regression-receipts/details").glob("*.json"))
        ]
        self.assertFalse(any(receipt["stage"] == "qa" for receipt in receipts))
        self.assertEqual((receipts[-1]["stage"], receipts[-1]["status"]), ("test", "regressed"))
        self.assertNotIn("handoff", receipts[-1]["details"])
        healthy = self.root / "regression-receipts/frozen/iteration-1-pre-regression"
        healthy_receipt = next(receipt for receipt in receipts if receipt["details"].get("fault_checkpoint") == "pre-regression")
        self.assertEqual(hash_tree(healthy), healthy_receipt["bindings"]["frozen_candidate_sha256"])
        self.assertEqual(healthy_receipt["bindings"]["candidate_sha256"], result["healthy_candidate_sha256"])

    def test_self_mutating_candidate_stops_before_test_receipt_acceptance_and_qa(self) -> None:
        project = self._project("self-mutating-project")
        source = DeterministicRoleAdapter._source_for_iteration(3).replace(
            "    findings = []\n",
            """\
    self_path = Path(__file__)
    self_path.chmod(0o644)
    with self_path.open("a", encoding="utf-8") as handle:
        handle.write("# mutated during oracle\\n")
    findings = []
""",
        )
        project.joinpath("linkcheck.py").write_text(source, encoding="utf-8")
        adapter = DeterministicRoleAdapter(completed_developer=True)

        with self.assertRaisesRegex(HarnessError, "changed during oracle execution"):
            self._loop("self-mutating", project, adapter).run()

        self.assertEqual(adapter.calls, [(1, "planner"), (1, "developer")])
        receipts = [
            json.loads(path.read_text(encoding="utf-8"))["payload"]
            for path in sorted(
                (self.root / "self-mutating-receipts/details").glob("*.json")
            )
        ]
        refusal = receipts[-1]
        self.assertEqual((refusal["stage"], refusal["status"]), ("test", "incomplete"))
        self.assertNotEqual(
            refusal["bindings"]["frozen_candidate_before_sha256"],
            refusal["bindings"]["frozen_candidate_after_sha256"],
        )
        self.assertFalse(any(payload["stage"] == "qa" for payload in receipts))


class StageBindingAndHandoffTests(unittest.TestCase):
    """Control decisions on real files, with no candidate process or real clock.

    Native sessions, Git checkpoints, oracle observations, and the deadline are
    explicit test doubles. The complete strict suite owns their runtime proof.
    """

    class DeadlineDouble:
        expires_unix_ns = 2_000_000_000

        def __init__(self, path):
            self.path = path

        def remaining(self):
            return 60

    def setUp(self):
        self.root = preserved_test_dir("stage-control-")
        self.project = self.root / "project"
        shutil.copytree(ROOT / "docs/product/multi-project/fixtures/hoh-loop", self.project)
        self.project.chmod(0o755)
        for path in self.project.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        self.baseline_hash = hash_tree(self.project)
        self.adapters = {
            runtime: DeterministicRoleAdapter(runtime_id=runtime)
            for runtime in ("claude", "codex")
        }
        self.config = test_workflow("mixed", 2, ("claude", "codex", "claude"))
        self.deadline = self.DeadlineDouble(self.root / "receipts/iteration-1-deadline.json")
        self.loop = self._open()
        self.loop._append(1, "iteration", "started", hash_tree(self.project), {"observation": "control-test-only"})
        self.loop._save_state(1, "iteration_started", self.deadline.path, previous_candidate_sha256=None, no_progress_count=0)

    def _open(self, config=None):
        loop = HeadlessLoop(
            project=self.project, receipt_dir=self.root / "receipts", prompt_dir=ROOT / "tools/hoh/prompts",
            run_id="mixed", iterations=2, iteration_timeout_seconds=60, reported_token_budget=1000,
            usage_ledger=self.root / "usage.json", workflow=config or self.config, adapters=self.adapters,
        )
        loop.receipts = ReceiptStore(loop.receipt_dir, "mixed")
        loop.baseline_sha256 = self.baseline_hash
        loop.baseline_commit, loop.baseline_tree = "1" * 40, "2" * 40
        loop._git_value = lambda *_args: "1" * 40
        loop._verify_fixed_inputs = lambda: None
        return loop

    def _view(self, role, iteration=1):
        sources = {"receipts": self.loop._receipt_projection(role, iteration)}
        if role in {"planner", "qa"}:
            sources["specification"] = self.project / "spec.md"
        if role in {"developer", "qa"}:
            sources["candidate"] = self.project / "linkcheck.py"
            sources["development"] = self.loop.documents / f"iteration-{iteration}-development.md"
        if role == "qa":
            sources["developer-report"] = self.loop.documents / f"iteration-{iteration}-developer.md"
        return self.loop._new_view(role, iteration, sources, "candidate" if role == "developer" else None)

    def _evidence(self, iteration=1, red=False):
        return {
            "schema": "vivary.hoh-evidence/v1", "run_id": "mixed", "iteration": iteration,
            "candidate_sha256": hash_tree(self.project), "command": ["control-test-oracle-double"],
            "returncode": 1 if red else 0, "output_sha256": "sha256:" + "f" * 64,
            "observations": [sorted(REQUIREMENT_IDS)[0]] if red else [], "complete": True,
        }

    def _phase(self, role, *, iteration=1, red=False, verdict=None, mutate=None):
        candidate = hash_tree(self.project)
        evidence = self._evidence(iteration, red) if role == "qa" else None
        if evidence is not None:
            self.loop._append(iteration, "test", "complete", candidate, {"evidence": evidence})
        view = self._view(role, iteration)
        result = self.loop._role_call(
            role, iteration, "FAILED" if red else "control test prompt", view, self.deadline, candidate,
            test_evidence_sha256=record_hash(evidence) if evidence else None,
        )
        if verdict:
            result["submission"]["decision"] = verdict
        if mutate:
            mutate(result)
        suffix = {"planner": "development", "developer": "developer", "qa": "evidence"}[role]
        (self.loop.documents / f"iteration-{iteration}-{suffix}.md").write_text(result["output_text"], encoding="utf-8")
        gate = evaluate_phase(
            result["_request"], result, iterations=2, candidate_unchanged=True,
            developer_source=view.read_text("candidate/linkcheck.py") if role == "developer" else None,
            developer_files={"linkcheck.py"} if role == "developer" else None, evidence=evidence,
        )
        if gate["decision"] == "blocked":
            self.loop._reject_phase(result, gate, candidate, self.deadline, evidence=evidence)
        if role == "developer":
            view.export_writable(self.project, {"linkcheck.py"})
        candidate = hash_tree(self.project)
        details = self.loop._phase_details(result, gate, candidate, evidence=evidence)
        bindings = {}
        if role == "developer":
            details["control_transition"] = {
                "prior_state_sha256": sha256_file(self.loop.state_path),
                "usage_ledger_sha256": sha256_file(self.loop.usage_ledger_path),
            }
            bindings = {
                "development_document_sha256": details["handoff"]["artifacts"]["development_document_sha256"],
                "developer_report_sha256": details["handoff"]["artifacts"]["developer_report_sha256"],
                "developer_checkpoint": "1" * 40,
            }
        if role == "qa":
            bindings = {"frozen_candidate_before_sha256": candidate, "frozen_candidate_after_sha256": candidate}
        self.loop._append(iteration, role, "complete", candidate, details, **bindings)
        return result, gate, details["handoff"], view

    def test_accepted_developer_recovers_only_its_bound_state_and_keeps_shared_usage(self):
        self._phase("planner")
        self._phase("developer")
        stale = json.loads(self.loop.state_path.read_text(encoding="utf-8"))
        usage = self.loop.usage_ledger_path.read_bytes()
        reopened = self._open()
        recovered = reopened._state()
        self.assertEqual(recovered["stage"], "developer_complete")
        self.assertEqual(recovered["deadline_path"], stale["deadline_path"])
        self.assertEqual(reopened.usage_ledger_path.read_bytes(), usage)
        self.assertEqual(reopened._state(), recovered)
        self.loop = reopened
        self._phase("qa")
        self.assertEqual(self.adapters["claude"].calls, [(1, "planner"), (1, "qa")])
        self.assertEqual(self.adapters["codex"].calls, [(1, "developer")])
        self.assertEqual(self.loop.ledger.snapshot()["charged"], 6)

    def test_developer_recovery_refuses_unbound_state_usage_and_artifact_changes(self):
        for target in ("state", "usage", "missing-usage", "developer-report"):
            with self.subTest(target=target):
                self.setUp()
                self._phase("planner")
                self._phase("developer")
                if target == "state":
                    state = json.loads(self.loop.state_path.read_text(encoding="utf-8"))
                    state["no_progress_count"] = 1
                    self.loop.state_path.write_text(json.dumps(state), encoding="utf-8")
                elif target == "usage":
                    self.loop.ledger.reserve("orphan", 10)
                elif target == "missing-usage":
                    self.loop.usage_ledger_path.unlink()
                else:
                    (self.loop.documents / "iteration-1-developer.md").write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(HarnessError, "binding differs|artifact differs"):
                    self._open()._state()
                self.assertEqual(self.adapters["claude"].calls, [(1, "planner")])

    def test_terminal_replay_revalidates_every_accepted_document(self):
        for iteration in (1, 2):
            for role in ("planner", "developer", "qa"):
                self._phase(role, iteration=iteration)
        candidate = hash_tree(self.project)
        self.loop._verify_terminal_evidence(candidate)
        for suffix in ("development", "developer", "evidence"):
            path = self.loop.documents / f"iteration-2-{suffix}.md"
            original = path.read_bytes()
            path.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(HarnessError, "accepted handoff artifact differs"):
                self.loop._verify_terminal_evidence(candidate)
            path.unlink()
            with self.assertRaisesRegex(HarnessError, "accepted handoff artifact differs"):
                self.loop._verify_terminal_evidence(candidate)
            path.write_bytes(original)
        self.loop._verify_terminal_evidence(candidate)

    def test_mixed_adapters_receive_distinct_stage_bindings_and_one_shared_budget(self):
        planner = self._phase("planner")
        developer = self._phase("developer")
        qa = self._phase("qa")
        self.assertEqual(self.adapters["claude"].calls, [(1, "planner"), (1, "qa")])
        self.assertEqual(self.adapters["codex"].calls, [(1, "developer")])
        requests = [item[0]["_request"] for item in (planner, developer, qa)]
        self.assertEqual(len({item["binding"]["agent_id"] for item in requests}), 3)
        self.assertEqual(len({item["binding"]["session_id"] for item in requests}), 3)
        self.assertIsNone(requests[0]["handoff_sha256"])
        self.assertEqual(requests[1]["handoff_sha256"], record_hash(planner[2]))
        self.assertEqual(requests[2]["handoff_sha256"], record_hash(developer[2]))
        self.assertIn("developer-report", requests[2]["read_roots"])
        self.assertIn("developer-report/iteration-1-developer.md", qa[0]["_opened_files"])
        self.assertEqual(qa[2]["successor"], self.loop.workflow.binding(2, "planner"))
        self.assertEqual(UsageLedger(self.root / "usage.json", 1000).snapshot()["charged"], 6)
        self.loop._verify_workflow_receipts()

    def test_complete_response_with_missing_plan_checks_does_not_dispatch_developer(self):
        with self.assertRaisesRegex(HarnessError, "completion gate rejected"):
            self._phase("planner", mutate=lambda result: result["submission"].update(requirements=[]))
        last = self.loop.receipts.last_payload
        self.assertTrue(last["details"]["role_result"]["complete"])
        self.assertEqual(last["details"]["phase_gate"]["decision"], "blocked")
        self.assertIsNone(last["details"]["handoff"]["successor"])
        with self.assertRaisesRegex(HarnessError, "predecessor handoff"):
            self.loop._consume_handoff(self.loop.workflow.binding(1, "developer"))
        self.assertEqual(self.adapters["codex"].calls, [])
        self.assertEqual(self.loop.ledger.snapshot()["charged"], 2)

    def test_rejected_developer_keeps_the_candidate_and_never_dispatches_qa(self):
        self._phase("planner")
        before = hash_tree(self.project)
        with self.assertRaisesRegex(HarnessError, "completion gate rejected"):
            self._phase("developer", verdict="blocked")
        self.assertEqual(hash_tree(self.project), before)
        self.assertEqual(self.adapters["claude"].calls, [(1, "planner")])

    def test_valid_incomplete_response_is_a_gate_rejection_without_schema_retry(self):
        adapter = self.adapters["claude"]
        original = adapter.invoke
        def incomplete(*args):
            result = original(*args)
            result["complete"] = False
            result["usage"]["complete"] = False
            return result
        with patch.object(adapter, "invoke", side_effect=incomplete):
            with self.assertRaisesRegex(HarnessError, "response_and_usage"):
                self._phase("planner")
        self.assertEqual(adapter.calls, [(1, "planner")])
        self.assertEqual(self.loop.ledger.snapshot()["charged"], 10)
        last = self.loop.receipts.last_payload
        self.assertEqual(last["details"]["phase_gate"]["decision"], "blocked")
        self.assertIsNone(last["details"]["handoff"]["successor"])
        self.assertEqual(self.adapters["codex"].calls, [])

    def test_qa_rework_handoff_is_bounded_and_final_completion_requires_ready_green(self):
        self._phase("planner")
        self._phase("developer")
        result, gate, handoff, _ = self._phase("qa", red=True)
        self.assertEqual(gate["decision"], "rework")
        self.assertEqual(handoff["successor"]["role"], "planner")
        self.assertEqual(handoff["successor"]["iteration"], 2)
        self.assertEqual(self.loop._consume_handoff(self.loop.workflow.binding(2, "planner")), record_hash(handoff))
        for final, red, verdict, expected in (
            (False, True, "ready", "blocked"), (False, False, "blocked", "blocked"),
            (True, True, "rework", "blocked"), (True, False, "rework", "blocked"),
            (True, False, "ready", "complete"),
        ):
            with self.subTest(final=final, red=red, verdict=verdict):
                request = deepcopy(result["_request"])
                iteration = 2 if final else 1
                request.update(iteration=iteration, binding=self.loop.workflow.binding(iteration, "qa"))
                evidence = self._evidence(iteration, red)
                request["test_evidence_sha256"] = record_hash(evidence)
                response = {**deepcopy(result), "iteration": iteration, "binding": request["binding"],
                            "request_sha256": record_hash(request), "submission": submission(request, verdict)}
                decision = evaluate_phase(request, response, iterations=2, candidate_unchanged=True, evidence=evidence)
                self.assertEqual(decision["decision"], expected)

    def test_identity_mismatches_retain_the_maximum_and_never_retry(self):
        for field in ("runtime", "agent_id", "session_id", "stage_id", "attempt", "run_id"):
            with self.subTest(field=field):
                self.setUp()
                adapter = self.adapters["claude"]
                original = adapter.invoke
                def mismatched(*args):
                    result = original(*args)
                    if field == "attempt":
                        result[field] = 2
                    elif field == "run_id":
                        result[field] = "other-run"
                    else:
                        result["binding"][field] = "other-identity"
                    return result
                with patch.object(adapter, "invoke", side_effect=mismatched):
                    with self.assertRaisesRegex(HarnessError, "identity mismatch"):
                        self._phase("planner")
                self.assertEqual(adapter.calls, [(1, "planner")])
                self.assertEqual(self.loop.ledger.snapshot()["charged"], 10)
                self.assertEqual(self.adapters["codex"].calls, [])

    def test_unsupported_runtime_reused_session_and_shared_agent_fail_before_dispatch(self):
        for mutation in (
            lambda config: config["stages"][1].update(runtime="unavailable"),
            lambda config: config["stages"][2].update(session_id=config["stages"][0]["session_id"]),
            lambda config: config["stages"][1].update(agent_id=config["stages"][0]["agent_id"]),
            lambda config: config.update(policy="unknown-policy"),
            lambda config: config["stages"].pop(),
        ):
            config = deepcopy(self.config)
            mutation(config)
            with self.assertRaises(ProtocolError):
                self._open(config)
        self.assertEqual(sum(len(a.calls) for a in self.adapters.values()), 0)

    def test_reopening_an_accepted_handoff_cannot_dispatch_the_successor_twice(self):
        self._phase("planner")
        self._phase("developer")
        _, _, _, qa_view = self._phase("qa")
        before = self.loop.ledger.snapshot()
        self.loop = self._open()
        with self.assertRaisesRegex(HarnessError, "already dispatched"):
            self.loop._role_call("qa", 1, "prompt", qa_view, self.deadline, hash_tree(self.project), record_hash(self._evidence()))
        self.assertEqual(self.loop.ledger.snapshot(), before)
        self.assertEqual(self.adapters["claude"].calls, [(1, "planner"), (1, "qa")])

    def test_crash_after_dispatch_claim_retains_reservation_and_blocks_replay(self):
        class SimulatedCrash(BaseException):
            pass
        view = self._view("planner")
        with patch.object(self.adapters["claude"], "invoke", side_effect=SimulatedCrash):
            with self.assertRaises(SimulatedCrash):
                self.loop._role_call("planner", 1, "prompt", view, self.deadline, hash_tree(self.project))
        self.loop = self._open()
        self.assertEqual(self.loop.ledger.snapshot()["charged"], 10)
        self.assertEqual(self.loop.receipts.last_payload["status"], "started")
        with self.assertRaisesRegex(HarnessError, "already dispatched"):
            self.loop._role_call("planner", 1, "prompt", view, self.deadline, hash_tree(self.project))
        self.assertEqual(self.adapters["claude"].calls, [])

    def test_repeated_handoff_record_is_refused_without_a_second_reservation(self):
        self._phase("planner")
        payload = deepcopy(self.loop.receipts.last_payload)
        self.loop._append(1, "planner", "complete", hash_tree(self.project), payload["details"])
        with self.assertRaisesRegex(HarnessError, "missing or repeated"):
            self.loop._consume_handoff(self.loop.workflow.binding(1, "developer"))
        with self.assertRaisesRegex(HarnessError, "missing or repeated"):
            self.loop._verify_workflow_receipts()
        self.assertEqual(self.loop.ledger.snapshot()["charged"], 2)

    def test_artifact_revision_and_successor_mismatches_refuse_dispatch(self):
        _, _, handoff, _ = self._phase("planner")
        changed = deepcopy(handoff)
        changed["successor"]["session_id"] = "wrong-session"
        with self.assertRaisesRegex(BindingError, "successor"):
            self.loop.workflow.validate_handoff(changed)
        document = self.loop.documents / "iteration-1-development.md"
        document.write_text("changed after acceptance", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "artifact differs"):
            self.loop._consume_handoff(self.loop.workflow.binding(1, "developer"))
        self.assertEqual(self.adapters["codex"].calls, [])

    def test_changed_workflow_or_deleted_usage_cannot_reset_a_resumed_balance(self):
        self._phase("planner")
        self.loop._save_state(1, "iteration_started", self.deadline.path, previous_candidate_sha256=None, no_progress_count=0)
        changed = deepcopy(self.config)
        changed["stages"][2]["session_id"] = "replacement-qa-session"
        with self.assertRaisesRegex(HarnessError, "resume ledger or iteration policy"):
            self._open(changed)._state()
        path = self.root / "usage.json"
        # Preserve the old ledger as fault evidence, then model a lost ledger.
        path.rename(self.root / "retained-usage-before-loss.json")
        with self.assertRaisesRegex(HarnessError, "usage ledger is missing"):
            self._open()._state()
        with self.assertRaisesRegex(HarnessError, "reservation is missing"):
            self._open()._verify_workflow_receipts()

    def test_qa_rejects_missing_stale_or_regressed_evidence_even_with_complete_usage(self):
        self._phase("planner")
        self._phase("developer")
        result, _, _, _ = self._phase("qa")
        for evidence, lost in ((None, ()), (self._evidence(red=True), ()), (self._evidence(), ("previously-passing",))):
            gate = evaluate_phase(result["_request"], result, iterations=2, candidate_unchanged=True, evidence=evidence, lost_passing=lost)
            self.assertEqual(gate["decision"], "blocked")
        stale = deepcopy(result)
        stale["submission"]["test_evidence_sha256"] = "sha256:" + "0" * 64
        with self.assertRaises(BindingError):
            evaluate_phase(result["_request"], stale, iterations=2, candidate_unchanged=True, evidence=self._evidence())

    def test_declared_gate_checks_refuse_missing_sections_invalid_code_and_extra_files(self):
        planner, _, _, _ = self._phase("planner")
        changed = deepcopy(planner)
        changed["output_text"] = "The response finished."
        changed["output_sha256"] = sha256_bytes(changed["output_text"].encode())
        gate = evaluate_phase(planner["_request"], changed, iterations=2, candidate_unchanged=True)
        self.assertEqual(gate["decision"], "blocked")
        self.assertFalse(gate["checks"]["report_sections"])
        developer, _, _, _ = self._phase("developer")
        for source, files, unchanged, reason in (
            ("def check_tree(:", {"linkcheck.py"}, True, "candidate_syntax"),
            ("def unrelated(): pass", {"linkcheck.py"}, True, "candidate_syntax"),
            ("def check_tree(root): pass", {"linkcheck.py", "other.py"}, True, "candidate_file_set"),
            ("def check_tree(root): pass", {"linkcheck.py"}, False, "candidate_unchanged"),
        ):
            gate = evaluate_phase(developer["_request"], developer, iterations=2, candidate_unchanged=unchanged,
                                  developer_source=source, developer_files=files)
            self.assertEqual(gate["decision"], "blocked")
            self.assertIn(reason, gate["reasons"])
        unknown = deepcopy(developer)
        unknown["submission"]["decision"] = "probably-complete"
        with self.assertRaises(ProtocolError):
            evaluate_phase(developer["_request"], unknown, iterations=2, candidate_unchanged=True)

    def test_no_progress_exhaustion_records_a_blocked_gate_without_a_successor(self):
        self._phase("planner")
        self._phase("developer")
        # Keep the role response but exercise the coordinator's no-progress observation.
        evidence = self._evidence()
        view = self._view("qa")
        candidate = hash_tree(self.project)
        result = self.loop._role_call("qa", 1, "green output", view, self.deadline, candidate, record_hash(evidence))
        (self.loop.documents / "iteration-1-evidence.md").write_text(result["output_text"], encoding="utf-8")
        gate = evaluate_phase(result["_request"], result, iterations=2, candidate_unchanged=True,
                              evidence=evidence, progress_allowed=False)
        with self.assertRaisesRegex(HarnessError, "progress_allowed"):
            self.loop._reject_phase(result, gate, candidate, self.deadline, evidence=evidence)
        handoff = self.loop.receipts.last_payload["details"]["handoff"]
        self.assertEqual(handoff["gate"]["decision"], "blocked")
        self.assertIsNone(handoff["successor"])
        with self.assertRaisesRegex(HarnessError, "workflow stopped"):
            self.loop._consume_handoff(self.loop.workflow.binding(2, "planner"))


class ClaudeAdapterTests(unittest.TestCase):
    def test_usage_mapping_counts_separate_cache_subsets_once_and_preserves_nulls(self) -> None:
        complete = normalize_claude_usage(
            {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
                "num_turns": 1,
            },
            command_complete=True,
        )
        self.assertEqual(complete["aggregate_input_tokens"], 15)
        self.assertEqual(complete["budget_counted_tokens"], 19)
        self.assertEqual(complete["claude_agentic_turns"], 1)
        incomplete = normalize_claude_usage({"input_tokens": 10}, command_complete=True)
        self.assertFalse(incomplete["complete"])
        self.assertIsNone(incomplete["aggregate_output_tokens"])
        self.assertIsNone(incomplete["cache_read_input_tokens"])

    def test_preflight_refuses_version_flags_isolation_usage_and_unknown_bound_without_runner(self) -> None:
        root = preserved_test_dir("claude-preflight-")
        executable = root / "claude"
        executable.write_text("native seam placeholder\n", encoding="utf-8")
        calls = []

        def runner(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner must not be invoked during failed preflight")

        valid = {
            "version": "2.1.241",
            "native_cli": True,
            "verified_flags": ["--print", "--output-format", "--tools"],
            "isolation": {
                "authenticated_host": True,
                "scoped_role_view": True,
                "builtin_tools_disabled": True,
                "credential_free_worker": True,
            },
            "usage_fields": [
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ],
            "whole_invocation_maximum_tokens": 100,
        }
        mutations = (
            {**valid, "version": "2.1.999"},
            {**valid, "verified_flags": ["--print"]},
            {**valid, "isolation": {**valid["isolation"], "credential_free_worker": False}},
            {**valid, "usage_fields": ["input_tokens", "output_tokens"]},
            {**valid, "whole_invocation_maximum_tokens": None},
            valid,
        )
        for evidence in mutations:
            with self.subTest(evidence=evidence):
                with self.assertRaises(ClaudePreflightError):
                    ClaudeAdapter(executable=executable, capability_evidence=evidence, runner=runner)
        self.assertEqual(calls, [])


class EntrypointTests(unittest.TestCase):
    def test_production_and_tests_only_entrypoints_parse_without_a_runtime_call(self) -> None:
        for script in (ROOT / "tools/hoh_loop.py", ROOT / "tools/tests/hoh_fault_probe.py"):
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    [sys.executable, "-B", str(script), "--help"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
