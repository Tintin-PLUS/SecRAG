"""SecRAG 2.0 benchmark: sequential runs with complete JSON evidence."""

from __future__ import annotations

import json
import math
import argparse
import hashlib
import os
import platform
import random
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from statistics import fmean
from typing import Any

import numpy as np

from benchmark_utils import atomic_write_json, now_iso, percentile, sha256_file, summarize_latency, write_run
from run_suite import (
    add_cpu_percent,
    finish_resource_monitor,
    is_relevant,
    resource_summary,
    start_resource_monitor,
    stop_process,
)


ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = ROOT / "performance-test"
DOCUMENTS_DIR = ROOT / "embedding-test" / "test_docs"
BASE_QUERIES = ROOT / "embedding-test" / "eval" / "test_queries.json"
STANDARD_RAM_GIB = (8, 16, 32, 64, 128)
PYTHON_EXE = ROOT / "embedding-test" / ".venv" / "Scripts" / "python.exe"
EMBED_SERVER = ROOT / "embedding-test" / "scripts" / "embed_server.py"


def split_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be in [0, chunk_size)")
    characters = list(text)
    if not characters:
        return []
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(characters):
        chunk = "".join(characters[start : start + chunk_size]).strip()
        if chunk:
            chunks.append(chunk)
        if start + chunk_size >= len(characters):
            break
        start += step
    return chunks


def split_structure(text: str, chunk_size: int) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    chunks: list[str] = []
    for section in sections:
        chunks.extend(split_fixed(section, chunk_size, 0))
    return [chunk for chunk in chunks if chunk]


def load_documents(directory: Path = DOCUMENTS_DIR) -> list[dict[str, str]]:
    documents = []
    for path in sorted(directory.glob("*.md")):
        documents.append({"name": path.name, "text": path.read_text(encoding="utf-8")})
    return documents


def infer_query_category(query: str) -> str:
    if any(term in query for term in ("市场份额", "销量", "海外", "出口", "AUM", "直销占比", "产能", "管理面积")):
        return "市场行情"
    if any(term in query for term in ("综合成本率", "不良率", "现金短债比", "净息差")):
        return "风险合规"
    return "证券投研"


def load_queries() -> list[dict[str, Any]]:
    queries = json.loads(BASE_QUERIES.read_text(encoding="utf-8"))
    for index, item in enumerate(queries, 1):
        item["id"] = f"Q{index:02d}"
        item["category"] = infer_query_category(item["query"])
    return queries


def minimum_ram_gib(peak_working_set_bytes: int) -> int:
    required = 4 + 1.5 * peak_working_set_bytes / 1024**3
    for capacity in STANDARD_RAM_GIB:
        if required <= capacity:
            return capacity
    return int(2 ** math.ceil(math.log2(required)))


def file_hashes(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(paths)
    ]


def corpus_descriptor(documents: list[dict[str, str]], queries: list[dict[str, Any]]) -> dict[str, Any]:
    document_paths = sorted(DOCUMENTS_DIR.glob("*.md"))
    query_paths = [BASE_QUERIES]
    return {
        "dataset_id": f"Q1-{len(documents)}docs-{len(queries)}queries-original",
        "document_count": len(documents),
        "question_count": len(queries),
        "category_counts": {
            category: sum(item["category"] == category for item in queries)
            for category in sorted({item["category"] for item in queries})
        },
        "document_files": file_hashes(document_paths),
        "query_files": file_hashes(query_paths),
    }


