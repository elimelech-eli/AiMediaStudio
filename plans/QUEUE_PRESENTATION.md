# Job queue presentation — 2026-10-21

Compact rows replace large job cards. The active row shows the engine stage, progress (indeterminate when unavailable), and an elapsed timer updated each second. Finished durations stay fixed; pending jobs show position rather than a generation timer. Project/model metadata and existing reorder, cancel, retry, dismiss and open-output controls remain.

Video stages use the same local log reader as the work screen. The frontend supports the currently running version 38 backend via an owner-scoped work-state read, so an active render need not be restarted. Version 39 carries live stage/progress/elapsed directly in the queue API and loads on the next idle launcher restart.

Verification: 11 queue Python tests and 33 JavaScript tests passed. No generation started or cancelled. Browser preview could not attach in this session, so visual inspection in the running browser remains unverified.
