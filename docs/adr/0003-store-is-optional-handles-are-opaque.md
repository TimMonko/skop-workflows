---
status: proposed
---

# The store is optional; handles are opaque

Where arrays and records land is a choice, not a commitment. The recorder and
everything above it speak only in **handles**: opaque strings the store issues
when it takes an array, which nothing outside the store may parse. A store
answers a small fixed set of questions — take an array, return an array,
recognise an array it already has, append a record, list the records — and
describes what a handle refers to. The first store is deliberately plain: a
directory of `.npy` files beside a JSON Lines log, needing nothing but numpy.
Icechunk is the second backend, chosen for atomic commits, tags, garbage
collection and sharing over S3.

For Icechunk to earn its place, the protocol must let a run land in one
piece: the outputs and the run record committed together, not one snapshot
per array. The plain store can implement that shape trivially, so it is
settled now, while only one backend exists.

## Consequences

- Swapping the store changes no file above `store.py`; a recipe contains no
  handle, so it is portable between stores.
- `Store.describe(handle)` names a handle — root name, ndim, dtype — and
  `export` uses it; no caller splits a handle string.
- Handle identity for in-memory arrays is the store's record of what it has
  seen; mutating an array in place breaks it, which is what the edited mark
  exists for.
