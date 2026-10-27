# Validation and scope

This report separates working implementation evidence from optional features and unmeasured claims. The source requirements were the supplied 25-page architecture review. The product is an offline personal-file application for a single user, not a secure multi-user service.

Final regression: **22 tests passed in 50.26 seconds**. The separately installed offline environment passed its 21-test run before the final additional cross-root move regression. Ruff, dependency consistency, model integrity, wheel integrity and audit verification all passed. Saved logs are in `verification/`.

October 2026 update: the suite now holds 58 tests. All 58 passed on a Linux x86-64 Python 3.12 environment built from `requirements.lock` with the same pinned MiniLM and Qwen model files, including the local-model tests. Run the full suite once more on the destination computer before submission.

## Verified behavior

- A fresh Python 3.12 virtual environment installed the locked dependencies using only `wheels/` with `--no-index`.
- The deployable bundle contains 127 wheels and a SHA-256 inventory. The local CPU llama.cpp build is versioned `0.3.35+cpu`.
- The demo index contains 26 logical documents, including an archive child. Sources are not modified by indexing.
- Real PDF, wrong-extension PDF, DOCX, XLSX, PPTX, HTML and image-OCR fixtures extract and produce chunks. Tables are retained for spreadsheets. OCR retrieves the invoice token from a rendered image.
- Plain text, JSON, RFC822 email body/headers, and ZIP child extraction are exercised. Archive traversal members are blocked. A corrupt PDF is attempted twice, then recorded as failed/quarantined without moving it.
- Incremental rescans skip unchanged files. Missing files disappear from current retrieval. Offline/unmounted roots are reported without treating their content as deleted.
- Three duplicate tiers remain distinct and store evidence. Semantic candidates show matching chunk excerpts and cosine scores.
- HDBSCAN preserves noise; class-based TF-IDF supplies deterministic labels. Qwen produced valid JSON labels for all five non-noise demo clusters: Pasta Recipes, NLP Research, Annual Financial Report and two invoice groups.
- The browser dashboard and invoice search were visually checked. Search found spreadsheet, PDF and scanned-image evidence, with page references.
- Tests cover read-only root boundaries, symlink rejection, model tampering, unmanifested model files, outbound socket/DNS blocking, audit-chain edits, approval gating, overwrite prevention, source-change rejection, undo, interrupted-action recovery and literal archive-path matching.
- The real model tests block outbound connections. Spawned extraction and generation workers install their own guard; the strict test mode also refuses loopback connections inside those workers.

## Evaluation

The reproducible evaluation corpus contains 24 English synthetic documents across finance, NLP and cooking. The original 15 documents are unchanged. Nine harder documents were added: an audit report, an edited final version, an executive summary, an excerpt, a different company's audit that shares most of the vocabulary, a research paper with its abstract, retrieval notes and an unrelated recipe. There are 10 queries. Three use exact identifiers and four are paraphrases with little word overlap. Ground-truth pairs and relevance labels are declared in `eval/corpus.py`, not inferred from the vectors. Copies are treated as one family, so a summary of a file that has three copies counts once.

| Metric | Measured result |
|---|---:|
| Tier 1 (exact bytes) precision / recall | 1.00 / 1.00 (1 pair) |
| Tier 2 (same text) precision / recall | 1.00 / 1.00 (2 pairs) |
| Tier 3 (edited version) precision / recall | 1.00 / 1.00 (2 pairs) |
| Tier 4 (summary or excerpt) precision / recall | 0.83 / 1.00 (5 pairs) |
| Version detector, tiers 3 and 4 together, F1 | 0.93 |
| Cosine threshold 0.93 alone, same pairs, F1 | 0.44 (recall 0.29) |
| Best cosine threshold chosen on this corpus (0.74 to 0.78), F1 | 0.93 |
| Adjusted Rand index (min cluster size 3) | 0.58 |
| Cluster purity, including noise as a group | 1.00 |
| Hybrid search MRR@10 / nDCG@10 / recall@10 | 0.83 / 0.85 / 1.00 |
| Keyword search MRR@10 / nDCG@10 / recall@10 | 0.83 / 0.76 / 0.92 |
| Semantic search MRR@10 / nDCG@10 / recall@10 | 0.65 / 0.72 / 0.90 |
| Indexing time, 24 files, cloud Linux CPU | 46 seconds |
| Ask your library, extractive mode: questions answered | 9 of 10 |
| Ask your library, extractive mode: cited passages from a relevant file | 0.60 |

The single tier 4 false positive links the executive summary to the excerpt. Both restate the same audit and share its figures, but neither was written from the other.

