# Phase 2 — app-wide adapter review

Reviewed changes across server request dispatch, all video helper functions, image Service callbacks, voice profile/request roots, chat ownership, worker thread entry points, HTTP serving and shared GPU admission. Existing tests plus adapter isolation tests pass (27 Python, 4 frontend regressions). Physical copy/verification is still running; deployment gate remains closed until its completion and post-copy checks.

Fixed during review:
- A thread-local context alone does not cover asynchronous image Service callbacks: capture the upload directory as an immutable local value when constructing Service.
- Holding the hub lock across chat inference would prevent project switches/status reads: use a short reservation/admission lock instead, released during inference.
- Independent project instances could admit competing GPU jobs: shared admission checks all instances and pending reservations.
- Idle image services in other projects could consume VRAM: release all idle image services at global admission after verifying no active job.
- Separate chat instances must not each start a server on the same port: share the model process while retaining separate history paths.
- A migration marker written before output indexing could claim completion too early: staged/complete states now block normal startup until publication completes.

Compatibility: legacy routes and default helpers remain available for the existing tests; live server scopes every request by an explicit workspace ID (default Free work) and captures worker scope. Original files remain intact. Media playback/join behavior is unchanged. Read-only baseline logs stay local.

Physical migration completed: 327 files copied/verified, 32 completed-media/reference assets indexed, all 3 shared voice profiles retained. Live upgraded backend: version 10, Free work, 12 video job records; video/audio ranged reads both HTTP 206 with expected bytes. Original studio-data remains intact. Phase 2 deployment gate passed; no GPU render was started for this gate.
