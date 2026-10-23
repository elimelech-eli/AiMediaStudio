# Chat startup preload — 2026-10-18

Studio's browser/desktop interface requests background loading of the selected verified writing model on opening. It uses the saved CPU/GPU preference and shows Loading / Ready / Deferred / Failed / Unloaded state in the sidebar. CPU/GPU selection stays consistent across project switches.

Preload loads weights and verifies the local server health/model listing. It does not generate a dummy response, open a conversation, or alter any chat history. Concurrent openings reuse one preload. A first real message waits for that same preload, with serialized shared-worker requests so readiness acknowledgements cannot be consumed as chat replies.

Active Studio work defers startup loading; the interface retries after resources become available. Existing RAM/GPU checks also defer loading when resources are busy. Once startup loading succeeds, weights remain resident beyond the old five-minute idle timeout. Explicit Unload and subsequent media generation release them. After media has unloaded chat, the next chat can require another load; this change does not automatically reload alongside media. Closing the window leaves the backend running as before.

## Review and verification

App-wide local self-review covered shared-worker ownership, model selection, generation admission, project/chat isolation, startup restoration, explicit unload, deferred startup retry and the previous idle timeout. Fixed a warmup/first-message race by joining the warmup before taking reply ownership, and ensured initial media deferral retries even while backend runtime state is Unloaded.

- 53 Python checks passed, including concurrent first-message/preload coordination, idempotent preload, resource deferral without history changes, and competing-media admission.
- 9 JavaScript checks passed, including loading without generation, reuse of loaded weights, explicit unload, media chaining and image-to-video handoff.
- Real GPU preload of the selected Hermes Q4 model reached Ready in **60.506 seconds** on this run. This is a cold-load observation, not a response-time promise.
- A separate native Electron check opened the app normally and confirmed `Chat ready · GPU` in the sidebar with GPU mode selected.
- Live evidence: `maintenance/chat-preload-live.json` and `maintenance/chat-startup-ui-check.json`.

Tests that open the full UI for unrelated checks explicitly disable automatic weight loading with the development-only `no-chat-preload` query parameter. Normal launchers do not supply it.
