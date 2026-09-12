# 12h: Integrate project root custody into canonical Vivary
Type: packet
Parent: 12
Status: done
Depends-on: [12a]
Owner: Coordinating Codex, sole integration writer; independent source reviewer
Scope: Integrate the existing Linux root observer, durable identity records, private provider, and focused tests into canonical dev.
Verification-kind: runtime
Evidence: [Core root custody integration receipt](../receipts/12h-core-root-custody-integration.md)
Verification-result: passed
Timebox: One coherent source PR with existing focused checks and independent boundary review.

## Goal

Give the Workbench integration a canonical implementation that recognizes a
configured project folder without treating saved paths or IDs as live authority.

## Context

Follow [the engineering policy](../../../../ENGINEERING.md), the accepted
[observation contract](../contracts/root-vcs-observation.md), and
[the root observation owner](../source-map/modules/root-observation/index.md).
The user authorized canonical branch integration on 2026-09-12. Preserve the
accepted private source and evidence; bring over only the required source.

## Owned files

- Core: `physical_observe.py`, `root_identity_lifecycle.py`,
  and `root_provider_stdio.py` under `packages/core/vivary_core/`.
- Their five focused test modules under `packages/core/tests/`.
- Core README, outcome 12, root observation route, receipt, and generated frontier.

## Done condition

Canonical source imports without new dependencies. Actual Linux filesystem and
provider tests pass, including replacement, aliasing, Git worktrees, durable-record
migration, malformed transport, process exit, and refusal after lost custody.
Independent review finds no unresolved blocker. Required PR checks pass before merge.

## Verify

Run as an ordinary user on a supported local Linux filesystem. On Zo, use a
disposable tmpfs directory through `TMPDIR`; the persistent workspace is v9fs.

```console
PYTHONPATH=packages/core:packages/core/tests python -m unittest test_physical_observe test_root_identity_lifecycle test_root_identity_reads test_root_vcs_identity_lifecycle test_root_provider_stdio
python scripts/check_multi_project_plan.py --check
python scripts/check-source-navigation.py --check
python scripts/check_line_endings.py
git diff --check
```

## Stop conditions

Keep user projects and their Git administration read-only. Do not infer restored
custody from serialized records. No cross-process mutation fence, Windows provider,
Jujutsu support, GUI publication, model runtime, or package release is included.

## Log

- 2026-09-12: Selected three existing product modules and their tests for the first
  canonical source increment. Normal tests use disposable temporary directories;
  retired witness serialization stays with the preserved private evidence.

## Verification log

- 2026-09-12: 73 filesystem, identity, and actual-provider tests pass on
  Zo as an unprivileged user. Three chmod cases in an initial root-user run could
  not enforce their intended permission failure; the unprivileged run covers it.
  A Git availability regression failed on all three Git layouts before the
  provider fix and passed afterward. Independent source review approved the final
  three-module closure. Planning, source navigation, line-ending, diff, site build,
  and site link checks pass. Required PR CI must pass before merge.

## Next packet

[06f](06f-workbench-source-integration.md) brings the working application source
onto this canonical custody implementation. Outcome 12 remains open for its
remaining VCS, recovery, and mutation requirements.
