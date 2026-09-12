---
project: Vivary
status: active
module_area: bounded checkout observation
contract_refs: [root-observation-contract]
source_refs: [checkout-observer-code]
test_refs: [checkout-observer-tests]
evidence_refs: [observation-receipt]
---

# Root observation

## Outcome ownership

Outcome [12](../../../tickets/12-implement-vcs-identity-adapters.md) owns VCS
observation and mutation-owner adapters. Packet 12a established the contract.
[Packet 12h](../../../packets/12h-core-root-custody-integration.md) integrates the
Linux application custody modules and their focused tests.

## Caller-visible contract and errors

Given an explicit allowlist of roots, observation returns normalized checkout facts
and preserves per-root failures as observations. A caller can distinguish an absent,
inaccessible, invalid, or non-repository root without losing successful siblings.

## Hidden concerns

The existing checkout graph uses path and topology identities. The application
custody modules instead hold Linux filesystem descriptors and revalidate folder
and Git administration continuity. Application identity records are durable;
verification remains tied to the owning process. Neither path grants write authority.

## Dependencies

This module supplies observed identities to the [project registry](../project-registry/index.md).
Its contract, Core implementation, focused tests, and accepted receipt are linked as
typed graph edges.

## Gaps

Core now contains the read-only Linux custody implementation described in the
[Core README](../../../../../../packages/core/README.md#project-root-custody-unreleased).
Usable root recovery after restart, cross-process mutation fencing, Jujutsu,
Windows custody, and supported persistent deployment storage remain open.
