#!/usr/bin/env python3
"""
Embedding 常驻服务
模型只加载一次，后续请求直接计算
端口: 8902
"""

import json
import os
import sys
import time
import traceback

# 禁用代理，直连HuggingFace镜像
for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
    os.environ.pop(key, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_OFFLINE"] = "1"

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from sentence_transformers import SentenceTransformer
import torch

MODELS = {}
MODEL_MAP = {
    "bge-small": "BAAI/bge-small-zh-v1.5",
    "m3e-base":  "moka-ai/m3e-base",
    "bge-m3":    "BAAI/bge-m3",
}

def get_model(model_key):
    if model_key not in MODELS:
        path = MODEL_MAP.get(model_key, MODEL_MAP["bge-small"])
        print(f"  加载模型: {model_key} ({path})...", flush=True)
        try:
            MODELS[model_key] = SentenceTransformer(path)
            print(f"  模型 {model_key} 加载完成", flush=True)
        except Exception as e:
            print(f"  模型 {model_key} 加载失败: {e}", flush=True)
            raise
    return MODELS[model_key]

def parse_startup_args(args):
    port = int(args[0]) if args else 8902
    model_key = args[1] if len(args) > 1 else "bge-small"
    thread_count = int(args[2]) if len(args) > 2 else None
    if len(args) > 3:
        raise ValueError("用法: embed_server.py [port] [model] [torch_threads]")
    if not 1 <= port <= 65535:
        raise ValueError("端口必须在 1-65535 之间")
    if model_key not in MODEL_MAP:
        raise ValueError(f"未知模型: {model_key}")
    if thread_count is not None and thread_count < 1:
        raise ValueError("torch_threads 必须大于 0")
    return port, model_key, thread_count


class EmbedHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req = json.loads(body)

            texts = req.get("texts", [])
            model_key = req.get("model", "bge-small")

            if not texts:
                response = json.dumps({"vectors": [], "dim": 0, "token_count": 0, "encode_ms": 0.0})
            else:
                model = get_model(model_key)
                tokenized = model.tokenize(texts)
                attention_mask = tokenized.get("attention_mask")
                token_count = int(attention_mask.sum().item()) if attention_mask is not None else 0
                started = time.perf_counter()
                vectors = model.encode(texts, show_progress_bar=False).tolist()
                encode_ms = (time.perf_counter() - started) * 1000.0
                dim = len(vectors[0]) if vectors else 0
                response = json.dumps({
                    "vectors": vectors,
                    "dim": dim,
                    "token_count": token_count,
                    "encode_ms": encode_ms,
                    "texts": len(texts),
                })

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.encode())

        except Exception as e:
            error_msg = json.dumps({"error": str(e)})
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(error_msg.encode())

    def do_GET(self):
        if self.path == "/health":
            loaded = list(MODELS.keys())
            dimensions = {
                key: MODELS[key].get_sentence_embedding_dimension()
                for key in loaded
            }
            response = json.dumps({
                "status": "ok",
                "loaded_models": loaded,
                "dimensions": dimensions,
                "device": "cpu",
                "torch_threads": torch.get_num_threads(),
            })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    port, preload_model, thread_count = parse_startup_args(sys.argv[1:])
    if thread_count is not None:
        torch.set_num_threads(thread_count)
        torch.set_num_interop_threads(1)
    print(f"预加载模型 {preload_model}...", flush=True)
    try:
        get_model(preload_model)
        print(f"模型 {preload_model} 加载完成", flush=True)
    except Exception as e:
        print(f"模型 {preload_model} 加载失败: {e}", flush=True)
        print("将在首次请求时重试加载", flush=True)
    print(f"Embedding服务启动: http://127.0.0.1:{port}", flush=True)
    print(f"可用模型: {list(MODEL_MAP.keys())}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), EmbedHandler)
    server.serve_forever()
