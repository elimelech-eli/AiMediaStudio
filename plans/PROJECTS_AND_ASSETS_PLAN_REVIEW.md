# Review of the projects/assets implementation plan

Date: 2026-10-17. Review type: self-review against inspected implementation and requested behavior; not an independent or executed-code review.

Scope: `PROJECTS_AND_ASSETS_IMPLEMENTATION_PLAN.md`. Application code, running workers and user data were not changed by this planning task.

## Findings resolved in the final plan

| Finding | Why the simpler approach would fail | Resolution |
| --- | --- | --- |
| Treat a job as a media asset | Deleting one segment could also delete its materialized chain and logs | Separate jobs from assets; map each output independently |
| Change global paths when selecting a project | A running image/video/voice worker could read/write the newly selected project's files | Capture workspace paths, context, inputs and model identity at submission; never use UI state in workers |
| Use SQLite alone for safe file moves | Filesystem and database commits are not one atomic transaction | Durable staged-operation journal, verified publication, recovery and idempotency |
| Use source ancestry as a hard dependency everywhere | Deleting an old source would unnecessarily block independently playable completed chains | Required-file vs provenance-only relationships; preserve ordered chain manifests |
| Promise snapshots while allowing ordinary purge | Snapshot manifests could point at deleted media | Pin immutable media; purge checks pins; explicit snapshot removal releases retention |
| Branch through cross-project hard links | Edits could corrupt shared bytes and ownership/accounting become confusing | Independent copies first; immutable assets; optional copy-on-write evaluated later |
| Create new IDs without remapping recipes | Copied/branched chains and voice profiles would still reference the source project | Dependency closure and explicit ID mapping, retained source lineage |
| Migrate only assets visible in Recent | Existing 50/100-item limits would omit older files | Full disk inventory plus unreferenced-upload handling |
| Show one global assistant conversation | Project context and replies could leak into another workspace | Separate threads/drafts, captured originating thread, scoped/stale-checked proposals |
| Move shared voices into one project | Deleting that project could break narration elsewhere | Explicit shared/project scopes, embedded references on portable export/branch |
| Roll back by restoring the old catalog | Work created after cutover could disappear from the app | Maintenance reconciliation or forward repair; no blind post-cutover downgrade |
| Infer engine compatibility from a downloaded filename | A valid model can still be incompatible with the engine | Separate engine-specific model catalog/adapters and validation milestone |

## Requirement coverage

| Requested capability | Plan location / acceptance |
| --- | --- |
| Dedicated project folders plus Free work | Storage design; phases 1–3 |
| Existing media usable across engines | Common asset resolver, reference copying, existing feature verification |
| Move video between projects | Move semantics, dependency review, checksum/journal and move/continue tests |
| Import/copy into another project | Independent ownership, staged copy, source unchanged |
| Branch an existing project | Phase 5; source deletion must not break the branch |
| Video/audio chaining preserved | Distinct segment/chain assets, ordered manifests, legacy compatibility and chain matrix |
| Delete and organize from the app | Library actions, tags/favorites, project archive, trash/restore and separate purge |
| Shared context | Explicit context selections, visible overrides, request snapshots, scoped chat |
| All three view layouts | One workspace state owner; layout switching remains presentation-only |
| Local operation/resource limits | No cloud dependency, existing job gate, no interruption of active work |
| Future interchangeable/downloadable models | Separate milestone; installed selection before downloader |
| Git-like history without heavy media Git | Snapshots, lineage and branches; no Git required |

## Tradeoffs accepted

- Independent branch/copy media takes additional storage. Show size estimates and allow selected-asset branches rather than introducing cross-project ownership surprises.
- File manifests plus an indexed SQLite catalog add coordination work. Recovery/rebuild tests are a release gate, not deferred polish.
- Capturing effective context/model/settings costs metadata space but avoids invisible changes and unreliable reproduction claims. Stored settings do not guarantee bit-identical model output.
- Imported legacy records may contain missing references from earlier deletions. Mark incomplete provenance; preserve playable outputs and report missing files rather than inventing links or blocking all migration.
- Project-relative storage improves portability of user assets, but installed runtimes/models still use existing absolute paths. Full application portability is a different task.

## Verdict

Ready to implement incrementally after user authorization. Start with phase 0's baseline and phase 1's storage/recovery core; do not start by merely adding a project dropdown or physically shuffling live job directories. Review each acceptance gate before advancing. No implementation has begun.
