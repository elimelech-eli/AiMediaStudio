# AiMediaStudio

A local Windows workspace for video, image, voice and writing tools, with project assets, reusable characters, media chaining and a shared generation queue.

## Repository scope

This repository contains application source, tests, design concepts, implementation notes and the locally adapted FreeVideo engine. It excludes model weights, installed runtimes, private projects, uploads, generated media, saved voices and personal reference artwork. GitHub is source control, not a backup of those files.

**This is currently a source snapshot of an installed development system, not a one-click installer for a clean machine.** The launcher expects dependencies already installed at the paths below. A fresh clone will need runtime/model provisioning; that is not automated for the complete app yet.

## Third-party engine

`freevideo-trial/FreeVideo` contains vendored [FlashML FreeVideo](https://github.com/FlashML-org/FreeVideo) source from commit `0b0c2ec2ae7111e86da4e2209fc3e3dd769e9d7a`, plus our local checkpoint/resume adaptations. Its Apache 2.0 license, NOTICE and third-party notices are retained in that folder. Installed AI models retain their respective licenses and are downloaded separately. The original nested Git checkout remains local; the application repository tracks actual engine source files rather than a submodule pointer.

## Development checks

On the current installed machine, run Python tests from `freevideo-trial` using `runtime\envs\unified\Scripts\python.exe -m unittest discover -p "test_*.py"`. Frontend tests run with Node’s built-in test runner against the `*.test.cjs` and `test_*.cjs` files. Tests do not replace live GPU quality/performance validation.

## Current local installation

Start **FreeVideo Studio.lnk** or **Start-FreeVideo-Studio.cmd**. The local desktop launcher starts/reuses http://127.0.0.1:57846/. Refresh an existing window after an update.

- `media-workspaces/`: live Free work, dedicated project folders, asset catalog, context, conversations, snapshots, shared voices, export ZIPs, operation journals and model registry/downloads.
- `freevideo-trial/`: Studio code and the existing FreeVideo runtime/model packs. Its original studio-data media is retained as a pre-migration backup; new project work lives in media-workspaces.
- `media-runtime/`: Electron, FFmpeg, Python 3.11 and Qwen voice models/environment.
- `conversation-engine/`: original Hermes weights and CPU/CUDA llama.cpp runtimes.
- `Lexi-stills/`: 1,117 preserved still images with SHA256 manifest.
- `references/canonical/`: original approved Lexi image/specification.
- `plans/`: implementation plan, per-phase local code-review reports and current validation status.
- `maintenance/`: baseline and integration-check evidence/scripts.

Use the project tree and right-click project/item actions. Characters define reusable identity, outfits, behavior and saved narration voices within each project; Project context shares selected references, style and preferred voices. Workspace view switches presentation without resetting work. Settings exposes compatible models and storage information.

One media job runs at a time; Studio releases its own idle models as needed and never stops external workloads. Generation/reference processing is local. Additional supported model downloads are explicit network operations. The original approved Lexi sample 3 is preserved as a shared saved voice.

Installed runtimes use absolute paths, so keep this application at D:\LEXI_App. Portable project ZIPs carry project data, not installed model/runtime weights. The writing worker currently uses Node at D:\nodejs\node.exe.

See freevideo-trial/STUDIO.md for workflows and limits. See plans/IMPLEMENTATION_STATUS.md for tests and the deferred live GPU validation gate.
