# 20c deterministic headless-loop preparation receipt

Evidence-record: 20c
Date: 2026-09-07. Verification kind: runtime. Result: Passed, offline preparation only.

## Accepted result

The coordinator binds each planner, developer, and QA stage to its configured
agent, runtime, and session reference. Explicit gates govern accepted artifacts
and durable handoffs. One ledger preserves reservations across retries and
replay. The strict full suite now passes in two fresh offline Habitat containers.
Independent QA reviewed the source and verified both execution records.

| Wave | Result |
| --- | --- |
| `full-author-f` | 62 passed, 62.101s, exit 0 |
| `full-review-b` | 62 passed, 62.841s, exit 0 |

Both ran `python3 -B -m unittest discover -s tools/tests -p 'test_hoh*.py' -v`.
There were no skips. This includes real disposable candidate subprocesses,
process-group termination, fixed-oracle execution, Git checkpoints, restart,
receipt-chain validation, and usage persistence. Native agent calls use test
doubles. No live model, authentication, install, or network request ran.

## Corrections verified

The first strict author run reproduced three regression-path errors. The
coordinator detected a regression and then tried to consume a stopped handoff
for QA. It now persists a terminal test record before any QA view, dispatch,
reservation, or successor. Healthy proof and lost test IDs remain inspectable.

Independent review found four related edge cases. Incomplete oracle output now
takes precedence over inferred regression. Project and frozen-candidate drift
refuse acceptance. Deadline expiry after receipt processing records an incomplete
terminal result. An incomplete preliminary regression oracle saves process
evidence and stops before fault injection. Tests reopen each stopped run and
prove that no agent dispatch, ledger reset, or deadline reset occurs.

Two new edge tests first failed against the unfixed source. The first expanded
suite also caught a diagnostic hash placed outside the strict receipt schema.
it now lives in receipt details. The corrected test assertion compares a
read-only freeze with its frozen hash and the mutable candidate with its own
binding. Protocol validation and the production clock guard remain strict.

One Windows PowerShell 5 launcher attempt stopped on normal unittest stderr.
It is not acceptance evidence. The completed waves used PowerShell 7.

## Acceptance coverage

| Packet checks | Executed evidence |
| --- | --- |
| 1: fixed fixture/oracle | Exact expected-red starter, completed green copy, shadowed runner and false-green refusals |
| 2-3: protocol and sequencing | Strict request/result/evidence validation, immutable receipt chain, retry and committed artifact checks |
| 4: role views | Three iterations plus undeclared path, link, process, shell, and write refusals |
| 5-6: shared usage | Unknown/over-budget maxima refuse before dispatch. partial charges persist. reopened balance does not reset |
| 7: recovery | Developer checkpoint and receipt/state-write interruption recover without a second developer call |
| 8: regression | Ordinary and injected loss stop. healthy proof survives. incomplete, changed, and late evidence refuse |
| 9-10: adapter boundary | Claude preflight refuses unsupported capabilities without invoking its runner. scoped native MCP tools are not implemented |
| 11: evidence | Matching 13-file source manifests, exact command, container inspection, logs, test trees, and verified export |
| 12: deadline/processes | Stalled child and descendant are stopped/reaped. expiry persists. clock rollback and boot changes refuse |
| 13: stage gates/handoffs | Mixed adapter routing, identity/gate rejection, artifact binding, shared ledger, and duplicate replay refusal |

## Execution and source identity

The existing Habitat image is
`sha256:ffdba5d54dd6f91875fa60fc15103b6b30bb23ecaaf2d8ed65559d3cdff05bee`,
with Python 3.11.16. Both containers used `--pull never`, no network, read-only
root and source, unprivileged `ubuntu`, all capabilities dropped,
no-new-privileges, two CPU quota units on CPU 0, 1 GiB memory, and 128 processes.
Exactly two task-contained binds exposed the source and writable `/tmp`.
There were no credentials, Docker socket, or production checkout mounts.
Both containers exited 0 without OOM. The strict clock guard remained enabled.

