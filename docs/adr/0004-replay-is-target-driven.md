---
status: proposed
---

# Replay is driven by an explicit target set

What a run should return is a decision made when replaying or exporting, not a mark kept in the log. A target is a step whose output the caller asked for; replay runs the backward closure of the targets at their current runs and nothing else, so "return these" and "only run what is needed" are the same rule. The default target set is the graph's leaves and any intermediate may be named instead. Export writes the closure of the chosen targets, which keeps abandoned branches out of the file while keeping every intermediate available to be named as a target later.

## Considered Options

- **A keep mark stored in the log.** Rejected: it is selection state in an append-only log, it has no home that survives a store change, and it must be maintained even when only one answer is wanted.
- **The recipe is the whole session.** Rejected: an explored and abandoned branch travels to a colleague.
- **An exclusion set, with everything else included.** Rejected: the same state problem, with the subtraction of a gesture.

## Consequences

- Nothing in the log says which output is the point. A published workflow's intent therefore lives in the exported file as a default target set, and code should never infer it from what a host happens to be showing.
- Deleting a layer in napari excludes nothing; it only stops that host drawing the step.
