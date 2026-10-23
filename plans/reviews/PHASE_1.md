# Phase 1 — app-wide storage-core review

Gate passed: 25 Python tests and 4 existing frontend regressions. Existing app routes/workers are not yet switched to the new storage layer. Reviewed the storage module against HTTP, frontend, existing engine adapters, resource admission, deletion and legacy schemas.

Fixed during review/testing:
- SQLite context managers do not close connections: explicit closing now prevents Windows catalog file locks.
- Move recovery originally retained a temporary destination record: preserve the temporary ID before replacing it with the stable moved ID. Fault-injection tests now pass after publication and catalog cutover.
- Replaying a completed import could overwrite later edits: completed operation IDs return the existing record instead.
- Operation IDs cannot be reused with different source content; scoped asset lookup rejects cross-workspace IDs.

Other verified boundaries: immutable media copies, original external files retained, required-dependency deletion refusal, snapshot-held purge refusal, context revision conflicts, Free work protection, path containment, rebuildable SQLite index and startup import/move recovery. No network/model inference added. No live data migrated.

Intentional implementation refinement: trash is an explicit manifest state while immutable file paths remain stable, rather than moving bytes immediately. This preserves snapshot references and avoids locked-file rename failures. Purge is separate. UI must accurately report retained space. Dependencies requiring graph copying are rejected until the later dependency-copy stage; no silent incomplete copies.
