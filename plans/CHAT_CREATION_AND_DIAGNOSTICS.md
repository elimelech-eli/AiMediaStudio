# Chat creation cards and diagnostics — 2026-10-18

## Phase 1: Windows status-file failure

Recorded image jobs failed with WinError 5 while replacing `job.tmp` with `job.json`, during model loading. This was a Studio progress-persistence failure, not evidence of a rejected image prompt or missing model.

All Studio JSON writers now use a shared helper with unique temporary names, fsync, bounded retries for transient PermissionError and cleanup on failure. Existing committed JSON survives a failed replacement. Project manifests, voice status and chat saves use the same helper.

Image submission establishes writable metadata before starting GPU work. A delayed progress write logs a warning and continues monitoring. Exceptional monitor failures cancel/stop the owned service. Final persistence failures are logged and always release the active marker; current-process status retains the result for diagnostics rather than leaving the worker tracked as running forever.

App-wide self-review checked generation admission, worker ownership, terminal cleanup, concurrent writers/readers, project manifests, voice jobs, chat history and model registry compatibility. 22 focused backend tests passed, including injected file locks and a mocked image completion despite a blocked progress write.

## Phase 2: User-facing creation and logs

Internal studio JSON is replaced with a readable creation card: description, dimensions/duration, project, Create, Review & edit, status, and result actions. Image results include Open and Use for video. Errors have a readable summary, collapsed technical details and View logs. Broken/truncated tool blocks show a retry notice instead of raw protocol. Historical proposals retain project/context guards. Persisted card job IDs resume monitoring after reload; creating another result is explicit. No automatic execution was introduced.

Settings → Activity & logs provides recent structured activity, generation history, backend output/errors and the local chat runtime log. It supports level/search filters, refresh, automatic refresh while open and a local diagnostic download. Backend errors include IDs for correlation. Error paths and UI failures are rendered as text, never HTML. Request bodies and chat messages are not recorded by the event logger. Raw runtime messages may contain filesystem paths; logs remain local.

Structured logs rotate at 5 MiB with three previous files. The viewer is bounded to recent entries and raw log tails; it is not an unlimited permanent audit archive. Only fixed source names are accepted, preventing arbitrary filesystem reads. Logging-storage errors do not replace the original application result/error.

App-wide self-review checked three-layout integration, project ownership, stale contexts, playback/reference handoff, duplicate-submission protection, storage failures, archived/deleted results, existing chaining, log access validation and safe text rendering.

## Phase 3: Verification

- 58 Python tests passed. A subsequent scoped HTTP check passed for job isolation, diagnostic error IDs and rejection of arbitrary log paths.
- 13 JavaScript checks passed, including creation parsing, malformed/truncated blocks, storage failures, image-to-video handoff, chaining and worker unload/preload.
- Native Electron confirmed readable cards, no raw tool JSON, Create action, friendly errors, collapsed technical details and 60 visible diagnostic rows, including historical generation errors.
- A real local image job completed successfully: a 256×256 ladybug image in 197.497 seconds. It passed model loading, text encoding, denoising, decoding and final persistence. No WinError 5 occurred. The disposable project was removed after saving verification evidence; user projects/history were untouched.

Evidence: `maintenance/image-flow-live-check.json`, `.png`, and `maintenance/chat-cards-ui-check.json`, `.png`.

Reviews are local self-reviews. Genuine permanent folder-permission problems can still fail writes and are reported; the fix does not disable antivirus or require administrator access. The live small-image test validates this pipeline, not every model/resolution/reference combination.
