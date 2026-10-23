# Phase 6 — app-wide model-manager and final integration review

Implementation/review gate passed: 44 Python tests, 5 JavaScript regressions, and real Electron checks for all three layouts, project isolation, engine/chat drafts, unsaved context-draft restoration and presence of model settings. Current backend version: 14. The migration now includes one project-owned legacy reference explicitly required by an old recipe (33 indexed Free work assets); it does not impose any Lexi preset on generic projects.

Reviewed the full app: HTTP routing/authentication and byte ranges, project lifecycle, SQLite/manifests/recovery, video/image callbacks, audio/voice profiles and transcripts, local chat worker, project inputs/context, copy/move/branch/export/import, model selection/download/import, UI state/polling, launchers and resource admission.

Model-manager scope: one existing validated video profile and one existing validated image pack; selectable supported voice/writing variants. Optional downloads: official pinned Hermes Q5_K_M and official Qwen Base 1.7B. Exact official GGUF import is supported; arbitrary architectures or executable model repositories are not accepted. Compatibility is not a benchmark claim. Existing model weights remain selected; no additional weights were downloaded during validation.

Verified a real official Hermes Q5 manifest preflight (revision 307a5dfb59aa38d88b6cfd32f44b8ad7c1da9fb8, 5,732,987,008 bytes). Download integrity/cancellation tests use tiny offline fixtures. Supported catalog sources: https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B-GGUF and https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base.

Findings fixed in the final app-wide pass:
- Terminal download status could precede closing its status file on Windows: workers are tracked until termination; switches/cleanup cannot race finalization.
- A model published immediately before a crash can lose its registry entry: recover its verified manifest and require checksum verification before activation. Model removal is journaled.
- Uploads were visible to catalog scans while still writing: uploads now stage as .partial, validate where applicable and publish atomically. Upload/model-import owners are pinned against project deletion.
- Library polling recreated every preview and reset unsaved context: stable signatures avoid unnecessary rebuilding; dirty context retains its edit revision and survives workspace switches.
- Moving a chain could leave source history advertising a removed full-chain file: reconcile chain metadata after removal.
- Audio-chain assets originally retained only the last segment's transcript: full-chain transcript now travels with the chain asset.
- Continuation after copying a guided clip needs remapped identity inputs: explicit input-role maps and required dependencies are copied/remapped.
- Narration may use a project-owned voice: transfers copy and remap its reference profile so deleting the source project cannot break same-voice continuation.
- Manual joining an imported compatibility job inherited an imported marker and skipped catalog publication: remove that marker from real joined outputs.

Live CPU integration passes: moved videos still support actual final-frame extraction, continuation preparation and normalized joining; imported audio is normalized and joined; moved voice references survive source project purge. API isolation, portable security and crash/cancel recovery tests pass.

GPU validation limit: external local LLM/Python processes subsequently occupied about 6.2 GiB of the 8 GiB GPU. The neutral live image/voice/video/chat check stopped before starting any generation. No external process was stopped. Fresh GPU generation in the upgraded project pipeline remains an explicit follow-up gate when resources are free; existing prior engine tests are not misrepresented as new project-pipeline tests. The empty disposable GPU-check project was removed.

Final resource review: Hermes stop now waits for its owned worker to close (bounded five seconds) before acknowledging unload, reducing the race where media admission checked VRAM before the old model released it. External processes are never targeted.

Final concurrency/compatibility review addendum: all 44 Python and 5 JavaScript checks pass. A shared chat ownership guard prevents another project's Unload action consuming an in-flight reply. Asset publication merges only its derived records into the latest manifest, preserving concurrent context edits, snapshots, trash and tombstones. Dedicated tests cover that race. Soft-trashing a full chain sets an explicit false flag; legacy chains without flags remain compatible, while continuations no longer silently reuse trashed full-chain files. Asset purge/move cleans owned compatibility aliases so catalog rescans cannot resurrect them. Final source deployed as version 14; original data and external workloads remain untouched.
