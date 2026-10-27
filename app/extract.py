"""Docling adapters end here; only CanonicalDocument leaves this module."""
import hashlib
import io
import json
import multiprocessing
import zipfile
import tarfile
from pathlib import Path, PurePosixPath
from concurrent.futures import ProcessPoolExecutor, TimeoutError
from importlib.metadata import version
from app.canonical import CanonicalDocument
from app.guard import enable_offline, open_readonly, verify_model

STRUCTURED = {'pdf': 'pdf', 'docx': 'docx', 'xlsx': 'xlsx', 'pptx': 'pptx', 'doc': 'doc',
 'xls': 'xls', 'ppt': 'ppt', 'odt': 'odt', 'ods': 'ods', 'odp': 'odp', 'html': 'html',
 'xhtml': 'html', 'markdown': 'md', 'md': 'md', 'csv': 'csv', 'epub': 'epub',
 'png': 'png', 'jpeg': 'jpg', 'jpg': 'jpg', 'tiff': 'tiff', 'bmp': 'bmp', 'webp': 'webp',
 'rfc822': 'eml', 'eml': 'eml', 'email': 'eml', 'msg': 'msg', 'asciidoc': 'adoc', 'rtf': 'rtf'}
IMAGES = {'png', 'jpeg', 'jpg', 'tiff', 'bmp', 'webp'}


def _chunks(docling_document, config):
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from transformers import AutoTokenizer
    path, _ = verify_model(config.models, config.embedding_model)
    if not hasattr(_chunks, '_tokenizers'):
        _chunks._tokenizers = {}
    if str(path) not in _chunks._tokenizers:
        _chunks._tokenizers[str(path)] = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
    tokenizer = _chunks._tokenizers[str(path)]
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=256))
    result = []
    for chunk in chunker.chunk(dl_doc=docling_document):
        provenance = [p for item in chunk.meta.doc_items for p in getattr(item, 'prov', [])]
        result.append({'text': chunker.contextualize(chunk), 'page': provenance[0].page_no if provenance else None,
                       'section_path': ' / '.join(chunk.meta.headings or []),
                       'token_count': len(tokenizer.encode(chunker.contextualize(chunk)))})
    return result


def _structured(data, doc, config):
    from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
    from docling.datamodel.base_models import InputFormat, DocumentStream
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    options = PdfPipelineOptions(enable_remote_services=False)
    if doc.detected_type in IMAGES | {'pdf'}:
        artifacts, _ = verify_model(config.models, 'docling')
        ocr, _ = verify_model(config.models, 'ocr')
        options.artifacts_path = artifacts
        options.do_ocr = True
        options.do_table_structure = True
        options.ocr_options = RapidOcrOptions(backend='onnxruntime',
            det_model_path=str(next(ocr.glob('*det*.onnx'))),
            rec_model_path=str(next(ocr.glob('*rec*.onnx'))),
            cls_model_path=str(next(ocr.glob('*cls*.onnx'))))
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                                                   InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
    result = converter.convert(DocumentStream(name='input.' + STRUCTURED[doc.detected_type], stream=io.BytesIO(data)),
                               page_range=(1, config.max_pages), max_file_size=config.max_file_mb * 1024 ** 2,
                               raises_on_error=True)
    d = result.document
    doc.title = d.name if d.name and d.name != 'input' else doc.title
    # Plain text avoids format-specific Markdown markup in normalized-text duplicate hashes.
    doc.normalized_text = d.export_to_text()
    doc.sections = [{'text': item.text, 'label': str(item.label),
                     'pages': [p.page_no for p in getattr(item, 'prov', [])]}
                    for item, _ in d.iterate_items() if hasattr(item, 'text')]
    doc.tables = [t.model_dump(mode='json') for t in d.tables]
    doc.chunks = _chunks(d, config)
    doc.extractor = 'docling'
    doc.ocr_used = doc.detected_type in IMAGES and bool(doc.normalized_text.strip())
    for page in result.pages:
        parsed = getattr(page, 'parsed_page', None)
        if parsed and any(getattr(cell, 'from_ocr', False) for cell in getattr(parsed, 'textline_cells', [])):
            doc.ocr_used = True
    doc.metadata['ocr_enabled'] = doc.detected_type in IMAGES | {'pdf'}
    doc.processing_provenance = {'extractor_version': version('docling')}
    doc.extraction_status = 'partial' if 'partial' in str(result.status).lower() or result.input.page_count > config.max_pages else 'ok'
    return doc


