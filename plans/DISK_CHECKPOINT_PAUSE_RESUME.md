# Disk-backed generation pause/resume — 2026-10-21

## Behavior

Backend 41 adds Pause while running, Pausing while a safe boundary is reached, STP / paused only after the owned worker has exited, and Continue only for paused jobs. Controls exist on the project-tree item context menu, global Jobs screen, and selected video/image/audio work screen. Paused jobs have their own queue section. Joined-media CPU operations are excluded.

Pausing a job also pauses the global queue so the next job cannot immediately consume the released GPU. Continue keeps the same job ID and captured project ownership, appends that job to the pending order, and resumes queue dispatch. A manually resumed global queue can run other pending jobs while the saved job stays paused. Timers accumulate active execution time, excluding time paused or waiting to resume.

Paused jobs and their dependencies are protected from destructive workspace/voice/model operations. They do not count as active GPU work. Saved state survives ordinary Studio restarts; arbitrary process death during checkpoint writing is not advertised as crash recovery. Checkpoints are retained with their job; cancellation does not purge user work.

## Engine boundaries

- Images: Qwen Image Turbo saves packed CPU latents and the exact next Euler step (0–8). Seed, prompt, dimensions, reference pixels and sigma schedule bind the checkpoint. Reloading weights/text/reference conditioning may take time; completed denoising steps are skipped. The persistent image worker exits before the job becomes paused.
- Voice: completed speech sections are stored as PCM WAV, with deterministic per-section seeds. Resume reads those files and generates remaining sections. A designed audition can be retained after its generation completes. A section already in progress finishes before pausing; mixing usually finishes normally.
- Sound effects: existing validated effect cache is retained; pause boundaries occur between effects. An in-progress effect finishes before pausing.
- Video: completed prompt/reference encoding and completed whole sampling are retained. During sampling, Pause waits for the entire sampling stage (including two-pass refinement), then retains the existing provenance-validated video/audio latents. Resume launches a fresh isolated worker from the captured request; completed sampling uses FreeVideo's decoder-only recovery route. This is NOT per-denoising-step video pause. A request arriving during decoding may finish normally rather than pause. Stable job-owned conditioning survives the encoder controller's temporary-directory cleanup. Retained latents use hard links where possible.

## Verification and deployment

104 app-wide Python tests passed, 35 JavaScript tests passed. Seven focused checkpoint tests passed after adding one extra lifecycle check: real local child process exit before publishing paused, image CPU pipeline exact-result resume after four of eight steps, video CPU latent/provenance validation after original conditioning deletion, narration completed-section reuse with a fake model, fresh pause receipts, mismatch rejection, and identical-copy latent retention.

No new media GPU generation was started. A user video on backend 38 was allowed to finish. After Studio reported idle, the backend was upgraded to 41; /api/state confirmed version 41 and /api/queue confirmed checkpoint_support=true. Browser inspection confirmed the compact Jobs screen and its Paused / saved-to-disk section. Real image/video/voice GPU pause/reload cycles remain a validation gate; other GPU activity was present.

## Review

Reviewed queue state transitions and serialization, same-ID normalized settings/seed retention, per-project paths, safe worker teardown ordering, restart visibility, pause-versus-cancel precedence, stale receipt rejection, cumulative timing, input/provenance binding, model/dependency protection, UI selected-job targeting and old-backend compatibility. The HTTP test now uses temporary diagnostics instead of reading/appending to live user logs; the complete suite passes with that isolation.
