# File Intel: detailed operating reference

An offline document-understanding application built from the supplied **Local-First NLP Architecture Review v2.1 PDF**. It discovers files by actual content, extracts text and tables, builds a searchable knowledge index, identifies duplicates, groups related documents, and proposes reversible organization actions.

The default folder is the included `demo/` corpus. Your original PDF, TXT and architecture images have not been moved or modified.

## Start the app

### Run on this Mac (already set up)

Open Terminal in this project's folder and run:

```sh
sh scripts/run_macos.command
```

Or double-click `scripts/run_macos.command` in Finder. Keep the Terminal window open, then visit **http://127.0.0.1:8501/** in your browser. Stop the app with **Control+C** in that Terminal window; run the same command to start it again. You do not need to reinstall dependencies each time.

The launcher checks the project's local environments and its prepared runtime cache, including the older macOS cache. It uses a cache only when it belongs to this project.

### First-time setup on another computer

Install Python 3.12 on the destination computer. From the project folder, set up a fresh environment once:

```sh
python scripts/install.py
python scripts/run.py
```

Use `python3` if that is the name of your Python 3.12 command, or `py -3.12` on Windows. After setup, double-click `scripts/run.command` on macOS, or `scripts/run_windows.bat` on Windows. The shared Python launcher also works on Linux.

Open **http://127.0.0.1:8501**. Processing stays on this device; no account or API key is required. Online setup downloads dependencies once. Runtime uses local models from `models/` and works offline after setup and model verification.

**Copy source code, models and sample files between computers; create the environment on each computer.** Copied virtual environments and compiled wheels cannot be shared across operating systems or processor types. `requirements.txt` resolves native packages for the current computer; `requirements.lock` preserves the original offline bundle. If a native package must build from source, install the operating system's C/C++ build tools first. See [Deployment](DEPLOYMENT.md).

The launcher derives all project paths from its own location and checks the available environments before using one. `FILE_INTEL_PYTHON` can select an installed Python command without editing the launcher. Legacy launcher names continue to forward to the shared launcher.

### Install without internet

You need Python 3.12 installed, the complete `models/` directory with its manifest, and a verified `wheels/` bundle for the destination computer. The existing wheel bundle targets **Apple Silicon macOS / Python 3.12**; it cannot install on Windows or an Intel Mac.

From the project folder:

```sh
python3.12 scripts/install.py --offline
python3.12 scripts/run.py --python -m app.cli models verify
python3.12 scripts/run.py
```

An environment that already exists is preserved. To make a separate installation, use `python3.12 scripts/install.py --offline --env .venv-new`, then start it with `python3.12 scripts/run.py --env .venv-new`.

The small project snapshot ZIP contains source, settings, sample files and an index backup; it **does not include models, wheels or Python environments**. Keep those assets separately or use the complete offline release bundle. Install and keep the project outside cloud-synced storage for dependable offline startup. Any source documents in iCloud must be downloaded before disconnecting.

### Check that it works

1. Open **Library → Scan & Index** to index the supplied sample documents.
2. Search for `Orion garden project`; the Markdown, PDF and text samples should appear.
3. In **Collections**, refresh the groups. The top-right folder icon opens the collection's original-file list; click a filename to reveal its location in your file manager.
4. In **Organize**, choose **Same content**, then **Preview folder structure**. The matching Orion files should share a folder; the revised text should stay separate. Previewing does not move files. Changes require proposals and approval in **Activity**.

Run automated checks from the project folder:

```sh
# Full regression suite, including real local models and extraction:
python scripts/run.py --python -m pytest -q
# Only the added sample-corpus checks:
python scripts/run.py --python scripts/verify_grouping_test.py
# Collection navigation and location controls:
python scripts/run.py --python -m pytest tests/test_collection_dashboard.py tests/test_locations.py -q
```

Use `python3` or `py -3.12` instead of `python` when appropriate. Real-model tests take several minutes and use temporary copies for move/undo tests.

### Startup troubleshooting

