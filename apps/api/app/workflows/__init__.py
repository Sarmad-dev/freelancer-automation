"""The workflow engine (MVP Prompt 11): definition, catalogue, validator, executors, queue and events.

Execution is a backend concern. A workflow is a versioned graph of typed nodes; a run walks one version of it, one
step at a time, recording every step durably, pausing for people (approvals) and time (delays) without holding a
request open or an in-memory timer, and resuming from the database. See docs/WORKFLOWS.md.
"""
