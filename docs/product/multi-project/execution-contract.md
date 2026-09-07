# How agents execute the Vivary program

The 36 numbered records are product outcome contracts. Some require several
sessions. Lettered packets are the units an agent claims and verifies in one
context window. Completing a packet does not complete its parent outcome.

## One current frontier

Read [the generated graph](graph.md). Outcome and packet files own their fields.
the graph is generated and checked against them. Do not dispatch an older
GitHub release map or a local historical handoff. [The authority map](issue-authority.md)
preserves those issue histories and names their surviving responsibilities.

Outcome dependencies are completion gates, not a prohibition on independent
preparation. Packet `Depends-on` fields are start gates. Do not add a product
release, optional connector, source import, or account prerequisite to a packet
that can finish without it. For example, registry contract fixtures can be
reviewed before a database is selected. Live pod execution requires a connection.

## One reviewable iteration

The owner's [2026-09-06 process decision](design.md#iterative-process-decision-2026-09-06)
sets the development rhythm. Choose one outcome small enough to inspect together.
State what changes and what proves it. Check the required environment before
coding. Implement, run the relevant checks, review the evidence, clean up, and
return the result to the owner. Plan, implementation, QA, fixes, independent
review, and cleanup belong to one continuous ticket. Do not stop between those
phases to request routine continuation. Stop only for a consequential decision
or a concrete blocker outside existing authority. Stop before claiming the next
ticket after completing that flow.

Use one lead writer. Delegate a bounded investigation or independent review when
it saves work. Default to at most two helpers, each with explicit ownership.
Scale checks to the change. A documentation correction does not need product
runtime tests. A runtime change needs behavior evidence from its named environment.

## Finish without accumulating debris

Each fact has one owner: the packet holds work and status, the receipt holds
verification, and the existing private handoff holds the next starting point.
Replace stale handoff content in place. Link to decisions and receipts instead
of copying their histories. Keep the handoff near 100 lines. Do not create a
dated handoff or a second continuation prompt for each session.

Before creating a document, identify its reader, source owner, and retirement
condition. Put a correction in its existing owner when possible. Historical
assignments are optional provenance and never active instructions. Generated
HTML and site pages are views. Edit their source and regenerate the views.

Use one named scratch directory per ticket and reuse it across retries. Record
created containers, directories, servers, and caches in that ticket's receipt.
Keep one verified final evidence export and the minimum unresolved failure
evidence. After verifying the export, remove authorized disposable copies and
stopped task resources by exact identity and contained path. Report retained
resources with a reason and removal condition. Never prune unrelated resources.
Shared dependency caches have a named owner and reuse purpose, not a copy per run.

Include resource cleanup in the packet's initial authority. If that authority is
missing, prepare the exact cleanup list and request only that operation. A failed
test does not justify retaining every source copy and container indefinitely.
On close, check links, graph status, generated views, stopped processes, retained
bytes, and the next command. Leave failed product acceptance open.

Project knowledge remains plain files with stable IDs, source links, and checked
relationships. Use the existing [source map](source-map/index.md) and task graph.
Brain Open Knowledge Format owns cross-project knowledge. Do not create another
graph database or duplicate project records in Brain by default.

## Status and ownership

- Outcomes use `planned`, `in-progress`, or `done`.
- Packets use `ready-for-agent`, `in-progress`, `needs-info`,
  `ready-for-human`, or `done`.
- `ready-for-agent` means the packet has sufficient existing inputs, one named
  writer, owned outputs, observable acceptance, verification, and stop conditions.
- `needs-info` must name the exact missing fact or external prerequisite and its
  owner. It does not mean unfinished dependencies or outputs not yet created.
- `ready-for-human` names one actual operation that requires a human after the
  agent has prepared and verified everything else. PR merge approval remains
  separate from an agent's documentation or contract acceptance.
- `done` requires `Verification-result: passed`, a verification log, and a linked
  receipt whose `Evidence-record` is the exact outcome or packet ID. The structured
  result is authoritative. The log records commands, details, and relevant history,
  including earlier failures. Duplicate or ambiguous result and binding fields are
  invalid. A packet's success never automatically closes the outcome or a release gate.

Claim the lowest ready packet whose verification environment is available.
Record one writer before editing. Other agents may review, but must not edit its
owned files concurrently. Checkpoint at one context window or the packet's
timebox: changed files, evidence, remaining work, exact next command, and owner.
Do not reset dirty work, run a competing push, or take over another active writer.

## Execution and verification

Use the bounded Habitat development environment. The owner confirmed BrowserPod
is unavailable on 2026-09-05. See the latest answer in the design decision.
BrowserPod setup and execution are outside the active task list.
Runtime packets name the environment and require its live preflight for the exact
tools they execute. Habitat results cannot satisfy BrowserPod-specific checks. Native CLI, Python, database, persistence, and isolation support
remain separate capabilities until each is observed.

Inspection packets may read source, write contracts and fixtures, inspect diffs,
and use the existing repository CI for documentation checks. They do not need a
live pod and cannot claim runtime behavior. Record `Verification-kind: inspection`
or `Verification-kind: runtime`. A common plan-lint command proves document
consistency only. A runtime packet also needs its own failing/passing behavior
checks and observed results.

The SDK, model loop, native run/session state, resource connections, tasks,
messaging, and automations retain their existing owners. Use [the owner inventory](native-owners.md)
before adding infrastructure. New product records require a demonstrated gap.
do not create another reasoning loop, transcript store, task queue, or scheduler.

## Ticket quality before dispatch

Every packet names its parent, writer, scope, existing inputs, exact outputs,
observable acceptance, execution environment, verification, stop conditions,
and evidence destination. Future output files are created by the packet. their
absence is not a missing input. Runtime packets must include adversarial failure
cases, user-visible behavior where applicable, and recovery evidence.

Keep a bounded packet for the current frontier and prepare the next one before
closing its predecessor. Future outcomes retain their complete acceptance and
scope mapping. Do not fabricate exact APIs or make giant outcomes look like
single-session implementation tickets. A newly discovered gap repairs the owning
packet and dependency edge, with a log entry. It does not erase product scope.

For optional VCS, hosting, task-source, and Brain paths, implement and verify the
native/skip path independently. Completion of the full optional integration may
still gate release coverage. A missing connector must not disable the core path.
Behavior docs move with each feature. Outcome 24 audits the installed journey.

## Gates and release truth

Routine in-scope design, fixture, documentation, and implementation choices are
agent work under the existing authorization. Account changes, spending, source
publication rights, destructive operations, scheduled activation, outbound email,
production release, and merges keep their specific authority requirements.
Stop only the dependent operation, continue independent packets, and name the
concrete prerequisite. Do not request blanket product reauthorization.

The real 100% scanner result remains an unmet release requirement. Neither
document checks, mock services, historical Habitat tests, nor a successful
BrowserPod Node fixture can close unrelated acceptance gates.

## Maintaining the graph

This section owns the common planning checks. Outcome contracts link here instead
of copying the commands. After changing outcome or packet metadata:

```console
python scripts/check_multi_project_plan.py --render
python scripts/check_multi_project_plan.py --check
python scripts/check_line_endings.py
git diff --check
```

The renderer only transforms the generated frontier index and full graph. CI runs
the guard's adversarial fixtures and rejects frontier, dependency, status, coverage,
and evidence drift.
