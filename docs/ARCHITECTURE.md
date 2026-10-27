# Implementation architecture

The supplied PDF's six-module modular monolith is retained. There are no cloud connectors or separate inference services.

| Module | Implementation | Boundary |
|---|---|---|
| Discover | `app/discover.py` | Allow-list, stat short-circuit, streamed byte hash, Magika content type |
| Extract | `app/extract.py`, `app/canonical.py` | Bounded parser workers; Docling/std-library result becomes CanonicalDocument |
| Represent | `app/represent.py` | NFC and whitespace normalization, local MiniLM, normalized mean document vectors, KeyBERT-style phrases |
| Analyze | `app/analyze.py`, `app/llm.py`, `app/local_model.py` | Four match tiers (bytes, normalized text, edited version, summary or excerpt), HDBSCAN, class-based TF-IDF, bounded JSON interpretation |
| Store | `app/store.py`, `app/search.py` | SQLite tables, FTS5 triggers, float32 vectors, hybrid RRF search |
| Interact | `app/cli.py`, `ui/app.py`, `ui/discover.py`, `app/actions.py`, `app/report.py` | Dashboard, review queues, Ask your library, More like this, exports, CLI, approved reversible executor |
| Facts | `app/facts.py` | Rule-based amounts, dates, references, organisations and emails stored as tags with source `fact` |
| Guard | `app/__init__.py`, `app/guard.py` | Offline flags before third-party imports, capability checksum checks, read-only opener, external connection blocking |

The pipeline orchestrator exchanges canonical documents and database rows. The representer never imports Docling. The pure labelling module imports only JSON and regular-expression utilities; it receives a generation function and has no filesystem or database access. Native inference is run in a separate process with a 90-second deadline. Invalid output, missing models, timeouts and native failures retain keyword labels and generate audit events.

Extraction workers are recycled after eight files, with a per-job wall-clock deadline and a CPU-time ceiling. Archives are read from bounded byte streams without extracting member paths onto the filesystem. Traversal names, links, oversized members and excessive depth are rejected; parent-child provenance is persisted.

Model verification is capability-scoped: embeddings must verify before indexing/search, and layout/OCR models verify before PDF/image extraction. Missing LLM assets disable interpretation but preserve deterministic clustering. No runtime route tries to repair a missing model by downloading it.

`files` represents physical sources and virtual archive children. `documents` stores logical content. `chunks` and `embeddings` preserve chunk provenance and the exact embedding revision. The remaining tables hold duplicate evidence, cluster runs/members, tags, action intents, scan statistics, model metadata and the audit chain. SQLite WAL/SHM files may exist while the app runs; there is one logical database, not literally one physical file at every instant.

Keyword results use FTS5 BM25. Semantic results use cosine similarity of normalized vectors. Reciprocal-rank fusion uses 1/(60+rank), then groups by document. Exact filename matches also contribute. Filters are applied to the eligible documents before rank fusion.

## Course learning outcome evidence

| Outcome | Evidence |
|---|---|
| CLO-1: normalization and classification | Unicode normalization tests; Magika wrong-extension fixture; local tokenizer chunking |
| CLO-2: practical NLP pipelines | Real PDF/Office/image/archive fixtures through canonical content, representations and analysis |
| CLO-3: pretrained models and local LLM | MiniLM/GGUF manifest, isolated local generation, JSON validation |
| CLO-4: system design and ethics | Offline install, guard, allow-list, human approval, reversible execution |
| CLO-5: transparency and evaluation | Duplicate excerpts, keyword vs LLM labels, audit verification and reproducible metrics |

## Match tiers

Tiers 1 and 2 group documents by byte hash and by normalized-text hash, so they need no pairwise comparison. Tiers 3 and 4 start from document vectors. Cosine similarity is computed in blocks of 512 rows, and only pairs at or above 0.70 are examined further.

For each candidate pair the relation detector compares word 3-grams in both directions. If the shorter document is at most 70% of the longer one, it is labelled an excerpt when at least 60% of its 3-grams occur in the longer text, or a summary when cosine is at least 0.75, at least 30% of its content words occur in the longer text and it repeats at least one figure (a token with digits, excluding bare years). Otherwise the pair is an edited version when at least half of the 3-grams survive in both directions, or when cosine reaches the configured semantic threshold. Edited versions store up to three word-level changes from `difflib`, and semantic matches keep their two best chunk pairs as evidence. Existing review decisions are carried over when the analysis is rerun.

## Ask your library

`app/ask.py` retrieves passages with the same hybrid search, filters weak matches (cosine below 0.25, or word-only matches when the question has no identifier) and merges identical copies. The local model runs in the same isolated, time-limited process as cluster naming (`LocalAnswerer` in `app/local_model.py`) with a JSON grammar of `answer` and `citations`. `validate()` rejects empty or over-long answers and any citation outside the supplied passage numbers. Rejections fall back to an extractive answer: passage sentences ranked by cosine to the question, deduplicated and kept in reading order. The model never sees file paths and has no file, database or action access.
