# 06f: Integrate the working Workbench into canonical Vivary
Type: packet
Parent: 06
Status: ready-for-agent
Depends-on: [03c, 12h]
Owner: Coordinating Codex, sole integration writer; independent boundary reviewer
Scope: Bring the existing project registry, catalog, readiness, activity, selection UI, and normal application startup into canonical dev as reviewed source increments.
Verification-kind: runtime
Timebox: One coherent application increment per reviewed PR; use existing checks and the real application.

## Goal

Run the Workbench from canonical Vivary source, register two disposable projects,
switch between them, and retain the selected project after a browser refresh.

## Context

Read [the engineering policy](../../../../ENGINEERING.md),
[the current frontier](../index.md), [Native ownership](../native-owners.md),
and [12h](12h-core-root-custody-integration.md). The user authorized canonical
integration on 2026-09-12. Use the existing authorized Zo checkout and private
handoff to locate the working implementation and its accepted runtime evidence.

Keep one writer. Review the source dependency closure and copy only what the
normal app needs. Preserve private history, runtime data, transcripts, and old
verification infrastructure at their existing private locations.

## Owned files

- The required application/configuration source under `packages/workbench/`.
- Required changes to the existing registry contract model and its focused tests.
- Existing app verification commands, relevant CI coverage, README, and outcome 06.
- A concise receipt and regenerated frontier after acceptance.

## Done condition

The canonical source boots through normal startup with disposable Native identity,
SQLite, supported temporary project roots, and disabled model providers. Two
projects can register and switch; refresh restores the current selection. Missing
or revoked access clears stale project state. Shutdown cleans up the owned provider.
Relevant tests, actual application checks, source review, and PR CI pass.

## Verify

Use the existing package scripts after the source has been integrated:

```console
pnpm --dir packages/workbench typecheck
pnpm --dir packages/workbench test:project-services
pnpm --dir packages/workbench build
pnpm --dir packages/workbench doctor
python scripts/check_multi_project_plan.py --check
python scripts/check-source-navigation.py --check
git diff --check
```

Exercise the normal app through the existing concise browser journey. Keep an
ordinary command/result record. Do not recreate the retired C5 proof campaign.

## Stop conditions

Inspect source provenance and any applicable template license before publishing
copied files. Core and Toolkit package metadata declares MIT; preserve required
notices. Review the shell's recorded dependency advisories before admitting an
exposed deployment. Do not infer production readiness from the disposable setup.

Root recovery, persistent deployment storage, project mutations, paid model calls,
and activation of scheduled work remain separate requirements. Stop only the
operation whose actual prerequisite is missing and continue independent work.

## Log

- 2026-09-12: Prepared the next canonical application increment after the reviewed
  Core custody import. Existing private application behavior is the implementation
  source; its history and retained evidence remain private.
