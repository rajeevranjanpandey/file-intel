# Tool and model selection

Researched 10 September 2026 against the supplied 25-page v2 architecture review and the primary sources linked below. There were no Markdown inputs in the source folder; the provided design prompt was a TXT file. The PDF text is retained in `source-specification.txt` for traceability.

## Decisions

| Role | Selected | Why | Licence |
|---|---|---|---|
| Content detection | Magika | Uses file bytes; small bundled classifier; no cloud lookup | Apache-2.0 |
| Structured extraction | Docling | One adapter for Office/PDF/HTML/images; structure and page provenance | MIT |
| OCR | RapidOCR, ONNX Runtime | Open-source, no operating-system OCR service or external binary | Apache-2.0 / MIT |
| Embeddings | all-MiniLM-L6-v2, Sentence Transformers | 384 dimensions; roughly 90 MB weights; adequate English retrieval baseline | Apache-2.0 |
| Chunking | Docling HybridChunker | Uses the same local tokenizer as embeddings | MIT |
| Similarity and clustering | NumPy + scikit-learn HDBSCAN | No vector database server; unknown group count; explicit noise | BSD-3-Clause |
| Local interpretation | Qwen3-0.6B Q8_0 GGUF via llama-cpp-python | Publisher-supplied small model; only names, summaries and tags | Apache-2.0 / MIT |
| Persistence | SQLite + FTS5 | Transactions, keyword search, vectors, journal, audit in one logical database | Public domain |
| Interface | Streamlit + Typer | Single Python application; local browser UI and batch CLI | Apache-2.0 / MIT |

The user's request for smaller models takes precedence over the PDF's 1.7B default. Qwen3-0.6B is a size-first choice, not a claim that it outperforms 1.7B models. The official GGUF repository provides Q8_0; retaining that publisher artifact avoids trusting an arbitrary third-party quantization. No cloud language-model service or API key is used.

MiniLM is an English-focused default. The PDF's multilingual-e5-small profile is intentionally not bundled: it adds hundreds of megabytes. Arabic and other languages may extract correctly while retrieval quality remains weaker. A multilingual deployment needs its own bundle and evaluation; the current report does not claim multilingual search accuracy.

Docling is the largest necessary dependency. Replacing it with a lightweight PDF-only parser would reduce installation size but lose the supplied specification's OCR, tables and heterogeneous document requirements. No Tika, Java, Ollama, FAISS, Qdrant, or separate application frontend was added. Streamlit includes its own bundled browser assets; no Node build step is needed.

## Primary references

- [Magika repository and licence](https://github.com/google/magika)
- [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [Docling offline artifacts and remote-service controls](https://docling-project.github.io/docling/usage/advanced_options/)
- [Docling chunking concepts](https://docling-project.github.io/docling/concepts/chunking/)
- [RapidOCR](https://github.com/RapidAI/RapidOCR)
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [Sentence Transformers local loading API](https://sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)
- [Qwen official 0.6B GGUF model card](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF)
- [Qwen3 technical report](https://arxiv.org/abs/2505.09388)
- [llama-cpp-python installation and constrained generation](https://github.com/abetlen/llama-cpp-python)
- [HDBSCAN API](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)
- [SQLite FTS5](https://sqlite.org/fts5.html)
- [Streamlit configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)

## Measurement and interpretation

`eval/report.json` records measurements from the reproducible 24-document English synthetic corpus. It reports each match tier separately and compares the version detector with a cosine-threshold sweep on the same pairs. Search is measured with hit@5, MRR@10, recall@10 and nDCG@10 for keyword, semantic and hybrid modes. On the harder queries, hybrid search had the highest nDCG and recall, but ten queries cannot support a significance claim. ARI measures agreement with the predefined topic labels, and a sweep over the minimum cluster size is included alongside noise counts and purity.

No model was trained on this corpus. The semantic threshold is the PDF's 0.93 default, not an independently calibrated optimum. Expand the labelled corpus and use held-out queries before making dissertation claims about generalization. Model-generated labels are interpretations, not evidence of document truth.

## Reproducibility

Exact package versions are in `requirements.lock`; platform wheels are in `wheels/`. `models/manifest.json` records artifact inventories, hashes, model revisions and source/licence identifiers. Installing on another operating system requires its own wheel bundle. The application itself never invokes either package installation or model downloading.

## Apple CPU runtime correction

The tested `llama-cpp-python` 0.3.35 build file forcibly sets `GGML_METAL` on for Apple platforms, overriding the usual build flag. Its context initialization failed in the restricted environment. The local build script changes that setting to off, retains CPU Accelerate, and gives the wheel the distinct version `0.3.35+cpu`. The resulting wheel contains no Metal libraries, loads Qwen successfully, and is included in the offline bundle. The patch is limited to build configuration; the language model weights are unchanged. See the [upstream versioned CMake file](https://github.com/abetlen/llama-cpp-python/blob/v0.3.35/CMakeLists.txt).

Model licence detail: Docling the software is MIT. The bundled Heron layout weights declare Apache-2.0; the TableFormer bundle declares **CDLA-Permissive-2.0**, an open data/model licence. These are recorded separately in the model manifest. See the bundled model cards and [Docling model bundle](https://huggingface.co/docling-project/docling-models).
