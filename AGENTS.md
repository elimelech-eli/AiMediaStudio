# Project constraints

- Work only inside `D:\LEXI_App` unless explicitly authorized elsewhere.
- This project is AiMediaStudio: local video, image, voice and writing tools. See README.md and freevideo-trial/STUDIO.md.
- Generation and reference processing stay local unless the user explicitly authorizes a cloud exception.
- Do not interrupt active user renders or games. Check Studio job state and GPU activity before generation or restarting workers.
- Preserve Studio uploads, history, saved voices and outputs unless their deletion is specifically requested.
- Lexi stills are archived in Lexi-stills, with SHA256 manifest. The definitive visual identity remains references/canonical/Lexi-approved-2026-10-15.png. Read references/canonical/VISUAL_IDENTITY.md before changing Lexi visuals; do not alter her approved identity.
- Preserve original Lexi voice sample 3 in Studio's saved profiles; Windows CPU speech is a different voice.
- Hermes is used by Studio's Writing assistant. Keep its model/runtimes and the Studio adapter; no ChatGPT provider or companion app dependency is required.
- Live user work is under media-workspaces: per-project manifests, context, conversations, immutable assets and operation journals. Original freevideo-trial/studio-data is a retained pre-migration backup; do not delete it without explicit acceptance/cleanup authorization.
- Workspace selection must never mutate global engine paths. Requests and workers capture ownership; model/GPU admission stays global. Preserve both segment and materialized-chain assets, required input-role mappings and project-owned voice references during transfers/exports.
- Keep compatible-model selection adapter-specific. Do not claim arbitrary video/image model support or fresh GPU validation; see plans/IMPLEMENTATION_STATUS.md and per-phase reviews.
