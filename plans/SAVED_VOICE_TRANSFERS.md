# Saved voice drag transfers — 2026-10-22

Backend 43 supports saved voice move/copy via the same pointer drag flow as images, videos, recordings, documents and chats. Drop on a project, Audio parent or matching Saved voices collection. Ctrl requests copy. Destination Audio/Saved voices expands after success. Active saved-voice work follows the mapped destination ID.

Voice transfers use /api/voices/action with copy/move, captured source ownership and destination ID. Both projects are checked for active/pending/paused work and file-operation locks. IDs, reference WAV hashes, containment and metadata are verified. Copy creates a new ID; move preserves the ID when available and avoids destination collisions. The operation journal can finish an interrupted verified copy on restart. Unresolved recovery retains source data, locks the affected projects and reports diagnostics instead of stopping Studio startup.

Source references remain on disk for existing recordings, continuation and snapshots. A library_hidden flag removes a moved source profile from Saved voices and its dropdown, while valid internal references still work. Retained profile IDs permit same-voice recording continuation without making those profiles visible as saved voices. A moved preferred voice is cleared from source project context. Original/shared Lexi voice files are untouched.

Review covered backend admission, dependencies, file publication before hiding source, journal recovery, hash verification, collisions, context cleanup, retained narration references, UI grouping and source/destination scope. Mixed asset/chat/voice batches retain the existing sequential transfer semantics.

Validation: 110 Python tests and 42 frontend tests passed; the five focused voice-transfer tests were rerun after the recovery safeguard. A browser pointer drag moved a disposable saved voice into a different project's Saved voices collection, verified against the live tree. Only exact-ID disposable fixture projects were removed. Backend 43 activated while Studio was idle. Evidence: maintenance/voice-drag-check.json. No AI generation was needed.
