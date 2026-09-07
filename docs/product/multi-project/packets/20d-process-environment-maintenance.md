# 20d: Repair the environment and simplify the development process

Type: packet
Parent: 20
Status: done
Depends-on: [10c]
Owner: Codex maintenance session, sole document writer, with bounded cleanup and independent review helpers
Scope: One process and environment maintenance iteration. No product feature expansion or live model call.
Verification-kind: runtime
Evidence: [Maintenance receipt](../receipts/20d-process-environment-maintenance.md)
Verification-result: passed
Timebox: One reviewable maintenance iteration, then return to the owner.

## Goal

Make the next development session understandable and repeatable. Replace the
existing handoff, clean disposable task resources, prepare the documentation
build environment, and record the exact remaining runtime prerequisite.

## Context

Read the [owner decision](../design.md#iterative-process-decision-2026-09-06),
[execution rules](../execution-contract.md), and [20c receipt](../receipts/20c-headless-loop-preparation.md).
The preserved implementation checkout owns its private handoff and GUI decision
ledger. Its source index names the checkout. Keep those local paths private.
The source map already links program execution through a typed source reference.

## Owned files

- This packet, its receipt, and the parent outcome log.
- Existing execution contract and owner decision in the design.
- Existing private handoff, source index, and GUI JSON decision/status fields.
- Generated planning and document views, through their existing renderers.
- One private scratch directory and exact inventoried disposable 20c resources.

## Done condition

- A short existing handoff explains state and the next operation without copied history.
- Execution rules include task sizing, bounded delegation, source ownership, and cleanup at task close.
- The existing task graph and source navigation checks pass.
- Documentation dependencies and build are attempted in the verified Habitat image. Record actual results and any specific prerequisite.
- The authorized existing-source clock resync is attempted. Record Windows access and sync results without weakening runtime checks.
- Cleanup preserves verified exports and needed failure evidence, with measured removal and residual ownership.
- Independent review finds no missing authority, lost continuation, or unsupported completion claim.

## Verify

Run the [common planning checks](../execution-contract.md#maintaining-the-graph),
source navigation check, private document renderer checks, and relevant build.
The receipt must distinguish maintenance completion from 20c runtime acceptance.

```console
python scripts/check_multi_project_plan.py --check
python scripts/check-source-navigation.py --check
```

## Stop conditions

Do not change clock configuration, service startup mode, registry, or protections.
An Administrator-only clock operation stops that operation. Do not rerun the full
20c suite without meaningful clock repair and its required preflight.
No paid action, publication, merge, new factory activation, or next packet claim.

## Log

- 2026-09-07 UTC, 2026-09-06 owner-local date: Claimed the owner-requested maintenance iteration. Windows denied the existing-source resync with error 0x80070005. Habitat's pinned image supplies Node 22.23.2 and npm 10.9.8.

- 2026-09-07: Source navigation passed. The private document renderer passed after handoff anchor repairs. The exact Habitat build-preparation permission was declined. Complete the remaining setup only after renewed authority. The strict 20c clock gate remains separate.

- 2026-09-07: Renewed setup permission received. Audit/install passed with zero vulnerabilities, offline build produced 33 pages, and built links passed. Administrator clock sync and the 60-second Habitat preflight passed. See the receipt for exact limits. Maintenance completed, with full 20c acceptance still open.
