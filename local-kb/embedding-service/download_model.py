#!/usr/bin/env python3
"""Explicitly download one supported model into local-kb/models."""

import argparse
from pathlib import Path

from sentence_transformers import SentenceTransformer

MODELS = {
    "bge-small": "BAAI/bge-small-zh-v1.5",
    "m3e-base": "moka-ai/m3e-base",
    "bge-m3": "BAAI/bge-m3",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id", choices=MODELS)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {MODELS[args.model_id]} to {destination}")
    model = SentenceTransformer(MODELS[args.model_id], local_files_only=False)
    model.save(str(destination))
    print(f"Saved {args.model_id} to {destination}")


if __name__ == "__main__":
    main()
