# FreeVideo Studio

Completed media no longer prevents deleting its reference inputs (including saved voices used by recordings). Single and bulk deletion preserve finished output files. Permanently removed inputs are unavailable for exact recreation; transfers skip deleted references. Active/queued/paused work remains protected, as do references explicitly retained by project context, character definitions or snapshots. Backend 51 activates on a safe relaunch.

**Native character audio:** choose Native video generator audio in a character speech dropdown. Optional dialogue/vocal direction is sent to the video model, and generated sound is enabled automatically. Exact wording, voice identity and speaker assignment are not guaranteed; saved voices are not applied. Native audio cannot currently be mixed with unrendered Text/Recording plans in the same scene.

**Video scene workspace:** use the Scene / Characters / References / Output inspector tabs. Character cards separate physical actions from Text or Recording speech plans; optional ordered beats sit below the preview. Actions and beats guide video generation. Voice assembly/lip-sync is not connected yet: speech plans are retained, and you must explicitly choose a silent actions-only render when a scene contains planned speech. Drafts restore in the same browser profile; submitted jobs capture scene snapshots. See [scene workspace workflow and validation](../plans/SCENE_WORKSPACE.md).

**New clip output sound:** Silent is the default for new requests and removes generated audio without re-encoding the video. Choose Generated sound to retain engine audio, which can include invented speech. Existing joined segments keep their original audio. Character references guide identity; the requested scene/action is emphasized separately, but action adherence is not guaranteed.

Project-wide **Characters** are available from the project tree. Upload/select up to 10 reference images per character, each with optional free-text descriptions/tags. Preview or manually select the subset used within each engine’s capacity. Set behavior instructions, outfits/current state and saved narration voices, then use **Project characters & continuity** in the work interface. Names/aliases resolve automatically; continuations keep captured character versions. See [character workflow and limits](../plans/PROJECT_CHARACTERS.md). Identity guidance improves conditioning but cannot guarantee identical output.

Duration choices now include approximately 10, 15 and 30 seconds, in addition to 3, 5 and 8. Longer settings are available for user experimentation and have not been rendered or benchmarked here. Relaunch after any active generation finishes to activate an older running server's update; the launcher preserves active jobs.

Double-click `D:\LEXI_App\Start-FreeVideo-Studio.cmd`. The small local server opens `http://127.0.0.1:57846/` in your browser. No ComfyUI server, new model download, new Python environment or frontend package installation is needed.

Enter a prompt, optionally select **Use Lexi.png** or a local image, and optionally add a video reference. Choose duration, framing and High or Light, then Generate. High is the setting used for the approved trials; Light is the engine's two-pass preview setting and has not been visually benchmarked here. The engine may fetch official supporting data when a new preset needs it. References are processed locally.

An image alone supplies the starting frame. When a video is supplied, image/video inputs become guidance references; they do not guarantee copied motion or an exact starting frame. Duration rounds up to supported frame counts. Eight seconds is exactly 192 frames; shorter selections may be slightly longer than their labels. For consistent identity, describe her face, clothing and camera framing in the prompt.

One Studio job runs at a time. FreeVideo's own lock also prevents conflicting managed-engine jobs. Generation can take tens of minutes on this GPU. Other GPU-heavy tools/games compete for memory and time; this launcher does not stop them automatically.

Closing the tab leaves the local server and generation running. Reopening the launcher returns to the same history. Cancel stops only the Studio-owned render process tree; partial files/logs remain for diagnosis. Avoid terminating the server during a render. An unexpected server restart marks unfinished records interrupted; it does not resume generation automatically.

Outputs, job metadata and logs: `freevideo-trial/studio-data/jobs/<job-id>/`. Uploaded references: `freevideo-trial/studio-data/uploads/`. Upload limits: 32 MiB per image, 256 MiB per video. These files remain local and are retained; the tool does not automatically delete your references or results. The approved framing-trial entry uses a hard link to its existing video, avoiding a duplicate data allocation.

Implementation: standard-library Python HTTP server and plain HTML/JavaScript. Bound only to 127.0.0.1, with strict Host/Origin checks and a per-process mutation token; no external frontend assets or exposed LAN endpoint. The existing managed FreeVideo engine handles actual inference. App chat/gesture backend remains unchanged.