- **No compatible environment found:** run the first-time installer with Python 3.12. Do not copy a virtual environment from another computer.
- **Models missing or altered:** restore the complete verified models directory from your offline bundle, then run the model-verification command above. Installing Python packages alone does not supply model weights.
- **Port 8501 already in use:** open the existing app at the URL above, or stop its Terminal process with Control+C before relaunching.
- **Blank or slow startup from iCloud:** ensure the project files are downloaded locally. Keep the complete project and runtime outside cloud-synced folders when possible.
- **UI edits are not visible:** refresh the browser. If Python modules changed, stop and restart the app as well.

## Workflow

1. **Connect folders** lets you choose several folders on your device or enter one path per line. **Scan & Index** reads their files and subfolders.
2. **Search** finds exact tokens, filenames, or meaning, with source excerpts and page references.
3. **Find duplicates** sorts matches into four kinds. Exact copies share identical bytes. Same-text files match after normalization. Edited versions keep most of their wording, and the review card lists the words that changed. Summaries and excerpts are much shorter files that quote or restate a longer one, anchored by shared figures such as amounts or reference numbers. Summaries are never offered for removal.
4. **Group related files** builds HDBSCAN topic groups and retains uncertain documents as noise. Keyword labels remain visible alongside local Qwen interpretations.
5. **Approvals** shows proposed moves, renames and soft-deletes. Approve and execute are separate actions. Undo verifies the moved file's hash before restoring it.
6. **System** checks model integrity, extraction issues and the audit chain.

### Features added in October 2026

- **Ask your library** (Search → Ask your library) answers a question from your indexed files. Hybrid search finds up to five passages; identical copies are merged into one passage. A passage found only by meaning must reach a cosine of 0.25, and word matches alone count only when the question contains an identifier such as `INV-2026-0142`. The local Qwen model writes at most three sentences and must cite passage numbers it was given. If the model is off, slow or breaks that contract, the two sentences closest in meaning to the question are quoted instead, each with its passage number. A question with no matching passage gets no answer rather than a guess.
- **More like this** lists the files closest in meaning to any file. It is available on search results, Ask passages, key-fact results and collection file lists.
- **Version timelines** in Duplicates chain files linked as edited versions, oldest to newest by modification date. When every version has the same file type, **Keep latest** proposes moving the older versions to recovery storage. Versions in different formats are never offered for bulk removal.
- **Batch review** in Duplicates marks every pair on the current page as Keep both or Confirmed duplicate, and **Remove extra exact copies** keeps the first file in each identical group and proposes moving the rest. Like every change to files, these proposals wait for approval in Activity and can be undone.
- **Key facts** are extracted at indexing time and back-filled for existing indexes: amounts with their currency (including درهم), dates, reference numbers, organisations with a legal suffix, and email addresses. Choose one in Search → Key fact to list every file that mentions it.
- **Search language** in Settings switches between the English model and an optional multilingual model for Arabic and more than 50 other languages. Install it once while connected with `python scripts/run.py --python scripts/bundle_models.py --multilingual` (about 470 MB). Switching rebuilds the index so that every vector comes from one model.
- **Export review report** in Settings downloads the duplicate decisions as CSV and a full HTML report (matches, collections and measured quality) that can be printed to PDF from a browser. Exports list file names only.

Development is automated; the finished product deliberately retains the specification's human approval gate for changes to source files. It never automatically deletes documents based on a model score.

## Configure folders and limits

Edit `config.toml`. Relative paths resolve against that file's directory. Keep the data and model folders outside every source root.

You can also connect folders directly from the sidebar, Settings, or Organize. Connections persist without restarting. In **Organize → Choose files**, filter by several source folders and select individual files across them. Filenames include a compact folder label to distinguish files with the same name.

```toml
[paths]
roots = ["demo", "/absolute/path/to/documents"]
data = "data"
models = "models"
```

Mounted external drives can be roots. Unavailable roots are reported without declaring all their files deleted. Rescan manually to detect changes. Symlinks are excluded, and the application's trash folders are not ingested.

