#!/usr/bin/env python3
"""
Embedding 常驻服务
模型只加载一次，后续请求直接计算
端口: 8902
"""

import json
import os
import sys
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

# 启动时预加载默认模型
print("预加载默认模型 bge-small...", flush=True)
try:
    get_model("bge-small")
    print("默认模型加载完成", flush=True)
except Exception as e:
    print(f"默认模型加载失败: {e}", flush=True)
    print("将在首次请求时重试加载", flush=True)


class EmbedHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req = json.loads(body)

            texts = req.get("texts", [])
            model_key = req.get("model", "bge-small")

            if not texts:
                response = json.dumps({"vectors": [], "dim": 0})
            else:
                model = get_model(model_key)
                vectors = model.encode(texts, show_progress_bar=False).tolist()
                dim = len(vectors[0]) if vectors else 0
                response = json.dumps({"vectors": vectors, "dim": dim})

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
            response = json.dumps({"status": "ok", "loaded_models": loaded})
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8902
    print(f"Embedding服务启动: http://127.0.0.1:{port}", flush=True)
    print(f"可用模型: {list(MODEL_MAP.keys())}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), EmbedHandler)
    server.serve_forever()
