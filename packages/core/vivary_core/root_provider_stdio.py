"""Private bounded stdio transport for the existing root-custody owner.

The application starts this file with an isolated Python interpreter and sends
one trusted configuration. Requests contain locator references, never paths.
No verification response survives loss of this process as authority.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

# This executable's own package tree is the sole application import root under -I.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vivary_core.physical_observe import ObservationFailure
from vivary_core.root_identity_lifecycle import RootIdentityLifecycle


LIMIT = 16384
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
REPOSITORY_ID = re.compile(r"repo_[0-9a-f]{32}\Z")
CHECKOUT_ID = re.compile(r"checkout_[0-9a-f]{32}\Z")


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def read_message(stream):
    line = stream.readline(LIMIT + 1)
    if not line:
        return None
    if len(line) > LIMIT or not line.endswith(b"\n"):
        raise ValueError("invalid frame")
    value = json.loads(line.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))
    if type(value) is not dict:
        raise ValueError("invalid message")
    return value


def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("invalid fields")


def identifier(value):
    if type(value) is not str or not ID.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def vcs_reference(result):
    if result.mutation_authorized is not False:
        raise ValueError("mutation authority is not observable")
    if result.layout == "none":
        if any(value is not None for value in
               (result.repository_id, result.checkout_id, result.mutation_owner)):
            raise ValueError("contradictory no-vcs identity")
        return {"kind": "none", "repositoryId": None,
                "checkoutId": None, "mutationOwner": None}
    if result.layout in {"git", "git-linked-worktree", "git-nested-project"}:
        if type(result.repository_id) is not str \
                or not REPOSITORY_ID.fullmatch(result.repository_id) \
                or type(result.checkout_id) is not str \
                or not CHECKOUT_ID.fullmatch(result.checkout_id) \
                or result.mutation_owner != "git":
            raise ValueError("invalid git application identity")
        return {"kind": "git", "repositoryId": result.repository_id,
                "checkoutId": result.checkout_id, "mutationOwner": "git"}
    raise ValueError("unsupported vcs identity")


def initialize(message):
    exact(message, ["version", "sequence", "operation", "config"])
    if message["version"] != 1 or type(message["version"]) is not int or message["sequence"] != 0 \
            or type(message["sequence"]) is not int or message["operation"] != "initialize":
        raise ValueError("invalid initialization")
    config = message["config"]
    exact(config, ["deviceId", "scope", "statePath", "locations"])
    identifier(config["deviceId"])
    if type(config["locations"]) is not dict or not 1 <= len(config["locations"]) <= 16:
        raise ValueError("invalid inventory")
    locations = {}
    for ref, value in config["locations"].items():
        identifier(ref)
        if type(value) is not str or not Path(value).is_absolute():
            raise ValueError("invalid locator")
        locations[ref] = Path(value)
    for field in ["scope", "statePath"]:
        if type(config[field]) is not str or not Path(config[field]).is_absolute():
            raise ValueError("invalid private path")
    return RootIdentityLifecycle(device_id=config["deviceId"], scope=Path(config["scope"]),
                                 state_path=Path(config["statePath"]), locations=locations)


def serve(input_stream, output_stream):
    owner = None
    try:
        owner = initialize(read_message(input_stream))
        output_stream.write(b'{"version":1,"sequence":0,"code":"ready"}\n')
        output_stream.flush()
        sequence = 1
        while (request := read_message(input_stream)) is not None:
            exact(request, ["version", "sequence", "operation", "locationRef"])
            if type(request["version"]) is not int or request["version"] != 1 \
                    or type(request["sequence"]) is not int or request["sequence"] != sequence \
                    or request["operation"] not in {"observe", "inspect"}:
                raise ValueError("invalid request")
            ref = identifier(request["locationRef"])
            result = owner.enroll(ref) if request["operation"] == "observe" else owner.inspect_location(ref)
            response = {"version": 1, "sequence": sequence}
            if isinstance(result, ObservationFailure):
                response["code"] = "identity-unverified"
            elif request["operation"] == "observe":
                try:
                    vcs = vcs_reference(result)
                except ValueError:
                    response["code"] = "identity-unverified"
                else:
                    response.update(code="observed", rootId=result.root_id, locationRef=ref,
                                contentRevision=result.content_revision,
                                vcs=vcs)
            elif result.layout in {"none", "git", "git-linked-worktree", "git-nested-project"}:
                response.update(code="available", rootId=result.root_id, locationRef=ref,
                                contentRevision=result.content_revision)
            else:
                response["code"] = "identity-unverified"
            output_stream.write(json.dumps(response, separators=(",", ":")).encode() + b"\n")
            output_stream.flush()
            sequence += 1
    except (ValueError, TypeError, OSError, RecursionError):
        return 1
    finally:
        if owner is not None:
            owner.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(serve(sys.stdin.buffer, sys.stdout.buffer))
    except Exception:
        # Never expose private paths, source bytes or a traceback on the wire.
        raise SystemExit(1)