Defaults: 50 MB input cap, 100-page extraction range, 120-second parser deadline, archive depth 3, 500 archive members, 100 MB cumulative expanded content. Oversize files retain searchable metadata. Parser failures are retried once, then quarantined in the index without moving the source. Changing the file permits a fresh scan.

## Command line

```sh
python scripts/run.py --python -m app.cli --help
python scripts/run.py --python -m app.cli scan
python scripts/run.py --python -m app.cli index
# After changing model or extraction settings:
python scripts/run.py --python -m app.cli index --rebuild
# Retry temporary extraction failures without editing source files:
python scripts/run.py --python -m app.cli index --retry-failed
python scripts/run.py --python -m app.cli dedupe
python scripts/run.py --python -m app.cli cluster
python scripts/run.py --python -m app.cli search 'INV-2026-0142'
python scripts/run.py --python -m app.cli search 'group documents by meaning' --mode semantic
python scripts/run.py --python -m app.cli export --format json
python scripts/run.py --python -m app.cli models verify
python scripts/run.py --python -m app.cli audit verify
python scripts/run.py --python -m app.cli eval run
python scripts/run.py --python -m app.cli ask 'Which invoice is due in thirty days?'
python scripts/run.py --python -m app.cli similar demo/finance-1.txt
python scripts/run.py --python -m app.cli facts demo/finance-1.txt
python scripts/run.py --python -m app.cli report --format html > report.html
```

Use `--config /path/to/config.toml` before the subcommand for a separate corpus/index. Exports print to stdout; UI exports download locally. The core search function also supports root, type, date, cluster and tag filters.

```sh
python scripts/run.py --python -m app.cli propose move /source/file.txt --dst /source/new-name.txt
python scripts/run.py --python -m app.cli approve 1
python scripts/run.py --python -m app.cli apply 1
python scripts/run.py --python -m app.cli undo 1
python scripts/run.py --python -m app.cli recover
```

`delete` is always a move into `<root>/.file-intel-trash/<action-id>/`. There is no permanent-purge command. Cross-volume moves and overwrites are refused. Recovery reconciles interrupted filesystem operations against the durable action intent and the file hash.

## Offline installation

Prepare a complete wheel bundle for the destination operating system, processor and Python 3.12 version, together with its `wheels/manifest.json` and matching `requirements.lock`.

```sh
python scripts/install.py --offline
python scripts/run.py
```

The installer verifies wheel hashes and uses `--no-index`; it never overwrites an existing environment. Choose a fresh name with `--env .venv-new` if needed, then launch it with `python scripts/run.py --env .venv-new`. The originally included compiled wheels are for one processor/platform combination and are not a universal offline installer.

To install the interface alone, use `python scripts/install.py --ui-only`. AI indexing requires the full dependencies and verified local models. Setup verifies models and fails if they are absent or altered. Developers can prepare missing models while connected with `python scripts/bundle_models.py`; this rewrites the manifest and should be done deliberately.

## Validation and limitations

```sh
python scripts/run.py --python -m pytest -q
python scripts/run.py --python -m ruff check app ui eval tests scripts
```

`eval/report.json` contains precision and recall for all four match types, a comparison between the version detector and a plain cosine-threshold baseline, adjusted Rand index with a cluster-size sweep, MRR, recall and nDCG for keyword, semantic and hybrid search, and throughput. **Settings → Quality report** shows the latest results in the app. The 24-document synthetic English corpus now includes an edited version, a summary, an excerpt and same-topic distractors, but it is still small and cannot establish real-world or multilingual accuracy. Read [Validation](VALIDATION.md) for tested behavior and scope.

