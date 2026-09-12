# Core root custody integration receipt

Evidence-record: 12h
Date: 2026-09-12
Result: focused Zo checks and independent source review passed.

The canonical integration contains three existing Vivary-authored Core modules.
Their imports use the standard library and the existing checkout observer. No
new dependency or copied Littleagent UI is included.

The Linux observer holds filesystem descriptors, detects aliases and root or Git
administration replacement, and produces bounded read observations. The lifecycle owner persists application identity records while retaining live
verification only within the owning process. The private stdio provider accepts
one trusted installation configuration and subsequent location references.

Verification on Zo used Python 3.11.2, installed Git and Node, an unprivileged
user, a minimal environment, and disposable tmpfs roots. The command is in
[the packet](../packets/12h-core-root-custody-integration.md#verify).

- 73 filesystem, lifecycle, read, VCS, and actual-provider tests passed.
- Six tests invoke the actual Python provider: observe/inspect, refusal
  after restart, caller authority fields, malformed frames, protocol sequence,
  and Git repository/nested-folder/linked-worktree inspection.
- Independent review found that the provider discarded verified Git inspections.
  All three Git layout subcases reproduced the bug before the fix and pass now.
- Legacy VCS witness serialization was removed from the imported tests while
  retaining project/Git immutability, state, migration, and refusal assertions.
- Permission tests initially ran as root and produced three errors because root
  could still write. The passing unprivileged run exercises real denied writes.

Linux local filesystems are supported; Windows, v9fs, and unsupported layouts
refuse verification. Restart preserves records without restoring authority.
Root recovery, cross-process mutation fencing, Workbench publication, and live
project runtime remain open. This source integration is not a package release.

Independent review approved the final three-module dependency closure and the Git
inspection fix. Planning, source navigation, line-ending, diff, 33-page site build,
and 2,752 local-reference plus 1,553-anchor checks pass. Required GitHub checks
remain a merge gate; source acceptance does not bypass branch protection.
