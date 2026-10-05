---
status: proposed
---

# Recipe files hold op IDs and JSON parameters, never importable callables

Sharing a recipe means opening files from other people, and a file that names `package.module:function` makes loading it an import of arbitrary code (the failure mode of napari-workflows' unsafe YAML loader). A recipe therefore stores only op IDs, JSON-only parameters and edges between steps; a registry built from installed packages resolves IDs to code, and an unknown ID loads as a placeholder that cannot run. Environment specs carried by a recipe are a separate, explicit user consent, not something loading performs.

## Consequences

- Ops must be registered (for example via entry points) to be replayable; an ad hoc `@op` in a script is not portable until it is.
- Parameters must be JSON-representable, so ops cannot take arbitrary Python objects as recipe parameters.
