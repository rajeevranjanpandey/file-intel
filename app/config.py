from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib
from app import BASE

@dataclass
class Config:
    roots: list[Path] = field(default_factory=lambda: [BASE / 'demo'])
    data: Path = BASE / 'data'
    models: Path = BASE / 'models'
    max_file_mb: int = 50
    max_pages: int = 100
    timeout_seconds: int = 120
    archive_depth: int = 3
    archive_members: int = 500
    archive_total_mb: int = 100
    embedding_model: str = 'minilm'
    llm_model: str = 'qwen'
    semantic_threshold: float = 0.93
    min_cluster_size: int = 3
    min_samples: int = 2
    use_llm: bool = True

    def validate(self):
        self.roots = [Path(p).resolve() for p in self.roots]
        self.data, self.models = Path(self.data).resolve(), Path(self.models).resolve()
        if self.models == (BASE / 'models').resolve() and os.environ.get('FILE_INTEL_MODELS'):
            self.models = Path(os.environ['FILE_INTEL_MODELS']).resolve()
        for root in self.roots:
            if any(protected.is_relative_to(root) or root.is_relative_to(protected)
                   for protected in (self.data, self.models)):
                raise ValueError('Index and model directories must be outside source roots.')
        for key in ('max_file_mb', 'max_pages', 'timeout_seconds', 'archive_members', 'archive_total_mb', 'min_samples'):
            if getattr(self, key) < 1:
                raise ValueError(f'{key} must be positive')
        if self.archive_depth < 0 or self.min_cluster_size < 2:
            raise ValueError('archive_depth must be nonnegative and min_cluster_size at least 2')
        if not 0 < self.semantic_threshold <= 1:
            raise ValueError('Semantic threshold must be in (0, 1].')
        return self


def load(path=None):
    path = Path(path or BASE / 'config.toml').resolve()
    raw = tomllib.loads(path.read_text())
    values = {k: v for group in raw.values() for k, v in group.items()}
    values['roots'] = [(path.parent / Path(p).expanduser()).resolve() for p in values.get('roots', ['demo'])]
    for k in ('data', 'models'):
        values[k] = (path.parent / Path(values.get(k, k)).expanduser()).resolve()
    return Config(**values).validate()