def _text(data, doc, config):
    from charset_normalizer import from_bytes
    from docling_core.types.doc import DoclingDocument, DocItemLabel
    decoded = from_bytes(data).best()
    if decoded is None or '\x00' in str(decoded):
        return doc
    text = str(decoded)
    # Magika can label RFC822 messages as generic text; parse only when headers prove the structure.
    if text.startswith(('From:', 'Return-Path:', 'MIME-Version:')) and '\nSubject:' in text:
        from email import policy
        from email.parser import BytesParser
        message = BytesParser(policy=policy.default).parsebytes(data)
        doc.metadata['headers'] = dict(message.items())
        doc.metadata['attachments'] = [part.get_filename() for part in message.iter_attachments()]
        body = message.get_body(preferencelist=('plain',))
        text = body.get_content() if body else text
        doc.title = str(message.get('Subject', doc.title))
    if doc.detected_type in ('json', 'jsonl'):
        try:
            doc.metadata['structure'] = json.loads(text)
        except ValueError:
            pass
    d = DoclingDocument(name=doc.title)
    for paragraph in text.split('\n\n'):
        if paragraph.strip():
            d.add_text(label=DocItemLabel.TEXT, text=paragraph.strip())
    doc.normalized_text = text
    doc.chunks = _chunks(d, config)
    doc.sections = [{'text': text, 'label': 'text', 'pages': []}]
    doc.extractor, doc.extraction_status = 'stdlib', 'ok'
    return doc


def _member_ok(name):
    p = PurePosixPath(name)
    return not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name


def _bytes(data, path, label, config, depth=0, budget=None):
    from app.discover import detect
    budget = budget if budget is not None else {'bytes': 0, 'members': 0}
    doc = CanonicalDocument(source_path=path, detected_type=label, title=Path(path).name)
    doc.metadata.update({'byte_sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
    archive = label in ('zip', 'tar', 'gzip')
    if archive:
        if depth >= config.archive_depth:
            doc.extraction_status = 'skipped:archive-depth'
            return [doc]
        result = [doc]
        doc.extractor, doc.extraction_status = 'stdlib-archive', 'ok'
        stream = io.BytesIO(data)
        container = zipfile.ZipFile(stream) if label == 'zip' else tarfile.open(fileobj=stream, mode='r:*')
        with container:
            members = container.infolist() if label == 'zip' else container
            for item in members:
                name = item.filename if label == 'zip' else item.name
                if (item.is_dir() if label == 'zip' else item.isdir()):
                    continue
                if budget['members'] >= config.archive_members:
                    doc.extraction_status = 'partial'
                    doc.metadata['archive_limit'] = 'member-count'
                    break
                size = item.file_size if label == 'zip' else item.size
                safe = _member_ok(name) and (label == 'zip' and ((item.external_attr >> 16) & 0o170000) != 0o120000 or label != 'zip' and item.isfile())
                budget['members'] += 1
                budget['bytes'] += size
                if (not safe or size > config.max_file_mb * 1024 ** 2 or
                    budget['members'] > config.archive_members or budget['bytes'] > config.archive_total_mb * 1024 ** 2):
                    doc.extraction_status = 'partial'
                    doc.metadata.setdefault('blocked_members', []).append(name)
                    continue
                reader = container.open(item) if label == 'zip' else container.extractfile(item)
                with reader:
                    content = reader.read(size + 1)
                if len(content) > size:
                    raise ValueError('Archive size mismatch')
                child_path = path + '::' + name
                child_label, _, _ = detect(content[:1024 * 1024])
                try:
                    children = _bytes(content, child_path, child_label, config, depth + 1, budget)
                    children[0].metadata['parent_path'] = path
                    result.extend(children)
                except Exception as exc:
                    result.append(CanonicalDocument(source_path=child_path, detected_type=child_label,
                        title=name, extraction_status='failed:' + str(exc)[:300],
                        metadata={'parent_path': path, 'byte_sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}))
        return result
    if label in STRUCTURED:
        return [_structured(data, doc, config)]
    if label not in {'unknown', 'elf', 'pebin', 'macho', 'mp3', 'mp4', 'wav', 'rar', '7zip', '7z'}:
        return [_text(data, doc, config)]
    return [doc]


def _worker(path, label, config):
    enable_offline()
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (config.timeout_seconds * 8, config.timeout_seconds * 8 + 1))
    except (ImportError, ValueError):
        pass
    with open_readonly(path, config.roots) as f:
        data = f.read(config.max_file_mb * 1024 ** 2 + 1)
    if len(data) > config.max_file_mb * 1024 ** 2:
        return [CanonicalDocument(source_path=path, detected_type=label, title=Path(path).name,
                                  extraction_status='skipped:over-cap')]
    return _bytes(data, path, label, config)


class ExtractionPool:
    def __init__(self, config):
        self.config = config.validate()
        self.pool = None
    def close(self):
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)
            self.pool = None
    def run(self, file):
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'), max_tasks_per_child=8)
        future = self.pool.submit(_worker, file['path'], file['magika_label'], self.config)
        try:
            return future.result(timeout=self.config.timeout_seconds)
        except TimeoutError as exc:
            for process in list(self.pool._processes.values()):
                process.terminate()
                process.join(5)
                if process.is_alive():
                    process.kill()
            self.close()
            raise RuntimeError('Extraction timeout') from exc
        except Exception:
            self.close()
            raise


def extract(file, config, pool=None):
    owned = pool is None
    pool = pool or ExtractionPool(config)
    try:
        return pool.run(file)
    finally:
        if owned:
            pool.close()
