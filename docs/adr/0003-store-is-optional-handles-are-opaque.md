---
status: proposed
---

# Lineage is derived from run records, not from the store's structure

A run records what it consumed, what it produced and its parameters, and the dependency graph is derived from those records. The store is only where the arrays and the records land: Icechunk is one such place, a directory of zarr arrays beside a log file is another. This matters because the store's own history cannot carry the graph anyway: Icechunk snapshots have one parent each, so they cannot express a run with two inputs, and their order records when runs happened rather than what depended on what.

## Considered Options

- **Graph as Icechunk branches and ancestry.** Rejected: cannot represent joins, conflates time order with dependency, and ties the model to one storage engine.
- **A separate mutable graph document kept in the store.** Rejected: a second writer for the same fact, and an old record cannot be edited to repair it.

## Consequences

- Staleness is derived from the run records rather than stored. An edit, and the acceptance of an edit, are appended as their own records, so the store stays append-only.
- The recipe is exported separately and carries no data handles, so it does not depend on the store at all.
- A handle is an opaque string issued by the store. Nothing outside the store parses one, so swapping the store changes no other code.