Verification: seven automated tests cover media/keyframe schema, validation and traversal rejection, single-job admission, cancellation targeting, terminal job status/errors, progress, an actual lightweight worker lifecycle, local HTTP upload/authentication, and ranged playback. Browser review confirmed the Lexi shortcut, saved history, layout and existing MP4 preview. No additional full GPU render was started solely to test this UI; the underlying engine's prior successful renders remain the inference evidence.

Run tests:

```powershell
Set-Location D:\LEXI_App
& .\video-engine\.venv\Scripts\python.exe -m unittest discover -s freevideo-trial -p test_studio.py -v
```

## Continue from last frame
Select a completed creation and click Continue from last frame. Enter the next action, select how much time to add, and Generate video. The source resolution is preserved, other references are cleared, and a fresh seed is selected unless entered. Clear beside Starting image exits continuation mode.
The server extracts the actual final decoded video frame into the new job and uses it as the image-to-video starting reference. Original clips remain unchanged. Every successful continuation saves its own video.mp4; a joined combined.mp4 contains the prior chain plus the new segment, available through Download joined video. If joining fails, the new segment remains available and an error explains the failed join. Continue again from the newest segment to extend the chain further.
Everything stays local. Last-frame conditioning does not guarantee seamless motion, identity or audio continuity; longer chains can drift. No AI render was run for this feature check. Nine tests passed, including actual last-frame extraction, three-clip joining, source validation/inherited framing and authenticated HTTP/range downloads.


## Image studio — Qwen Image 2.1 Turbo
The optional 16.1 GiB image pack is installed under runtime/models/vdn/image_gen and was verified by FreeVideo's hash-pinned installer. Choose Image studio for text-to-image or upload one to four references. Files are labelled image 1–4 in upload order; describe which background, characters and placement each should supply. No references means prompt-only generation. Composition is generative, not a guaranteed pixel-perfect cut-and-paste.
Image results have Download image and Use for video. The latter selects the PNG as the video starting image, clears previous video references/continuation state, and lets you enter the motion prompt before rendering. Images and videos share a single-job gate; the image worker releases its model before a video starts and idles out after 30 seconds. Other applications' GPU workers are never terminated.
Image outputs and history stay in studio-data; uploaded references and reusable output PNGs stay in studio-data/uploads. Model-install progress is shown in the Image studio panel. Ten tests cover existing video behavior, image reference validation, single-job isolation, image downloads and image-to-video preparation. Actual GPU validation is recorded separately below.


Live GPU validation passed (2026-10-17): prompt-only 512x512 green teapot completed in 230 seconds including cold load; two-reference 512x512 composition completed in 251 seconds and visually preserved the green teapot while adopting the second reference's blue wall and beige table. Results were inspected. Image-to-video preparation passed the pipeline test; no extra video render was started. These two measured durations are examples, not performance guarantees.


## Frame capture, manual attachment and consistency (2026-10-17)
Select a completed video and Capture last frame. Download the PNG or Use frame as starting image for an independently generated clip. Capture reads the final three seconds instead of buffering a whole long chain.
Attach / join videos lets you choose an existing Studio base (its whole chain, if present) and a segment to append, or upload either video. Joining creates a new history item, preserves originals, fits mismatched aspect ratios into the base dimensions, normalizes to 24 FPS, re-encodes H.264 at CRF 18 and preserves audio as stereo AAC with silence where absent. This local CPU operation cannot be cancelled from the render button. Repeat with the joined result as base to extend it. Normal continuation auto-joining still uses stream copy.
Character consistency contains an appearance description, optional identity upload and approved Lexi preset. Continuing a clip inherits this profile. Default first-frame mode repeats the description while retaining the exact starting-frame conditioning layout. Optional identity image guidance switches to ref2va, using the starting image and fixed identity image as references. FreeVideo rejects simultaneous first-frame anchoring and reference-image layouts, so reference guidance cannot guarantee an exact first frame. These are prompt/conditioning improvements, not an anatomy lock; no new AI render was run to measure their visual effectiveness.
Twelve tests passed, including final-frame export, actual mixed-size/FPS joining with audio retained, chain handling, profile inheritance and validation with the engine's media parser. UI scripts and referenced controls were checked.


## Generic profiles and full-chain preview
Character-specific shortcuts have been removed from Studio. Consistency fields start empty and accept any character, subject or scene; references/descriptions inherit only from the selected chain. Existing saved profiles remain intact for compatibility.
Completed joined results now preview combined.mp4 by default. Continuation jobs offer Full joined chain / Individual segment. A manually assembled job already contains the whole assembly, so only the full-chain view is shown. When an attachment finishes, Studio selects it and refreshes the preview automatically. Individual segment and joined downloads remain separate. Two preview regression tests and twelve backend/media tests passed. Refresh existing browser tabs to load the new controls; no active render needs a restart.


