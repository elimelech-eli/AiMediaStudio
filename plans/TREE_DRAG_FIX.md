# Project tree drag/drop fix — 2026-10-22

The user reported image/video moves between projects failing. Internal moves now use pointer capture on the item name, with a six-pixel drag threshold, source feedback and valid-destination outlines. Native HTML dragging from the name button was unreliable in live browser testing. External file drops still use the existing import route.

Project containers and expanded collections accept drops, including empty space and child rows. Matching collection type, writable destination, different project and movable selection are checked. Ctrl on release requests copy; regular drop moves. Saved voice profiles, unfinished generation records, Trash and archived sources remain excluded. Existing backend dependency, context/snapshot and active-job protections remain authoritative.

Tree rebuilds are deferred while the pointer is held, during drag, and throughout the transfer. The destination project and relevant collections expand after success. A native HTML dialog replaces browser confirm for the transfer summary, including required references. Active work is preserved unless it is itself the moved asset, in which case the existing follow-item behavior applies.

Review: source/name-button handling, pointer capture and cancellation, nested drop propagation, mismatched types, multi-selection filtering, in-flight refreshes, copy/move payloads, immutable supporting references, destination expansion and no engine restarts.

Verification: all 41 JavaScript tests passed, including six new drag/transfer regressions. Actual pointer drags moved a tiny image into an expanded destination Images collection and a tiny CPU-encoded video onto the destination project heading. The destination tree and stored manifests confirmed both moves and absence from the source. The two exact-ID disposable projects were removed after verification. Evidence: maintenance/tree-drag-check.json. No user assets were moved/deleted, no worker restarted and no AI generation started. Existing tabs need a refresh to load the updated JavaScript; backend 41 already serves it.

Saved-voice exclusion superseded by backend 43: see SAVED_VOICE_TRANSFERS.md. Saved voices now use the same move/copy gesture, with retained internal references for recordings.
