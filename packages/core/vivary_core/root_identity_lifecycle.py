"""Durable application root and VCS records with live-only verification.

This trusted local owner writes only its private metadata directory. It composes
the existing physical observer, never serializes physical identity, and grants
no project or repository mutation. Restarted, migrated, and imported records
remain inert until a separate authorized reconciliation procedure exists.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
from typing import Callable, Mapping
from uuid import uuid4

from vivary_core.physical_observe import (
    CaptureLimits, ObservationFailure, PhysicalCapture, PhysicalRootObserver,
)


_SCHEMA_V1 = "vivary.application-root-records/v1"
_SCHEMA = "vivary.application-root-records/v2"
_PERSISTED_VERIFICATION = "unavailable-without-live-custody"
_MAX_STATE_BYTES = 65536
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_ROOT_ID = re.compile(r"root_[0-9a-f]{32}\Z")
_REPOSITORY_ID = re.compile(r"repo_[0-9a-f]{32}\Z")
_CHECKOUT_ID = re.compile(r"checkout_[0-9a-f]{32}\Z")


class IdentityStateError(Exception):
    """A private lifecycle store cannot be opened safely."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LiveRootIdentity:
    """Current trusted result, never portable or sufficient for an effect.

    The UUIDs identify application records. ``mutation_owner`` describes the
    observed VCS kind. It selects no lock and grants no mutation capability.
    Consumers must inspect again at their current authorization boundary.
    """

    root_id: str
    location_ref: str
    content_revision: str
    layout: str
    verification: str = "verified-current-custody"
    mutation_authorized: bool = False
    repository_id: str | None = None
    checkout_id: str | None = None
    mutation_owner: str | None = None

    def __reduce_ex__(self, protocol):
        raise TypeError("live root verification cannot be serialized as authority")


@dataclass(frozen=True)
class RootAvailability:
    """Current read result. A missing application ID means never enrolled here."""

    location_ref: str
    content_revision: str
    layout: str
    root_id: str | None = None
    mutation_authorized: bool = False
    repository_id: str | None = None
    checkout_id: str | None = None
    mutation_owner: str | None = None

    def __reduce_ex__(self, protocol):
        raise TypeError("root availability cannot be serialized as authority")


@dataclass(frozen=True)
class _VcsReference:
    kind: str
    repository_id: str | None
    checkout_id: str | None

    def persisted(self) -> dict:
        return {
            "kind": self.kind,
            "repository_id": self.repository_id,
            "checkout_id": self.checkout_id,
        }


@dataclass(frozen=True)
class _ApplicationRoot:
    root_id: str
    location_refs: tuple[str, ...]
    vcs: _VcsReference

    def persisted(self) -> dict:
        return {
            "root_id": self.root_id,
            "location_refs": sorted(self.location_refs),
            "vcs": self.vcs.persisted(),
        }


@dataclass(frozen=True)
class _PhysicalCustody:
    observer_lifetime: str
    root_id: str
    repository_id: str | None
    checkout_id: str | None
    mutation_owner: str | None

    @classmethod
    def from_capture(cls, capture: PhysicalCapture) -> _PhysicalCustody:
        return cls(
            capture.observer_lifetime,
            capture.root_id,
            capture.repository_id,
            capture.checkout_id,
            capture.mutation_owner,
        )


_UNRESOLVED_VCS = _VcsReference("unresolved", None, None)
_NO_VCS = _VcsReference("none", None, None)


def linux_mount_epoch() -> str | None:
    """Fingerprint the observed boot, mount namespace and mount configuration.

    This is a change detector, not a never-reused physical identity. A platform
    that can restore storage without changing these observations must also
    invalidate its lifecycle owner. Nothing here grants remount/restore powers.
    """
    if sys.platform != "linux":
        return None
    try:
        pieces = [os.readlink("/proc/self/ns/mnt").encode()]
        for name, limit in [("/proc/sys/kernel/random/boot_id", 128),
                            ("/proc/self/mountinfo", 1024 * 1024)]:
            with open(name, "rb") as stream:
                data = stream.read(limit + 1)
            if not data or len(data) > limit:
                return None
            pieces.append(data)
        return hashlib.sha256(b"\0".join(pieces)).hexdigest()
    except OSError:
        return None


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate record key")
        result[key] = value
    return result