## Standalone desktop launcher
Double-click D:\LEXI_App\FreeVideo Studio.lnk or Start-FreeVideo-Studio.cmd. Both open a dedicated FreeVideo Studio desktop window using the existing project Electron runtime; no extra runtime/model download is required. The app starts the existing Python backend directly with the project's configured environment if the local service is absent, or reconnects without restarting existing jobs. A second launch focuses the existing app window. Closing the window leaves the backend/render running; reopening returns to the same history. No ChatGPT or Codex session is required to launch it.
The app uses isolated, sandboxed web content without Node access, denies permission prompts and external navigation, and offers downloads with the default location studio-data/exports. Its runtime/session/log data remains in studio-data. The project folder and its existing runtimes must remain in place; this is a local desktop app launcher, not a separately bundled installer. Live cold-start and warm-connect window checks passed, with both image/video tabs and Node isolation verified in studio-data/desktop-check.json.


## Voice studio
Design a voice with a descriptive prompt and up to 600 characters of English audition text. Listen, give it a name and Save voice profile. Select a saved voice and paste up to 12,000 characters under Read a prepared script. Preview/download the resulting PCM WAV. Design uses existing local Qwen VoiceDesign; narration uses the existing smaller Base model with the saved audition as its reference. Original Lexi voice files/profile remain unchanged.
Delivery descriptions guide the audition; saved-profile narration follows reference prosody and punctuation, without guaranteed per-line emotion control. Long scripts are divided at sentence/word boundaries with short inter-section pauses; whole emoji sequences are omitted from spoken input. Voice jobs share the image/video gate, refuse a busy GPU, run offline, retain history/profiles, and support owned-worker cancellation. No AI script generator is included.
Live local tests passed: 5.76s designed audition in 107s including cold load, then saved-profile narration of different text produced 9.92s audio in 69s. WAV files validated; evidence in studio-data/voices/live-check.json. These measure execution, not a guarantee of subjective naturalness. Sixteen Python/backend tests and two preview tests passed. Standalone app supports F5/Ctrl+R after reopening it with the new wrapper.


## Narration length and audio chains
Each prepared narration accepts up to 12,000 characters; each voice-design audition accepts up to 600. A narration is internally split into bounded sections. To go beyond one job, select a finished narration and Continue with this voice: enter the next script and generate. It uses the same saved profile and appends the new audio to the entire parent chain. Repeat from the newest result. Clearing continuation starts a separate narration.
Join existing voice clips combines a base clip/whole chain and an appended individual clip, with a pause of 0–5000 ms (default 250). All Studio voices are PCM WAV; joins copy samples without re-encoding, preserve original files, and support repeated chains. Mixed voice profiles can be joined but do not offer same-profile continuation. Full audio chain is previewed by default; Individual clip selects only the latest segment. The exact submitted-script panel follows the preview selection, and clip/full-chain WAV downloads are separate. Audio serving supports HTTP range seeking and streams bounded blocks rather than loading a long recording wholly into RAM.
Seventeen Python tests and three UI-preview tests passed, including repeated model-free continuation jobs, exact sample ordering, pause length, parent transcripts, unsafe-path rejection and audio-chain seeking. This update did not run another GPU speech generation; existing live voice-engine tests still apply. Matching a saved voice does not guarantee identical emotion/pacing across clip boundaries.

## Local writing assistant (2026-10-17)
Writing assistant adds Hermes 3 chat with its own studio-data/chat.json history, separate from Lexi persona/history and online providers. No new weights were downloaded. GPU mode requires free resources; CPU mode is available but slower. First replies load the model; warm replies reuse it until unloaded or idle for five minutes. The model is not literally unrestricted and its answers/tool JSON can be mistaken.

Ask for prompts, scripts, lyrics or descriptions. When asked to create media, Hermes can propose one image, video or saved-profile narration job as a fenced studio JSON object. The panel displays the exact proposal and a Run button. Clicking Run submits through the existing authenticated, validated Studio endpoints. This is assisted tool use, not an unattended multi-step agent: no arbitrary shell access, file browsing, automatic reference selection, retry loop or autonomous result inspection. Use engine tabs to upload references or adjust advanced options. Job progress/results appear in those tabs.

