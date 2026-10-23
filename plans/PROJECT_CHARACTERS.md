# Project characters — 2026-10-22

Initial implementation: backend 46. Current free-text reference workflow: backend 48. Core character functionality was activated and verified on backend 45; a new user render then started. The launcher correctly deferred activation of final build 46, which adds combined face/body guidance and loads on the next idle launch. This is generic project functionality, with no automatic modification of Lexi’s approved identity or voice.

## Workflow

1. Import reference media into the desired project using the existing collection + buttons.
2. Use + beside **Characters**. Give the character a name and aliases, concise appearance/body-language descriptions and optionally a behavior MD/TXT file.
3. Add up to 10 reference images, uploaded directly or selected from project assets. Each has optional free-text descriptions/tags; no fixed categories or approval requirement. Add outfits with optional reference images, choose the current outfit, location, hairstyle and props. Assign a saved narration voice from the same project if needed.
4. In image/video/chat/narration work, expand **Project characters & continuity**. Auto resolves names and aliases in the prompt; explicit selection handles prompts without a name. None opts out. Scene roles disambiguate multiple subjects. Outfit overrides apply to this job; editing the character’s current state persists it for later jobs.
5. Continue a clip or use a generated image for video. The captured definitions, outfit, fingerprints and identity references carry forward. Use latest definitions explicitly to adopt subsequent edits. A source image uploaded independently has no character metadata to inherit.

## Engine behavior and limits

- Strict mode requires at least one image reference per selected character for image/video work, enabled reference conditioning and a valid reference budget. It rejects unsupported combinations before enqueueing. It is a validation mode, not a guarantee of visual identity.
- Automatic selection fills the adapter budget in library order, allocating one image per character before extra images. Select a character explicitly to choose individual images; Preview references shows the captured choice. Automatic image-to-video handoff adapts to the smaller available budget; manual selections stay pinned and must be adjusted explicitly if over capacity. Selected-outfit guidance remains supported. Images allow four combined references; video image references, including the starting frame, share a four-image budget. Multiple characters may require fewer references.
- Video identity guidance uses ref2va conditioning. This trades an exact first-frame anchor for identity guidance; the engine can still drift. The explicit existing identity image and motion-video input remain supported within their limits.
- Character appearance, body language, outfit and state are added to visual prompts. Full behavior instructions stay in chat context rather than overflowing visual prompt limits. Image prompts plus guidance must fit the existing 2,000-character limit.
- Narration selects the assigned character voice unless Override is checked; the submitted script remains unchanged. One character voice per narration. Voice notes are contextual descriptions, not automatic voice synthesis instructions.
- Saved TTS voices do not control voices inside generated videos. Character motion/sound references are retained but not silently interpreted as supported generation inputs. Select an explicit video reference to guide motion.
- Continuations capture versions at submission; character edits do not mutate queued or paused jobs. Jobs embed their definitions and asset checksums. Chat creation cards carry selected characters; stale proposals require review.

## Storage and review

Definitions and history live in the project manifest. Required media and saved voice dependencies are remapped during copies, branches and export/import. Individual asset transfers carry captured character data, not the destination’s editable character library. Branch/export includes that library. Character definitions currently stay with their project; branch the project to duplicate the complete library.

Character versions retain their reference assets and voices, including after a soft delete. Purge a deleted character to release its definition/history retention; job and project snapshots can retain dependencies independently. Existing project operations and active-job protections remain in place.

Reviewed project ownership, optimistic revision checks, immutable queue capture, typed references, path containment, asset/voice deletion guards, transfer journals, remapping, adapter preparation, chat proposal handoff, tree actions and existing image-to-video flows. Raw client-supplied snapshots/guidance are discarded and rebuilt from project records. No new cloud path or model/runtime dependency was added.

Validation: full 120-test Python suite passed before the final adapter guards; 40 targeted tests covering changed adapters/chat/storage passed afterward. Added face/body-conditioning test also passed. All 45 frontend checks passed. Live backend/UI verified editor opening, saving a disposable character, local prompt resolution and project isolation; exact QA project was removed. Evidence: maintenance/characters-live-check.json and maintenance/characters-workspace.png.

The user’s initial render was left running and completed normally before activation. No new GPU media generation was started. Fresh visual quality/identity benchmarks remain unvalidated; successful metadata/preparation tests do not establish output quality.

## Free-text reference update — 2026-10-22

Backend 48 is active. Characters store up to 10 distinct image references with optional descriptions up to 1,000 characters each. Images can be uploaded individually/in batches or selected from the project. Descriptions reach image/video prompts with the correct reference index. Blank descriptions use general visual guidance; no separate tagging model is called. Generator interpretation is fallible.

Existing face/body/image roles become descriptive text when edited and saved; repeated legacy uses of the same image merge their descriptions. Existing motion/sound references and immutable job snapshots remain retained. Continuations preserve definitions and manual image choices; copies/exports remap asset IDs and keep descriptions. Historical character libraries over the new limit are shown intact and require manual reduction before saving; no assets are deleted.

Review covered upload scoping, tag validation, the 10-image library limit versus four-image adapter limit, strict mode without fixed roles, automatic/manual selection, legacy compatibility, prompt numbering, continuation capacity changes and reference-ID remapping. The full 126-test suite and 45 frontend checks passed; final 17 character-specific tests passed afterward. Live UI upload/save and local engine-prompt capture were verified with an isolated fixture; its exact project was removed. See maintenance/freeform-reference-check.json and maintenance/freeform-character-references.png. No GPU media generation was run.