class RootIdentityLifecycle:
    """One exclusive local writer with a bounded complete locator inventory.

    Trusted application composition supplies device, scope, locators and the
    private state path. These are not per-request authority fields. Persisted
    records always declare verification unavailable without live custody.
    """

    def __init__(self, *, device_id: str, scope: Path,
                 locations: Mapping[str, Path], state_path: Path,
                 epoch_reader: Callable[[], str | None] = linux_mount_epoch,
                 limits: CaptureLimits = CaptureLimits()):
        self._lock = threading.RLock()
        self._directory_fd = self._writer_fd = self._state_fd = None
        self._state_stamp = self._state_raw = None
        self._invalid_reason = None
        self._closed = False
        self._records: dict[str, _ApplicationRoot] = {}
        self._custody: dict[str, _PhysicalCustody] = {}
        self._schema: str | None = None
        self._revision = 0
        self._pending_cleanup: list[str] = []
        self._observer = PhysicalRootObserver(device_id=device_id, scope=scope,
                                               locations=locations, limits=limits)
        self._limits = limits
        self._epoch_reader = epoch_reader
        self._device_id = device_id
        self._path = Path(state_path)
        try:
            if sys.platform != "linux":
                raise IdentityStateError("identity-platform-unsupported")
            if not callable(epoch_reader):
                raise IdentityStateError("identity-epoch-unavailable")
            self._epoch = self._read_epoch()
            if self._epoch is None:
                raise IdentityStateError("identity-epoch-unavailable")
            if (not self._path.is_absolute() or ".." in self._path.parts
                    or self._path.parent.resolve(strict=True) != self._path.parent
                    or self._path.parent.is_relative_to(self._observer.scope.resolve(strict=True))):
                raise IdentityStateError("identity-state-scope-invalid")
            self._directory_fd = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._directory_identity = _stamp(os.fstat(self._directory_fd))[:2]
            self._writer_name = self._path.name + ".lock"
            self._writer_fd = os.open(self._writer_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                      0o600, dir_fd=self._directory_fd)
            info = os.fstat(self._writer_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IdentityStateError("identity-lock-invalid")
            self._writer_identity = _stamp(info)[:2]
            import fcntl
            try:
                fcntl.flock(self._writer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise IdentityStateError("identity-owner-already-active") from error
            try:
                self._state_fd, self._state_raw, self._state_stamp = self._read_state()
            except FileNotFoundError:
                pass
            if self._state_raw is not None:
                self._records, self._revision, self._schema = self._decode_state(
                    self._state_raw,
                )
        except IdentityStateError:
            self.close()
            raise
        except (OSError, ValueError, TypeError, RecursionError) as error:
            self.close()
            raise IdentityStateError("identity-record-invalid") from error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def pending_cleanup(self) -> tuple[str, ...]:
        """Private metadata names retained after a failed cleanup attempt."""
        with self._lock:
            return tuple(self._pending_cleanup)

    def close(self):
        with self._lock:
            self._closed = True
            self._custody.clear()
            self._observer.close()
            for field in ("_state_fd", "_writer_fd", "_directory_fd"):
                fd = getattr(self, field)
                if fd is not None:
                    os.close(fd)
                    setattr(self, field, None)

    def _read_epoch(self):
        try:
            value = self._epoch_reader()
            return value if isinstance(value, str) and 1 <= len(value) <= 256 else None
        except Exception:
            return None

    def _read_state(self):
        fd = os.open(self._path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=self._directory_fd)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size > _MAX_STATE_BYTES):
                raise IdentityStateError("identity-record-invalid")
            raw = os.read(fd, _MAX_STATE_BYTES + 1)
            if len(raw) != before.st_size or _stamp(before) != _stamp(os.fstat(fd)):
                raise IdentityStateError("identity-record-invalid")
            return fd, raw, _stamp(before)
        except BaseException:
            os.close(fd)
            raise

    @staticmethod
    def _decode_vcs(value) -> _VcsReference:
        if type(value) is not dict or set(value) != {
                "kind", "repository_id", "checkout_id"}:
            raise IdentityStateError("identity-record-invalid")
        kind = value["kind"]
        repository_id = value["repository_id"]
        checkout_id = value["checkout_id"]
        if kind in {"none", "unresolved"}:
            if repository_id is not None or checkout_id is not None:
                raise IdentityStateError("identity-record-invalid")
        elif kind == "git":
            if (type(repository_id) is not str
                    or not _REPOSITORY_ID.fullmatch(repository_id)
                    or type(checkout_id) is not str
                    or not _CHECKOUT_ID.fullmatch(checkout_id)):
                raise IdentityStateError("identity-record-invalid")
        else:
            raise IdentityStateError("identity-record-invalid")
        return _VcsReference(kind, repository_id, checkout_id)

    def _decode_state(self, raw):
        state = json.loads(raw.decode("utf8"), object_pairs_hook=_strict_pairs)
        if (type(state) is not dict
                or set(state) != {"schema", "device_id", "revision", "verification", "records"}
                or state.get("schema") not in {_SCHEMA_V1, _SCHEMA}
                or state["device_id"] != self._device_id
                or state["verification"] != _PERSISTED_VERIFICATION
                or type(state["revision"]) is not int
                or not 1 <= state["revision"] <= 2**53 - 1
                or type(state["records"]) is not list
                or not 1 <= len(state["records"]) <= self._limits.max_roots):
            raise IdentityStateError("identity-record-invalid")
        schema = state["schema"]
        records: dict[str, _ApplicationRoot] = {}
        locators = set()
        checkout_repositories: dict[str, str] = {}
        for value in state["records"]:
            fields = {"root_id", "location_refs"}
            if schema == _SCHEMA:
                fields.add("vcs")
            if (type(value) is not dict or set(value) != fields
                    or type(value["root_id"]) is not str
                    or not _ROOT_ID.fullmatch(value["root_id"])
                    or value["root_id"] in records
                    or type(value["location_refs"]) is not list
                    or not 1 <= len(value["location_refs"]) <= self._limits.max_roots
                    or any(type(ref) is not str or not _ID.fullmatch(ref)
                           for ref in value["location_refs"])
                    or len(set(value["location_refs"])) != len(value["location_refs"])
                    or locators.intersection(value["location_refs"])):
                raise IdentityStateError("identity-record-invalid")
            vcs = (_UNRESOLVED_VCS if schema == _SCHEMA_V1
                   else self._decode_vcs(value["vcs"]))
            if vcs.kind == "git":
                prior = checkout_repositories.setdefault(
                    vcs.checkout_id, vcs.repository_id,
                )
                if prior != vcs.repository_id:
                    raise IdentityStateError("identity-record-invalid")
            record = _ApplicationRoot(
                value["root_id"], tuple(sorted(value["location_refs"])), vcs,
            )
            records[record.root_id] = record
            locators.update(record.location_refs)
        return records, state["revision"], schema

    def _invalidate(self, reason):
        if self._invalid_reason is None:
            self._invalid_reason = reason
        self._custody.clear()
        self._observer.close()
        return ObservationFailure("identity-unverified", self._invalid_reason)

    def _before(self):
        if self._closed:
            return ObservationFailure("identity-unverified", "identity-owner-closed")
        if self._invalid_reason:
            return ObservationFailure("identity-unverified", self._invalid_reason)
        epoch = self._read_epoch()
        if epoch is None:
            return self._invalidate("identity-epoch-unavailable")
        if epoch != self._epoch:
            return self._invalidate("identity-epoch-changed")
        try:
            directory = os.stat(self._path.parent, follow_symlinks=False)
            writer = os.stat(self._writer_name, dir_fd=self._directory_fd, follow_symlinks=False)
            if (_stamp(directory)[:2] != self._directory_identity
                    or _stamp(writer)[:2] != self._writer_identity or writer.st_nlink != 1):
                return self._invalidate("identity-state-changed")
            try:
                fd, raw, stamp = self._read_state()
            except FileNotFoundError:
                if self._state_fd is None:
                    return None
                return self._invalidate("identity-state-changed")
            try:
                if self._state_fd is None or raw != self._state_raw or stamp != self._state_stamp:
                    return self._invalidate("identity-state-changed")
            finally:
                os.close(fd)
        except (OSError, IdentityStateError):
            return self._invalidate("identity-state-changed")
        return None

    def _save(self, records):
        failure = self._before()
        if failure is not None:
            return failure
        if (self._revision == 2**53 - 1 or not records
                or len(records) > self._limits.max_roots
                or any(len(record.location_refs) > self._limits.max_roots
                       for record in records.values())):
            return ObservationFailure("identity-unverified", "identity-record-limit")
        state = {"schema": _SCHEMA, "device_id": self._device_id, "revision": self._revision + 1,
                 "verification": _PERSISTED_VERIFICATION,
                 "records": [records[root_id].persisted() for root_id in sorted(records)]}
        raw = (json.dumps(state, indent=2) + "\n").encode("utf8")
        if len(raw) > _MAX_STATE_BYTES:
            return ObservationFailure("identity-unverified", "identity-record-limit")
        try:
            decoded, revision, schema = self._decode_state(raw)
            if decoded != records or revision != state["revision"] or schema != _SCHEMA:
                return self._invalidate("identity-record-conflict")
        except (IdentityStateError, ValueError, TypeError, RecursionError, UnicodeError):
            return self._invalidate("identity-record-conflict")
        temporary = self._path.name + "." + uuid4().hex + ".tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self._directory_fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Reject cooperative changes observed during the temporary write.
            # This is not an atomic CAS against an adversarial same-user writer.
            failure = self._before()
            if failure is not None:
                return failure
            os.replace(temporary, self._path.name, src_dir_fd=self._directory_fd,
                       dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            fd, observed, stamp = self._read_state()
            if observed != raw:
                os.close(fd)
                return self._invalidate("identity-state-changed")
            if self._state_fd is not None:
                os.close(self._state_fd)
            self._state_fd, self._state_raw, self._state_stamp = fd, raw, stamp
            self._records, self._revision, self._schema = records, state["revision"], _SCHEMA
        except (OSError, IdentityStateError):
            return self._invalidate("identity-record-write-failed")
        finally:
            try:
                os.unlink(temporary, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                self._pending_cleanup.append(temporary)
        return self._before()

    def _capture(self, location_ref):
        if type(location_ref) is not str or not _ID.fullmatch(location_ref):
            return ObservationFailure("invalid-input", "identity-location-invalid")
        if location_ref not in self._observer.locations:
            return ObservationFailure("denied", "identity-locator-grant-missing")
        capture = self._observer.observe()[location_ref]
        if isinstance(capture, ObservationFailure):
            return self._invalidate("identity-observation-unverified")
        failure = self._before()
        return failure if failure is not None else capture

    @staticmethod
    def _custody_change(expected: _PhysicalCustody,
                        current: _PhysicalCustody) -> str | None:
        if expected.observer_lifetime != current.observer_lifetime:
            return "observer-continuity-changed"
        if expected.root_id != current.root_id:
            return "root-incarnation-changed"
        if (expected.repository_id, expected.checkout_id, expected.mutation_owner) != (
                current.repository_id, current.checkout_id, current.mutation_owner):
            return "vcs-incarnation-changed"
        return None

    @staticmethod
    def _custody_kind(custody: _PhysicalCustody) -> str | None:
        if (custody.repository_id is None and custody.checkout_id is None
                and custody.mutation_owner is None):
            return "none"
        if (type(custody.repository_id) is str
                and type(custody.checkout_id) is str
                and custody.mutation_owner == "git"):
            return "git"
        return None

    def _live_graph_failure(self):
        physical_repositories = {}
        physical_checkouts = {}
        application_repositories = {}
        application_checkouts = {}
        for root_id, custody in self._custody.items():
            record = self._records.get(root_id)
            if record is None or custody.observer_lifetime != self._observer.lifetime:
                return self._invalidate("identity-live-mapping-conflict")
            kind = self._custody_kind(custody)
            if kind is None or record.vcs.kind != kind:
                return self._invalidate("identity-live-mapping-conflict")
            if kind == "none":
                continue
            application_pair = (record.vcs.repository_id, record.vcs.checkout_id)
            prior = physical_repositories.setdefault(
                custody.repository_id, record.vcs.repository_id,
            )
            if prior != record.vcs.repository_id:
                return self._invalidate("identity-live-mapping-conflict")
            prior = physical_checkouts.setdefault(
                custody.checkout_id, application_pair,
            )
            if prior != application_pair:
                return self._invalidate("identity-live-mapping-conflict")
            prior = application_repositories.setdefault(
                record.vcs.repository_id, custody.repository_id,
            )
            if prior != custody.repository_id:
                return self._invalidate("identity-live-mapping-conflict")
            physical_pair = (custody.repository_id, custody.checkout_id)
            prior = application_checkouts.setdefault(
                record.vcs.checkout_id, physical_pair,
            )
            if prior != physical_pair:
                return self._invalidate("identity-live-mapping-conflict")
        return None

    def _allocate_application_id(self, prefix: str, existing: set[str]):
        value = prefix + "_" + uuid4().hex
        if value in existing:
            return self._invalidate("identity-allocation-conflict")
        return value

    def _application_vcs(self, custody: _PhysicalCustody):
        kind = self._custody_kind(custody)
        if kind is None:
            return self._invalidate("identity-vcs-custody-invalid")
        if kind == "none":
            return _NO_VCS
        repository_id = checkout_id = None
        for root_id, other in self._custody.items():
            record = self._records[root_id]
            if other.repository_id == custody.repository_id:
                if repository_id not in {None, record.vcs.repository_id}:
                    return self._invalidate("identity-live-mapping-conflict")
                repository_id = record.vcs.repository_id
            if other.checkout_id == custody.checkout_id:
                if other.repository_id != custody.repository_id:
                    return self._invalidate("identity-live-mapping-conflict")
                if checkout_id not in {None, record.vcs.checkout_id}:
                    return self._invalidate("identity-live-mapping-conflict")
                checkout_id = record.vcs.checkout_id
                if repository_id not in {None, record.vcs.repository_id}:
                    return self._invalidate("identity-live-mapping-conflict")
                repository_id = record.vcs.repository_id
        repository_ids = {
            record.vcs.repository_id for record in self._records.values()
            if record.vcs.repository_id is not None
        }
        checkout_ids = {
            record.vcs.checkout_id for record in self._records.values()
            if record.vcs.checkout_id is not None
        }
        if repository_id is None:
            repository_id = self._allocate_application_id("repo", repository_ids)
            if isinstance(repository_id, ObservationFailure):
                return repository_id
        if checkout_id is None:
            checkout_id = self._allocate_application_id("checkout", checkout_ids)
            if isinstance(checkout_id, ObservationFailure):
                return checkout_id
        return _VcsReference("git", repository_id, checkout_id)

    @staticmethod
    def _result_fields(record: _ApplicationRoot, custody: _PhysicalCustody):
        if record.vcs.kind == "none":
            return None, None, None
        return record.vcs.repository_id, record.vcs.checkout_id, custody.mutation_owner

    def update_locations(self, locations: Mapping[str, Path]):
        """Update the trusted locator inventory; never adopt a serialized ID."""
        with self._lock:
            failure = self._before()
            if failure is not None:
                return failure
            self._observer.update_locations(locations)
            return None

    def migrate_legacy_records(self):
        """Explicitly convert valid v1 records to inert unresolved v2 records."""
        with self._lock:
            failure = self._before()
            if failure is not None:
                return failure
            if self._schema is None:
                return {"status": "nothing-to-migrate", "schema": None, "revision": 0}
            if self._schema == _SCHEMA:
                return {
                    "status": "already-current",
                    "schema": _SCHEMA,
                    "revision": self._revision,
                }
            if self._schema != _SCHEMA_V1:
                return self._invalidate("identity-record-invalid")
            failure = self._save(dict(self._records))
            if failure is not None:
                return failure
            return {"status": "migrated", "schema": _SCHEMA, "revision": self._revision}

    def enroll(self, location_ref: str) -> LiveRootIdentity | ObservationFailure:
        """Create or extend an application record under current physical custody."""
        with self._lock:
            failure = self._before()
            if failure is not None:
                return failure
            if set(self._records) != set(self._custody):
                return ObservationFailure("identity-unverified", "identity-reconciliation-required")
            failure = self._live_graph_failure()
            if failure is not None:
                return failure
            capture = self._capture(location_ref)
            if isinstance(capture, ObservationFailure):
                return capture
            current = _PhysicalCustody.from_capture(capture)
            known = next((key for key, record in self._records.items()
                          if location_ref in record.location_refs), None)
            root_id = known
            if root_id is None:
                aliases = [key for key, custody in self._custody.items()
                           if custody.root_id == current.root_id]
                if len(aliases) > 1:
                    return self._invalidate("identity-live-mapping-conflict")
                root_id = aliases[0] if aliases else None
            if root_id is not None:
                change = self._custody_change(self._custody[root_id], current)
                if change is not None:
                    return self._invalidate(change)
                record = self._records[root_id]
            else:
                root_id = self._allocate_application_id("root", set(self._records))
                if isinstance(root_id, ObservationFailure):
                    return root_id
                vcs = self._application_vcs(current)
                if isinstance(vcs, ObservationFailure):
                    return vcs
                record = _ApplicationRoot(root_id, (), vcs)
            if location_ref not in record.location_refs:
                updated = _ApplicationRoot(
                    record.root_id,
                    tuple(sorted((*record.location_refs, location_ref))),
                    record.vcs,
                )
                records = dict(self._records)
                records[root_id] = updated
                failure = self._save(records)
                if failure is not None:
                    return failure
                record = updated
            self._custody[root_id] = current
            # Persistence can take time. Reinspect the full tuple after commit
            # before issuing a current-custody result.
            return self.inspect(root_id, location_ref=location_ref)

    def inspect_location(self, location_ref: str) -> RootAvailability | ObservationFailure:
        """Inspect an allowed locator without allocating or persisting a record.

        Transient descriptor custody can establish physical availability for an
        unregistered root. Only continuous custody of an existing application
        record supplies its UUID. Reading an alias never adds a saved locator.
        """
        with self._lock:
            failure = self._before()
            if failure is not None:
                return failure
            if set(self._records) != set(self._custody):
                return ObservationFailure("identity-unverified", "identity-reconciliation-required")
            failure = self._live_graph_failure()
            if failure is not None:
                return failure
            capture = self._capture(location_ref)
            if isinstance(capture, ObservationFailure):
                return capture
            current = _PhysicalCustody.from_capture(capture)
            known = next((key for key, record in self._records.items()
                          if location_ref in record.location_refs), None)
            if known is None:
                aliases = [key for key, custody in self._custody.items()
                           if custody.root_id == current.root_id]
                if len(aliases) > 1:
                    return self._invalidate("identity-live-mapping-conflict")
                known = aliases[0] if aliases else None
            if known is None:
                return RootAvailability(location_ref, capture.content_revision, capture.layout)
            change = self._custody_change(self._custody[known], current)
            if change is not None:
                return self._invalidate(change)
            record = self._records[known]
            repository_id, checkout_id, mutation_owner = self._result_fields(record, current)
            return RootAvailability(
                location_ref,
                capture.content_revision,
                capture.layout,
                known,
                repository_id=repository_id,
                checkout_id=checkout_id,
                mutation_owner=mutation_owner,
            )

    def inspect(self, root_id: str, *, location_ref: str) -> LiveRootIdentity | ObservationFailure:
        """Revalidate current custody; imported record IDs never regain authority."""
        with self._lock:
            failure = self._before()
            if failure is not None:
                return failure
            if not isinstance(root_id, str) or root_id not in self._records:
                return ObservationFailure("identity-unverified", "identity-record-unknown")
            if root_id not in self._custody:
                return ObservationFailure("identity-unverified", "identity-reconciliation-required")
            failure = self._live_graph_failure()
            if failure is not None:
                return failure
            capture = self._capture(location_ref)
            if isinstance(capture, ObservationFailure):
                return capture
            current = _PhysicalCustody.from_capture(capture)
            change = self._custody_change(self._custody[root_id], current)
            if change is not None:
                return self._invalidate(change)
            record = self._records[root_id]
            repository_id, checkout_id, mutation_owner = self._result_fields(record, current)
            return LiveRootIdentity(
                root_id,
                location_ref,
                capture.content_revision,
                capture.layout,
                repository_id=repository_id,
                checkout_id=checkout_id,
                mutation_owner=mutation_owner,
            )