The first independent repeat, `full-review-a`, refused a real 11.90 ms backward
clock observation. Host synchronization alone did not stabilize startup.
Habitat was repeatedly stopping between short host commands. its time service
reported a new initial synchronization on restart. The accepted repeat kept one
bounded foreground Habitat process alive through startup synchronization,
a fresh 60-second clock preflight, the suite, and evidence capture. Time synchronization, the shared clock source, and deadline policy remain unchanged.
This is a required execution prerequisite, not proof the host clock never moves.

Both manifests have SHA-256 `2a863a0900e6ae58ea8677212429583d3b5a91c638c4a6b59f0a63f9dee98f53`. Independent QA compared every
entry with the canonical source. Exact source hashes follow.

| Source | SHA-256 |
| --- | --- |
| `docs/product/multi-project/fixtures/hoh-loop/linkcheck.py` | `3323e052e3649b9c811c0a685121f0ab73027f1ab87c364b31c8adc0928f96d5` |
| `docs/product/multi-project/fixtures/hoh-loop/spec.md` | `8a9c239f21e9613fb18d7a813ac3a62e53863d9ba4e777bab6b4090c3ad9b26d` |
| `docs/product/multi-project/fixtures/hoh-loop/tests/test_links.py` | `4fb90f88091d486cb034f53e41c46f03508e06aedf4478068c7b4e950801dc2d` |
| `tools/hoh_loop.py` | `8b31c51338374f2a17751a1f614d82024a7329e69f13aa1e68ecd4cc277609a7` |
| `tools/hoh/__init__.py` | `0b95447b469c56520f69606b3e57114ac5605a4683ec27cfd4eb2866d643e707` |
| `tools/hoh/claude.py` | `60fb46370fae88bf16d4fbad2dfe593e6126a340fd7c1119702c1544160e66a7` |
| `tools/hoh/prompts/developer.md` | `8e13aa84b9ec2af0d150ddd932e6f30b91f23eb6be9567b759ef5c245cbce446` |
| `tools/hoh/prompts/planner.md` | `5cb41df1a5f6cfcf5b26b86f642f6283c3d5581a4409f93a923310cc6a46b3da` |
| `tools/hoh/prompts/qa.md` | `db078a57ee0a1d4da87e8c49edb85a09db0370cd3ee5514b85ab0a44cf006943` |
| `tools/hoh/protocol.py` | `6d033539874c84ab95155c9a052b5d73a41c434085db34754f83e870ae7b0ed2` |
| `tools/hoh/workflow.py` | `9dfeceab1ee4ce5333efc0c2fb4716d9c9a73c95ca66a7e8c840ee55effa4420` |
| `tools/tests/hoh_fault_probe.py` | `4c677ec8682052cff65f1370fd9efa6be7810ef34dc92a8470cd1716047ebf4a` |
| `tools/tests/test_hoh_loop.py` | `b12115e8159b936dd767e648798a57671adf2aec693199a491921bb5e857c9b6` |

## Evidence and cleanup

The private logical artifact `full-evidence.zip` owns final source bundles,
commands, inspection, full logs, and final author/reviewer test trees. Its
manifest and restoration proof record entry hashes. The archive contains 90
entries and 3,667,287 bytes, with SHA-256
`fe2b0b567c4f4bd2d1e3ca841bdd038504a781be0143fdc9fa41d32e28ef2d18`.
Its manifest SHA-256 is
`4e858731c0cf8113a2de2b066b73f62e909db01888e2ba5741b815abed981297`.
Every restored entry matched its size and hash. The final independent review
record SHA-256 is
`133da658745e8d887aa7f15be5ac0b608ffc9482faa7c61674dd5e270068eeb2`. The existing private
cleanup receipt owns exact container IDs, paths, removals, and retained files.
Cleanup follows the owner's exact task-resource authority after verified export.
Earlier failed attempts and clock investigations remain historical evidence.
their old inventories do not describe current resources.

The [20d receipt](20d-process-environment-maintenance.md) owns environment repair
and dependency/build results. This receipt replaces the older clock-held status.
Git history and verified private exports retain those earlier observations.

## Remaining boundary

Packet 20c is complete. [20a](../packets/20a-headless-loop-proof.md) still needs
a verified whole-invocation input-plus-output token bound before its live Claude
proof. Offline routing does not prove native session enforcement, credential
isolation, provider behavior, live usage, factory activation, or a product release.
No following packet, publication, push, or merge is part of this acceptance.
