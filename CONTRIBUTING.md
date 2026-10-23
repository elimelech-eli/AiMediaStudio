# Development workflow

Keep `main` as the stable baseline. Use a focused branch for each change, review the diff, run relevant tests and merge through a pull request when practical.

Do not commit installed engines/model weights, user projects, generated media, saved voices, personal references or credentials. These remain local and need separate backups. The `.gitignore` covers the current layout.

Frontend tests run automatically on pushes and pull requests. Python integration tests currently use the installed Windows environment described in README.md; GPU generation checks are separate and must not interrupt active user work.

The FreeVideo source is vendored under `freevideo-trial/FreeVideo`, including our adaptations. Preserve its license and notices. The existing development installation has a nested upstream Git checkout; a fresh clone has ordinary source files. When making engine changes, ensure they are staged in the AiMediaStudio repository too.

The full application currently depends on machine-local runtimes and absolute paths. Do not describe a source clone as a portable installation until provisioning and clean-machine setup have been implemented and validated.
