#!/usr/bin/env python3
"""
Embedding 服务：接收文本，返回向量
依赖: pip install sentence-transformers
用法: echo '{"texts": ["文本"], "model": "bge-small"}' | python3 scripts/embed.py

支持的模型:
  bge-small  - BAAI/bge-small-zh-v1.5  (~100MB, 512维)  轻量快速
  m3e-base   - moka-ai/m3e-base         (~400MB, 768维)  中等均衡
  bge-m3     - BAAI/bge-m3              (~2.3GB, 1024维) 多语言最强
"""
import os
import sys
import json
import time

# 使用国内镜像下载模型（必须在import sentence_transformers之前设置）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'

from sentence_transformers import SentenceTransformer

MODELS = {
    "bge-small": {
        "name": "BAAI/bge-small-zh-v1.5",
        "size": "~100MB",
        "dim": 512,
    },
    "m3e-base": {
        "name": "moka-ai/m3e-base",
        "size": "~400MB",
        "dim": 768,
    },
    "bge-m3": {
        "name": "BAAI/bge-m3",
        "size": "~2.3GB",
        "dim": 1024,
    },
}

_model = None
_current_model_key = None

def get_model(model_key: str):
    global _model, _current_model_key

    if model_key not in MODELS:
        raise ValueError(f"未知模型: {model_key}，可选: {list(MODELS.keys())}")

    if _model is None or _current_model_key != model_key:
        model_name = MODELS[model_key]["name"]
        print(f"正在加载模型: {model_name} ({MODELS[model_key]['size']})...", file=sys.stderr)
        t0 = time.time()
        _model = SentenceTransformer(model_name)
        load_time = time.time() - t0
        print(f"模型加载完成，耗时 {load_time:.1f}s", file=sys.stderr)
        _current_model_key = model_key

    return _model

def main():
    input_data = json.loads(sys.stdin.read())
    texts = input_data["texts"]
    model_key = input_data.get("model", "bge-small")

    model = get_model(model_key)

    t0 = time.time()
    vectors = model.encode(texts).tolist()
    embed_time = time.time() - t0

    result = {
        "vectors": vectors,
        "dim": len(vectors[0]) if vectors else 0,
        "model": model_key,
        "model_name": MODELS[model_key]["name"],
        "embed_time_ms": round(embed_time * 1000, 1),
    }
    print(json.dumps(result))

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass

if __name__ == "__main__":
    main()
