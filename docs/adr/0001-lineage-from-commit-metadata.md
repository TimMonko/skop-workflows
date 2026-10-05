---
status: proposed
---

# Lineage is derived from run records, not from the store's structure

A run records what it consumed, what it produced and its parameters, and the graph is derived from those records. The store is only where the arrays and the records land, and its own history cannot carry the graph: Icechunk snapshots have one parent each, so they cannot express a run with two inputs, and their order records when runs happened rather than what depended on what. We own the record schema and the graph derivation; Icechunk is one store among others. See [ADR 0003](0003-store-is-optional-handles-are-opaque.md).

## Considered Options

- **Graph as icechunk branches and ancestry.** Rejected: cannot represent joins, conflates time order with dependency, and ties the recipe to a storage engine.
- **A separate mutable graph document kept in the repo.** Rejected: a second writer for the same fact, and old commit metadata cannot be edited to repair it.

## Consequences

- Staleness is derived from the run records. An edit, and the acceptance of an edit, are appended as their own records, so the store stays append-only.
- The recipe is exported separately and carries no data handles, so it does not depend on the store at all.
