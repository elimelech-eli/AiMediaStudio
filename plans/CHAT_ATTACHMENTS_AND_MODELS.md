# Chat attachments and work-area model selectors — 2026-10-19

Implemented:
- Chat upload accepts four workspace-owned attachments per message. TXT, Markdown, JSON/JSONL, CSV/TSV, YAML, XML, HTML, logs, INI/TOML and common source-text extensions are decoded locally (UTF-8/BOM or UTF-16). Text limit: 2 MiB/file. Binary content is rejected. Long text uses labeled query-relevant excerpts within a 12,000-character combined budget; it is not represented as fully read.
- Originals are imported into the active project's asset store. Access to an attachment resolves through that workspace's manifest. Text/excerpts and visual observations remain in conversation context; the visible transcript shows the user's message and attachment names. Pending file selections are scoped to individual chats.
- Qwen2.5-VL 3B Q4_K_M with matching Q8 projector is installed locally from ggml-org/Qwen2.5-VL-3B-Instruct-GGUF, pinned revision 5037fcf163dd95d1e41d1974465f0898ed108ca2. Both files were verified against publisher SHA256 manifests. Weights occupy about 2.77 GB. Vision runs on CPU, sequentially with the selected text model; it does not send references to the cloud.
- Image analysis resizes to at most 768px. Video analysis accepts clips up to 120 seconds/256 MiB and samples four frames using CPU FFmpeg. Timestamp labels are approximate sampling positions. Maximum eight frames/images in a message. No audio transcription or continuous temporal understanding. Captions can be wrong. A deterministic video-limit notice appears under assistant replies.
- Enter sends; Shift+Enter inserts a line. IME composition does not submit.
- Chat, image, video, voice design and voice narration have installed/available-model selectors filtered to their exact adapter. Chat also exposes the local vision helper. Missing/unverified model files are excluded from work controls. Model selection remains global, clearly announced, and changes future jobs. Project/job captures remain intact.
- Document extensions are supported by asset import, publication and ZIP import/export as well as chat; no document code is executed.

Review and evidence:
- App-wide regression run: 65 Python tests and 16 JavaScript tests passed. One earlier HTTP run had a localhost connection reset; isolated rerun and subsequent full suite passed.
- Final focused run after availability checks and deterministic video notice: 19 Python + 8 JS tests passed.
- Native hidden Electron check verified six filtered selectors, correct Rocinante selection, real Enter handler behavior, attachment input, and no console errors. Evidence: maintenance/chat-attachments-ui-check.json and .png.
- Real local end-to-end CSV + picture + 3-second video test: 201.77 seconds CPU. Correctly answered Alice=42 and orange circle on blue. Described test-pattern frames but invented explanations of missing/incomplete pattern content. Added stronger literal-observation instructions and deterministic sampling/audio limitations afterward. Those final prompt changes are functionally tested, not a repeated accuracy benchmark. Evidence: maintenance/chat-attachments-live-check.json.
- Low-frame-rate end seeking failed in the first live attempt; replaced with uniform FPS sampling and added a real 1fps video regression. Disposable live-test projects were purged; no user projects were deleted.

Limitations: no PDF/DOCX extraction, audio analysis, arbitrary model architectures, permanent persona/memory redesign, exhaustive long-file retrieval, or guarantee of visual accuracy. Follow-up visual questions use saved observations unless the image/video is attached again.