Chat and media take turns. Starting generation unloads Studio-owned Hermes; chat refuses an active media job and releases Studio's idle image worker before loading. It never stops external programs. Unload model releases its memory; Clear conversation removes Studio chat history. Original Lexi voice and companion history are unchanged. Existing desktop/local-conversation.cjs remains a runtime dependency and must be retained during cleanup.

Verification: 19 Python tests and 3 UI regression tests passed. A real GPU reply through the new authenticated endpoint returned the requested neutral sentence in 101.7 seconds including cold initialization/system delays. That is a single cold sample, not a speed promise. The test conversation was cleared and Hermes unloaded afterward. Image/video/voice rendering was not repeated for this addition.
## Delete video and audio jobs
Each Recent video/audio row has a Delete button. Confirming permanently removes that job directory (outputs, its joined output, temporary render files, logs and job metadata) and its Recent entry. Uploaded references, downloaded exports and saved voice profiles are retained. Other completed chains already contain their own materialized media and remain playable after deleting an ancestor; an ancestor's deleted standalone clip cannot be recovered from Recent. Delete is refused while any media job is active. Paths and terminal status are validated; links/junctions in a job tree are rejected. Hard-linked copies in other jobs are preserved by normal filesystem unlink semantics. No user creations were deleted during verification.
## Studio runtime separation
Studio no longer uses the retired companion app or old Wan/Flux environment. Electron lives in media-runtime/electron, FFmpeg in media-runtime/ffmpeg, and voice uses media-runtime/voice with media-runtime/python311. Video bootstrap uses the existing FreeVideo unified environment. The Hermes adapter is freevideo-trial/local-conversation.cjs. The launcher shortcut and command file use the separated Electron executable. The former companion's approved sample 3 is imported as a regular saved Studio voice profile. Stills were copied and checksum-verified before retirement; see Lexi-stills/manifest.json.
## Switchable workspaces
The header's Workspace view selector switches instantly between Production desk (media / preview / controls), Creative library (media above preview and controls), and Director workspace (writing assistant alongside the selected engine). The choice persists locally in the browser/desktop profile. Switching reuses existing DOM nodes and never reloads the page, submits a job, clears uploads/drafts, changes selected media, or resets chain state. All engine tabs and existing controls remain available; narrower windows stack the sections. Project management and downloadable-model settings remain planned features, not implemented by this layout change.
Verification: 21 backend tests, 4 existing media UI regressions, plus real Electron renderer checks for all three views preserving draft inputs, selected media and node identity. Evidence: studio-data/desktop-check.json. No engine render was interrupted or started.
## Projects, asset management and model settings — current build (2026-10-17)

Backend version 14 uses media-workspaces/free-work and media-workspaces/projects/<UUID>. The header selects Project / Free work; Project actions contains create, rename, archive, project trash, snapshots, branching and ZIP import/export. All three workspace views remain available. Project names are metadata and do not rename runtime paths.

Media library supports validated image/video/audio/text imports, preview/use, downloads, rename, tags/favorites, copy/move with supporting assets, batch selection, asset trash/restore and explicit permanent purge. A segment and its joined chain are separate assets. Copy/move remaps required input IDs and copies project-owned voice references; independently copied projects never depend on the source project's files. Snapshot-held assets refuse destructive removal until the snapshot is removed. Global shared voices, model weights, exports and pre-migration backups are separate resources.

Project context contains a brief, visual style, up to four selected image references and a preferred voice. Apply project context can be disabled per creation; Preview request shows effective settings and pending uploads. Running jobs capture workspace/context/model settings. Narration text is never augmented with project prose. Project conversations are separate. Engine/chat/context drafts persist by workspace in the current browser/desktop profile; unsent drafts are not included in portable projects. Dirty context retains its edit revision and must be saved before it affects generation.

Save snapshot pins committed media and optionally captures conversation history. Restore creates a new project. Branch makes independent asset/profile copies; estimates include needed voice references. Portable ZIPs include manifests, hashes, media, required references and optionally captured conversation history, but not model weights. Imports reject unsafe paths and executable asset types and verify checksums. Large file operations are staged/journaled; pending operations appear in the library with cancellation/recovery where applicable.

