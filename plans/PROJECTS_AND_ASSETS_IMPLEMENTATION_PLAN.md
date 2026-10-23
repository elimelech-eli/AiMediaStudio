# AiMediaStudio: projects, assets and shared context

Status: reviewed implementation proposal; no application changes authorized by this document.
Prepared: 2026-10-17.

## Outcome and boundaries

Give every project its own folder, assets, context and conversations. Provide a permanent Free work workspace with the same creation tools. Support importing, moving, copying, organizing, trashing/restoring and branching from inside Studio. Preserve every current generation, chaining and playback capability in all three workspace views.

Model downloads/switching get a separate milestone and adapter boundary. They must not delay a reliable project/asset foundation. No Git repository, Git LFS, cloud storage, extra generation engine or new model download is needed for the project work.

## What the current implementation requires us to change

Inspected sources: `freevideo-trial/studio.py`, `voice_studio.py`, `studio_chat.py`, `studio_admin.py`, frontend scripts and `STUDIO.md`.

- Video jobs, image jobs, uploads, saved voices and chat currently live in separate global locations under `studio-data`.
- Video functions and serving routes resolve against global JOBS/UPLOADS roots. Voice has its own root and identifier validator. These need a common storage resolver, not project-specific copies of each engine.
- Image Service retains an uploads-directory callback. Concurrent workspace switches must never change a running worker's input/output directory.
- The voice worker receives a profile-root path, while chat loads one global JSON conversation. Both need explicit workspace/request scope.
- Current deletion permanently removes an entire job directory. A job may hold an individual clip, a joined result and diagnostics; therefore a job is not the same thing as an asset.
- Chains are materialized MP4/WAV files. Their source relationships are valuable provenance, but already completed joined files do not need every ancestor to remain playable.
- The shared media admission gate and Hermes unloading/resource checks already exist. Preserve those limits rather than introducing concurrent GPU execution.
- Current Recent APIs cap results at 50 video/image jobs or 100 voice jobs. Migration must enumerate disk records, not just what Recent returns.
- All three layouts reuse existing DOM nodes. Project selection must have one state owner shared by the layouts and engine tabs.

## Storage design

Keep installed engine/runtime paths in place. Put new user-workspace storage under a dedicated root; do not rename the whole project or move model installations during this feature.

```text
D:/LEXI_App/
  media-workspaces/
    catalog.sqlite
    operations/                         # durable move/import/migration journals
    projects/
      <project-uuid>/                    # stable folder name, independent of display name
        project.json
        assets/
          images/<asset-uuid>/<file>
          videos/<asset-uuid>/<file>
          audio/<asset-uuid>/<file>
          documents/<asset-uuid>/<file>
        jobs/<job-uuid>/                 # requests, progress, logs, staging outputs
        context/                        # revisions, reference selections, creative brief
        conversations/                  # separate local chat threads
        voices/                         # project-owned voice profiles/reference audio
        snapshots/<snapshot-uuid>/
        trash/<operation-uuid>/
    free-work/                          # same workspace contract, permanent ID
      workspace.json
      assets/ jobs/ context/ conversations/ voices/ snapshots/ trash/
    shared/voices/                      # global reusable voices, including approved sample 3
```

Free work is a real, non-null workspace ID with a different workspace type. It cannot be deleted. Its folder uses the same internal structure as a project. The abbreviated folder line above denotes separate subdirectories.

SQLite supplies transactions, indexed lists/search and relation checks using Python's standard library. Versioned project manifests and asset sidecars describe portable contents; the SQLite catalog can be rebuilt from these records. Do not pretend a database transaction can also atomically commit file moves: use the operation journal described below.

Display names, tags, favorites and virtual collections live in metadata. Renaming an asset or project need not rename its physical UUID directory. A later explicit export may use friendly filenames. No requirement for users to organize UUID directories by hand.

### Records and identifiers

| Record | Required information |
| --- | --- |
| Workspace | UUID, type, name, timestamps, schema version, archived state, context revision |
| Asset | UUID, workspace ID, media type, display name, relative file path, byte count, checksum, media properties, status, tags, originating job |
| Job | UUID, captured workspace ID, status, engine/model identity, seed/settings, input IDs, context snapshot, output IDs, timestamps |
| Dependency | Source ID, consumer ID, relationship, required-file vs provenance-only classification |
| Voice profile | UUID, shared/project scope, reference asset and checksum, transcript, description, provenance |
| Snapshot | UUID, parent snapshot, manifest/context revisions and exact asset IDs/checksums |
| Operation | UUID, kind, source/destination IDs, staged/final paths, state, verification and recovery outcome |

