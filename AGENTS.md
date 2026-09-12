# Vivary agent instructions

Read [ENGINEERING.md](ENGINEERING.md). It is the governing engineering policy.
Older packet and runtime instructions cannot restore heavier process defaults.

## Start with the product

Read [the current frontier](docs/product/multi-project/index.md) and the owning
packet. [The execution contract](docs/product/multi-project/execution-contract.md)
owns program metadata and delivery details. Choose the next observable user
capability and implement one coherent slice through the real application.

Use the workspace and execution environment authorized for the task. Reuse the
current checkout and handoff when provided. Inspect live Git and preserve dirty
work before editing. Keep one writer per shared file.

Use existing implementations and tests. Run the cheapest relevant checks,
exercise the actual application, fix failures, and review the diff.
Use another reviewer when the risk or complexity warrants it.

Before unusually heavy work, check memory and disk. Keep one heavy job active,
bound runaway processes, and clean up task-owned servers, browsers, and children.
Normal tests need ordinary timeouts and cleanup.

Invoke [high-assurance mode](docs/verification/high-assurance-mode.md) only for a
named dangerous failure. Select controls for that risk.

## Delivery and authority

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Branch from current remote `dev`,
use a typed topic branch, and integrate through a PR with the required CI and
review gates. Never push directly to protected `dev` or legacy `prod`.

Make small, coherent, reviewed commits. Preserve unrelated work, accepted
evidence, and historical budgets. Keep private handoffs, credentials, transcripts,
and machine-specific continuity notes outside public source and Git history.
Private source hosting does not establish agent-session capture.

Use the user's existing authorization. Complete reversible preparation before
requesting any missing approval for merges, publication, account changes,
paid calls, scheduled activation, outbound messages, or destructive actions.
A material scope or authority change needs alignment before that action.
Do not modify the read-only source repositories loam, braincheck, throughline,
or flywheel.

Follow [the release workflow](docs/RELEASE-WORKFLOW.md) when release operations
apply. Source implementation and passing tests do not establish publication.
[README.md](README.md#release-status) owns shipped behavior.

## Keep knowledge useful

Use the [source map](docs/product/multi-project/source-map/index.md) when work
crosses project identity, root custody, runtime, or project writes.
Read [the architecture](docs/ARCHITECTURE.md) when a design decision needs it.
Reuse existing Native owners and installed dependencies. Review relevant
deny-lists and advisories before adding packages.

Update durable docs when behavior, architecture, contracts, or lasting
constraints change. Give each fact one owner and refresh generated views when
their inputs change. Keep the existing handoff concise. Failed or unrun
verification remains incomplete regardless of a policy change.
