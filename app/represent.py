import hashlib
import unicodedata
import numpy as np
from app.guard import verify_model


def normalize(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())

class Representer:
    def __init__(self, config):
        from sentence_transformers import SentenceTransformer
        path, entry = verify_model(config.models, config.embedding_model)
        self.model_id = config.embedding_model + ':' + entry['revision']
        self.model = SentenceTransformer(str(path), local_files_only=True, device='cpu', trust_remote_code=False)
        self.model.max_seq_length = 256
    def encode(self, texts):
        return self.model.encode([normalize(t) for t in texts], normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
    def represent(self, doc):
        doc.normalized_text = normalize(doc.normalized_text)
        doc.text_sha256 = hashlib.sha256(doc.normalized_text.encode()).hexdigest() if doc.normalized_text else ''
        if not doc.chunks:
            return [], None, []
        for chunk in doc.chunks:
            chunk['text'] = normalize(chunk['text'])
        vectors = self.encode([c['text'] for c in doc.chunks])
        mean = vectors.mean(axis=0)
        mean /= max(float(np.linalg.norm(mean)), 1e-12)
        # KeyBERT-style ranking using the existing model, with a bounded candidate set.
        from sklearn.feature_extraction.text import CountVectorizer
        try:
            cv = CountVectorizer(stop_words='english', ngram_range=(1, 2), max_features=100)
            cv.fit([doc.normalized_text])
            candidates = cv.get_feature_names_out()
            scores = self.encode(list(candidates)) @ mean
            tags = [str(candidates[i]) for i in np.argsort(-scores)[:8]]
        except ValueError:
            tags = []
        return vectors, mean, tags