An individual clip, a joined chain, an image and an extracted frame are separately addressable assets. A job may produce several. Completed media files are immutable: editing or generating a replacement creates a new asset/version. Legacy job IDs remain available through an alias map so old URLs and saved records can resolve during migration.

No global deduplicated blob store or cross-project hard links in the first version. Checksums detect duplicates and verify copies; independent project ownership is more important than clever space savings. Report the real copy size before branching. Filesystem copy-on-write can be evaluated later without changing the ownership contract.

## Dependency and operation rules

### Import, move and copy

- Import copies a selected external file. Never move or delete the original. Validate media type by decoding/probing, not just extension; preserve original filename in metadata. Support existing image/video formats, Studio WAV audio and UTF-8 text documents initially. Additional audio formats require explicit playback/probe support.
- Copy creates a new asset ID, retains source provenance and copies bytes into the destination. Show the proposed supporting assets and total size before starting.
- Move preserves the asset ID while changing ownership/location. Dependency checks happen first. If required consumers or sources would be left in another project, offer a self-contained copy instead, or move the required set together; do not create hidden cross-project file dependencies.
- Using another project's media in a generation imports a project-owned copy, rather than relying on that project's folder forever.
- Distinguish required dependencies (a reference needed for a saved recipe/voice profile) from provenance-only links (the source of an already materialized joined clip). A playable chain may move alone, carrying its ordered manifest and provenance records; absent ancestors must be clearly labelled unavailable for regeneration.
- Preserve segment order, segment/full-chain identity, pause settings and continuation parameters. Copying a reproducible chain optionally includes its source segments and references with an ID remapping table.
- Shared voices are intentional shared resources. Project export/branch must embed selected reference audio/transcripts so the result can stand alone; never bundle model weights.

### Trash, restore and project lifecycle

- Delete moves assets into workspace trash. Restore preserves IDs and metadata; resolve name conflicts without overwriting another asset.
- Explain required dependents and offer deleting the dependent set or cancelling. Do not cascade automatically. Provenance-only ancestry does not block deletion of playable materialized outputs.
- Trashing one output must not delete sibling outputs from the same job. Keep diagnostics/recipes with the job until explicit job cleanup or project purge.
- Empty trash is a separate, explicit irreversible operation. It must account for snapshot-held assets and active-job pins before freeing bytes. Show potentially reclaimable space separately from retained snapshot data.
- Archive project hides it from the default list without deleting files. Restore archive reverses this. Delete project moves the entire workspace to a managed project-trash area; permanent purge is separate.
- Block destructive operations on a workspace/assets pinned by a running job, unfinished copy/export or branch operation. Queued jobs, if introduced later, must also hold pins.

### File-operation recovery

Use a single asset service for UI actions and eventual assistant tools. It validates workspace IDs and resolves paths server-side inside approved roots. Reject traversal, junctions/symlinks, unexpected reparse points and hostile archive paths. Client filenames are labels, not trusted destination paths.

For copy/import/move/branch: preflight permissions and space; record the operation; copy into a destination staging area; calculate/verify checksums; write a manifest; publish through same-volume atomic renames where available; commit catalog ownership; then clean up the source for a move. Never delete the source before verified publication. A same-volume fast rename may be added only with equivalent journal/rollback behavior. Cross-volume copies always use staging and verification.

Persist each operation's phase. Startup recovery reconciles filesystem, manifest and catalog; it finishes or rolls back an incomplete operation without silently treating partial files as complete assets. Copy cancellation leaves the original intact. If Windows locks a file open in playback, pause/release the viewer when possible or report a retryable error; never force-kill another process.

Coordinate operations with workspace/asset locks acquired in stable ID order and durable pins. Do not hold the global generation lock or an open SQLite write transaction during a long copy, checksum pass or model inference. Revalidate versions/ownership before commit. Enable foreign-key checks on every database connection; define one write coordinator or carefully scoped per-thread connections for the threaded HTTP server. Retryable HTTP submissions carry operation IDs so a refresh/retry cannot duplicate a move, import or branch.

## Projects and shared context

Project context includes creative brief, style notes, selected character/scene references, reusable appearance descriptions and preferred voices. It contains explicit selections, not every asset or every conversation automatically.