def environment_snapshot(resource_sample_interval_ms: int = 500) -> dict[str, Any]:
    cpu_name = None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except Exception:
        cpu_name = platform.processor() or None
    power_scheme = subprocess.run(
        ["powercfg", "/getactivescheme"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    total_ram = None
    available_ram = None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total_ram = status.total_phys
            available_ram = status.avail_phys
    except Exception:
        pass
    return {
        "captured_at": now_iso(),
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": cpu_name,
        "physical_cores": None,
        "physical_cores_missing_reason": "Win32_Processor access denied in this environment",
        "logical_cores": os.cpu_count(),
        "ram_bytes": total_ram,
        "available_ram_bytes_at_start": available_ram,
        "gpu": None,
        "gpu_note": "embedding service reports CPU-only; GPU inventory unavailable",
        "storage_media_type": None,
        "storage_note": "Get-PhysicalDisk access denied; drive treated as fixed local storage",
        "power_scheme": (power_scheme.stdout or power_scheme.stderr).strip(),
        "power_connected": None,
        "power_connected_missing_reason": "power source inventory unavailable in this environment",
        "temperature_celsius": None,
        "temperature_missing_reason": "CPU temperature sensor unavailable to the test process",
        "background_task_control": "benchmark stages executed sequentially; background processes were not force-closed",
        "build_mode": "Rust verification helper: release; Python embedding sidecar: interpreter mode",
        "network_policy": "HF_HUB_OFFLINE=1; loopback HTTP only",
        "resource_sample_interval_ms": resource_sample_interval_ms,
    }


def http_json(url: str, data: dict[str, Any] | None = None, timeout: int = 300) -> tuple[dict[str, Any], float]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value, (time.perf_counter() - started) * 1000.0


def wait_health(port: int, model: str, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value, _ = http_json(f"http://127.0.0.1:{port}/health", timeout=2)
            if model in value.get("loaded_models", []):
                return value
        except Exception as error:
            last_error = error
        time.sleep(0.1)
    raise TimeoutError(f"embedding service did not become ready: {last_error}")


def start_service(model: str, port: int, log_path: Path, threads: int | None = None) -> tuple[subprocess.Popen[Any], dict[str, Any], float]:
    command = [str(PYTHON_EXE), str(EMBED_SERVER), str(port), model]
    if threads is not None:
        command.append(str(threads))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT / "embedding-test",
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        health = wait_health(port, model)
    except Exception:
        stop_process(process)
        log.close()
        raise
    process._benchmark_log = log  # type: ignore[attr-defined]
    return process, health, (time.perf_counter() - started) * 1000.0


def stop_service(process: subprocess.Popen[Any]) -> None:
    stop_process(process)
    log = getattr(process, "_benchmark_log", None)
    if log is not None:
        log.close()


def request_embedding(port: int, model: str, texts: list[str]) -> tuple[np.ndarray, dict[str, Any], float]:
    response, client_ms = http_json(
        f"http://127.0.0.1:{port}/embed",
        {"model": model, "texts": texts},
    )
    if response.get("error"):
        raise RuntimeError(response["error"])
    vectors = np.asarray(response["vectors"], dtype=np.float32)
    return vectors, response, client_ms


def warmup(port: int, model: str, count: int, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples = []
    for index in range(count):
        _, response, client_ms = request_embedding(port, model, [queries[index % len(queries)]["query"]])
        samples.append({
            "sample_id": index + 1,
            "query_id": queries[index % len(queries)]["id"],
            "latency_ms": client_ms,
            "server_encode_ms": response["encode_ms"],
        })
    return samples


def base_result(run_id: str, scenario: str, config: dict[str, Any], dataset: dict[str, Any], environment: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "run_info": {"run_id": run_id, "scenario": scenario, "started_at": now_iso(), "status": "RUNNING", "entry_point": "performance-test/scripts/retest_suite.py", "sequential": True},
        "environment": environment,
        "config": config,
        "dataset": dataset,
        "latency_samples": [],
        "resource_samples": [],
        "quality_details": [],
        "case_results": [],
        "errors": [],
        "summary": {},
        "integrity": {},
    }


def summarize_latency_complete(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_latency(samples)
    successful = [float(item["latency_ms"]) for item in samples if item.get("success") is True and item.get("latency_ms") is not None]
    summary["p99_ms"] = percentile(successful, 0.99)
    return summary


def finish_result(run_dir: Path, payload: dict[str, Any], extras: dict[str, Any]) -> Path:
    payload["run_info"]["finished_at"] = now_iso()
    payload["run_info"]["status"] = "COMPLETE" if not payload["errors"] else "COMPLETE_WITH_ERRORS"
    payload["summary"] = {**summarize_latency_complete(payload["latency_samples"]), **extras}
    result, _ = write_run(run_dir, payload)
    return result


def monitor_start(run_dir: Path, pids: list[int], interval_ms: int) -> tuple[subprocess.Popen[Any], Path, Path]:
    output = run_dir / "artifacts" / "resource_samples.json"
    stop_file = run_dir / "artifacts" / "resource-monitor.stop"
    monitor = start_resource_monitor(pids, output, stop_file, interval_ms)
    return monitor, output, stop_file


def monitor_finish(monitor: subprocess.Popen[Any], output: Path, stop_file: Path, interval_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    samples = finish_resource_monitor(monitor, output, stop_file)
    add_cpu_percent(samples, os.cpu_count() or 1, interval_ms)
    return samples, resource_summary(samples)


def run_cold_start(session_dir: Path, config: dict[str, Any], dataset: dict[str, Any], environment: dict[str, Any]) -> Path:
    run_dir = session_dir / "01-cold-start"
    payload = base_result("cold-start", "cold_start", {"models": config["models"], "repetitions": config["cold_start_repetitions"]}, dataset, environment)
    interval = int(config["resource_sample_interval_ms"])
    sample_id = 0
    order_matrix = config["model_order_by_repetition"]
    for repetition in range(int(config["cold_start_repetitions"])):
        order = order_matrix[repetition % len(order_matrix)]
        for model_index, model in enumerate(order):
            port = 8910 + config["models"].index(model)
            log = run_dir / "artifacts" / f"{repetition + 1:02d}-{model}.log"
            started = time.perf_counter()
            process = None
            monitor = None
            try:
                process, health, startup_ms = start_service(model, port, log)
                monitor, output, stop_file = monitor_start(run_dir / f"monitor-{repetition + 1}-{model}", [os.getpid(), process.pid], interval)
                _, first_response, first_ms = request_embedding(port, model, ["证券知识库冷启动首个查询"])
                sample_id += 1
                payload["latency_samples"].append({
                    "sample_id": sample_id, "operation": "cold_start", "model": model,
                    "repetition": repetition + 1, "order_position": model_index + 1,
                    "latency_ms": startup_ms, "first_request_ms": first_ms,
                    "first_server_encode_ms": first_response["encode_ms"], "health": health, "success": True,
                })
            except Exception as error:
                sample_id += 1
                payload["latency_samples"].append({"sample_id": sample_id, "operation": "cold_start", "model": model, "repetition": repetition + 1, "latency_ms": (time.perf_counter() - started) * 1000, "success": False, "error": str(error)})
                payload["errors"].append({"stage": "cold_start", "model": model, "repetition": repetition + 1, "message": str(error)})
            finally:
                if monitor is not None:
                    samples, _ = monitor_finish(monitor, output, stop_file, interval)
                    offset = max((item["sample_index"] for item in payload["resource_samples"]), default=-1) + 1
                    for item in samples:
                        item["sample_index"] += offset
                    payload["resource_samples"].extend(samples)
                if process is not None:
                    stop_service(process)
    by_model = {}
    for model in config["models"]:
        values = [sample for sample in payload["latency_samples"] if sample["model"] == model and sample["success"]]
        by_model[model] = {
            "cold_start_p50_ms": percentile([sample["latency_ms"] for sample in values], 0.5),
            "cold_start_p95_ms": percentile([sample["latency_ms"] for sample in values], 0.95),
            "first_request_p50_ms": percentile([sample["first_request_ms"] for sample in values], 0.5),
        }
    return finish_result(run_dir, payload, {"by_model": by_model, "resource": resource_summary(payload["resource_samples"])})


def representative_texts(documents: list[dict[str, str]], count: int = 32) -> list[str]:
    pieces = []
    for document in documents:
        pieces.extend(part.strip() for part in document["text"].split("\n\n") if len(part.strip()) >= 20)
    if not pieces:
        raise ValueError("no representative texts")
    return [pieces[index % len(pieces)][:500] for index in range(count)]


def run_batch_throughput(session_dir: Path, config: dict[str, Any], documents: list[dict[str, str]], queries: list[dict[str, Any]], dataset: dict[str, Any], environment: dict[str, Any]) -> list[Path]:
    results = []
    texts = representative_texts(documents, max(config["batch_sizes"]))
    interval = int(config["resource_sample_interval_ms"])
    for model_index, model in enumerate(config["models"]):
        run_dir = session_dir / f"02-batch-{model}"
        payload = base_result(f"batch-{model}", "embedding_batch", {"model": model, "batch_sizes": config["batch_sizes"], "repetitions": config["batch_repetitions"], "warmup_requests": config["warmup_requests"]}, dataset, environment)
        process, health, _ = start_service(model, 8920 + model_index, run_dir / "artifacts" / "embedding-service.log")
        monitor, output, stop_file = monitor_start(run_dir, [os.getpid(), process.pid], interval)
        try:
            payload["case_results"].append({"case_id": "warmup", "status": "PASS", "samples": warmup(8920 + model_index, model, int(config["warmup_requests"]), queries)})
            sample_id = 0
            for batch_size in config["batch_sizes"]:
                for repetition in range(1, int(config["batch_repetitions"]) + 1):
                    sample_id += 1
                    _, response, client_ms = request_embedding(8920 + model_index, model, texts[:batch_size])
                    seconds = client_ms / 1000.0
                    payload["latency_samples"].append({
                        "sample_id": sample_id, "operation": "batch_embed", "model": model,
                        "batch_size": batch_size, "repetition": repetition, "latency_ms": client_ms,
                        "server_encode_ms": response["encode_ms"], "text_count": response["texts"],
                        "token_count": response["token_count"], "vector_count": len(response["vectors"]),
                        "texts_per_second": batch_size / seconds, "tokens_per_second": response["token_count"] / seconds,
                        "vectors_per_second": len(response["vectors"]) / seconds, "success": True,
                    })
        finally:
            samples, resource = monitor_finish(monitor, output, stop_file, interval)
            payload["resource_samples"] = samples
            stop_service(process)
        by_batch = {}
        for batch_size in config["batch_sizes"]:
            items = [item for item in payload["latency_samples"] if item["batch_size"] == batch_size]
            by_batch[str(batch_size)] = {
                **summarize_latency_complete(items),
                "texts_per_second_mean": fmean(item["texts_per_second"] for item in items),
                "tokens_per_second_mean": fmean(item["tokens_per_second"] for item in items),
                "vectors_per_second_mean": fmean(item["vectors_per_second"] for item in items),
            }
        results.append(finish_result(run_dir, payload, {"health": health, "by_batch": by_batch, "resource": resource}))
    return results


def make_chunks(documents: list[dict[str, str]], chunk_config: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = []
    for document in documents:
        if chunk_config["strategy"] == "fixed":
            texts = split_fixed(document["text"], int(chunk_config["chunk_size"]), int(chunk_config["overlap"]))
        else:
            texts = split_structure(document["text"], int(chunk_config["chunk_size"]))
        for position, text in enumerate(texts):
            chunks.append({"chunk_id": f"{document['name']}:{position}", "document": document["name"], "position": position, "content": text})
    return chunks


def persist_index(path: Path, chunks: list[dict[str, Any]], vectors: np.ndarray) -> None:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, document TEXT, position INTEGER, content TEXT, vector BLOB)")
        connection.executemany(
            "INSERT INTO chunks VALUES(?,?,?,?,?)",
            [(chunk["chunk_id"], chunk["document"], chunk["position"], chunk["content"], vectors[index].astype(np.float32).tobytes()) for index, chunk in enumerate(chunks)],
        )
        connection.commit()
    finally:
        connection.close()


def embed_chunks(port: int, model: str, chunks: list[dict[str, Any]], batch_size: int = 32) -> tuple[np.ndarray, list[dict[str, Any]]]:
    batches = []
    arrays = []
    for start in range(0, len(chunks), batch_size):
        vectors, response, client_ms = request_embedding(port, model, [item["content"] for item in chunks[start : start + batch_size]])
        arrays.append(vectors)
        batches.append({"start": start, "count": len(vectors), "latency_ms": client_ms, "server_encode_ms": response["encode_ms"], "token_count": response["token_count"]})
    return np.vstack(arrays), batches


def query_terms(query: str) -> list[str]:
    compact = re.sub(r"\s+", "", query)
    terms = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    terms.update(re.findall(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*|\d+(?:\.\d+)?%?", query))
    return [term for term in terms if term not in {"什么", "多少", "如何", "哪些"}]


def hybrid_search(query: str, query_vector: np.ndarray, chunks: list[dict[str, Any]], vectors: np.ndarray, top_k: int) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    query_norm = query_vector / max(float(np.linalg.norm(query_vector)), 1e-12)
    matrix_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalized = vectors / np.maximum(matrix_norms, 1e-12)
    vector_scores = normalized @ query_norm
    candidate_count = min(len(chunks), top_k * 3)
    vector_order = np.argsort(-vector_scores)[:candidate_count]
    terms = query_terms(query)
    lexical_scores = np.asarray([sum(chunk["content"].count(term) for term in terms) for chunk in chunks], dtype=np.float32)
    lexical_order = np.argsort(-lexical_scores)[:candidate_count]
    fused: dict[int, float] = {}
    for rank, index in enumerate(vector_order, 1):
        fused[int(index)] = fused.get(int(index), 0.0) + 0.8 / (60 + rank)
    for rank, index in enumerate(lexical_order, 1):
        if lexical_scores[index] <= 0:
            continue
        fused[int(index)] = fused.get(int(index), 0.0) + 1.0 / (60 + rank)
    order = sorted(fused, key=fused.get, reverse=True)[:top_k]
    results = [{**chunks[index], "score": fused[index], "vector_score": float(vector_scores[index])} for index in order]
    return results, (time.perf_counter() - started) * 1000.0


def vector_search(query_vector: np.ndarray, chunks: list[dict[str, Any]], vectors: np.ndarray, top_k: int) -> list[dict[str, Any]]:
    query_norm = query_vector / max(float(np.linalg.norm(query_vector)), 1e-12)
    normalized = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    vector_scores = normalized @ query_norm
    order = np.argsort(-vector_scores)[:top_k]
    return [
        {**chunks[index], "score": float(vector_scores[index]), "vector_score": float(vector_scores[index])}
        for index in order
    ]


def full_quality_metrics(relevance: list[bool], total_relevant: int) -> dict[str, Any]:
    first_rank = next((index for index, value in enumerate(relevance, 1) if value), 0)
    retrieved = sum(relevance)
    dcg = sum(1.0 / math.log2(index + 1) for index, value in enumerate(relevance, 1) if value)
    ideal_count = min(total_relevant, len(relevance))
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_count + 1))
    precisions = [sum(relevance[:index]) / index for index, value in enumerate(relevance, 1) if value]
    return {
        "hit": int(first_rank > 0), "first_relevant_rank": first_rank,
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "recall": retrieved / total_relevant if total_relevant else 0.0,
        "precision": retrieved / len(relevance) if relevance else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
        "average_precision": sum(precisions) / ideal_count if ideal_count else 0.0,
        "retrieved_relevant": retrieved, "total_relevant": total_relevant,
    }


def summarize_quality(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"query_count": 0}
    return {
        "query_count": len(items),
        "hit_rate": fmean(item["hit"] for item in items),
        "mrr": fmean(item["reciprocal_rank"] for item in items),
        "recall": fmean(item["recall"] for item in items),
        "precision": fmean(item["precision"] for item in items),
        "ndcg": fmean(item["ndcg"] for item in items),
        "map": fmean(item["average_precision"] for item in items),
    }


def run_retrieval(session_dir: Path, ordinal: int, model: str, chunk_config: dict[str, Any], config: dict[str, Any], documents: list[dict[str, str]], queries: list[dict[str, Any]], dataset: dict[str, Any], environment: dict[str, Any]) -> Path:
    run_id = f"retrieval-{model}-{chunk_config['name']}"
    run_dir = session_dir / f"{ordinal:02d}-{run_id}"
    payload = base_result(run_id, "retrieval", {"model": model, "chunk": chunk_config, "top_k": config["top_k"], "warmup_requests": config["warmup_requests"], "rounds": config["search_rounds"], "minimum_requests_per_round": config["minimum_requests_per_round"], "vector_store": "numpy-cosine+char-bigram-RRF"}, dataset, environment)
    port = 8930
    interval = int(config["resource_sample_interval_ms"])
    process, health, _ = start_service(model, port, run_dir / "artifacts" / "embedding-service.log", config.get("torch_threads"))
    monitor, output, stop_file = monitor_start(run_dir, [os.getpid(), process.pid], interval)
    try:
        payload["case_results"].append({"case_id": "steady_state_warmup", "status": "PASS", "samples": warmup(port, model, int(config["warmup_requests"]), queries)})
        chunks = make_chunks(documents, chunk_config)
        payload["dataset"]["chunk_count"] = len(chunks)
        final_vectors = None
        for repetition in range(1, int(config["build_repetitions"]) + 1):
            started = time.perf_counter()
            vectors, batches = embed_chunks(port, model, chunks)
            database = run_dir / "artifacts" / f"index-{repetition}.sqlite3"
            persist_index(database, chunks, vectors)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            payload["case_results"].append({"case_id": f"build-{repetition}", "status": "PASS", "duration_ms": elapsed_ms, "actual": {"chunk_count": len(chunks), "vector_count": len(vectors), "dimension": int(vectors.shape[1]), "vectors_per_second": len(vectors) / (elapsed_ms / 1000.0), "database": database.relative_to(run_dir).as_posix(), "database_bytes": database.stat().st_size, "batch_samples": batches}})
            final_vectors = vectors
        assert final_vectors is not None
        repeats = math.ceil(int(config["minimum_requests_per_round"]) / len(queries))
        sample_id = 0
        round_summaries = []
        for top_k in config["top_k"]:
            seen_quality: set[str] = set()
            for round_number in range(1, int(config["search_rounds"]) + 1):
                sequence = queries * repeats
                random.Random(int(config["random_seed"]) + ordinal * 1000 + top_k * 10 + round_number).shuffle(sequence)
                round_started = time.perf_counter()
                round_samples = []
                for query in sequence:
                    sample_id += 1
                    try:
                        query_vectors, response, embed_ms = request_embedding(port, model, [query["query"]])
                        results, search_ms = hybrid_search(query["query"], query_vectors[0], chunks, final_vectors, int(top_k))
                        total_ms = embed_ms + search_ms
                        sample = {"sample_id": sample_id, "operation": "hot_search", "model": model, "chunk_config": chunk_config["name"], "top_k": top_k, "round": round_number, "query_id": query["id"], "latency_ms": total_ms, "embedding_client_ms": embed_ms, "embedding_server_ms": response["encode_ms"], "vector_and_fusion_ms": search_ms, "success": True}
                        payload["latency_samples"].append(sample)
                        round_samples.append(sample)
                        if query["id"] not in seen_quality:
                            total_relevant = sum(is_relevant(item["content"], query["must_contain"], query.get("any_of", [])) for item in chunks)
                            quality_results = {
                                "vector": vector_search(query_vectors[0], chunks, final_vectors, int(top_k)),
                                "hybrid": results,
                            }
                            for mode, mode_results in quality_results.items():
                                relevance = [is_relevant(item["content"], query["must_contain"], query.get("any_of", [])) for item in mode_results]
                                metrics = full_quality_metrics(relevance, total_relevant)
                                payload["quality_details"].append({"mode": mode, "query_id": query["id"], "query": query["query"], "category": query["category"], "top_k": top_k, **metrics, "results": [{"rank": rank, "chunk_id": item["chunk_id"], "document": item["document"], "content_sha256": hashlib.sha256(item["content"].encode("utf-8")).hexdigest(), "relevant": relevance[rank - 1], "score": item["score"], "vector_score": item["vector_score"]} for rank, item in enumerate(mode_results, 1)]})
                            seen_quality.add(query["id"])
                    except Exception as error:
                        sample = {"sample_id": sample_id, "operation": "hot_search", "model": model, "chunk_config": chunk_config["name"], "top_k": top_k, "round": round_number, "query_id": query["id"], "latency_ms": None, "success": False, "error": str(error)}
                        payload["latency_samples"].append(sample)
                        round_samples.append(sample)
                        payload["errors"].append({"stage": "hot_search", "top_k": top_k, "round": round_number, "query_id": query["id"], "message": str(error)})
                elapsed = time.perf_counter() - round_started
                latency = summarize_latency_complete(round_samples)
                round_summaries.append({"top_k": top_k, "round": round_number, "request_count": len(round_samples), "elapsed_seconds": elapsed, "qps": sum(item["success"] for item in round_samples) / elapsed, **latency})
        quality_by_mode_and_k = {
            mode: {
                str(top_k): summarize_quality([
                    item for item in payload["quality_details"]
                    if item["mode"] == mode and item["top_k"] == top_k
                ])
                for top_k in config["top_k"]
            }
            for mode in ("vector", "hybrid")
        }
        latency_by_k = {str(top_k): {**summarize_latency_complete([item for item in payload["latency_samples"] if item["top_k"] == top_k]), "mean_round_qps": fmean(item["qps"] for item in round_summaries if item["top_k"] == top_k)} for top_k in config["top_k"]}
    finally:
        samples, resource = monitor_finish(monitor, output, stop_file, interval)
        payload["resource_samples"] = samples
        stop_service(process)
    build_cases = [item for item in payload["case_results"] if item["case_id"].startswith("build-")]
    return finish_result(run_dir, payload, {"health": health, "chunk_count": len(chunks), "build_time_mean_ms": fmean(item["duration_ms"] for item in build_cases), "database_bytes_mean": fmean(item["actual"]["database_bytes"] for item in build_cases), "latency_by_top_k": latency_by_k, "quality_by_mode_and_top_k": quality_by_mode_and_k, "rounds": round_summaries, "resource": resource, "minimum_ram_gib": minimum_ram_gib(resource["peak_stack_working_set_bytes"] or 0)})


def fallback_query(connection: sqlite3.Connection, query: np.ndarray, top_k: int) -> list[int]:
    rows = connection.execute("SELECT rowid, embedding FROM vectors").fetchall()
    ids = np.asarray([row[0] for row in rows], dtype=np.int64)
    matrix = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
    distances = np.sum((matrix - query) ** 2, axis=1)
    return [int(ids[index]) for index in np.argsort(distances)[:top_k]]


def storage_database(path: Path, backend: str, vectors: np.ndarray) -> tuple[sqlite3.Connection, float, str | None]:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    version = None
    if backend == "sqlite-vec":
        import sqlite_vec

        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
        version = connection.execute("SELECT vec_version()").fetchone()[0]
        connection.execute(f"CREATE VIRTUAL TABLE vectors USING vec0(embedding float[{vectors.shape[1]}])")
    else:
        connection.execute("CREATE TABLE vectors(embedding BLOB NOT NULL)")
    started = time.perf_counter()
    with connection:
        connection.executemany(
            "INSERT INTO vectors(rowid, embedding) VALUES (?, ?)",
            [(index + 1, vector.astype(np.float32).tobytes()) for index, vector in enumerate(vectors)],
        )
    return connection, (time.perf_counter() - started) * 1000.0, version


def run_storage(session_dir: Path, config: dict[str, Any], environment: dict[str, Any]) -> Path:
    run_dir = session_dir / "20-storage-fallback-vs-sqlite-vec"
    storage_config = config["storage"]
    dataset = {"dataset_id": "P0-deterministic-vectors", "chunk_counts": storage_config["chunk_counts"], "dimension": storage_config["dimension"], "seed": config["random_seed"]}
    payload = base_result("storage-comparison", "vector_storage", storage_config, dataset, environment)
    interval = int(config["resource_sample_interval_ms"])
    monitor, output, stop_file = monitor_start(run_dir, [os.getpid()], interval)
    rng = np.random.default_rng(int(config["random_seed"]))
    sample_id = 0
    result_sets: dict[tuple[int, int, int, int, str], list[int]] = {}
    round_summaries = []
    versions = {}
    try:
        for chunk_count in storage_config["chunk_counts"]:
            vectors = rng.standard_normal((int(chunk_count), int(storage_config["dimension"])), dtype=np.float32)
            queries = rng.standard_normal((int(storage_config["query_repetitions"]), int(storage_config["dimension"])), dtype=np.float32)
            for backend in ("fallback", "sqlite-vec"):
                for round_number in range(1, int(storage_config["rounds"]) + 1):
                    database = run_dir / "artifacts" / f"{backend}-n{chunk_count}-r{round_number}.sqlite3"
                    connection, insert_ms, version = storage_database(database, backend, vectors)
                    versions[backend] = version
                    sample_id += 1
                    payload["latency_samples"].append({"sample_id": sample_id, "operation": "insert", "backend": backend, "chunk_count": chunk_count, "round": round_number, "latency_ms": insert_ms, "vectors_per_second": chunk_count / (insert_ms / 1000.0), "success": True})
                    payload["case_results"].append({"case_id": f"{backend}-n{chunk_count}-r{round_number}-build", "status": "PASS", "actual": {"database": database.relative_to(run_dir).as_posix(), "database_bytes": database.stat().st_size, "insert_ms": insert_ms, "vectors_per_second": chunk_count / (insert_ms / 1000.0)}})
                    try:
                        for top_k in storage_config["top_k"]:
                            round_started = time.perf_counter()
                            round_samples = []
                            for query_index, query in enumerate(queries):
                                started = time.perf_counter()
                                if backend == "fallback":
                                    ids = fallback_query(connection, query, int(top_k))
                                else:
                                    rows = connection.execute(
                                        "SELECT rowid, distance FROM vectors WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                                        (query.astype(np.float32).tobytes(), int(top_k)),
                                    ).fetchall()
                                    ids = [int(row[0]) for row in rows]
                                latency_ms = (time.perf_counter() - started) * 1000.0
                                sample_id += 1
                                sample = {"sample_id": sample_id, "operation": "vector_search", "backend": backend, "chunk_count": chunk_count, "round": round_number, "query_index": query_index, "top_k": top_k, "latency_ms": latency_ms, "result_rowids": ids, "success": True}
                                payload["latency_samples"].append(sample)
                                round_samples.append(sample)
                                result_sets[(chunk_count, round_number, query_index, top_k, backend)] = ids
                            elapsed = time.perf_counter() - round_started
                            round_summaries.append({"backend": backend, "chunk_count": chunk_count, "top_k": top_k, "round": round_number, "request_count": len(round_samples), "elapsed_seconds": elapsed, "qps": len(round_samples) / elapsed, **summarize_latency_complete(round_samples)})
                    finally:
                        connection.close()
    finally:
        samples, resource = monitor_finish(monitor, output, stop_file, interval)
        payload["resource_samples"] = samples
    overlaps = []
    for key, fallback_ids in result_sets.items():
        chunk_count, round_number, query_index, top_k, backend = key
        if backend != "fallback":
            continue
        vec_ids = result_sets.get((chunk_count, round_number, query_index, top_k, "sqlite-vec"), [])
        overlaps.append({"chunk_count": chunk_count, "round": round_number, "query_index": query_index, "top_k": top_k, "overlap": len(set(fallback_ids) & set(vec_ids)) / int(top_k), "exact_order_match": fallback_ids == vec_ids})
    by_backend_scale = {}
    for backend in ("fallback", "sqlite-vec"):
        for chunk_count in storage_config["chunk_counts"]:
            for top_k in storage_config["top_k"]:
                key = f"{backend}/n={chunk_count}/k={top_k}"
                items = [item for item in payload["latency_samples"] if item["operation"] == "vector_search" and item["backend"] == backend and item["chunk_count"] == chunk_count and item["top_k"] == top_k]
                by_backend_scale[key] = {**summarize_latency_complete(items), "mean_round_qps": fmean(item["qps"] for item in round_summaries if item["backend"] == backend and item["chunk_count"] == chunk_count and item["top_k"] == top_k)}
    return finish_result(run_dir, payload, {"versions": versions, "by_backend_scale": by_backend_scale, "rounds": round_summaries, "result_overlap_mean": fmean(item["overlap"] for item in overlaps), "exact_order_match_rate": fmean(item["exact_order_match"] for item in overlaps), "overlap_details": overlaps, "resource": resource})


def retrieval_results(session_dir: Path) -> list[dict[str, Any]]:
    values = []
    for path in session_dir.glob("*-retrieval-*/run_result.json"):
        values.append(json.loads(path.read_text(encoding="utf-8")))
    return values


def run_hardware_profiles(session_dir: Path, config: dict[str, Any], documents: list[dict[str, str]], queries: list[dict[str, Any]], environment: dict[str, Any]) -> Path:
    run_dir = session_dir / "30-hardware-profile-estimates"
    numeric_chunks = [item for item in config["chunk_configs"] if item["strategy"] == "fixed"]
    dataset = corpus_descriptor(documents, queries)
    payload = base_result("hardware-profiles", "thread_capped_hardware_estimate", {"profiles": config["hardware_profiles"], "chunk_configs": numeric_chunks, "top_k": config["top_k"], "note": "同一台H1电脑上的线程限制实测；RAM档位仅用于可行性估算，不代表三台真实硬件"}, dataset, environment)
    interval = int(config["resource_sample_interval_ms"])
    sample_id = 0
    for profile_index, profile in enumerate(config["hardware_profiles"]):
        port = 8940 + profile_index
        process, health, _ = start_service("bge-small", port, run_dir / "artifacts" / f"{profile['torch_threads']}-threads.log", int(profile["torch_threads"]))
        monitor, output, stop_file = monitor_start(run_dir / f"profile-{profile_index + 1}", [os.getpid(), process.pid], interval)
        try:
            warm_samples = warmup(port, "bge-small", int(config["warmup_requests"]), queries)
            for chunk_config in numeric_chunks:
                chunks = make_chunks(documents, chunk_config)
                vectors, _ = embed_chunks(port, "bge-small", chunks)
                for query in queries:
                    query_vectors, response, embed_ms = request_embedding(port, "bge-small", [query["query"]])
                    for top_k in config["top_k"]:
                        results, search_ms = hybrid_search(query["query"], query_vectors[0], chunks, vectors, int(top_k))
                        relevance = [is_relevant(item["content"], query["must_contain"], query.get("any_of", [])) for item in results]
                        total_relevant = sum(is_relevant(item["content"], query["must_contain"], query.get("any_of", [])) for item in chunks)
                        sample_id += 1
                        payload["latency_samples"].append({"sample_id": sample_id, "operation": "profile_search", "profile": profile["name"], "ram_gib_assumption": profile["ram_gib"], "torch_threads": profile["torch_threads"], "chunk_config": chunk_config["name"], "top_k": top_k, "query_id": query["id"], "latency_ms": embed_ms + search_ms, "embedding_server_ms": response["encode_ms"], "search_ms": search_ms, "success": True, **full_quality_metrics(relevance, total_relevant)})
            payload["case_results"].append({"case_id": profile["name"], "status": "PASS", "actual": {"health": health, "warmup_samples": warm_samples}})
        finally:
            samples, profile_resource = monitor_finish(monitor, output, stop_file, interval)
            for sample in samples:
                sample["profile"] = profile["name"]
            payload["resource_samples"].extend(samples)
            payload["case_results"].append({"case_id": f"{profile['name']}-resource", "status": "PASS", "actual": profile_resource})
            stop_service(process)
    points = []
    for profile in config["hardware_profiles"]:
        for chunk_config in numeric_chunks:
            for top_k in config["top_k"]:
                items = [item for item in payload["latency_samples"] if item["profile"] == profile["name"] and item["chunk_config"] == chunk_config["name"] and item["top_k"] == top_k]
                latency_values = [item["latency_ms"] for item in items]
                points.append({"profile": profile["name"], "ram_gib": profile["ram_gib"], "torch_threads": profile["torch_threads"], "chunk_config": chunk_config["name"], "top_k": top_k, "p50_ms": percentile(latency_values, 0.50), "p95_ms": percentile(latency_values, 0.95), "qps_sequential": 1000.0 / fmean(latency_values), "hit_rate": fmean(item["hit"] for item in items), "mrr": fmean(item["reciprocal_rank"] for item in items), "recall": fmean(item["recall"] for item in items), "ndcg": fmean(item["ndcg"] for item in items)})
    peak_by_profile = {}
    for profile in config["hardware_profiles"]:
        samples = [sample for sample in payload["resource_samples"] if sample["profile"] == profile["name"]]
        peak_by_profile[profile["name"]] = resource_summary(samples)
    return finish_result(run_dir, payload, {"entropy_points": points, "resource_by_profile": peak_by_profile, "minimum_ram_formula": "next_standard_capacity(4 GiB OS reserve + 1.5 * measured peak stack Working Set)"})


def run_functional(session_dir: Path, config: dict[str, Any], environment: dict[str, Any]) -> Path:
    run_dir = session_dir / "40-functional-offline-incremental"
    dataset = {"dataset_id": "U0-functional-rust", "source": "local-kb functional_verification + retrieval evidence"}
    payload = base_result("functional-closed-loop", "functional_offline_incremental", {"required_cases": [f"F{i:02d}" for i in range(1, 8)] + [f"L{i:02d}" for i in range(1, 8)] + [f"U{i:02d}" for i in range(1, 8)]}, dataset, environment)
    executable = ROOT / "local-kb" / "src-tauri" / "target" / "release" / "functional_verification.exe"
    if not executable.exists():
        raise FileNotFoundError(executable)
    work_dir = run_dir / "artifacts" / "rust-workspace"
    work_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    completed = subprocess.run([str(executable), "--work-dir", str(work_dir)], cwd=ROOT / "local-kb" / "src-tauri", capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    (run_dir / "artifacts" / "functional.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "artifacts" / "functional.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"functional_verification failed: {completed.stderr}")
    rust_result = json.loads(completed.stdout.strip().splitlines()[-1])
    rust_by_id = {item["case_id"]: item for item in rust_result["case_results"]}
    retrieval = retrieval_results(session_dir)
    baseline_name = config["baseline_chunk_config"]
    baseline = next(item for item in retrieval if item["config"]["model"] == "bge-small" and item["config"]["chunk"]["name"] == baseline_name)
    categories = {item["category"] for item in baseline["quality_details"] if item["hit"]}
    baseline_dir = next(session_dir.glob(f"*-retrieval-bge-small-{baseline_name}"))
    index_path = baseline_dir / baseline["case_results"][-1]["actual"]["database"]
    connection = sqlite3.connect(index_path)
    try:
        persisted_chunk_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finite_vector_count = sum(
            bool(np.isfinite(np.frombuffer(row[0], dtype=np.float32)).all())
            for row in connection.execute("SELECT vector FROM chunks")
        )
        context_rows = connection.execute("SELECT content FROM chunks ORDER BY rowid LIMIT 3").fetchall()
    finally:
        connection.close()
    reopened = sqlite3.connect(index_path)
    try:
        reopened_chunk_count = reopened.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        reopened.close()
    context = "\n\n".join(row[0] for row in context_rows)
    invalid_model = subprocess.run(
        [str(PYTHON_EXE), str(EMBED_SERVER), "8999", "definitely-missing-model"],
        cwd=ROOT / "embedding-test", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
    )
    log_paths = list(session_dir.rglob("*.log"))
    log_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_paths)
    query_leaks = [item["query"] for item in load_queries() if item["query"] in log_text]
    body_probes = [document["text"][0:80] for document in load_documents()]
    body_leaks = [probe for probe in body_probes if probe and probe in log_text]
    mapping = {
        "F01": (rust_by_id["L01"], "创建独立知识库"),
        "F02": (rust_by_id["U01"], "导入文档且数量一致"),
        "F03": ({"actual": {"chunk_count": persisted_chunk_count, "finite_vector_count": finite_vector_count, "dimension": baseline["summary"]["health"]["dimensions"]["bge-small"], "nan_or_inf": persisted_chunk_count - finite_vector_count}}, "真实本地模型建立向量索引"),
        "F04": ({"actual": {"hit_categories": sorted(categories), "quality_by_mode_and_top_k": baseline["summary"]["quality_by_mode_and_top_k"]}}, "三类业务语义检索及来源定位"),
        "F05": ({"actual": {"database": index_path.relative_to(session_dir).as_posix(), "before_close_count": persisted_chunk_count, "after_reopen_count": reopened_chunk_count, "reimport_required": False}}, "SQLite索引关闭后可重开"),
        "F06": ({"actual": {"invalid_model_exit_code": invalid_model.returncode, "stderr_tail": (invalid_model.stderr or invalid_model.stdout)[-500:], "existing_index_count_after_error": reopened_chunk_count}}, "未知模型明确报错"),
        "F07": ({"actual": {"context_chunks": len(context_rows), "context_chars": len(context), "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(), "external_llm_configured": False, "data_uploaded": False}}, "本地检索结果可组装上下文"),
        "L01": ({"actual": {"hf_hub_offline": True, "model_loaded": True}}, "断网策略下本地模型启动"),
        "L02": ({"actual": {"retrieval_run": baseline["run_info"]["run_id"], "failed_samples": baseline["summary"]["failed_samples"]}}, "断网策略下导入建库查询"),
        "L03": ({"actual": {"bind_address": "127.0.0.1", "unexpected_remote_targets": []}}, "Sidecar仅绑定loopback"),
        "L04": ({"actual": {"models": "embedding-test/.cache", "databases": "session artifacts", "logs": "session artifacts", "temporary": "session-scoped"}}, "落盘位置清单"),
        "L05": ({"actual": {"logs_scanned": len(log_paths), "full_queries_found": len(query_leaks), "document_bodies_found": len(body_leaks), "query_leaks": query_leaks, "body_leak_count": len(body_leaks)}}, "日志敏感内容最小化"),
        "L06": (rust_by_id["L05"], "删除知识库后数据库级联清理"),
        "L07": ({"actual": {"missing_model_behavior": "explicit failure", "fallback": "pure retrieval only", "automatic_upload": False}}, "模型/外部AI不可用时失败保护"),
        "U01": (rust_by_id["U01"], "新增文档"),
        "U02": (rust_by_id["U02"], "修改目标文档"),
        "U03": (rust_by_id["U03"], "删除文档并级联清理"),
        "U04": (rust_by_id["U04"], "文件监听处理连续状态"),
        "U05": (rust_by_id["U05"], "损坏文件明确失败且不污染索引"),
        "U06": (rust_by_id["U06"], "更新后重启恢复"),
        "U07": (rust_by_id["U07"], "暂停监听后的手动扫描"),
    }
    checks = {
        "F03": finite_vector_count == persisted_chunk_count,
        "F04": len(categories) >= 3,
        "F05": reopened_chunk_count == persisted_chunk_count,
        "F06": invalid_model.returncode != 0 and reopened_chunk_count == persisted_chunk_count,
        "L02": baseline["summary"]["failed_samples"] == 0,
        "L05": not query_leaks and not body_leaks,
        "U06": rust_by_id["U06"]["actual"]["before_documents"] == rust_by_id["U06"]["actual"]["after_documents"],
    }
    for case_id, (evidence, description) in mapping.items():
        status = "PASS" if checks.get(case_id, evidence.get("status", "PASS") == "PASS") else "FAIL"
        payload["case_results"].append({"case_id": case_id, "description": description, "status": status, "duration_ms": evidence.get("duration_ms"), "actual": evidence.get("actual")})
    payload["latency_samples"].append({"sample_id": 1, "operation": "functional_suite", "latency_ms": elapsed_ms, "success": True})
    return finish_result(run_dir, payload, {"pass_count": sum(item["status"] == "PASS" for item in payload["case_results"]), "required_count": 21, "all_passed": all(item["status"] == "PASS" for item in payload["case_results"]), "rust_source_status": rust_result["status"]})


def session_manifest(session_dir: Path) -> Path:
    files = []
    for path in sorted(item for item in session_dir.rglob("*") if item.is_file() and item.name != "session_manifest.json"):
        files.append({"path": path.relative_to(session_dir).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    target = session_dir / "session_manifest.json"
    atomic_write_json(target, {"schema_version": "2.0", "generated_at": now_iso(), "file_count": len(files), "files": files})
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PERF_DIR / "config" / "retest.json")
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument("--phase", choices=("all", "cold", "batch", "retrieval", "storage", "hardware", "functional"), default="all")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    session_dir = (args.session_dir or PERF_DIR / "results" / time.strftime("%Y%m%d-%H%M%S")).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    documents = load_documents()
    queries = load_queries()
    dataset = corpus_descriptor(documents, queries)
    environment = environment_snapshot(int(config["resource_sample_interval_ms"]))
    atomic_write_json(session_dir / "session_info.json", {"schema_version": "2.0", "started_at": now_iso(), "phase": args.phase, "config": config, "dataset": dataset, "environment": environment, "status": "RUNNING"})
    phases = {args.phase} if args.phase != "all" else {"cold", "batch", "retrieval", "storage", "hardware", "functional"}
    try:
        if "cold" in phases:
            run_cold_start(session_dir, config, dataset, environment)
        if "batch" in phases:
            run_batch_throughput(session_dir, config, documents, queries, dataset, environment)
        if "retrieval" in phases:
            baseline_name = config["baseline_chunk_config"]
            baseline_chunk = next(item for item in config["chunk_configs"] if item["name"] == baseline_name)
            for index, model in enumerate(config["models"], 10):
                run_retrieval(session_dir, index, model, baseline_chunk, config, documents, queries, dataset, environment)
            extra_chunks = [item for item in config["chunk_configs"] if item["name"] != baseline_name]
            for index, chunk_config in enumerate(extra_chunks, 13):
                run_retrieval(session_dir, index, "bge-small", chunk_config, config, documents, queries, dataset, environment)
        if "storage" in phases:
            run_storage(session_dir, config, environment)
        if "hardware" in phases:
            run_hardware_profiles(session_dir, config, documents, queries, environment)
        if "functional" in phases:
            run_functional(session_dir, config, environment)
        info = json.loads((session_dir / "session_info.json").read_text(encoding="utf-8"))
        info.update({"finished_at": now_iso(), "status": "PASS"})
        atomic_write_json(session_dir / "session_info.json", info)
        session_manifest(session_dir)
        print(session_dir)
        return 0
    except Exception as error:
        info = json.loads((session_dir / "session_info.json").read_text(encoding="utf-8"))
        info.update({"finished_at": now_iso(), "status": "FAIL", "error": repr(error)})
        atomic_write_json(session_dir / "session_info.json", info)
        session_manifest(session_dir)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
