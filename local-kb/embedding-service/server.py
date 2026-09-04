#!/usr/bin/env python3
"""Local KB SentenceTransformer sidecar.

The service owns tokenizer/model/pooling/normalization. Rust owns chunk identity,
compatibility validation, persistence, retrieval, and RAG orchestration.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_BATCH_SIZE = int(os.getenv("LOCAL_KB_EMBEDDING_MAX_BATCH_SIZE", "128"))
ENCODE_BATCH_SIZE = int(os.getenv("LOCAL_KB_EMBEDDING_ENCODE_BATCH_SIZE", "32"))
OFFLINE = os.getenv("LOCAL_KB_EMBEDDING_OFFLINE", "1").lower() not in {"0", "false", "no"}

if OFFLINE:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "bge-small": {
        "model_name": "BAAI/bge-small-zh-v1.5",
        "model_version": "v1.5",
        "dimension": 512,
        "config_hash": "st-bge-small-zh-v1.5-f32-normalized-model-pooling-v1",
        "path_env": "LOCAL_KB_MODEL_BGE_SMALL",
    },
    "m3e-base": {
        "model_name": "moka-ai/m3e-base",
        "model_version": "configured",
        "dimension": 768,
        "config_hash": "st-m3e-base-f32-normalized-model-pooling-v1",
        "path_env": "LOCAL_KB_MODEL_M3E_BASE",
    },
    "bge-m3": {
        "model_name": "BAAI/bge-m3",
        "model_version": "configured",
        "dimension": 1024,
        "config_hash": "st-bge-m3-f32-normalized-model-pooling-v1",
        "path_env": "LOCAL_KB_MODEL_BGE_M3",
    },
}

MODELS: dict[str, Any] = {}
MODEL_LOCKS = {model_id: threading.Lock() for model_id in MODEL_CONFIGS}


def model_info(model_id: str) -> dict[str, Any]:
    config = MODEL_CONFIGS[model_id]
    return {
        "model_id": model_id,
        "model_name": config["model_name"],
        "model_version": config["model_version"],
        "dimension": config["dimension"],
        "runtime": "python-sentence-transformers",
        "precision": "f32",
        "normalize": True,
        "pooling": "model-defined",
        "max_length": None,
        "query_prefix": None,
        "document_prefix": None,
        "config_hash": config["config_hash"],
    }


def get_model(model_id: str) -> Any:
    if model_id not in MODEL_CONFIGS:
        raise ValueError(f"unknown model '{model_id}'; supported: {list(MODEL_CONFIGS)}")
    with MODEL_LOCKS[model_id]:
        if model_id in MODELS:
            return MODELS[model_id]
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers is not installed; run scripts/setup-embedding.ps1"
            ) from error
        config = MODEL_CONFIGS[model_id]
        model_path = os.getenv(config["path_env"]) or config["model_name"]
        print(f"loading {model_id} from {model_path} (offline={OFFLINE})", flush=True)
        started = time.perf_counter()
        MODELS[model_id] = SentenceTransformer(model_path, local_files_only=OFFLINE)
        print(f"loaded {model_id} in {time.perf_counter() - started:.2f}s", flush=True)
        return MODELS[model_id]


def encode(model_id: str, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if len(texts) > MAX_BATCH_SIZE:
        raise ValueError(f"batch exceeds maximum size {MAX_BATCH_SIZE}")
    model = get_model(model_id)
    with MODEL_LOCKS[model_id]:
        vectors = model.encode(
            texts,
            batch_size=ENCODE_BATCH_SIZE,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
    result = vectors.tolist()
    expected = MODEL_CONFIGS[model_id]["dimension"]
    for vector in result:
        if len(vector) != expected:
            raise RuntimeError(
                f"model {model_id} returned dimension {len(vector)}, expected {expected}"
            )
    return result


class EmbedHandler(BaseHTTPRequestHandler):
    server_version = "LocalKBEmbedding/1.0"

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError(f"request body must be 1..{MAX_BODY_BYTES} bytes")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(
                200,
                {
                    "status": "ok",
                    "protocol_version": "1",
                    "dependency_available": importlib.util.find_spec("sentence_transformers") is not None,
                    "offline": OFFLINE,
                    "loaded_models": sorted(MODELS),
                },
            )
        elif self.path == "/v1/models":
            self._json(200, {"models": [model_info(key) for key in MODEL_CONFIGS]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            request = self._read_json()
            if self.path == "/v1/embeddings":
                self._v1_embeddings(request)
            elif self.path == "/embed":
                self._legacy_embeddings(request)
            else:
                self._json(404, {"error": "not found"})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:  # service boundary: report and keep serving
            traceback.print_exc()
            self._json(500, {"error": str(error)})

    def _v1_embeddings(self, request: dict[str, Any]) -> None:
        model_id = request.get("model_id")
        inputs = request.get("inputs")
        if model_id not in MODEL_CONFIGS:
            raise ValueError(f"unknown model '{model_id}'; supported: {list(MODEL_CONFIGS)}")
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("inputs must be a non-empty array")
        texts: list[str] = []
        for item in inputs:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError("each input must be an object containing string field 'text'")
            if item.get("input_type") not in {"DOCUMENT", "QUERY"}:
                raise ValueError("input_type must be DOCUMENT or QUERY")
            texts.append(item["text"])
        started = time.perf_counter()
        vectors = encode(model_id, texts)
        info = model_info(model_id)
        outputs = []
        for item, vector in zip(inputs, vectors, strict=True):
            outputs.append(
                {
                    "request_id": item.get("request_id"),
                    "input_type": item.get("input_type"),
                    "model_info": info,
                    "vector": vector,
                    "chunk_id": item.get("chunk_id"),
                    "metadata": item.get("metadata") or {},
                }
            )
        self._json(
            200,
            {
                "model_info": info,
                "outputs": outputs,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )

    def _legacy_embeddings(self, request: dict[str, Any]) -> None:
        model_id = request.get("model", "bge-small")
        texts = request.get("texts", [])
        if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
            raise ValueError("texts must be an array of strings")
        vectors = encode(model_id, texts)
        self._json(
            200,
            {
                "model": model_id,
                "model_info": model_info(model_id),
                "vectors": vectors,
                "dim": MODEL_CONFIGS[model_id]["dimension"],
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8902)
    parser.add_argument("--preload", choices=list(MODEL_CONFIGS))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("embedding service must bind to loopback")
    if args.preload:
        get_model(args.preload)
    server = ThreadingHTTPServer((args.host, args.port), EmbedHandler)
    print(f"Local KB embedding service listening on http://{args.host}:{args.port}", flush=True)
    print(f"models={list(MODEL_CONFIGS)} offline={OFFLINE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
