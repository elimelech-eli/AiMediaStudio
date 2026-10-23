# Project tree implementation — 2026-10-17

## Phase 1 — Data and lifecycle

Named conversations live in workspace manifests with independent message histories and local drafts. Existing single-chat history is imported once. Branches and portable exports include all non-deleted named chats when conversation inclusion is enabled. Historical media proposals keep their ownership guards; copying a conversation does not authorize an old proposal against unrelated destination assets.

Archive creates and verifies a portable ZIP before making the original project read-only. Optional reclamation removes only checksum-matching active media paths and compatibility aliases. It retains the ZIP, manifests, conversations, saved voice profiles, snapshots and trash. Restoration verifies and restores media before enabling work. Previewing a reclaimed archived asset restores that individual file. Separate exports and the original pre-migration backup are retained.

App-wide self-review: checked existing engine admission, immutable asset publication, snapshots, ZIP imports, voice references, shared local chat process and workspace isolation. Fixed named-chat admission/pinning, archive upload rejection, checksum validation and portable named-chat schema validation. Initial backend phase checks passed (12 focused checks; app-wide suite subsequently passed).

## Phase 2 — Navigation and interaction

The project tree is independent from the active work owner. Projects/collections expand in place. Asset/chat selection opens the matching interface. Collection plus buttons offer generation/import; chat plus opens a native naming dialog. Project creation leaves current work open.

Asset/chat menus provide rename, duplicate and deletion to trash. Asset menus retain reference use, continuation, final-frame capture, download and joining where applicable. Project menus provide rename, deletion with counts, branch including chats, verified ZIP export, archive, snapshots and context. Archived projects have restore/export/delete/reclaim actions. Free work is protected.

Drag/drop moves to another project; Ctrl-drag copies. Required asset dependencies and estimated transfer sizes are explained before submission. Mixed assets/chats are transferred sequentially; each successful transfer is retained if a later transfer fails. Multi-selection, search, F2 rename and Delete-to-trash are available. Failed/running jobs remain visible in their collection. Running jobs can be canceled; failed records can be hidden. Existing media chaining remains in each tool.

App-wide self-review: checked all three layouts, form identity, uploads, context revisions, playback, model settings and existing engine helpers. Fixed the old Director layout's automatic legacy chat dock, removed whole Recents columns, replaced unsupported Electron prompt dialogs, scoped named-chat responses/drafts, guarded pending jobs and preserved file extensions on downloads. Visual verification also caught and fixed a tree-selection helper shadowing the video engine selection variable; native coverage now includes starting a fresh video. Fixed startup restoration racing with an already opened item, and background completion publication when browsing another project. Opening or moving a current item follows its ownership; browsing and unrelated organization leave it open.

## Phase 3 — Integration and validation

- 50 Python checks pass, including real CPU media joining/frame extraction, scoped HTTP requests, independent conversations, branch/ZIP round trips, archive reclaim/restore and damaged-archive rejection.
- 5 JavaScript runtime/media checks pass.
- Native Electron checks cover all three layouts, workspace drafts/context, project isolation, independent tree browsing, named-chat drafts, context menus, duplicate via the in-app name dialog, drag/drop and removal of Recents/navigation.
- No GPU inference or model download was needed for this interface change.

Reviews are local code self-reviews, not independent reviewer certification. No guarantee that automated checks cover every interactive edge case. Browser/desktop drafts remain local to their respective client profile. Archive restoration requires free disk space. Linked dependencies/context/snapshots can block a move or permanent deletion; copying remains available. Project ZIPs exclude model weights.
