"""Synthetic read-only filesystem proof for the Linux physical observer."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vivary_core.physical_observe import (
    CaptureLimits,
    ObservationFailure,
    PhysicalCapture,
    PhysicalRootObserver,
)


def tree_state(root: Path) -> tuple:
    """Product bytes/modes/write timestamps, including Git administration."""
    rows = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        payload = None
        if stat.S_ISREG(info.st_mode):
            payload = hashlib.sha256(path.read_bytes()).hexdigest()
        elif stat.S_ISLNK(info.st_mode):
            payload = os.readlink(path)
        rows.append((str(path.relative_to(root)), info.st_mode, info.st_size,
                     info.st_mtime_ns, info.st_ctime_ns, payload))
    return tuple(rows)


class BoundaryTests(unittest.TestCase):
    def test_rejects_unbound_or_caller_authority_fields(self):
        with self.assertRaises(ValueError):
            PhysicalRootObserver(device_id="", scope="/tmp", locations={"r": "/tmp/r"})
        with self.assertRaises(ValueError):
            PhysicalRootObserver(device_id="device", scope="relative", locations={"r": "/tmp/r"})
        with self.assertRaises(ValueError):
            CaptureLimits(max_bytes=True)
        with self.assertRaises(TypeError):
            PhysicalRootObserver(device_id="device", scope="/tmp", locations={"r": "/tmp/r"},
                                 root_id="caller-chosen")

    def test_windows_refuses_before_filesystem_or_git_probe(self):
        root = Path(__file__).resolve().parent
        with PhysicalRootObserver(device_id="device", scope=root, locations={"r": root}) as observer:
            with patch("vivary_core.physical_observe.sys.platform", "win32"), \
                    patch("vivary_core.physical_observe._default_run_git") as git:
                self.assertEqual(observer.observe()["r"],
                                 ObservationFailure("identity-unverified", "platform-unsupported"))
                git.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "Linux held-descriptor identity proof only")
class PhysicalObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vivary-12b-")
        self.scope = Path(self.temporary.name).resolve()
        self.root = self.scope / "root"
        self.root.mkdir()
        (self.root / "file.txt").write_text("baseline\n", encoding="utf-8")
        self.observers = []

    def tearDown(self):
        for observer in self.observers:
            observer.close()
        self.temporary.cleanup()

    def observer(self, locations=None, **kwargs):
        observer = PhysicalRootObserver(device_id="device-fixture", scope=self.scope,
                                        locations=locations or {"root": self.root}, **kwargs)
        self.observers.append(observer)
        return observer

    def capture(self, observer, location="root"):
        before = tree_state(self.scope)
        result = observer.observe()
        self.assertEqual(tree_state(self.scope), before, "read probe changed project or administration")
        self.assertIsInstance(result[location], PhysicalCapture, result)
        self.assertFalse(result[location].mutation_authorized)
        return result[location]

    def git(self, cwd, *args):
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
        result = subprocess.run(["git", "-C", str(cwd), *args], env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def repository(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        self.git(self.root, "init", "-b", "main")
        self.git(self.root, "config", "user.name", "Fixture")
        self.git(self.root, "config", "user.email", "fixture@example.invalid")
        self.git(self.root, "add", ".")
        self.git(self.root, "commit", "-m", "fixture")

    def test_no_vcs_alias_and_rename_keep_one_pinned_incarnation(self):
        alias = self.scope / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        observer = self.observer({"root": self.root, "alias": alias})
        root = self.capture(observer)
        other = self.capture(observer, "alias")
        self.assertEqual(root.root_id, other.root_id)
        self.assertEqual(root.resource_keys, other.resource_keys)
        self.assertEqual(root.layout, "none")
        self.assertIsNone(root.mutation_owner)
        moved = self.scope / "moved"
        self.root.rename(moved)
        alias.unlink()
        alias.symlink_to(moved, target_is_directory=True)
        observer.update_locations({"root": moved, "alias": alias})
        renamed = self.capture(observer)
        self.assertEqual(root.root_id, renamed.root_id)
        self.assertEqual(root.content_revision, renamed.content_revision)
        self.assertIsInstance(observer.revalidate(root), PhysicalCapture)

    def test_recreation_cannot_reuse_the_held_inode(self):
        observer = self.observer()
        previous = self.capture(observer)
        (self.root / "file.txt").unlink()
        self.root.rmdir()
        self.root.mkdir()
        (self.root / "file.txt").write_text("baseline\n", encoding="utf-8")
        current = self.capture(observer)
        self.assertNotEqual(previous.root_id, current.root_id)
        self.assertEqual(previous.content_revision, current.content_revision)
        self.assertEqual(observer.revalidate(previous).code, "root-replaced")

    def test_restart_refuses_old_capture_instead_of_inventing_continuity(self):
        observer = self.observer()
        previous = self.capture(observer)
        observer.close()
        restarted = self.observer()
        self.assertEqual(restarted.revalidate(previous),
                         ObservationFailure("identity-unverified", "capture-continuity-unverified"))
        current = self.capture(restarted)
        self.assertNotEqual(current.observer_lifetime, previous.observer_lifetime)
        self.assertNotEqual(current.root_id, previous.root_id)

    def test_lost_descriptor_refuses_possible_inode_reuse(self):
        observer = self.observer()
        self.capture(observer)
        handle = next(iter(observer._handles.values()))
        os.close(handle.fd)
        self.assertEqual(observer.observe()["root"],
                         ObservationFailure("identity-unverified", "observer-continuity-lost"))

    def test_serialized_or_modified_capture_is_not_authority(self):
        observer = self.observer()
        original = self.capture(observer)
        self.assertEqual(observer.revalidate(replace(original, root_id="forged")).code,
                         "identity-unverified")
        self.assertEqual(observer.revalidate(vars(original)).code, "identity-unverified")

    def test_capture_history_limit_preserves_prior_evidence(self):
        observer = self.observer(limits=CaptureLimits(max_entries=2))
        previous = self.capture(observer)
        self.capture(observer)
        self.assertEqual(observer.observe()["root"],
                         ObservationFailure("identity-unverified", "capture-history-limit"))
        self.assertIs(observer._captures[previous.capture_id], previous)
        self.assertEqual(observer.revalidate(previous).reason, "capture-history-limit")

    def test_location_updates_remain_bounded_and_scope_is_fixed(self):
        observer = self.observer(limits=CaptureLimits(max_roots=1))
        with self.assertRaises(ValueError):
            observer.update_locations({"root": self.root, "extra": self.root})
        self.assertEqual(dict(observer.locations), {"root": self.root})
        with self.assertRaises(TypeError):
            observer.locations["extra"] = self.root
        with self.assertRaises(AttributeError):
            observer.scope = self.scope.parent
        previous = self.capture(observer)
        observer.update_locations({"replacement": self.root})
        self.assertEqual(observer.revalidate(previous),
                         ObservationFailure("denied", "locator-grant-removed"))

    def test_missing_file_and_outside_alias_have_distinct_refusals(self):
        missing = self.observer({"r": self.scope / "missing"})
        self.assertEqual(missing.observe()["r"].reason, "missing-root")
        file = self.observer({"r": self.root / "file.txt"})
        self.assertEqual(file.observe()["r"].code, "not-directory")
        alias = self.scope / "outside"
        alias.symlink_to(self.scope.parent, target_is_directory=True)
        escaped = self.observer({"r": alias})
        self.assertEqual(escaped.observe()["r"], ObservationFailure("denied", "root-outside-scope"))

    def test_inventory_includes_untracked_ignored_and_mode_changes(self):
        self.repository()
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        observer = self.observer()
        first = self.capture(observer)
        self.assertEqual(first.dirty_state, "untracked-content")
        for name in ("file.txt", "untracked.txt", "ignored.txt"):
            with self.subTest(name=name):
                (self.root / name).write_text("changed\n", encoding="utf-8")
                changed = self.capture(observer)
                self.assertNotEqual(first.content_revision, changed.content_revision)
                self.assertEqual(observer.revalidate(first).code, "content-conflict")
                first = changed
        (self.root / "file.txt").chmod(0o755)
        self.assertNotEqual(first.content_revision, self.capture(observer).content_revision)

    def test_git_probe_preserves_index_hooks_filters_and_all_administration(self):
        self.repository()
        marker = self.scope / "executed"
        command = f"touch {marker}"
        self.git(self.root, "config", "core.fsmonitor", command)
        self.git(self.root, "config", "filter.fixture.clean", command)
        self.git(self.root, "config", "filter.fixture.process", command)
        (self.root / ".gitattributes").write_text("*.txt filter=fixture\n", encoding="utf-8")
        (self.root / "file.txt").write_text("changed\n", encoding="utf-8")
        observer = self.observer()
        capture = self.capture(observer)
        self.assertEqual(capture.mutation_owner, "git")
        self.assertFalse(marker.exists())
        self.assertEqual(capture.head_state, "branch")

    def test_config_include_refuses_before_native_probe(self):
        self.repository()
        config = self.root / ".git" / "config"
        with config.open("a", encoding="utf-8") as stream:
            stream.write('\n[include]\n\tpath = /outside/unauthorized\n')
        observer = self.observer()
        before = tree_state(self.scope)
        with patch("vivary_core.physical_observe._default_run_git") as git:
            self.assertEqual(observer.observe()["root"].reason, "vcs-config-include-unsupported")
            git.assert_not_called()
        self.assertEqual(before, tree_state(self.scope))

    def test_linked_worktree_shares_repository_but_not_checkout_key(self):
        self.repository()
        linked = self.scope / "linked"
        self.git(self.root, "worktree", "add", "-b", "linked", str(linked))
        observer = self.observer({"root": self.root, "linked": linked})
        primary = self.capture(observer)
        other = self.capture(observer, "linked")
        self.assertEqual(primary.repository_id, other.repository_id)
        self.assertNotEqual(primary.checkout_id, other.checkout_id)
        self.assertNotEqual(primary.root_id, other.root_id)
        self.assertEqual({key for key in primary.resource_keys if key[1] == "repository"},
                         {key for key in other.resource_keys if key[1] == "repository"})
        self.assertEqual(other.layout, "git-linked-worktree")

    def test_private_administration_replacement_changes_checkout_only(self):
        self.repository()
        linked = self.scope / "linked"
        self.git(self.root, "worktree", "add", "-b", "linked", str(linked))
        observer = self.observer({"linked": linked})
        previous = self.capture(observer, "linked")
        private = Path(self.git(linked, "rev-parse", "--absolute-git-dir"))
        old = self.scope / "old-private-administration"
        private.rename(old)
        shutil.copytree(old, private)
        current = self.capture(observer, "linked")
        self.assertEqual(previous.root_id, current.root_id)
        self.assertEqual(previous.repository_id, current.repository_id)
        self.assertNotEqual(previous.checkout_id, current.checkout_id)
        self.assertEqual(observer.revalidate(previous).code, "stale-binding")

    def test_common_administration_replacement_changes_repository(self):
        self.repository()
        observer = self.observer()
        previous = self.capture(observer)
        old = self.scope / "old-administration"
        (self.root / ".git").rename(old)
        shutil.copytree(old, self.root / ".git")
        current = self.capture(observer)
        self.assertEqual(previous.root_id, current.root_id)
        self.assertNotEqual(previous.repository_id, current.repository_id)
        self.assertEqual(observer.revalidate(previous).code, "stale-binding")

    def test_monorepo_siblings_and_parent_share_one_domain(self):
        self.repository()
        left, right = self.root / "left", self.root / "right"
        left.mkdir()
        right.mkdir()
        observer = self.observer({"root": self.root, "left": left, "right": right})
        parent = self.capture(observer)
        for name in ("left", "right"):
            child = self.capture(observer, name)
            self.assertNotEqual(parent.root_id, child.root_id)
            self.assertEqual(parent.resource_keys, child.resource_keys)

    def test_nested_no_vcs_roots_and_independent_repository_refuse_overlap(self):
        child = self.root / "child"
        child.mkdir()
        observer = self.observer({"root": self.root, "child": child})
        self.assertTrue(all(value.code == "ambiguous-ownership" for value in observer.observe().values()))
        self.git(child, "init", "-b", "child")
        self.assertEqual(observer.observe()["root"].code, "ambiguous-ownership")

    def test_jj_colocation_never_selects_git_or_runs_jj(self):
        self.repository()
        (self.root / ".jj").mkdir()
        observer = self.observer()
        before = tree_state(self.scope)
        with patch("vivary_core.physical_observe._default_run_git") as git:
            self.assertEqual(observer.observe()["root"].reason, "jj-identity-unsupported")
            git.assert_not_called()
        self.assertEqual(before, tree_state(self.scope))

    def test_capture_race_preserves_failure_and_never_accepts_new_bytes(self):
        self.repository()
        observer = self.observer()
        original_git = observer._git
        changed = False

        def racing_git(root, args):
            nonlocal changed
            output = original_git(root, args)
            if not changed:
                (self.root / "file.txt").write_text("concurrent edit\n", encoding="utf-8")
                changed = True
            return output

        with patch.object(observer, "_git", side_effect=racing_git):
            self.assertEqual(observer.observe()["root"],
                             ObservationFailure("identity-unverified", "unstable-capture"))
        self.assertEqual((self.root / "file.txt").read_text(), "concurrent edit\n")

    def test_new_ancestor_marker_during_capture_refuses(self):
        child = self.root / "child"
        child.mkdir()
        observer = self.observer({"root": child})
        inventory = observer._inventory
        count = 0

        def racing_inventory(path):
            nonlocal count
            result = inventory(path)
            count += 1
            if count == 1:
                (self.root / ".git").write_text("broken", encoding="utf-8")
            return result

        with patch.object(observer, "_inventory", side_effect=racing_inventory):
            self.assertIsInstance(observer.observe()["root"], ObservationFailure)

    def test_content_symlink_hardlink_fifo_and_limits_refuse(self):
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                entry = self.root / "special"
                if kind == "symlink":
                    entry.symlink_to("file.txt")
                elif kind == "hardlink":
                    os.link(self.root / "file.txt", entry)
                else:
                    os.mkfifo(entry)
                observer = self.observer()
                self.assertEqual(observer.observe()["root"].reason, "content-link-or-type-unsupported")
                entry.unlink()
        limited = self.observer(limits=CaptureLimits(max_bytes=1))
        self.assertEqual(limited.observe()["root"].reason, "content-byte-limit")

    def test_detached_head_does_not_change_physical_identity(self):
        self.repository()
        observer = self.observer()
        previous = self.capture(observer)
        self.git(self.root, "checkout", "--detach", "HEAD")
        current = self.capture(observer)
        self.assertEqual(previous.root_id, current.root_id)
        self.assertEqual(previous.repository_id, current.repository_id)
        self.assertEqual(previous.checkout_id, current.checkout_id)
        self.assertEqual(current.head_state, "detached")


if __name__ == "__main__":
    unittest.main()
