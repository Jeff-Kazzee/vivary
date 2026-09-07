# 20c: Prepare the deterministic headless loop proof
Type: packet
Parent: 20
Status: needs-info
Depends-on: [10c]
Owner: Codex 20c session on 2026-09-07, sole writer
Needs: A Habitat wall clock proven nondecreasing across one complete container and subprocess acceptance lifecycle, supplied by the Habitat environment maintainer. CPU affinity and continuous distro activity did not prevent backward steps; do not rerun the strict candidate until this environment prerequisite is met.
Scope: Offline fixture, prompts, protocol, sequencer, Claude adapter test seam, and adversarial tests; no coding-runtime or model call.
Verification-kind: runtime
Timebox: One context window. Stop after the offline Habitat evidence and closure records are complete.

## Goal

Create and verify every deterministic input and control needed by
[20a](20a-headless-loop-proof.md), while its live Claude proof remains blocked
on a verified whole-invocation token bound. The frozen draft is a reviewed
baseline under the earlier contract. The owner's
[multi-agent phase decision](../design.md#multi-agent-phase-decision-2026-09-06)
adds the implementation gaps below. Runtime acceptance also requires a stable
Habitat clock; the earlier test results do not accept these added requirements.

## Required phase and handoff changes

The 2026-09-07 source implements stage-specific runtime/agent bindings, a
separate phase-gate decision, and durable handoff identities under the decision
above. Response and usage completeness remain distinct from phase acceptance. The existing planner,
developer, and QA fixture is the bounded proof. Offline cases cover mixed
adapter routing, refused phase completion, wrong agent/session/runtime binding,
and a repeated accepted handoff that dispatches no second successor. Keep usage
accounting shared across stages. Native adapter and session enforcement remain
live-runtime proof; test doubles do not establish them. Source work can proceed
independently while the clock prerequisite holds executable Habitat acceptance.

## Declared phase checks and rework routes

Defined before the 2026-09-07 implementation. These are agent-selected checks
for this fixture, under the owner's phase decision.

The workflow configuration names every iteration's planner, developer, and QA
binding. Each binding contains a runtime, assigned agent, and native session
reference. Agents differ by role. Session references differ across stages,
including later iterations. The configured adapter must identify the selected
runtime. Unknown runtimes and changed resume bindings fail before dispatch.
Native adapters retain session creation and verification. Offline doubles prove
request routing and binding checks only.

| Phase | Required checks | Accepted route | Rejected route |
| --- | --- | --- | --- |
| Planner | Complete response and usage, exact request and identity, all four fixture requirement IDs, nonempty priority, preservation, and acceptance sections, unchanged candidate | Developer receives the accepted development document and its revision | Block this attempt. No developer call |
| Developer | Complete response and usage, exact identity, nonempty changes and validation sections, only `linkcheck.py` writable, valid Python with a `check_tree` function, fixed inputs unchanged, committed candidate | QA receives the accepted development document, developer report, and candidate checkpoint. The coordinator runs the fixed oracle before QA | Block this attempt. No QA call or candidate export for a rejected submission |
| QA | Complete response and usage, exact identity, all four requirement IDs, explicit `ready`, `rework`, or `blocked` verdict bound to candidate and deterministic evidence hashes, nonempty status/evidence/gaps/next-action sections, frozen candidate unchanged | Green plus `ready` advances to the next iteration, or completes the final iteration | Known red plus `rework`, or a green candidate needing review rework, returns to the next planner while iterations remain. Regression, missing evidence, contradictory verdict, explicit block, or exhausted rework stops acceptance |

The existing configured iteration limit bounds rework. Two consecutive
iterations without candidate progress also stop. There is no hidden quality
threshold or freeform completion inference. These mechanical planner/developer
checks do not establish semantic correctness. QA's explicit review is required,
and the fixed oracle independently constrains its verdict.

Each request carries its stage binding, invocation attempt, consumed handoff
hash, and QA evidence hash when applicable. Response/usage completeness and the
coordinator's gate decision are separate records. One schema retry remains
available only for an unchanged role view. Gate rejection is not a schema retry.

The existing receipt chain stores dispatch claims and gate/handoff records.
An accepted handoff binds the workflow revision, predecessor and successor,
predecessor attempt, accepted artifact hashes, and candidate Git checkpoint.
Dispatch verifies those bytes before reserving from the shared ledger. It
persists a claim before calling the adapter. The run lock serializes competing
resumes. A repeated claim or ambiguous crash interval refuses dispatch, retains
the original reservation, and requires reconciliation. An accepted developer
checkpoint can resume at QA with the original identities and deadline. The
accepted receipt binds the exact prior control state and ledger for recovery
between receipt and state writes. Terminal replay revalidates every accepted
document and report hash, including final QA with no successor.

New tests that exercise only these deterministic decisions may run by exact
test class in the same offline Habitat boundary. They do not run candidate
subprocesses or relax the production clock guard. Record this narrow evidence
separately. The complete strict suite and independent runtime acceptance remain
held until the recorded clock prerequisite changes meaningfully.

## Context

### Workflow input

`--workflow` replaces the draft's `--runtime` option in both entry points.
Supply a JSON file with `schema: vivary.hoh-workflow/v1`,
`policy: vivary.hoh-fixture-gates/v1`, the exact `run_id`, integer `iterations`,
and an ordered `stages` array. Every iteration has exactly three entries in
planner, developer, QA order. Each entry has these fields:

| Field | Required value |
| --- | --- |
| `stage_id` | `<run_id>-i<iteration>-<role>` |
| `run_id` | The same value passed to `--run-id` |
| `iteration` | Integer from 1 through `iterations` |
| `role` | `planner`, `developer`, or `qa` |
| `runtime` | A registered adapter whose `runtime_id` matches this value |
| `agent_id` | Assigned agent reference, distinct by role and stable across iterations |
| `session_id` | Native session reference, unique within that runtime across all stages |

The runtime integration maintainer supplies verified native session references.
The offline tests use explicit fake references. The native entry point supports
only the existing Claude adapter, which remains blocked by its preflight.
Selecting Codex before its adapter exists refuses without substituting Claude.
The original workflow hash is persisted with baseline and resume state. Changing
assignments or sessions requires a new run and preserves the existing ledger.

For the 20a healthy proof, use run ID `claude-healthy`, three iterations, and
nine stage entries. The resume and regression fault configurations each contain
one iteration and three entries, with their own run IDs and session references.
The 20a command examples name each private configuration path. Store it using
the same fresh-path, ignore, containment, and evidence rules as other proof inputs.

Read [20a](20a-headless-loop-proof.md), especially its usage contract, fixture
layout, done condition, and fault commands. Those sections remain normative for
field meanings, hashes, role visibility, expected-red behavior, reservation,
resume, and regression semantics. Also read [the direction decision](../design.md#direction-decision-2026-09-06),
[the execution contract](../execution-contract.md), and the accepted
[10c Habitat packet](10c-habitat-fallback-proof.md) and
[receipt](../receipts/10c-habitat-fallback-proof.md). Use the HoH appendix A.2
prompts through 20a's source link; do not copy its paper or 20a's full contract.

Python `3.11.16` is present in the existing Habitat image. Use only the standard
library. Install nothing. The tracked implementation files are outputs of this
packet, so their initial absence is not a prerequisite failure.

## Owned files

- Create `tools/hoh_loop.py`, `tools/hoh/__init__.py`,
  `tools/hoh/protocol.py`, `tools/hoh/workflow.py`, and `tools/hoh/claude.py`.
- Create `tools/hoh/prompts/planner.md`, `developer.md`, and `qa.md`.
- Create `tools/tests/test_hoh_loop.py` and the tests-only executable
  `tools/tests/hoh_fault_probe.py`.
- If the installed Claude design uses scoped MCP tools, create
  `tools/hoh/role_tools.py` and `tools/tests/test_hoh_role_tools.py`.
- Create `docs/product/multi-project/fixtures/hoh-loop/spec.md`,
  `linkcheck.py`, and `tests/test_links.py`.
- Create `docs/product/multi-project/receipts/20c-headless-loop-preparation.md`.
- Record the owner's phase clarification in `docs/product/multi-project/design.md`.
- At closure update this packet, 20a's preparation evidence link and prerequisite
  status, and parent outcome 20. Regenerate the planning
  index and graph, update `CHANGELOG.md`, and run the approved canonical sync
  for its generated changelog and `llms-full.txt` mirrors.

Keep captured output and the source manifest under the verified preserved
Littleagent checkout's `.tmp/hoh-proof/20c/`. Apply 20a's separate ignore and
resolved-containment checks to every actual output and temporary filename
before writing; refuse existing files. Record source-bundle and writable test
paths privately. Retain each stopped task container and its test tree after
verification. After independent acceptance and a restore-and-hash check of the
exported evidence, the 20c owner prepares an itemized cleanup receipt and asks
for approval for each container or path removal. Record stopped-process
evidence, exact targets, archive hashes, owner, and a review-by date seven days
after closure. Keep pending removals visible at the next handoff; schedule no
job. Archives remain inputs for 20a and follow its later retention contract.
Private evidence and source bundles are not product source.

## Done condition

1. The fixture holds a fixed specification, fixed oracle, and incomplete
   starter. The harness runs the starter in a disposable copy and accepts only
   the exact declared failing test IDs and observations. An arbitrary red is a
   harness failure. Tests also prove a deterministically completed copy passes
   the unmodified oracle.
2. The protocol defines the runtime-neutral role request/result, evidence,
   transition, usage, reservation, and receipt records used by 20a. Strict
   validation rejects missing, unknown, mistyped, stale, or cross-run fields.
3. The sequencer owns prompt assembly, one schema retry, transition order,
   candidate and evidence hashes, deterministic test execution, no-progress
   detection, committed developer checkpoints, QA freeze, and atomic receipt
   writes. Every receipt binds the baseline, specification, oracle, prompts,
   role inputs, candidate state, test output, and prior receipt state.
   The retry applies only while the role's input view is unchanged. An invalid
   developer result that changed its writable candidate fails closed, retains
   the failed view and full reservation, and launches no retry or next role.
4. Deterministic role doubles exercise the three-iteration structure. Planner,
   developer, and QA receive only the views defined by 20a; tests prove the
   planner cannot request candidate access and QA cannot mutate its frozen view.
5. Before any adapter invocation, the ledger atomically reserves a verified
   maximum cumulative input-plus-output charge. Unknown or unenforceable maxima
   refuse safely without calling the adapter. A reservation larger than the
   remaining balance also refuses before invocation.
6. Complete usage settles the reservation under 20a's cache-counting rules.
   Interrupted, partial, malformed, or incomplete usage retains the full
   reservation. Missing vendor values stay `null`. Tests reopen the same ledger
   in a new process and prove the packet balance never resets.
7. The tests-only resume probe interrupts after the committed developer
   checkpoint and before QA. It resumes the same bound run without rerunning the
   developer, or classifies the attempt as a restart and keeps the first run
   incomplete when safe continuation cannot be proved.
8. The regression probe changes only disposable candidate implementation before
   the QA freeze. It proves the sequencer reports the regressed observation,
   stops acceptance, and preserves healthy evidence without editing the oracle
   or prompts.
9. The Claude adapter preflight fails closed for unsupported versions, flags,
   isolation, usage fields, and whole-invocation bounds. It invokes only the
   installed native CLI seam and contains no provider API client or substitute
   provider path. No test makes a real Claude request.
10. If scoped MCP tools are implemented, deterministic permission tests place a
    synthetic canary outside each role view and prove every read-only role tool
    refuses path, link, environment, process-file, shell, and write access. These
    tests do not establish the live OS, CLI, network, or credential boundary.
11. The 20c receipt records the source-bundle manifest and hashes, image and
    Python identities, exact commands and exit status, named adversarial
    observations, fault checkpoints, ledger and receipt bindings, and explicit
    absence of authentication mounts, network access, installs, and model calls.
12. The sequencer enforces 20a's one-hour iteration deadline across native CLI,
    role-tool worker, and deterministic test processes. Pass the remaining
    duration to every launch, refuse work after expiry, and reject late output.
    Stop and reap the exact owned process group and stop any owned role container
    within a five-second grace period; retain its files and stopped container.
    Preserve elapsed time and the original expiry across resume, and refuse a
    backward or uncertain clock observation rather than resetting the allowance.
    Adversarial tests use a stalled child and child-of-child to prove timeout,
    descendant termination, incomplete receipts, retained token reservations,
    no next-role launch, and no deadline reset after restart.
13. Each stage binds its agent and runtime independently. Completion requires a
    declared gate over the required output and evidence, separate from response
    or usage completeness. The persisted handoff binds its accepted artifact
    revision, predecessor, successor, and stage attempt. Tests prove configured
    mixed-runtime routing, fail-closed gates and identity checks, and no duplicate
    successor on replay. See the governing decision for the acceptance boundary.

## Verify

Use the existing host Python for source and plan inspection only. Tests that
execute mutable candidates run inside the offline Habitat boundary below.
Before creating the task container, verify the installed image without pulling:

```console
docker image inspect sha256:ffdba5d54dd6f91875fa60fc15103b6b30bb23ecaaf2d8ed65559d3cdff05bee
```

Acceptance uses a reviewed source bundle outside the production checkout,
mounted read-only at `/opt/vivary-hoh-source`. Set `HABITAT_SOURCE_BUNDLE` to
its verified absolute host path. Set `HABITAT_TEST_ROOT` to a fresh persistent
task directory and `HABITAT_TEST_CONTAINER` to a unique `vivary-20c-test-` name.
Verify both paths remain in the task's authorized Habitat work root. Refuse an
existing test path or container name, then create that fresh directory with
write access for the image's verified `ubuntu` UID and GID. Mount it at `/tmp`
so stopping the container preserves candidate and test evidence. From Habitat's
Docker host, run the existing image with this boundary and no authentication volume:

```console
docker run --pull never --name "$HABITAT_TEST_CONTAINER" --network none --read-only --user ubuntu --cap-drop ALL --security-opt no-new-privileges --cpus 2 --cpuset-cpus 0 --memory 1g --pids-limit 128 --mount type=bind,src="$HABITAT_SOURCE_BUNDLE",dst=/opt/vivary-hoh-source,readonly --mount type=bind,src="$HABITAT_TEST_ROOT",dst=/tmp --workdir /opt/vivary-hoh-source sha256:ffdba5d54dd6f91875fa60fc15103b6b30bb23ecaaf2d8ed65559d3cdff05bee python3 -B -m unittest discover -s tools/tests -p 'test_hoh*.py'
docker inspect "$HABITAT_TEST_CONTAINER"
```

Record the resolved mount sources, image and container inspection, exact command,
source hashes, test names/counts, stdout, stderr, and exit status. If role-tool tests
exist, the discovery command includes them. Then run the common planning checks
from [the execution contract](../execution-contract.md#maintaining-the-graph).

## Stop conditions

Use no network, authentication volume, copied credential, model call, API key,
provider client, install, app server, schedule, production checkout bind, or
Docker socket mount. Do not create a token broker, daemon, database, queue, or
fallback accounting service. Stop if the source bundle is writable, its hashes
differ from the reviewed candidate, the container boundary differs from the
recorded command, or a deterministic adversarial check fails.
Use no `--rm`, automatic source/test-tree deletion, or cleanup job. Stop only
task-owned processes after tests; keep removal pending until explicit approval.

20c closure proves preparation only. Actual role-tool authority, authenticated
CLI behavior, provider network path, credential isolation, OS enforcement,
three live iterations, live usage, and both live fault runs remain 20a runtime
acceptance. Leave 20a `needs-info` until the runtime integration maintainer
supplies the required enforceable token bound or Jeff approves a specific,
reviewable policy alternative. Do not propose or assume that missing service in
this packet, and do not mark 20a done from deterministic evidence.

## Log

- 2026-09-06: PR #335 review separated claimable deterministic preparation from
  the blocked live proof. Packet 20c owns offline implementation and adversarial
  evidence; 20a retains every live-runtime claim and token-policy gate.
- 2026-09-06: Runtime classification now covers executable offline acceptance.
  The sequencer must prove enforced deadlines. Containers and test trees remain
  available for an itemized, explicitly approved cleanup after evidence export.
- 2026-09-06: The implementation was frozen at a twelve-file manifest, and an
  independent source review closed all six findings. Three unchanged strict
  acceptance waves refused after Habitat wall-clock reversals, including runs
  with CPU 0 affinity and continuous distro activity. Packet 20c is `needs-info`
  until the Habitat environment maintainer supplies a nondecreasing clock across
  the complete container and subprocess lifecycle. See the
  [preparation receipt](../receipts/20c-headless-loop-preparation.md).
- 2026-09-06: The owner clarified distinct agents, per-stage runtime choice,
  and deterministic completion/handoff. The frozen draft does not implement
  those full requirements. This packet owns the offline corrections; earlier
  source review and clock-held evidence remain historical.

- 2026-09-07: Implemented D26's stage bindings, completion gates, durable
  handoffs, shared accounting, and bounded accepted-developer recovery.
  Independent source review closed seven findings and one follow-up. The author
  wave and reviewer-requested repeat each passed 18 control tests in fresh offline
  Habitat containers. The strict guard is unchanged; full runtime acceptance
  remains blocked on the existing clock prerequisite. See the refreshed receipt
  for exact scope, source hashes, retained resources, and resume point. No next
  ticket, live call, push, or merge was claimed.
