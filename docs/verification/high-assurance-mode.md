# High-assurance mode

This optional mode contains controls previously required by default in the
Vivary program execution contract. Jeff demoted that workflow on 2026-09-12.
[ENGINEERING.md](../../ENGINEERING.md) remains the governing policy.

## When to invoke it

Use extra verification when a concrete failure could cause destructive writes,
authorization bypass, cross-project disclosure or mutation, lost durable data,
or an unsafe filesystem or process boundary. A risky migration, custody change,
or concurrency bug can justify selected controls from this mode.

Name the failure, its consequence, and the control that addresses it in the
existing task or change description. Ordinary UI layout, documentation, query
logic, or a failed test does not activate this mode by itself. An agent may
select proportionate controls without asking for routine phase approval.

Before adding infrastructure, check whether the existing test suite, the real
application, or a smaller assertion can catch the same failure. Stop and
simplify when verification approaches the feature's complexity.

## Controls to select

Select only the controls needed for the named risk. This is not a mandatory
sequence and does not require a new packet, ledger, or report for each control.

### Independent review

Use a separate reviewer for permission boundaries, filesystem custody,
migrations, or tricky concurrency. Give the reviewer a precise question and
explicit source ownership. A second evidence verifier can help when an external
effect or isolation claim needs independently checked observations.

The former Plan, Implement, QA, and Verify role split is available for unusually
consequential work. It is not required for every edit, execution, or retry.
Role separation alone does not provide operating-system isolation.

### State and authorization checks

Exercise the real application composition with safe test dependencies. Cover
foreign identities, revoked access, stale project selection, failed writes,
and recovery only where they affect the changed boundary.

Assert meaningful before/after state. Use rollback or mutation testing when it
can expose a defect that ordinary checks miss. Keep model providers disabled
unless a specific live-provider operation has authority.

### Filesystem and process containment

Use disposable roots and databases for tests. Keep access within named roots,
retain private custody state, and reject unsupported or ambiguous root identity.
Use the existing sandbox when the test needs one. Preserve Chromium sandboxing
for browser tests. Do not weaken isolation to make a test pass.

Identify owned processes before cleanup when shared services or process reuse
makes ownership uncertain. Exact identity inventories and external observers
belong here when ordinary child handles and cleanup cannot address that risk.
Stop only task-owned activity. Do not shut down shared Docker or WSL services.

### Resource and attempt limits

Before expensive builds, heavy browser jobs, or unstable workloads, check live
memory, disk, and included usage. Keep one heavy job active. Retain the existing
host reserve and cleanup path for already approved jobs.
Treat unavailable measurements as unknown.

Use strict cumulative attempts or elapsed-time budgets for expensive,
destructive, externally limited, or destabilizing operations. Count the actual
work without renaming retries to evade a limit. Changing a specifically approved
limit requires its owner's authority. Ordinary tests may be fixed and rerun
under normal timeouts and cleanup.

### Evidence and source binding

Keep the command, result, useful failure logs, and relevant screenshots first.
Add hashes, manifests, raw state capture, admission records, or archives only
when they answer the named risk. Prefer Git and lockfiles to whole dependency
tree manifests unless a concrete integrity concern requires more.

Separate source inspection, test execution, deployment, and actual external
effects. A fixture cannot establish default production startup or authentication.
Archive checks prove integrity, not a runtime rerun. Preserve failed evidence as
failed. Reference retained prior artifacts instead of copying them recursively.

## Leaving this mode

Stop adding evidence after the behavior, relevant tests, real application check,
and important failure cases satisfy the feature's definition of done. Record
any remaining limitation concisely in its existing owner, commit the increment,
and return to the default engineering loop.

Existing receipts, frozen inputs, and budget records remain historical evidence.
This mode grants no spending, destructive action, external publication, merge,
or authority to alter earlier results. Consult an old packet's exact profile
only when resuming that specifically bounded operation.
