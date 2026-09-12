"""Private Linux filesystem captures with descriptor-bounded identity continuity.

An observer holds every directory used for identity until it closes. Its IDs
are valid only within that observer lifetime. Revalidation rejects captures
from another instance. This module grants no mutation authority and provides
neither durable identity across restart nor a cross-process reservation fence.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

from vivary_core.workspace_observe import _default_run_git


OBSERVER_VERSION = "vivary.physical-observer/linux-held-fd-v1"
INVENTORY_POLICY = "all-files-no-follow-v1"
_LOCAL_FILESYSTEMS = {
    0xEF53: "ext-family",
    0x58465342: "xfs",
    0x9123683E: "btrfs",
    0x01021994: "tmpfs",
    0x794C7630: "overlayfs",
}
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


@dataclass(frozen=True)
class ObservationFailure:
    code: str
    reason: str


@dataclass(frozen=True)
class PhysicalCapture:
    """Private evidence. Derived keys are scoped to ``observer_lifetime``."""

    capture_id: str
    observer_lifetime: str
    observer_version: str
    device_id: str
    location_ref: str
    physical_path: str
    filesystem: str
    root_id: str
    repository_id: str | None
    checkout_id: str | None
    layout: str
    mutation_owner: str | None
    head_state: str
    dirty_state: str
    content_revision: str
    resource_keys: tuple[tuple[str, str, str], ...]
    inventory_policy: str
    entry_count: int
    captured_bytes: int
    mutation_authorized: bool = False


@dataclass(frozen=True)
class CaptureLimits:
    max_roots: int = 16
    max_entries: int = 10_000
    max_bytes: int = 64 * 1024 * 1024
    max_depth: int = 64
    max_handles: int = 256

    def __post_init__(self):
        for value in vars(self).values():
            if type(value) is not int or not 1 <= value <= 2**30:
                raise ValueError("capture limits must be bounded positive integers")


class _Refused(Exception):
    def __init__(self, reason: str, code: str = "identity-unverified"):
        self.failure = ObservationFailure(code, reason)


@dataclass
class _Handle:
    fd: int
    identity: tuple[int, int]
    filesystem: str


@dataclass(frozen=True)
class _Inventory:
    manifest: tuple[tuple, ...]
    stamps: tuple[tuple, ...]
    entries: int
    bytes: int


@dataclass
class _Observed:
    capture: PhysicalCapture
    root: Path
    checkout: Path | None
    common: Path | None
    private: Path | None
    inventories: tuple[tuple[Path, _Inventory], ...]
    handles: tuple[tuple[Path, _Handle], ...]


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stamp(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _filesystem(fd: int) -> str:
    """Read Linux fstatfs without assuming a portable struct layout."""
    buffer = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.fstatfs
    function.argtypes = [ctypes.c_int, ctypes.c_void_p]
    function.restype = ctypes.c_int
    if function(fd, buffer) != 0:
        raise _Refused("filesystem-unverified")
    magic = ctypes.c_long.from_buffer(buffer).value & 0xFFFFFFFF
    if magic not in _LOCAL_FILESYSTEMS:
        raise _Refused("filesystem-unsupported")
    return _LOCAL_FILESYSTEMS[magic]


def _location_map(locations: Mapping[str, str | Path], limits: CaptureLimits):
    if not isinstance(locations, Mapping) or not 0 < len(locations) <= limits.max_roots:
        raise ValueError("locations must be a bounded nonempty trusted mapping")
    if any(not isinstance(key, str) or not _ID.fullmatch(key) for key in locations):
        raise ValueError("location references must be ASCII identifiers")
    copied = {key: Path(value) for key, value in locations.items()}
    if any(not path.is_absolute() or ".." in path.parts for path in copied.values()):
        raise ValueError("locators must be absolute without parent traversal")
    return MappingProxyType(copied)


class PhysicalRootObserver:
    """Trusted local service API, never a caller-supplied observation decoder.

    ``scope`` authorizes reads of configured roots and their VCS metadata.
    Ancestor inspection reads marker existence only and refuses a repository
    outside that scope. ``locations`` must include all relevant writable roots
    from the connection owner. This class does not establish that authority.
    """

    def __init__(self, *, device_id: str, scope: str | Path,
                 locations: Mapping[str, str | Path],
                 limits: CaptureLimits = CaptureLimits()):
        if not isinstance(device_id, str) or not _ID.fullmatch(device_id):
            raise ValueError("device_id must be a bound ASCII identifier")
        self._scope = Path(scope)
        self._locations = _location_map(locations, limits)
        if not self.scope.is_absolute() or ".." in self.scope.parts:
            raise ValueError("scope must be absolute without parent traversal")
        self.device_id = device_id
        self.limits = limits
        self.lifetime = uuid4().hex
        self._handles: dict[tuple[int, int], _Handle] = {}
        self._captures: dict[str, PhysicalCapture] = {}
        self._scope_handle: _Handle | None = None
        self._closed = False
        self._poisoned = False
        self._lock = threading.RLock()

    @property
    def scope(self) -> Path:
        return self._scope

    @property
    def locations(self) -> Mapping[str, Path]:
        return self._locations

    def update_locations(self, locations: Mapping[str, str | Path]) -> None:
        """Replace trusted locator grants between captures without changing scope."""
        with self._lock:
            self._locations = _location_map(locations, self.limits)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._lock:
            if not self._closed:
                for handle in self._handles.values():
                    try:
                        os.close(handle.fd)
                    except OSError:
                        pass
                self._handles.clear()
                self._captures.clear()
                self._closed = True

    def _supported(self):
        if sys.platform != "linux":
            raise _Refused("platform-unsupported")
        if self._closed or self._poisoned:
            raise _Refused("observer-continuity-lost")
        for handle in self._handles.values():
            try:
                current = os.fstat(handle.fd)
            except OSError:
                self._poisoned = True
                raise _Refused("observer-continuity-lost") from None
            if (current.st_dev, current.st_ino) != handle.identity:
                self._poisoned = True
                raise _Refused("observer-continuity-lost")

    def _within(self, path: Path) -> bool:
        return path.is_relative_to(self.scope)

    def _resolve(self, path: Path) -> Path:
        if not self._within(path):
            raise _Refused("root-outside-scope", "denied")
        resolved = path.resolve(strict=True)
        if not self._within(resolved):
            raise _Refused("root-outside-scope", "denied")
        return resolved

    def _hold(self, path: Path) -> _Handle:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        if not self._within(path):
            raise _Refused("root-outside-scope", "denied")
        # Every component is opened relative to an already opened directory.
        # A concurrent intermediate symlink cannot redirect a metadata read.
        if self._scope_handle is None:
            fd = os.open("/", flags)
            parts = path.parts[1:]
        else:
            fd = os.dup(self._scope_handle.fd)
            parts = path.relative_to(self.scope).parts
        try:
            for part in parts:
                next_fd = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        except BaseException:
            os.close(fd)
            raise
        try:
            info = os.fstat(fd)
            key = (info.st_dev, info.st_ino)
            if info.st_nlink == 0:
                raise _Refused("root-incarnation-unverified")
            if key in self._handles:
                return self._handles[key]
            if len(self._handles) >= self.limits.max_handles:
                raise _Refused("identity-handle-limit")
            handle = _Handle(fd, key, _filesystem(fd))
            self._handles[key] = handle
            fd = -1
            return handle
        finally:
            if fd >= 0:
                os.close(fd)

    def _identifier(self, kind: str, *handles: _Handle) -> str:
        return kind + "_" + _digest([self.device_id, self.lifetime,
                                     [handle.identity for handle in handles]])

    def _check_handle(self, path: Path, handle: _Handle):
        info = os.stat(path, follow_symlinks=False)
        pinned = os.fstat(handle.fd)
        if (info.st_dev, info.st_ino) != handle.identity or pinned.st_nlink == 0:
            raise _Refused("unstable-capture")

    def _inventory(self, path: Path) -> _Inventory:
        handle = self._hold(path)
        rows: list[tuple] = []
        stamps: list[tuple] = []
        size = 0

        def visit(fd: int, relative: str, depth: int):
            nonlocal size
            if depth > self.limits.max_depth:
                raise _Refused("content-depth-limit")
            before = os.fstat(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            with os.scandir(fd) as entries:
                names = sorted(entry.name for entry in entries)
            for name in names:
                if len(rows) >= self.limits.max_entries:
                    raise _Refused("content-entry-limit")
                rel = relative + "/" + name if relative else name
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                stamps.append((rel, *_stamp(info)))
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=fd)
                    try:
                        if _stamp(os.fstat(child)) != _stamp(info):
                            raise _Refused("unstable-capture")
                        rows.append((rel, "directory", mode))
                        visit(child, rel, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    if info.st_size > self.limits.max_bytes - size:
                        raise _Refused("content-byte-limit")
                    child = self._open_regular(fd, name, info)
                    try:
                        if _stamp(os.fstat(child)) != _stamp(info):
                            raise _Refused("unstable-capture")
                        digest = hashlib.sha256()
                        count = 0
                        while block := os.read(child, min(65536, self.limits.max_bytes - size + 1)):
                            count += len(block)
                            size += len(block)
                            if size > self.limits.max_bytes:
                                raise _Refused("content-byte-limit")
                            digest.update(block)
                        if _stamp(os.fstat(child)) != _stamp(info) or count != info.st_size:
                            raise _Refused("unstable-capture")
                        rows.append((rel, "file", mode, count, digest.hexdigest()))
                    finally:
                        os.close(child)
                else:
                    raise _Refused("content-link-or-type-unsupported")
                if _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _stamp(info):
                    raise _Refused("unstable-capture")
            if _stamp(os.fstat(fd)) != _stamp(before):
                raise _Refused("unstable-capture")

        visit(handle.fd, "", 0)
        return _Inventory(tuple(rows), tuple(stamps), len(rows), size)

    @staticmethod
    def _open_regular(parent_fd: int, name: str, expected: os.stat_result) -> int:
        # O_PATH identifies the entry without opening a substituted device or
        # waiting on a substituted FIFO. Reopen that pinned regular file only.
        pin = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            info = os.fstat(pin)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _stamp(info) != _stamp(expected):
                raise _Refused("unstable-capture")
            return os.open(f"/proc/self/fd/{pin}", os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
        finally:
            os.close(pin)

    def _read_marker(self, path: Path) -> str:
        parent = self._hold(self._resolve(path.parent))
        info = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
        fd = self._open_regular(parent.fd, path.name, info)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4096 or before.st_nlink != 1:
                raise _Refused("vcs-identity-unverified")
            raw = os.read(fd, 4097)
            if len(raw) > 4096 or _stamp(os.fstat(fd)) != _stamp(before):
                raise _Refused("unstable-capture")
            text = raw.decode("utf-8", errors="strict").strip()
            if not text or "\n" in text or "\r" in text or "\x00" in text:
                raise _Refused("vcs-identity-unverified")
            return text
        except UnicodeError:
            raise _Refused("vcs-identity-unverified") from None
        finally:
            os.close(fd)

    def _topology(self, root: Path) -> tuple[Path | None, Path | None, Path | None]:
        for depth, ancestor in enumerate((root, *root.parents)):
            if depth > self.limits.max_depth:
                raise _Refused("topology-depth-limit")
            if os.path.lexists(ancestor / ".jj"):
                raise _Refused("jj-identity-unsupported")
            marker = ancestor / ".git"
            if os.path.lexists(marker):
                if not self._within(ancestor):
                    raise _Refused("vcs-outside-scope")
                info = marker.lstat()
                if stat.S_ISDIR(info.st_mode):
                    private = marker
                elif stat.S_ISREG(info.st_mode):
                    text = self._read_marker(marker)
                    if not text.startswith("gitdir: "):
                        raise _Refused("vcs-identity-unverified")
                    private = self._resolve(ancestor / text[8:])
                else:
                    raise _Refused("vcs-identity-unverified")
                private = self._resolve(private)
                common = private
                if os.path.lexists(private / "commondir"):
                    common = self._resolve(private / self._read_marker(private / "commondir"))
                    association = self._resolve(private / self._read_marker(private / "gitdir"))
                    if association != marker:
                        raise _Refused("vcs-root-association-unverified")
                return ancestor, common, private
            if (ancestor / "HEAD").is_file() and (ancestor / "objects").is_dir() and (ancestor / "refs").is_dir():
                raise _Refused("bare-repository-unsupported")
        return None, None, None

    def _git(self, root: Path, args: list[str]) -> str:
        # Only rev-parse, symbolic-ref, and ls-files callers occur below. None
        # reads worktree filters, fetches objects, refreshes the index, or runs hooks.
        result = _default_run_git(str(root), args, worktree_config={})
        if not result["ok"]:
            raise _Refused("vcs-probe-failed")
        return result["stdout"]

    def _reject_config_includes(self, paths: list[Path]):
        for path in paths:
            for name in ("config", "config.worktree"):
                config = path / name
                if not os.path.lexists(config):
                    continue
                handle = self._hold(path)
                info = os.stat(name, dir_fd=handle.fd, follow_symlinks=False)
                if info.st_size > 1024 * 1024:
                    raise _Refused("vcs-config-unverified")
                fd = self._open_regular(handle.fd, name, info)
                try:
                    raw = os.read(fd, 1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024 or _stamp(os.fstat(fd)) != _stamp(info):
                        raise _Refused("unstable-capture")
                    if re.search(rb"(?im)^\s*\[\s*include(?:if)?\b", raw):
                        raise _Refused("vcs-config-include-unsupported")
                finally:
                    os.close(fd)

    def _observe_one(self, location: str) -> _Observed:
        root = self._resolve(self.locations[location])
        root_handle = self._hold(root)
        checkout, common, private = self._topology(root)
        paths = [root]
        handles = [(root, root_handle)]
        for path in (checkout, common, private):
            if path is not None:
                held = self._hold(path)
                handles.append((path, held))
                if path not in paths:
                    paths.append(path)
        before = tuple((path, self._inventory(path)) for path in paths)
        # A project containing independent administration has no composite
        # reservation domain. Root metadata is checked separately above.
        for row in before[0][1].manifest:
            parts = Path(row[0]).parts
            if ".jj" in parts:
                raise _Refused("jj-identity-unsupported")
            if ".git" in parts and not (checkout == root and parts[0] == ".git"):
                raise _Refused("nested-repository", "ambiguous-ownership")
        repository_id = checkout_id = owner = None
        layout, head_state, dirty_state = "none", "not-applicable", "not-applicable"
        keys = ((self.device_id, "root", self._identifier("root", root_handle)),)
        if checkout is not None:
            self._reject_config_includes(list(dict.fromkeys((common, private))))
            expected = [str(checkout), str(private), str(common)]
            actual = [self._git(root, ["rev-parse", "--path-format=absolute", option]).strip()
                      for option in ("--show-toplevel", "--absolute-git-dir", "--git-common-dir")]
            if actual != expected:
                raise _Refused("vcs-root-association-unverified")
            head = self._git(root, ["rev-parse", "--verify", "HEAD"]).strip()
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
                raise _Refused("vcs-probe-failed")
            branch = _default_run_git(str(root), ["symbolic-ref", "--quiet", "--short", "HEAD"],
                                      worktree_config={})
            if branch["ok"]:
                head_state = "branch"
            elif branch.get("code") == 1:
                head_state = "detached"
            else:
                raise _Refused("vcs-probe-failed")
            tracked = self._git(root, ["ls-files", "--cached", "--full-name", "-z"])
            if tracked and not tracked.endswith("\x00"):
                raise _Refused("vcs-probe-failed")
            # A path absent from the index establishes untracked content. Git
            # may ignore it. Index/HEAD/worktree equivalence stays unverified.
            prefix = root.relative_to(checkout)
            names = {item for item in tracked.split("\x00") if item}
            content_names = {str(prefix / row[0]) for row in before[0][1].manifest
                             if row[1] == "file" and Path(row[0]).parts[0] != ".git"}
            dirty_state = "untracked-content" if content_names - names else "unverified"
            repository_id = self._identifier("repository", self._hold(common))
            checkout_id = self._identifier("checkout", self._hold(private), self._hold(checkout))
            owner = "git"
            layout = "git-linked-worktree" if common != private else "git"
            if root != checkout:
                layout = "git-nested-project"
            keys = tuple(sorted(((self.device_id, "repository", repository_id),
                                 (self.device_id, "checkout", checkout_id))))
        after = tuple((path, self._inventory(path)) for path in paths)
        if (before != after or self._resolve(self.locations[location]) != root
                or self._topology(root) != (checkout, common, private)):
            raise _Refused("unstable-capture")
        for path, handle in handles:
            self._check_handle(path, handle)
        revision = _digest([inventory.manifest for _, inventory in before])
        capture = PhysicalCapture(
            uuid4().hex, self.lifetime, OBSERVER_VERSION, self.device_id,
            location, str(root), root_handle.filesystem,
            self._identifier("root", root_handle), repository_id, checkout_id,
            layout, owner, head_state, dirty_state, revision, keys, INVENTORY_POLICY,
            sum(inventory.entries for _, inventory in before),
            sum(inventory.bytes for _, inventory in before),
        )
        return _Observed(capture, root, checkout, common, private, before, tuple(handles))

    @staticmethod
    def _failure(error: OSError) -> ObservationFailure:
        if isinstance(error, FileNotFoundError):
            return ObservationFailure("root-unavailable", "missing-root")
        if isinstance(error, NotADirectoryError):
            return ObservationFailure("not-directory", "non-directory-root")
        if isinstance(error, PermissionError):
            return ObservationFailure("denied", "root-inaccessible")
        return ObservationFailure("identity-unverified", "filesystem-probe-failed")

    def observe(self) -> dict[str, PhysicalCapture | ObservationFailure]:
        """Capture all configured roots and refuse uncertain overlap or races."""
        with self._lock:
            try:
                self._supported()
                if len(self._captures) + len(self.locations) > self.limits.max_entries:
                    raise _Refused("capture-history-limit")
                if self.scope.resolve(strict=True) != self.scope:
                    raise _Refused("scope-alias-unsupported")
                if self._scope_handle is None:
                    self._scope_handle = self._hold(self.scope)
                self._check_handle(self.scope, self._scope_handle)
            except _Refused as error:
                return {name: error.failure for name in self.locations}
            except OSError as error:
                return {name: self._failure(error) for name in self.locations}
            observed: dict[str, _Observed] = {}
            failures: dict[str, ObservationFailure] = {}
            for name in self.locations:
                try:
                    observed[name] = self._observe_one(name)
                except _Refused as error:
                    failures[name] = error.failure
                except OSError as error:
                    failures[name] = self._failure(error)
            if failures:
                failures.update({name: ObservationFailure("ambiguous-ownership", "overlap-unverified")
                                 for name in observed})
                return failures
            for name, left in observed.items():
                for other, right in observed.items():
                    if name >= other or left.capture.root_id == right.capture.root_id:
                        continue
                    if left.root.is_relative_to(right.root) or right.root.is_relative_to(left.root):
                        shared = (left.capture.repository_id is not None
                                  and left.capture.repository_id == right.capture.repository_id
                                  and left.capture.checkout_id == right.capture.checkout_id
                                  and left.capture.mutation_owner == right.capture.mutation_owner)
                        if not shared:
                            failure = ObservationFailure("ambiguous-ownership", "overlap-without-common-domain")
                            failures[name] = failures[other] = failure
            for name, item in observed.items():
                if name in failures:
                    continue
                try:
                    for path, old in item.inventories:
                        if self._inventory(path) != old:
                            raise _Refused("unstable-capture")
                    for path, handle in item.handles:
                        self._check_handle(path, handle)
                    if self._resolve(self.locations[name]) != item.root:
                        raise _Refused("unstable-capture")
                    if self._topology(item.root) != (item.checkout, item.common, item.private):
                        raise _Refused("unstable-capture")
                except _Refused as error:
                    failures[name] = error.failure
                except OSError:
                    failures[name] = ObservationFailure("identity-unverified", "unstable-capture")
            if failures:
                failures.update({name: ObservationFailure("ambiguous-ownership", "overlap-unverified")
                                 for name in observed if name not in failures})
                return failures
            result = {name: item.capture for name, item in observed.items()}
            self._captures.update({item.capture_id: item for item in result.values()})
            return result

    def revalidate(self, previous: PhysicalCapture) -> PhysicalCapture | ObservationFailure:
        """Recheck an issued capture without trusting a serialized ID or map."""
        with self._lock:
            if (not isinstance(previous, PhysicalCapture)
                    or previous.observer_lifetime != self.lifetime
                    or self._captures.get(previous.capture_id) is not previous):
                return ObservationFailure("identity-unverified", "capture-continuity-unverified")
            if previous.location_ref not in self.locations:
                return ObservationFailure("denied", "locator-grant-removed")
            current = self.observe()[previous.location_ref]
            if isinstance(current, ObservationFailure):
                return current
            if previous.root_id != current.root_id:
                return ObservationFailure("root-replaced", "root-incarnation-changed")
            if (previous.repository_id, previous.checkout_id, previous.mutation_owner) != (
                    current.repository_id, current.checkout_id, current.mutation_owner):
                return ObservationFailure("stale-binding", "vcs-incarnation-changed")
            if previous.content_revision != current.content_revision:
                return ObservationFailure("content-conflict", "content-revision-changed")
            return current