Scope order: app defaults → workspace context → explicit creation overrides. Show the effective references and prompt/context that will be submitted. Voice descriptions must not be injected into literal narration text. Project text must not silently modify engine settings in incompatible ways.

Capture workspace ID, context revision, reference IDs/checksums, selected model identity, voice profile and settings when a job is submitted. The running job uses that immutable request even if the user changes projects, context or engine preferences. The completion event refreshes its owning workspace; it must not change the user's current workspace automatically.

Each workspace owns chat conversations and unsent drafts for all engine tabs. Switching workspace loads that workspace's drafts, selected media and chat. Switching between the three layouts changes presentation only. Chat replies and errors go to the originating thread even after a switch.

Assistant proposals carry workspace ID and context revision. If either becomes stale, re-review the proposal before submission. The server validates asset ownership and compatibility; the model cannot smuggle a reference from another project via a fabricated ID.

## Snapshots, branches and export

- A snapshot records a consistent project state: brief/context, recipes, asset list, conversations selected for inclusion, voice profiles and model/version identities. It is not a filesystem-wide backup or an engine checkpoint.
- Snapshot a committed metadata revision and completed assets only. In-flight jobs may be listed as running historical records, but their partial files are not promised snapshot contents. Restoring/importing a project never auto-resumes or submits recorded jobs. Export uses the same revision boundary and verifies bytes before declaring completion.
- Snapshot manifests pin immutable media needed to restore that state. Trash purge cannot remove pinned bytes unless the relevant snapshots are explicitly removed too.
- Restore snapshot creates a new project by default; it does not overwrite the current workspace. In-place restore is deferred.
- Branch creates an independent project from the current committed state or a snapshot. Default includes context and selected media/dependencies; chat inclusion is an explicit choice, off by default. Remap local asset/profile IDs and retain lineage back to the source.
- A branch operation stages all copies and publishes only after verification. Cancelling/failing it leaves the source untouched and does not show a half-complete project.
- Export produces a portable folder first, with checksums, manifests, necessary references and optional selected conversation history. Portable ZIP export/import follows with traversal, expansion-size and schema validation. Engine/model requirements are listed, not bundled.
- No Git in the initial implementation. Optional future Git integration may track text manifests/context only, after it has a concrete benefit; it must not become a hidden dependency for ordinary users.

## User flows and API boundaries

The header gains a persistent Project / Free work selector and New project action. All layouts consume the same workspace state. Create/Library/Assistant remain views within that workspace. Library actions include preview, use as input, continue, join, rename, favorite, tag, move/copy, export and trash; multi-selection supports batch operations with a single reviewed plan.

Switching away from an active render is allowed. A global status strip shows its owning project and links back; generation keeps the existing shared admission limit. Drafts are autosaved by workspace; stale async responses cannot overwrite the new workspace's draft or selection.

Use versioned storage/asset services beneath existing engine adapters. Proposed resource families: workspaces, assets, jobs, contexts, conversations, snapshots and operations. Clients submit asset/workspace IDs, not absolute paths. Playback and downloads resolve immutable asset IDs and keep HTTP byte-range support. Keep current localhost Host/Origin/token protections.

Preserve old routes temporarily through an alias/compatibility layer. A migration adapter resolves legacy jobs until each workspace is converted. Pagination replaces Recent-only caps; the same filter/query powers video, image and audio views.

## Implementation sequence and acceptance gates

| Phase | Deliverable | Gate before proceeding |
| --- | --- | --- |
| 0. Baseline and migration design | Current feature map, complete on-disk inventory, hashes, compatibility fixtures, source/destination and disk-space report | Every existing asset/job/profile/chat record classified; existing regression suite passes; no live-data moves |
| 1. Storage and operation core | SQLite schema/migrations, portable manifests, UUID resolver, dependency types, durable journal, staging/recovery, shared voice scope | Fault-injection tests pass; catalog rebuild matches manifests; import/copy/move/trash semantics exercised on disposable files |
| 2. Engine integration and physical migration | Workspace storage adapters for video/image/voice/chat; legacy aliases; migrate existing data into Free work; shared voices into shared/voices | All legacy media and chains hash-verified; new test jobs resolve only captured paths; old data retained for rollback |
| 3. Project and library interface | Create/rename/archive projects, selector, scoped library/drafts/chat, imports, move/copy, tagging/favorites, trash/restore and explicit purge | All three layouts exercise equivalent flows; no feature disappears; switching mid-job/chat sends completion to original workspace |
| 4. Shared context and assistant tools | Context editor, selected references, preferred voices, per-job snapshot/override preview, scoped proposals | Cross-project isolation, stale proposal and context-version tests pass; exact narration text remains intact |
| 5. Snapshots, branching and portability | Asset pins, branch with reviewed dependency closure, restore as new project, folder export/import; then ZIP support | Delete source project after a test branch and verify branch playback/regeneration inputs remain valid; export/import checksums and ID mappings pass |
| 6. Model settings milestone | Compatible installed-model selection first; supported downloads/import, hashes, licenses, disk/RAM/VRAM requirements and cancellation later | Each supported engine/model pair validated; active jobs retain the selected immutable model version; no arbitrary-model compatibility promise |

