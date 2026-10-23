# Layered behavior instructions and Cydonia trial — 2026-10-19

Settings → Chat behavior & personality provides two editable/uploadable layers:
- Global: applies to all workspaces; persisted locally in media-workspaces/shared/chat-instructions.json.
- Project: applies only to the active work owner, including Free work as its own scope; persisted in that workspace's manifest as chat_behavior. Upload .md, .markdown or .txt into the editor, then Save. The source file is copied as text, not watched or executed. UTF-8 and UTF-16 are accepted. Each layer is limited to 16,000 characters, with a 128 KiB upload limit.

Each layer has name, text, enabled and revision. Conflicting stale saves are rejected. Project instructions follow global instructions in the system message and take precedence over conflicting personality preferences. The Studio capability/tool protocol remains separate. Every chat request captures both layers afresh, so edits apply to the next message in existing conversations. Reference attachments remain untrusted data, separate from behavior instructions. No behavior file was automatically applied to real user workspaces.

The chat shows the active saved layer names and an Edit shortcut. Unsaved file/editor changes are clearly labeled. Drafts remain separate by project. Archived/deleted projects reject project-layer edits. Global instructions remain editable independently. Project snapshots, branches and ZIP exports/imports retain project behavior; global settings are not embedded into exported projects. Existing snapshots without instructions restore an empty project layer.

Model: Cydonia-24B-v4.3-heretic.Q4_K_M.gguf, source mradermacher/Cydonia-24B-v4.3-heretic-GGUF, pinned revision 7b7b06cf73df212fcbe9bc4385adf71afff2b4b0. Upstream base is coder3101/Cydonia-24B-v4.3-heretic, not the unmodified Cydonia model. Download size 14,333,911,104 bytes. SHA256 d8370bad0426d1cda2dfb1feda6b770b702e3f5dbad3e63a6f2caf818a8a92b6. Verified by Studio's downloader. Uses embedded Mistral template. Hermes remains installed as fallback; Rocinante remains removed. CPU is the trial mode; full GPU offload requires more VRAM than this 8 GB GPU. Partial offload is not implemented.

Review/evidence:
- All 69 Python tests and 16 JavaScript tests passed.
- New tests verify global/project separation, Free work isolation, disabled layers, revision conflicts, length limits, archived-project writes, snapshot/branch/ZIP retention and actual system-message assembly with both layers and tool contract intact.
- Isolated native Electron UI test imported an MD file, saved it to a disposable project, checked the active badge, switched to Free work and verified no leakage or global changes. No console errors. Evidence: maintenance/instructions-ui-check.json and .png.
- A running user narration was allowed to finish before backend 27 was activated. No active media work was stopped.
- A two-turn neutral identity test is recorded separately in maintenance/cydonia-instructions-live-check.json when complete. It tests instruction following, not adult-content willingness.

Limits: instruction layers do not bypass a model's learned behavior. Long combined instructions/attachments can exceed the 8,192-token runtime context; the app reports that rather than silently cutting the behavior instructions. Existing conversation history is preserved and can influence subsequent replies; use a fresh chat for a clean model/personality comparison.

Live result: Cydonia correctly answered Mira / Copper Finch, then after the project instructions changed in the same chat, Nova / Silver Kite. First turn: 164.55 seconds CPU; second turn: 17.55 seconds. Resident working memory was about 22.1 GiB. Test project was purged; shared global instructions were untouched. The test model was unloaded afterward when idle, while its selection remained Cydonia. Adult-output willingness was not tested or guaranteed.

