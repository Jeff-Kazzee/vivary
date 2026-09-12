"""Exercise the actual root provider process without application credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ENTRY = Path(__file__).resolve().parents[1] / "vivary_core/root_provider_stdio.py"


@unittest.skipUnless(sys.platform == "linux", "Root provider requires Linux custody")
class RootProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vivary-provider-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.scope = self.base / "projects"
        self.root = self.scope / "alpha"
        self.root.mkdir(parents=True)
        (self.root / "note.txt").write_text("unchanged\n")
        self.private = self.base / "private"
        self.private.mkdir()
        self.state = self.private / "roots.json"
        self.initialize = {
            "version": 1, "sequence": 0, "operation": "initialize",
            "config": {
                "deviceId": "device-test", "scope": str(self.scope),
                "statePath": str(self.state), "locations": {"alpha": str(self.root)},
            },
        }

    def request(self, operation, sequence=1, **extra):
        return {"version": 1, "sequence": sequence, "operation": operation,
                "locationRef": "alpha", **extra}

    def run_provider(self, *messages):
        payload = b"".join(message if isinstance(message, bytes) else
                           json.dumps(message).encode() + b"\n" for message in messages)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ENTRY)], input=payload,
            env={"PATH": os.defpath}, capture_output=True, timeout=10,
        )
        self.assertEqual(result.stderr, b"")
        self.assertEqual((self.root / "note.txt").read_text(), "unchanged\n")
        return result.returncode, [json.loads(line) for line in result.stdout.splitlines()]

    def test_observe_then_inspect_uses_the_owned_live_identity(self):
        code, replies = self.run_provider(self.initialize, self.request("observe"),
                                          self.request("inspect", 2))
        self.assertEqual(code, 0)
        self.assertEqual([reply["code"] for reply in replies],
                         ["ready", "observed", "available"])
        self.assertEqual(replies[1]["rootId"], replies[2]["rootId"])
        self.assertEqual(replies[1]["contentRevision"], replies[2]["contentRevision"])
        self.assertEqual(replies[1]["vcs"], {"kind": "none", "repositoryId": None,
                                             "checkoutId": None, "mutationOwner": None})

    def git(self, *args):
        result = subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
             "-C", str(self.root), *args],
            env={"PATH": os.defpath, "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
            capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_layouts_remain_available_after_registration(self):
        self.git("init", "--template=", "-b", "main")
        self.git("add", "note.txt")
        self.git("commit", "-m", "fixture")
        nested = self.root / "nested"
        nested.mkdir()
        linked = self.scope / "linked"
        self.git("worktree", "add", "-b", "linked", str(linked))
        for name, location in (("git", self.root), ("nested", nested), ("linked", linked)):
            with self.subTest(layout=name):
                self.initialize["config"]["locations"] = {"alpha": str(location)}
                self.initialize["config"]["statePath"] = str(self.private / (name + ".json"))
                code, replies = self.run_provider(self.initialize, self.request("observe"),
                                                  self.request("inspect", 2))
                self.assertEqual(code, 0)
                self.assertEqual([reply["code"] for reply in replies],
                                 ["ready", "observed", "available"])
                self.assertEqual(replies[1]["rootId"], replies[2]["rootId"])
                self.assertEqual(replies[1]["contentRevision"], replies[2]["contentRevision"])
                self.assertEqual(replies[1]["vcs"]["kind"], "git")

    def test_restart_keeps_records_without_reissuing_lost_custody(self):
        code, _ = self.run_provider(self.initialize, self.request("observe"))
        self.assertEqual(code, 0)
        saved = self.state.read_bytes()
        code, replies = self.run_provider(self.initialize, self.request("inspect"),
                                          self.request("observe", 2))
        self.assertEqual(code, 0)
        self.assertEqual([reply["code"] for reply in replies],
                         ["ready", "identity-unverified", "identity-unverified"])
        self.assertEqual(self.state.read_bytes(), saved)

    def test_request_cannot_supply_a_path_or_authority(self):
        for extra in ({"path": str(self.root)}, {"rootId": "caller-root"},
                      {"mutation_authorized": True}):
            with self.subTest(extra=extra):
                code, replies = self.run_provider(self.initialize,
                                                  self.request("observe", **extra))
                self.assertEqual(code, 1)
                self.assertEqual([reply["code"] for reply in replies], ["ready"])
                self.assertFalse(self.state.exists())

    def test_malformed_frames_fail_without_diagnostics_or_project_access(self):
        for raw in (b'{"version":1,"version":1}\n', b'{}', b'[]\n', b'\xff\n',
                    b'{"value":NaN}\n', b' ' * 16385 + b'\n'):
            with self.subTest(raw=raw[:40]):
                code, replies = self.run_provider(raw)
                self.assertEqual(code, 1)
                self.assertEqual(replies, [])
                self.assertFalse(self.state.exists())

    def test_sequence_and_operation_must_match_the_protocol(self):
        for request in (self.request("observe", 2), self.request("mutate"),
                        self.request("inspect", True)):
            with self.subTest(request=request):
                code, replies = self.run_provider(self.initialize, request)
                self.assertEqual(code, 1)
                self.assertEqual([reply["code"] for reply in replies], ["ready"])
                self.assertFalse(self.state.exists())
