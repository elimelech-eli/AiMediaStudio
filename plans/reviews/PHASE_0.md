# Phase 0 — app-wide baseline review

Completed 2026-10-17. Self-review across HTTP/backend, video/image adapters, voice worker/profile storage, chat worker, frontend scripts, Electron launcher and existing tests. The available Code Review connector only reads remote PR CI; there is no local repository PR to submit to it, so reviews here are explicit local code reviews, not claimed independent reviews.

Baseline: 336 user-data files, 4,830,585,831 logical bytes, checksum inventory and app-source copy under maintenance/project-baseline. 21 Python and 4 JavaScript tests pass.

Findings addressed in subsequent-phase design: all legacy records must be inventoried beyond Recent limits; global roots must become request/worker-local without mutation; global GPU admission must remain shared across project instances; voice IDs and materialized chains require compatibility routes; image Service upload callback must be fixed per workspace; model process must remain shared while chat histories are scoped. No baseline application changes. Phase 0 gate passed.
