# Phase 3 — app-wide project/library review

Gate passed: 28 Python tests, 4 JavaScript regressions and real Electron checks for all three layouts. HTTP integration tests use disposable workspaces and exercise create/copy, workspace isolation, asset byte-range playback, trash/restore and lifecycle protections. No user media was removed by verification.

Reviewed project selector/drafts, library actions, media URL routing, async refresh/chat callbacks, shared profiles, worker admission, HTTP auth, old Recent controls, deletion behavior and launcher.

Fixed: media URLs now capture workspace in playback/download queries; stale state responses cannot repaint another workspace; upload submission blocks workspace switching until its input sequence is complete; chat completion cannot clear a different workspace's draft; copy/move dialogs are server-scoped; asset tombstones prevent old output rescans recreating moved/purged assets; snapshot-pinned assets cannot be moved; Free work cannot be archived/deleted. Missing primary outputs no longer show as playable completed video rows.

Recent deletion now moves its indexed outputs to asset trash rather than irreversibly deleting a whole job. Restoring an output restores its history visibility. Shared voice profiles remain independent of project deletion. Completed engine outputs remain distinct from supporting job diagnostics.

Remaining planned work: shared-context injection/proposal validation (phase 4), dependency-closure copying and snapshots/branch/export (phase 5), model settings (phase 6). A project deletion is reversible metadata trash at this stage; no hidden permanent project purge has been exposed.