- MiniLM is the English-focused default. No claim is made about Arabic retrieval quality.
- RAR/7z and audio/video are metadata-only. Email attachment names are retained; attachment-content extraction is not enabled.
- Optional v2 features such as watchdog, SQLCipher, MinHash, NER and sqlite-vec are not required by this build and are not installed as application capabilities.
- Similarity is computed with blockwise NumPy matrix products, and only pairs above a 0.70 cosine floor receive the slower wording checks. The comparison is still quadratic in the number of documents, so there is no claim of a 100,000-file performance benchmark.
- Version and summary detection are transparent heuristics (word 3-gram overlap, content-word coverage and shared figures), not a trained model. A summary that repeats no amount or identifier is not detected, and two documents derived from the same source can be linked to each other.
- The audit chain detects edits to retained rows. It is not a digital signature and cannot defeat someone who can rewrite the whole database and recompute the chain.
- The Python network guard is defense in depth, not an operating-system sandbox for native libraries. Tests exercise offline paths; disconnecting the machine provides the strongest runtime guarantee.
- For strict local privacy, use non-synced local folders and OS disk encryption. A cloud-synced source or project folder may be synchronized independently by the operating system.

Project code is MIT licensed. Dependencies and model weights retain their original licences; see [Third-party licenses](THIRD_PARTY.json) and the wheel/model metadata.
# Content and date folder organization

Open **Organize** to preview a new folder under a configured source root. Choose content topic, date, topic/date, date/topic, or a single folder. Content groups use document embeddings across file formats; refresh them in **Clusters** after files change. Date folders use local last-modified dates, formatted as `YYYY-MM`, `YYYY-MM-DD`, `YYYY/MM`, or `YYYY`.

**Same content** creates one folder for each group of at least two selected files with identical, completely extracted text. Markdown, TXT, and PDF files can share a group. Whitespace and Unicode composition are normalized; text changes remain separate. Images, styling, and metadata are not compared by this mode. Incomplete or empty extractions are excluded. No topic model or LLM is needed to prepare this plan, and dates never divide an identical-text group. All original formats are retained.

Create move proposals from the preview, then approve and execute them in **Approvals**. Destination folders are created as moves execute. Existing filenames are preserved with numeric suffixes on collisions. Undo restores each file; empty destination folders remain. Files already under the selected destination and files with pending actions are skipped. Archive members stay inside their archive. Unclustered files are optional.

## Cross-format sample verification

`demo/content-check/` contains six files in three folders: the same garden project as Markdown, TXT, and PDF, an additional byte-identical TXT copy, a revised project, and an unrelated recipe. Run the real parser/model and move/undo check with:

```sh
python scripts/run.py --python -m pytest tests/test_content_samples_integration.py -q
```

The test uses copies in a separate temporary index, denies application socket connections, and writes `output/content-check/verification.json` only after all assertions pass. It tests reading all six files, matching the four originals, excluding the revision and recipe from the same-content folder, search, actual moves from three folders into one, undo, incremental scanning, and retrying an unreadable file.

## Keep the runtime outside cloud sync

Cloud services can offload dependencies and source files, causing startup delays or extraction timeouts. The launcher keeps its bytecode cache in the operating system's temporary directory. For a fully local runtime, use the installed project environment to run `scripts/prepare_local_runtime.py`:

```sh
python scripts/run.py --python scripts/prepare_local_runtime.py --check
python scripts/run.py --python scripts/prepare_local_runtime.py
python scripts/run.py
```

The helper copies installed packages and verified models to a project-specific cache under the current user's home directory. It does not download packages, move source documents, or make a runtime portable between computers. The destination is calculated at runtime; no username is fixed in code.

## Moving the project

Paths within the project are saved relative to `config.toml`. Home-folder connections are saved with `~`, which expands to the current user's home folder. External drives remain explicit connections and must be reconnected if their mount path changes.

When opening an existing index after moving the project, File Intel reconnects project-local roots only if the old root is unavailable and every present source file matches its saved hash. Both Windows and POSIX stored paths are understood. Changed, missing, ambiguous or symlinked files are not silently relinked. Pending approvals and active undo locations prevent automatic relocation of that root; review those on their original computer. Historical audit records keep their original paths and remain verifiable.

For a clean deployment to another computer, use a source release with its default configuration and no existing `data/` directory. Connect the destination folders and build a fresh index. Always recreate the environment after changing computers or moving its containing directory.
