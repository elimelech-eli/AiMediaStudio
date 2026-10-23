# Scene workspace UX — 2026-10-22

Backend 50 is active. The original user render was left untouched and completed before activation. No AI generation or model installation was run for this change.

## Layout and flows

The video workspace uses a stage containing the existing preview/progress/download/frame/continuation controls, with ordered scene beats beneath it. Existing Attach / join controls remain available under the beat list. A compact inspector replaces the long control column with Scene, Characters, References and Output tabs. Render controls and validation remain in its footer. Character cards collapse independently and show their speech-plan type when closed. Header/view selection share one row rather than consuming separate vertical space. The three existing workspace views and narrow-screen stacking remain supported.

Scene direction describes location, camera, atmosphere and global action. Up to three project characters each have their own action/script field and Speech: None / Text / Recording. Text plans have a project-scoped saved-voice selector, initialized from the character voice; recording plans select a project audio asset with playback. Up to 24 optional beats can be reordered, assigned to a character or the scene/camera, and removed. These are ordered prompt directions, not frame-accurate scheduling or independent rendered shots.

Drafts persist per workspace in the current browser profile and restore after refresh/navigation. Clear scene plan clears only the current direction/cast/beats; it does not delete character definitions or media. Submitted visual jobs capture a normalized scene snapshot. Definitions and references remain versioned through the existing character pipeline. Continuations can use captured characters even after their editable library definition is removed. Recorded speech/voice references are retained/remapped in transferred/exported captured recipes.

## Explicit implementation boundary

Action/script direction and ordered beats feed the video generator. Dialogue text and selected recordings are stored separately. No new speech synthesis, multi-speaker audio assembly or lip-sync engine is wired into scene rendering. The interface labels speech as planning, and both client and server require an explicit actions-only choice when a plan contains speech. Such previews are silent. Dialogue text is not silently inserted into the visual prompt or used as a fabricated backing track.

Existing first-frame/reference-image/video controls, identity options, model/length/quality/framing/seed/sound selection, pause/cancel, playback, output downloads, last-frame extraction, continuation and full-chain joining reuse their original nodes and handlers. No duplicate forms, players or global engine ownership were introduced. Archived scene controls remain read-only while inspector tabs remain navigable.

## Review and verification

Reviewed script order and wrapper composition, moved form ownership, unchanged media IDs/handlers, submission validation before uploads, immutable scene capture, project-scoped character/audio/voice references, export/transfer remapping, continuation snapshots, draft restoration, archived controls, keyboard tab navigation, responsive grids and progress/queue controls.

App-wide Python suite: 136 passed. After final storage/continuation changes, 32 focused scene/character/store/portable tests passed. Final frontend suite: 49 passed. The isolated local preview blocked all AI/chat/model-worker operations; browser checks covered cast cards, Text and Recording selectors, audio playback control, beat editing, speech safeguard, refresh restoration, view switching and Output settings. The local capture API verified ordered actions and retained recording IDs. Live backend 50, HTML script registration and CSS response checked after the user render completed. No fresh GPU output-quality benchmark was performed.

Evidence: maintenance/scene-ui-check.json and maintenance/scene-workspace.png. maintenance/scene-ui-preview.py is an isolated reproducible UI fixture, not a user workspace or alternate production launcher.