Each phase should be independently reviewable. Do not expose controls that only pretend to support a later phase. In particular, snapshot retention must exist before presenting snapshots or branches as dependable recovery tools.

### Migration cutover and rollback

1. Read-only inventory of all disk records, not just Recent APIs. Identify duplicated files, hard-linked outputs, unreferenced uploads, interrupted jobs and missing files without deleting anything.
2. Put the backend into an explicit migration mode after active jobs finish. Disable new writes across all tabs/windows. Do not interrupt renders or games.
3. Copy existing user data to staged Free work/shared locations; preserve original request JSON as historical evidence. Convert runtime references to stable IDs. Preserve individual and full-chain outputs as distinct assets. Import all supported unreferenced uploads into an Imported references collection so nothing disappears silently.
4. Map existing global chat to Free work, preserve approved voice identity and all saved voice references, and inventory image-service auxiliary outputs before classifying them as cache or assets.
5. Verify checksums, counts, relationship resolution, voice profile hashes, range playback and continuation/join workflows. Publish manifests/catalog and activate the new storage version.
6. Retain the legacy data until migration acceptance and a user-approved cleanup. Maintain a durable mapping for reruns; migration is idempotent.
7. Before cutover, rollback removes only staged copies. After cutover, rollback requires a maintenance export/reconciliation of any newly created assets back to a compatible store, or a forward repair. Never simply switch to an old database and hide post-cutover work. Do not promise unrestricted downgrades.

Moving the application directory or portable model installations is outside this migration. All new workspace assets use relative paths; historical absolute paths must not drive future workers.

## Verification matrix

- Preserve existing feature tests: video lengths/quality/references, final-frame capture, continuation and N-segment joining, full-chain vs segment previews, audio preservation, image composition/image-to-video, saved voice design/narration, audio chains/transcripts, deletion protections, local chat/proposals, HTTP authentication and seeking, all view switches and cold launcher startup.
- New core tests: workspace CRUD, UUID/path resolution, scope checks on every read/write, job IDs vs asset IDs, consistent manifests/catalog rebuild, ownership and dependency closure, filename collisions, Unicode/long Windows paths, read-only destination, low disk space, copy cancellation, locked files and hash mismatch.
- Fault-injection tests: crash before/after file publication, catalog commit and source cleanup; restart during branch/move/trash/migration; replay each operation twice without duplication or loss.
- Isolation tests: simultaneous tabs selecting different projects; switch while upload, chat reply, render or join completes; change context mid-job; stale assistant proposal; imported cross-project reference; archived/trashed workspace with pending operation.
- Chain tests: move a materialized chain alone; copy a full reproducible chain; trash a provenance-only ancestor; block deletion of a required reference; continue after moving; restore after trash; verify segment/full-chain links and ordered metadata.
- Snapshot tests: trash then attempt purge of a pinned asset; branch includes required dependencies; restore into a new project; deleting source never breaks branch; detect corrupt/missing snapshot bytes rather than reporting success.
- Migration tests: fixtures spanning every legacy record type, legacy ID aliases, more records than Recent caps, malformed/missing metadata, unreferenced uploads and repeated migration. Original files stay intact on failure.
- Live validation at the appropriate gate: one small image, short video and narration in separate disposable workspaces, plus scoped local chat, when GPU/resources are free. Most storage tests use synthetic media and CPU FFmpeg; do not burn full renders for every UI change.

## Review disposition

Reviewed against the current code and the user's requested flows. Findings and resolutions are recorded in `PROJECTS_AND_ASSETS_PLAN_REVIEW.md`. There are no known unresolved architectural blockers for phases 0–5. Model-format support is deliberately a separate engine-specific integration question. Passing this review authorizes no implementation or data migration; the user asked for planning only.
