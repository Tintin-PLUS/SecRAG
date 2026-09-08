"""Run one configurable retrieval benchmark and emit a top-level result.json."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmark_utils import atomic_write_json, now_iso
from retest_suite import (
    PERF_DIR,
    corpus_descriptor,
    environment_snapshot,
    load_documents,
    load_queries,
    run_retrieval,
    session_manifest,
)


MODELS = ("bge-small", "m3e-base", "bge-m3")


def load_completed_result(run_result_path: Path) -> dict[str, Any]:
    return json.loads(run_result_path.read_text(encoding="utf-8"))


def build_config(
    model: str,
    chunk_size: int,
    overlap: int,
    top_k: int,
    rounds: int,
    minimum_requests_per_round: int,
    warmup_requests: int,
    build_repetitions: int,
    torch_threads: int | None,
) -> dict[str, Any]:
    if model not in MODELS:
        raise ValueError(f"model must be one of: {', '.join(MODELS)}")
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be in [0, chunk_size)")
    if min(top_k, rounds, minimum_requests_per_round, warmup_requests, build_repetitions) <= 0:
        raise ValueError("top_k, rounds, requests, warmup, and build repetitions must be positive")
    if torch_threads is not None and torch_threads <= 0:
        raise ValueError("torch_threads must be positive")
    name = f"fixed-{chunk_size}-{overlap}"
    return {
        "schema_version": "2.0-single",
        "random_seed": 20260907,
        "resource_sample_interval_ms": 500,
        "models": [model],
        "top_k": [top_k],
        "search_rounds": rounds,
        "minimum_requests_per_round": minimum_requests_per_round,
        "warmup_requests": warmup_requests,
        "build_repetitions": build_repetitions,
        "torch_threads": torch_threads,
        "baseline_chunk_config": name,
        "chunk_configs": [
            {"name": name, "strategy": "fixed", "chunk_size": chunk_size, "overlap": overlap}
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-size", type=int, required=True)
    parser.add_argument("--overlap", type=int, required=True)
    parser.add_argument("--model", choices=MODELS, default="bge-small")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--requests-per-round", type=int, default=334)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--build-repetitions", type=int, default=3)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    config = build_config(
        args.model,
        args.chunk_size,
        args.overlap,
        args.top_k,
        args.rounds,
        args.requests_per_round,
        args.warmup,
        args.build_repetitions,
        args.threads,
    )
    output_dir = (args.output_dir or PERF_DIR / "results" / "single" / time.strftime("%Y%m%d-%H%M%S")).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = load_documents()
    queries = load_queries()
    dataset = corpus_descriptor(documents, queries)
    environment = environment_snapshot(config["resource_sample_interval_ms"])
    info_path = output_dir / "session_info.json"
    atomic_write_json(info_path, {
        "schema_version": "2.0-single",
        "started_at": now_iso(),
        "status": "RUNNING",
        "config": config,
        "dataset": dataset,
        "environment": environment,
    })
    try:
        run_result_path = run_retrieval(
            output_dir,
            1,
            args.model,
            config["chunk_configs"][0],
            config,
            documents,
            queries,
            dataset,
            environment,
        )
        result = load_completed_result(run_result_path)
        atomic_write_json(output_dir / "result.json", result)
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info.update({"status": "PASS", "finished_at": now_iso(), "result_file": "result.json"})
        atomic_write_json(info_path, info)
        session_manifest(output_dir)
        print((output_dir / "result.json").resolve())
        return 0
    except Exception as error:
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info.update({"status": "FAIL", "finished_at": now_iso(), "error": repr(error)})
        atomic_write_json(info_path, info)
        session_manifest(output_dir)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