Settings lists installed compatible profiles and supported alternatives. Video/image currently retain their installed FreeVideo profiles. Voice narration supports existing Qwen Base 0.6B and optional official Base 1.7B; writing supports existing Hermes Q4_K_M and optional official Q5_K_M. Supported downloads and exact official GGUF import verify publisher manifests/checksums before registration; installed versions are not overwritten. Optional alternatives have not been benchmarked on this GPU. Changing selection is blocked during active Studio jobs/downloads. Interrupted publication/removal is recoverable; canceled download staging can be cleaned separately. No extra weights were downloaded during implementation tests.

Original studio-data remains a pre-migration backup. Deleting a live workspace asset does not erase separate exports, external originals, snapshots retaining it, copies in other projects or that backup. Live model/reference processing stays local; only explicit model acquisition fetches public repository files.

Verification: 44 Python tests, 5 existing UI regressions and native Electron layout/project/draft/context/model-panel checks pass. Real CPU checks cover moving media, final-frame capture, continuation preparation, video/audio joining, voice-reference portability, snapshot/branch/export/import and fault recovery. Official Hermes Q5 manifest preflight succeeded. Fresh GPU image/voice/video/chat tests were deferred before generation because external local LLM/Python workloads occupied about 6.2 GiB VRAM. Reviews are in plans/reviews/PHASE_0.md through PHASE_6.md; implementation status and validation limits are in plans/IMPLEMENTATION_STATUS.md.


## Project tree interface (backend 17)

Use the sidebar collection plus buttons to create/import work; opening an item selects its engine. Browsing and project creation do not change the open work owner. Right-click items for rename/duplicate/delete and creative actions. Drag between projects to move; Ctrl-drag copies required references. F2 renames and Delete sends selections to Trash. Projects can branch with chats, export verified ZIPs and archive read-only. Archived media can optionally be reclaimed and restored from the verified ZIP. Models remain in Settings. Permanent Recents panels and engine navigation buttons are replaced by the tree. See `../plans/PROJECT_TREE_IMPLEMENTATION.md` for checks and operational limits.


## Chat startup loading (backend 18)

Opening Studio starts background loading of the selected writing model using the saved CPU/GPU preference. The sidebar reports loading/readiness. Loading creates no messages and changes no history. Existing media work and insufficient resources defer loading; first messages wait for a load already in progress. Startup-loaded weights remain warm until explicitly unloaded or released for media generation. See `../plans/CHAT_STARTUP_PRELOAD.md` for review and live evidence.


## Chat creation and diagnostics (backend 19)

Chat proposals appear as readable creation cards with Create, Review & edit, progress and result actions. Completed image cards can open the image or use it for video. Settings → Activity & logs exposes recent local events, generation history, runtime log tails and diagnostic download. Status-file writes tolerate brief Windows locks without aborting a running image job. See `../plans/CHAT_CREATION_AND_DIAGNOSTICS.md` for review and real-image verification.

### Saved voice scope (backend 20)
Saved voices are strictly workspace-local: Free work and each project have independent profiles. Only profiles with valid local metadata and a readable, nonempty reference WAV are offered. Narration requests cannot resolve profiles from another workspace or the legacy shared directory. Legacy shared profiles, including approved sample 3, remain preserved on disk but are not automatically listed; explicit project copies/imports become local profiles. Saving a newly designed voice always saves to the current workspace. Empty workspaces show a disabled saved-voice placeholder.

Validation: 60 Python tests and 13 JavaScript tests passed; final voice validation suite passed again after review. Live backend 20 reports no saved profiles in Free work.


## Rocinante-X chat trial (2026-10-19)
Studio now supports Rocinante-X 12B Q4_K_M alongside Hermes. The selected trial model is the author-linked bartowski quantization, revision 4302599a9fecd0e250c3790d77a38f3bd791fdd4, 7,477,207,712 bytes, SHA256 1ca25853a19d6b15f9a94f7e5bc86f4cc88bd0c9dea12a00ea55452b4208ade6. Installation used Studio's manifest/checksum-verifying installer.

Rocinante uses its embedded Mistral INST template; Hermes retains ChatML. Verified the embedded template merges the system prompt into the final user message without SYSTEM_PROMPT markers, matching upstream guidance. Model selection propagates template and display name through the existing adapter. Existing conversations and project context remain intact; Hermes remains selectable. No permanent character persona or memory system was added.

CPU is selected for the trial because the 8 GB GPU had only about 1.4 GB free. Full GPU offload is conservatively blocked by the model's 9,500 MiB admission threshold; partial offload is not implemented. Passing functional tests does not establish adult-content willingness or long-session character consistency.

