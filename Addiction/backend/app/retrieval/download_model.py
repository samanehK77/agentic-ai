"""Downloads the embedding model files at the pinned revision into backend/models/all-MiniLM-L6-v2 (about 91 MB).

    python -m app.retrieval.download_model

Run it once, after `pip install -r requirements-embeddings.txt`. It is the only step that uses the network; the model
itself is always loaded offline. The weights file is verified against the SHA-256 of the pinned revision.
"""
import hashlib
import sys

from app.retrieval.embedder import DEFAULT_MODEL_DIR, MODEL_NAME, MODEL_REVISION, WEIGHTS_FILE, WEIGHTS_SHA256

FILES = [
    "model.safetensors", "config.json", "modules.json", "sentence_bert_config.json", "1_Pooling/config.json",
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
]


def main() -> int:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface-hub is not installed. Run: pip install -r requirements-embeddings.txt", file=sys.stderr)
        return 2
    print(f"Downloading {MODEL_NAME} at revision {MODEL_REVISION[:8]} into {DEFAULT_MODEL_DIR.name}/ ...")
    snapshot_download(repo_id=MODEL_NAME, revision=MODEL_REVISION, local_dir=str(DEFAULT_MODEL_DIR), allow_patterns=FILES)
    digest = hashlib.sha256((DEFAULT_MODEL_DIR / WEIGHTS_FILE).read_bytes()).hexdigest()
    if digest != WEIGHTS_SHA256:
        print("The downloaded weights do not match the pinned SHA-256. Delete the folder and try again.", file=sys.stderr)
        return 1
    print("Done. Weights verified (SHA-256 matches the pinned revision).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
