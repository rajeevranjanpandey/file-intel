# File Intel: local deployment

The source application has launchers for macOS and Windows, with a shared Python launcher for Linux as well. Python 3.12 is required. Each destination needs compatible native dependencies and verified model files. A successful source-code portability test does not certify every hardware or operating-system combination.

## Install and start

1. Extract the project into a writable local folder. Keep `models/`, the source folders and the default configuration. A clean source release excludes virtual environments, databases and personal connections.
2. Install Python 3.12, then run `python scripts/install.py`. Use `python3` or `py -3.12` where appropriate. The installer creates `.venv-local` and refuses to overwrite existing environments. For a custom environment, pass the same `--env NAME` to both the installer and launcher. Native libraries are resolved for this computer. Building `llama-cpp-python` from source may need CMake and the system's C/C++ compiler: the developer command-line tools on macOS, Visual Studio C++ Build Tools on Windows, or the distribution's compiler on Linux.
3. Run `python scripts/run.py`, `scripts/run.command`, or `scripts/run_windows.bat`. Open http://127.0.0.1:8501. The app binds only to localhost.
4. Connect folders on this computer and scan. Folder picking uses the operating system's native dialog on macOS and a separate standard-library Tk dialog on Windows/Linux. The latter needs Python's Tk support and a desktop session; entering paths always remains available. Location buttons open the file manager and never execute a selected document.
5. Review proposed moves in Activity. Approval, execution and undo remain separate operations; existing destinations and cross-volume moves are refused.

Online installation downloads dependencies once. Full installation verifies model hashes; missing models must be prepared separately before claiming offline readiness. `--ui-only` installs the dashboard without the AI pipeline.

## Offline setup

Use `python scripts/install.py --offline` with a complete, hash-verified wheel bundle and matching lock file built for the destination OS, processor and Python version. The included historical wheel bundle is platform-specific. It cannot be installed unchanged on every computer. The offline installer performs no package downloads.

Do not copy virtual environments between computers. Their interpreters, compiled packages and installed entry points belong to the machine where they were created. Reinstall after moving an environment or its parent folder. See the [Python virtual-environment documentation](https://docs.python.org/3/library/venv.html).

## Paths and data

Project folders are saved relative to `config.toml`; home-folder connections use `~`. Runtime and bytecode-cache paths are calculated using this computer's home and temporary directories. No previous username is needed.

When a copied index contains unavailable project-local roots, File Intel verifies the new source hashes before reconnecting them. It refuses ambiguous mappings, changed files, symlinks and roots with pending approvals or active undo locations. External roots must be connected again as needed. The audit log retains historical paths rather than rewriting its evidence.

For independent deployments, start with a fresh index. Before retaining an existing library, stop the app and back up `config.toml` and `data/` together. Keep source-file backups independently. Cloud placeholders must be downloaded before offline use; system synchronization operates independently of the application.

## Verification

Run `python scripts/run.py --python -m pytest -q` for the suite. Parser/model tests need the complete environment and models. Windows launch and native dialogs still require an acceptance run on an actual Windows computer; simulated dispatch tests are not equivalent.

## Release

`python scripts/build_release.py file-intel.zip --models models`

The builder excludes virtual environments, personal settings, indexes, approvals and audit history. It includes the shared launcher, both operating-system launchers, dependency requirements, source, samples, models and an integrity manifest. Treat compiled wheels as a separate platform-specific inventory.