Validation: 60 Python tests and 14 JavaScript tests pass. Backend 21 successfully loads rocinante-q4 on CPU. Live short-dialogue evidence is saved in maintenance/rocinante-validation.json.

Live smoke test: CPU reply took 37.46 seconds. It produced character dialogue but also an unsolicited narration proposal with no saved voice. Tightened the system instruction to keep ordinary conversation/roleplay text-only unless media generation is explicitly requested. Long-session consistency and the revised instruction have not been live benchmarked.

## Chat attachments and work-area models (backend 25)
Chat now reads local text files, images and sampled video frames, with Enter-to-send / Shift+Enter for a new line. Each work area lists only installed, available models for its adapter; voice design and narration are separate. Model selections apply globally to future jobs. See ../plans/CHAT_ATTACHMENTS_AND_MODELS.md for limits, verification and measured CPU latency. Vision is fallible; video uses four sampled frames without audio.


## Conversation-first chat (backend 26)
Chat now uses a scrollable conversation and bottom composer, with compact model selection, Chat options, attachment chips and readable responses. Project navigation and media creation cards remain available. See ../plans/CHAT_LAYOUT_2026-10-19.md for review and UI evidence.


## Behavior instruction layers and Cydonia trial (backend 27)
Settings now includes Chat behavior & personality: upload/edit an MD file for global behavior and another for the active project, enable/disable and save each layer. Project preferences override conflicting global preferences and are retained in snapshots/branches/exports. Both layers are captured for every message. Chat displays active saved instruction names. Cydonia Heretic 24B Q4_K_M is selected for the next CPU trial; Hermes remains a fallback. See ../plans/CHAT_BEHAVIOR_LAYERS.md for verification, source hashes and context limits.


## Sound cues and grouped Settings (backend 28)
Voice scripts support sequential <action sounds> and mixed {background sounds}, with {stop}, optional timing/gain and cue preview. Local AudioLDM2 effects are generated after speech and cached. Settings is a separate searchable workspace grouped by media type, preserving current work. See ../plans/SOUND_CUES_AND_SETTINGS.md for syntax, limits, licensing and verification.


## Global media queue (backend 32)
Video, image and audio creation now queue globally with captured project/model/context ownership. Use Job queue for pending order, cancellation, retry and pause/resume. Project-tree badges show PND/WIP/FIN and error/cancellation states. Pending jobs persist across restart; interrupted rendering needs explicit retry. See ../plans/GLOBAL_JOB_QUEUE.md for validation and limits.

## PDF and chat drop attachments (backend 33)
Chat accepts drag-and-drop alongside the + picker, preserving scoped attachment drafts. PDFs support local embedded-text extraction and CPU OCR for scanned pages. Four attachments per message; PDF limit 32 MiB / 100 pages, OCR up to 12 pages. Long text uses excerpts; PDF charts/layout are not visually analyzed. See ../plans/CHAT_PDF_AND_DROP.md for installation, limits and test evidence.


## Audio collections and image handoff (backend 37)
Audio now contains Saved voices and Recordings. Saved profiles can be previewed and selected for narration; auditions stay in the design workspace/queue. Imported, generated and uploaded reference images have a visible Use as video first frame action, with a thumbnail in video creation. See ../plans/AUDIO_TREE_AND_IMAGE_HANDOFF.md. Character-bound video voices remain a deferred concept in ../plans/FUTURE_CHARACTER_VOICES.md.


## Save and resume active generations (backend 41)
Pause generation from the item's context menu, the Jobs screen, or the work screen. WIP changes to Pausing while a safe checkpoint is saved, then STP only after the worker exits and releases its GPU allocation. Continue is available only for STP jobs and reloads saved progress through the global queue. Job IDs, inputs, seeds and project ownership remain fixed. Pausing also pauses the waiting queue; continuing a job resumes queue dispatch.

Images save sampling steps; narration saves completed sections; effects save completed effects. Video saves completed encoding/sampling stages, so a pause during video sampling can take until the entire sampling stage finishes. A job already decoding/mixing may complete normally. Paused state survives a normal app restart. This does not yet provide automatic recovery from power loss while saving a checkpoint. Existing workers launched before the upgrade must finish first. Live GPU pause/resume validation is pending; see plans/DISK_CHECKPOINT_PAUSE_RESUME.md.
