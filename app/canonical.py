from dataclasses import dataclass, field

@dataclass
class CanonicalDocument:
    source_path: str
    detected_type: str
    title: str = ''
    document_id: int | None = None
    file_id: int | None = None
    parent_file_id: int | None = None
    mime_type: str = ''
    normalized_text: str = ''
    text_sha256: str = ''
    sections: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    chunks: list = field(default_factory=list)
    language: str = 'und'
    extractor: str = 'none'
    ocr_used: bool = False
    extraction_confidence: float | None = None
    extraction_status: str = 'metadata-only'
    processing_provenance: dict = field(default_factory=dict)
