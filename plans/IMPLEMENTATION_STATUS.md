# Implementation status

- Phase 0: implemented and reviewed; reviews/PHASE_0.md.
- Phase 1: implemented and reviewed; reviews/PHASE_1.md.
- Phase 2: implemented and reviewed; reviews/PHASE_2.md.
- Phase 3: implemented and reviewed; reviews/PHASE_3.md.
- Phase 4: implemented and reviewed; reviews/PHASE_4.md.
- Phase 5: implemented and reviewed; reviews/PHASE_5.md.
- Phase 6: supported-model milestone implemented and reviewed; reviews/PHASE_6.md.

Final verification: 44 Python tests, 5 frontend regressions and native desktop project/view/draft checks pass. Real CPU frame/continuation preparation/video/audio join checks pass. Official alternative-model manifest lookup passes; no new weights downloaded.

Remaining validation: fresh GPU image, voice, video and chat inference through project adapters. An external workload used about 6.2 GiB VRAM; the live check stopped before generation and did not interrupt it. Evidence: maintenance/project-integration.json.

Migrated data is live in media-workspaces/free-work; original studio-data retained as a pre-migration backup. A project-owned copy of a legacy reference is included only because old recipes explicitly used it. Model management is adapter-specific: video/image retain their current compatible profiles, while voice/writing expose supported alternatives. Arbitrary architectures need further adapters.

Workspace drafts currently persist in the current browser/desktop profile; committed context, conversations, media and snapshots live in project folders. Exports contain committed project data and optionally captured conversation history, not unsent browser drafts or model weights.


Project-tree UX follow-up: implemented 2026-10-17; see [project tree implementation and phased reviews](PROJECT_TREE_IMPLEMENTATION.md). Backend 17 adds independent navigation, named conversations, context menus, drag/drop, native name dialogs and verified archive/reclaim/restore.


2026-10-21: backend 41 implements disk checkpoints and Pause/Continue/STP controls across queue, tree and work screens; see DISK_CHECKPOINT_PAUSE_RESUME.md. 104 app-wide Python and 35 frontend checks passed, plus the added child-exit lifecycle check. Image/video/voice GPU pause/resume remains unvalidated while the user's render is active. Video pause boundaries are stage-level, not per sampling step. Activated backend 41 after the user render completed; API and browser inspection passed.

2026-10-22: backend 46 adds generic project Characters, versioned identity/outfit/behavior/voice context, automatic prompt resolution and continuation/reference inheritance. See PROJECT_CHARACTERS.md for validation and engine limits. User render preserved; no new GPU media generation.
Activation note: live backend 45 passed UI/API verification. A new user render began before final build 46 activation; it was preserved. The next idle launcher activation loads build 46.

2026-10-22: backend 48 active: up to 10 free-text-described character images, direct/batch uploads, general untagged guidance, automatic capacity fitting, manual reference selection and CPU preview. Legacy references preserved; descriptions and chosen IDs survive continuation and project operations. Full 126 Python tests + 45 frontend checks passed, followed by 17 focused character checks and live UI/API upload verification. No new GPU render. See PROJECT_CHARACTERS.md.

2026-10-22: backend 49 active: requested action emphasized separately from reference/body-language context; new clip Silent / Generated sound control, Silent default on new requests. Audio stripped before publication via video stream copy; captured legacy jobs retain previous behavior. 131 Python + 45 frontend tests passed, plus three final targeted checks. No new AI render. See VIDEO_ACTION_AUDIO_FIX.md.

2026-10-22: backend 50 active after user render completed: video scene workspace with compact tabbed inspector, collapsible per-character action/speech-plan cards, ordered beats below the preview, workspace draft restoration and captured scene recipes. Existing media controls retained. Speech assembly/lip-sync explicitly not connected; actions-only generation requires acknowledgment when speech is planned. 136 Python + 32 final targeted + 49 frontend checks passed; isolated browser/API review completed. See SCENE_WORKSPACE.md.


## Backend 51 — completed-output reference deletion
Completed asset dependency edges no longer block individual/bulk trash. Purge records omitted inputs and removes their required edges; publication excludes tombstoned inputs, and transfer skips trashed dependencies. Finished recording recipes no longer block saved-voice purge; portable branching skips absent historical voices. Explicit project context, character library, snapshot and active/paused workspace protections remain. No user data deleted. Nineteen targeted store/audio/portable/scene tests pass. Activation deferred because production backend 50 has active user work; safe launcher minimum is 51.


## Backend 52 — native character audio
Character speech dropdown supports native video generator audio with optional dialogue/delivery direction. Scene capture compiles native speech instructions and forces generated sound; video wrapper no longer contradicts them with no-dialogue direction. Text/Recording plans retain the silent-only limitation and mixed modes reject before upload/queue. No saved-voice binding or exact-word guarantee. Five frontend scene tests pass; no AI render run. Production activation deferred while the user render is active.