A single cosine threshold only matches the relation detector when the threshold is tuned on the test pairs themselves, which is optimistic. It also cannot say which file is the summary or show what changed. Hybrid search reached the best nDCG and recall here, but ten queries are too few for a significance claim. The cluster sweep in `report.json` reaches ARI 1.00 at a minimum cluster size of 5. The default stays at 3, because a value tuned on 24 files would hide small real groups in a personal library. Throughput includes model and parser start-up and depends on hardware. LLM naming is not measured by these metrics.

## Feature checks added in October 2026

- **Ask with the local model.** On the demo library, offline, Qwen3-0.6B answered "Which invoice is due in thirty days and how much is it?" with "The invoice INV-2026-0142 is due in thirty days and is worth 4200 AED", citing passages 1 and 2. A question with no matching passage ("What is the capital of France?") returned no answer. An integration test checks that an answer is written by the model, cites the invoice file and repeats a figure or date from it. In an earlier run, before the prompt asked for exact figures, the model left out the amount and attributed the payment to the wrong party. Small-model answers should therefore be read together with the cited passages, which the app always shows.
- **Extractive Ask** is measured in `eval/report.json`. 40% of cited passages came from files outside the relevance labels, mostly same-topic neighbours. The model was not run in the evaluation.
- **Arabic and cross-language search.** Three test files (an Arabic invoice, an Arabic recipe and an English budget) were indexed with each model. With the multilingual model the English query "pasta recipe with tomatoes" ranked the Arabic recipe first (cosine 0.51), and the Arabic query "طبخ المعكرونة" also ranked it first (0.53). With the English MiniLM model the same English query scored the Arabic recipe at 0.01, so cross-language search does not work without the multilingual model. Key-fact extraction read "5000 درهم" as 5000 AED.
- **Key facts, version timelines, batch review, More like this and the report** are covered by `tests/test_features.py`, including spreadsheet-formula protection in the CSV, skipped proposals for archive members and already-pending files, and a check that proposals never move files.

## Explicit limits and deviations

- Qwen3-0.6B Q8 replaces the specification's larger 1.7B Q4 suggestion to honor the user's size preference.
- The original compiled wheel inventory is platform-specific. The portable source uses a per-computer installer; destination operating systems and processors require their own integration tests and offline wheel inventory.
- Legacy DOC/XLS/PPT, OpenDocument, EPUB and MSG have Docling routes, but are not covered by the current real-file fixture set. They are not claimed as validated. RAR/7z and audio/video are deliberately metadata-only.
- Email attachment names are listed; attachment text extraction is not implemented. Non-English search, optional NER, filesystem watchers, MinHash and SQLCipher are outside the delivered default profile.
- Oversized input files retain metadata instead of partially reading arbitrary binary formats. PDF page-range extraction is capped. Pathological documents can still fail rather than produce useful partial content.
- Exhaustive vectors are read from SQLite into NumPy; no memory-mapped vector cache or sqlite-vec upgrade is implemented. Pair enumeration remains quadratic. The PDF's suggested 50,000/100,000-file speed targets were not measured.
- The action executor refuses cross-volume moves and destination overwrites. Permanent purge is intentionally absent, preserving reversibility of all supported actions.
- Audit hashing is tamper-evidence for retained records, not authentication. The manifest is a local trust inventory, not a publisher signature. Filesystem races against a malicious process running as the same OS user are outside this application's security guarantee.
- Python connection blocking and offline flags are not equivalent to an OS firewall for arbitrary native code. No claim is made that unit tests prove the absence of every possible native network syscall. All required artifacts are local, so disconnecting internet does not remove a runtime dependency.

The detailed package inventory is in `THIRD_PARTY.json`, measured machine-readable metrics in `../eval/report.json`, and source selection rationale in `RESEARCH.md`.

## October 3, 2026 portability checks

- 58 tests passed with `python -m pytest -q -m "not integration" -p no:cacheprovider`; eight model integration tests were excluded from that selection.
- The full suite was attempted with `-x` and stopped at `test_real_cross_format_grouping_and_multi_folder_move` because `sentence_transformers` is not installed in the local interface environment. Full AI processing is not certified by these checks.
- Code validation and shared-launcher checks passed. The live dashboard rendered device-neutral wording and project-relative filename locations.
- Copying settings between different user folders, expanding `~`, and hash-verified index relocation from Windows and POSIX paths are covered by the regression checks. Historical audit hashes remain unchanged.
- Windows folder dispatch and environment layout are tested by simulation. The Windows launcher, native folder dialog and complete AI pipeline still require acceptance testing on an actual Windows computer.
- The current copied library reconnected 33 indexed entries to the current project root; the audit chain verified after relocation. Source documents were not moved.

The online dependency plan also completed successfully on the local Intel system with `pip install --dry-run -r requirements.txt`. This verifies dependency resolution, not native-library compilation or a complete AI runtime installation.
