"""Sequential SecRAG benchmark runner. Formal tests never run in parallel."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from benchmark_utils import now_iso, sha256_file, summarize_latency, write_run


ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_DIR = ROOT / "performance-test"
LOCAL_KB_TAURI = ROOT / "local-kb" / "src-tauri"
EMBEDDING_TEST = ROOT / "embedding-test"


def is_relevant(content: str, must_contain: list[str], any_of: list[str]) -> bool:
    return all(term in content for term in must_contain) and (
        not any_of or any(term in content for term in any_of)
    )


def quality_metrics(relevance: list[bool], total_relevant: int) -> dict[str, Any]:
    first_rank = next((index for index, value in enumerate(relevance, 1) if value), 0)
    retrieved_relevant = sum(relevance)
    dcg = sum(1.0 / math.log2(index + 1) for index, value in enumerate(relevance, 1) if value)
    ideal_count = min(max(total_relevant, 0), len(relevance))
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_count + 1))
    return {
        "hit": int(first_rank > 0),
        "first_relevant_rank": first_rank,
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "recall": retrieved_relevant / total_relevant if total_relevant > 0 else 0.0,
        "ndcg": dcg / idcg if idcg > 0 else 0.0,
        "retrieved_relevant": retrieved_relevant,
        "total_relevant": total_relevant,
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def command_text(command: list[str], cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    output = (completed.stdout or completed.stderr).strip()
    return output if completed.returncode == 0 else f"ERROR({completed.returncode}): {output}"


def environment_snapshot() -> dict[str, Any]:
    return {
        "captured_at": now_iso(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "python": sys.version.splitlines()[0],
        "rustc": command_text(["rustc", "--version"]),
        "cargo": command_text(["cargo", "--version"]),
        "node": command_text(["node", "--version"]),
        "npm": command_text(["npm.cmd", "--version"]),
        "git_commit": command_text(["git", "rev-parse", "HEAD"]),
        "git_status": command_text(["git", "status", "--short"]),
    }


def base_payload(run_id: str, scenario: str, config: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_info": {
            "run_id": run_id,
            "scenario": scenario,
            "status": "COMPLETE",
            "started_at": now_iso(),
            "ended_at": None,
            "timezone": str(__import__("datetime").datetime.now().astimezone().tzinfo),
        },
        "environment": environment_snapshot(),
        "config": config,
        "dataset": dataset,
        "latency_samples": [],
        "resource_samples": [],
        "quality_details": [],
        "case_results": [],
        "errors": [],
        "summary": {"total_samples": 0, "successful_samples": 0, "failed_samples": 0},
        "integrity": {
            "runner": "performance-test/scripts/run_suite.py",
            "source_sha256": {
                "run_suite.py": sha256_file(Path(__file__)),
                "benchmark_utils.py": sha256_file(Path(__file__).with_name("benchmark_utils.py")),
                "monitor_processes.ps1": sha256_file(Path(__file__).with_name("monitor_processes.ps1")),
            },
        },
    }


def http_json(url: str, method: str = "GET", data: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for(url: str, predicate=lambda value: True, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "service did not respond"
    while time.monotonic() < deadline:
        try:
            value = http_json(url, timeout=5)
            if predicate(value):
                return value
            last_error = f"unexpected response: {value}"
        except Exception as error:  # service startup is expected to refuse connections briefly
            last_error = str(error)
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def require_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"TCP port {port} is already in use; refusing a contaminated run")


def process_ids_by_name(name: str) -> set[int]:
    if platform.system() != "Windows":
        return set()
    command = (
        f"@(Get-Process -Name '{name}' -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty Id) | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return set()
    value = json.loads(completed.stdout)
    return {int(item) for item in (value if isinstance(value, list) else [value])}


def directory_size(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def model_cache_path(model: str) -> Path:
    names = {
        "bge-small": "models--BAAI--bge-small-zh-v1.5",
        "m3e-base": "models--moka-ai--m3e-base",
        "bge-m3": "models--BAAI--bge-m3",
    }
    return Path.home() / ".cache" / "huggingface" / "hub" / names[model]


def dataset_hash(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_corpus(database_path: Path) -> list[str]:
    connection = sqlite3.connect(database_path)
    try:
        return [row[0] for row in connection.execute("SELECT content FROM chunks")]
    finally:
        connection.close()


def clear_embedding_database(timeout_seconds: int = 30) -> None:
    data_dir = (EMBEDDING_TEST / "data").resolve()
    for name in ("knowledge.db", "knowledge.db-wal", "knowledge.db-shm"):
        target = (data_dir / name).resolve()
        if target.parent != data_dir:
            raise RuntimeError(f"refusing to remove path outside test data directory: {target}")
        deadline = time.monotonic() + timeout_seconds
        while target.exists():
            try:
                target.unlink()
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)


def stop_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def start_resource_monitor(pids: list[int], output: Path, stop_file: Path, interval_ms: int) -> subprocess.Popen[Any]:
    script = PERFORMANCE_DIR / "scripts" / "monitor_processes.ps1"
    ready_file = output.with_suffix(".ready")
    stop_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    process = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-PidList",
            ",".join(str(pid) for pid in pids),
            "-OutputPath",
            str(output),
            "-StopFile",
            str(stop_file),
            "-IntervalMs",
            str(interval_ms),
            "-ReadyFile",
            str(ready_file),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if ready_file.exists():
            return process
        if process.poll() is not None:
            raise RuntimeError(f"resource monitor exited before startup (code {process.returncode})")
        time.sleep(0.05)
    stop_process(process)
    raise TimeoutError("resource monitor did not become ready within 15 seconds")


def finish_resource_monitor(process: subprocess.Popen[Any], output: Path, stop_file: Path) -> list[dict[str, Any]]:
    ready_file = output.with_suffix(".ready")
    stop_file.touch()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    stop_file.unlink(missing_ok=True)
    ready_file.unlink(missing_ok=True)
    if not output.exists():
        return []
    loaded = json.loads(output.read_text(encoding="utf-8-sig"))
    return loaded if isinstance(loaded, list) else [loaded]


def add_cpu_percent(samples: list[dict[str, Any]], logical_cpus: int, interval_ms: int) -> None:
    previous: dict[int, dict[str, Any]] = {}
    for sample in sorted(samples, key=lambda value: (value["pid"], value["sample_index"])):
        prior = previous.get(sample["pid"])
        sample["cpu_pct"] = None
        if prior is not None:
            elapsed_samples = sample["sample_index"] - prior["sample_index"]
            if elapsed_samples > 0:
                cpu_delta = sample["cpu_seconds"] - prior["cpu_seconds"]
                elapsed_seconds = elapsed_samples * interval_ms / 1000.0
                sample["cpu_pct"] = max(0.0, cpu_delta / (elapsed_seconds * max(logical_cpus, 1)) * 100.0)
        previous[sample["pid"]] = sample


def resource_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_index: dict[int, list[dict[str, Any]]] = {}
    for sample in samples:
        by_index.setdefault(int(sample["sample_index"]), []).append(sample)
    working_totals = [sum(item["working_set_bytes"] for item in group) for group in by_index.values()]
    private_totals = [sum(item["private_bytes"] for item in group) for group in by_index.values()]
    cpu_values = [sample["cpu_pct"] for sample in samples if sample.get("cpu_pct") is not None]
    return {
        "peak_stack_working_set_bytes": max(working_totals, default=None),
        "peak_stack_private_bytes": max(private_totals, default=None),
        "mean_process_cpu_pct": sum(cpu_values) / len(cpu_values) if cpu_values else None,
        "peak_process_cpu_pct": max(cpu_values, default=None),
    }


def quality_summary(details: list[dict[str, Any]]) -> dict[str, float]:
    if not details:
        return {"query_count": 0, "hit_rate": 0.0, "mrr": 0.0, "mean_recall": 0.0, "mean_ndcg": 0.0}
    return {
        "query_count": len(details),
        "hit_rate": sum(item["hit"] for item in details) / len(details),
        "mrr": sum(item["reciprocal_rank"] for item in details) / len(details),
        "mean_recall": sum(item["recall"] for item in details) / len(details),
        "mean_ndcg": sum(item["ndcg"] for item in details) / len(details),
    }


def run_embedding(config: dict[str, Any], session_dir: Path, interval_ms: int) -> list[Path]:
    python_exe = EMBEDDING_TEST / ".venv" / "Scripts" / "python.exe"
    embed_script = EMBEDDING_TEST / "scripts" / "embed_server.py"
    rust_exe = EMBEDDING_TEST / "target" / "release" / "knowledge_base.exe"
    for required in (python_exe, embed_script, rust_exe):
        if not required.exists():
            raise FileNotFoundError(f"required runtime not found: {required}")

    query_file = EMBEDDING_TEST / "eval" / "test_queries.json"
    queries = load_json(query_file)
    document_files = sorted(
        path for path in (EMBEDDING_TEST / "test_docs").iterdir() if path.suffix.lower() in {".md", ".txt", ".pdf"}
    )
    data_hash = dataset_hash(document_files + [query_file])
    dimensions = {"bge-small": 512, "m3e-base": 768, "bge-m3": 1024}
    outputs: list[Path] = []

    for model_index, model in enumerate(config["models"]):
        run_id = f"embedding-{model}"
        run_dir = session_dir / run_id
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        payload = base_payload(
            run_id,
            "embedding_quality_and_latency",
            {
                "model": model,
                "dimension": dimensions.get(model),
                "top_k": config["top_k"],
                "warmup_requests": config["warmup_requests"],
                "rounds": config["rounds"],
                "repeats_per_query": config["repeats_per_query"],
                "random_seed": config["random_seed"],
                "retrieval": "BM25 + vector RRF",
                "chunk_strategy": "structure(max_size=800,min_size=100)",
                "build_mode": "release",
                "model_cache_size_bytes": directory_size(model_cache_path(model) / "snapshots"),
            },
            {
                "dataset_id": "embedding-test-Q0",
                "dataset_sha256": data_hash,
                "document_count": len(document_files),
                "query_count": len(queries),
            },
        )
        embed_process = None
        rust_process = None
        monitor_process = None
        embedding_pids: list[int] = []
        resource_output = artifacts / "resource_samples.json"
        monitor_stop = artifacts / "monitor.stop"
        embed_log = (artifacts / "embedding-service.log").open("w", encoding="utf-8")
        rust_log = (artifacts / "knowledge-base.log").open("w", encoding="utf-8")

        try:
            require_port_available(8902)
            require_port_available(8901)
            python_pids_before = process_ids_by_name("python")
            clear_embedding_database()
            embed_process = subprocess.Popen(
                [str(python_exe), str(embed_script), "8902", model],
                cwd=EMBEDDING_TEST,
                stdout=embed_log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            loaded = wait_for(
                "http://127.0.0.1:8902/health",
                lambda value: model in value.get("loaded_models", []),
                timeout_seconds=600,
            )
            embedding_pids = sorted(
                (process_ids_by_name("python") - python_pids_before) | {embed_process.pid}
            )
            payload["case_results"].append(
                {
                    "case_id": "T01",
                    "category": "technology",
                    "status": "PASS",
                    "actual": {**loaded, "monitored_pids": embedding_pids},
                }
            )

            rust_process = subprocess.Popen(
                [str(rust_exe)],
                cwd=EMBEDDING_TEST,
                stdout=rust_log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            wait_for("http://127.0.0.1:8901/api/health", timeout_seconds=60)
            monitor_process = start_resource_monitor(
                embedding_pids + [rust_process.pid], resource_output, monitor_stop, interval_ms
            )

            ingest_results = []
            for document in document_files:
                started = time.perf_counter_ns()
                response = http_json(
                    "http://127.0.0.1:8901/api/ingest",
                    "POST",
                    {"file_path": f"test_docs/{document.name}", "model": model},
                    timeout=600,
                )
                duration_ms = (time.perf_counter_ns() - started) / 1_000_000
                success = response.get("status") == "success" and "error" not in response
                ingest_results.append(
                    {
                        "file_id": document.name,
                        "success": success,
                        "duration_ms": duration_ms,
                        "chunk_count": response.get("chunk_count"),
                        "error": response.get("error"),
                    }
                )
                if not success:
                    payload["errors"].append({"stage": "ingest", "file_id": document.name, "message": response.get("error", "unknown ingest failure")})

            stats = http_json("http://127.0.0.1:8901/api/stats")
            payload["dataset"].update(stats)
            payload["case_results"].append(
                {
                    "case_id": "F02",
                    "category": "functional",
                    "status": "PASS" if all(item["success"] for item in ingest_results) else "FAIL",
                    "actual": {"documents": ingest_results},
                }
            )
            vector_complete = stats.get("chunk_count", 0) > 0 and stats.get("vector_count") == stats.get("chunk_count")
            payload["case_results"].append(
                {
                    "case_id": "F03",
                    "category": "functional",
                    "status": "PASS" if vector_complete else "FAIL",
                    "actual": stats,
                }
            )

            corpus = load_corpus(EMBEDDING_TEST / "data" / "knowledge.db")

            sample_number = 0
            for top_k in config["top_k"]:
                for warmup_index in range(int(config["warmup_requests"])):
                    query = queries[warmup_index % len(queries)]
                    try:
                        response = http_json(
                            "http://127.0.0.1:8901/api/search",
                            "POST",
                            {"query": query["query"], "top_k": top_k, "model": model},
                            timeout=300,
                        )
                        if "error" in response:
                            raise RuntimeError(response["error"])
                    except Exception as error:
                        payload["errors"].append({"stage": "warmup", "top_k": top_k, "message": str(error)})

                quality_seen: set[int] = set()
                for round_number in range(1, int(config["rounds"]) + 1):
                    sequence = [
                        (query_index, query)
                        for _ in range(int(config["repeats_per_query"]))
                        for query_index, query in enumerate(queries)
                    ]
                    random.Random(int(config["random_seed"]) + model_index * 1000 + top_k * 10 + round_number).shuffle(sequence)
                    for query_index, query in sequence:
                        sample_number += 1
                        captured_at = now_iso()
                        started = time.perf_counter_ns()
                        response: dict[str, Any] = {}
                        error_message = None
                        try:
                            response = http_json(
                                "http://127.0.0.1:8901/api/search",
                                "POST",
                                {"query": query["query"], "top_k": top_k, "model": model},
                                timeout=300,
                            )
                            if "error" in response:
                                raise RuntimeError(response["error"])
                        except Exception as error:
                            error_message = str(error)
                        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
                        success = error_message is None
                        payload["latency_samples"].append(
                            {
                                "sample_id": sample_number,
                                "captured_at": captured_at,
                                "stage": "end_to_end_search",
                                "model": model,
                                "top_k": top_k,
                                "round": round_number,
                                "query_id": query_index + 1,
                                "success": success,
                                "latency_ms": latency_ms,
                                "error": error_message,
                            }
                        )
                        if not success:
                            payload["errors"].append({"stage": "search", "top_k": top_k, "query_id": query_index + 1, "message": error_message})
                            continue

                        if query_index not in quality_seen:
                            chunks = response.get("chunks", [])
                            relevance = [is_relevant(chunk.get("content", ""), query.get("must_contain", []), query.get("any_of", [])) for chunk in chunks]
                            total_relevant = sum(
                                is_relevant(content, query.get("must_contain", []), query.get("any_of", [])) for content in corpus
                            )
                            detail = {
                                "query_id": query_index + 1,
                                "query": query["query"],
                                "top_k": top_k,
                                "must_contain": query.get("must_contain", []),
                                "any_of": query.get("any_of", []),
                                **quality_metrics(relevance, total_relevant),
                                "results": [
                                    {
                                        "rank": rank,
                                        "doc_id": chunk.get("doc_id"),
                                        "position": chunk.get("position"),
                                        "title": chunk.get("title"),
                                        "source": chunk.get("source"),
                                        "score": chunk.get("score"),
                                        "relevant": relevance[rank - 1],
                                        "content_sha256": hashlib.sha256(chunk.get("content", "").encode("utf-8")).hexdigest(),
                                    }
                                    for rank, chunk in enumerate(chunks, 1)
                                ],
                            }
                            payload["quality_details"].append(detail)
                            quality_seen.add(query_index)

            search_failures = sum(not sample["success"] for sample in payload["latency_samples"])
            payload["case_results"].append(
                {
                    "case_id": "F04",
                    "category": "functional",
                    "status": "PASS" if payload["latency_samples"] and search_failures == 0 else "FAIL",
                    "actual": {"search_samples": len(payload["latency_samples"]), "failures": search_failures},
                }
            )
            for case_id, category, reason in (
                ("L01-L07", "closed_loop", "本轮未物理断网，外联与删除残留需单独人工验证"),
                ("U01-U07", "incremental_update", "embedding-test 无文件监听/增量更新接口，需在 local-kb Demo 单独验证"),
            ):
                payload["case_results"].append({"case_id": case_id, "category": category, "status": "NOT_RUN", "actual": {"reason": reason}})

        except Exception as error:
            payload["run_info"]["status"] = "INVALID"
            payload["errors"].append({"stage": "fatal", "message": str(error)})
        finally:
            if monitor_process is not None:
                try:
                    payload["resource_samples"] = finish_resource_monitor(monitor_process, resource_output, monitor_stop)
                except Exception as error:
                    payload["errors"].append({"stage": "resource_monitor", "message": str(error)})
            stop_process(rust_process)
            stop_process(embed_process)
            embed_log.close()
            rust_log.close()

        role_by_pid = {pid: "embedding_service" for pid in embedding_pids}
        if rust_process is not None:
            role_by_pid[rust_process.pid] = "knowledge_base_service"
        for sample in payload["resource_samples"]:
            sample["process_role"] = role_by_pid.get(sample.get("pid"), "unknown")
        add_cpu_percent(payload["resource_samples"], os.cpu_count() or 1, interval_ms)

        payload["summary"] = summarize_latency(payload["latency_samples"])
        payload["summary"]["by_top_k"] = {
            str(top_k): summarize_latency([sample for sample in payload["latency_samples"] if sample["top_k"] == top_k])
            for top_k in config["top_k"]
        }
        payload["summary"]["quality_by_top_k"] = {
            str(top_k): quality_summary([detail for detail in payload["quality_details"] if detail["top_k"] == top_k])
            for top_k in config["top_k"]
        }
        payload["summary"]["resources"] = resource_summary(payload["resource_samples"])
        payload["run_info"]["ended_at"] = now_iso()
        result_path, _ = write_run(run_dir, payload)
        outputs.append(result_path)
        print(f"[embedding] {run_id}: {payload['run_info']['status']}", flush=True)

    return outputs


def run_storage(config: dict[str, Any], session_dir: Path) -> list[Path]:
    executable = LOCAL_KB_TAURI / "target" / "release" / "storage_benchmark.exe"
    if not executable.exists():
        raise FileNotFoundError(f"release benchmark binary not found: {executable}")

    outputs: list[Path] = []
    repetitions = int(config["repetitions"])
    for chunk_count in config["chunk_counts"]:
        for dimension in config["dimensions"]:
            run_id = f"storage-n{chunk_count}-d{dimension}"
            payload = base_payload(
                run_id,
                "rust_storage_microbenchmark",
                {
                    "chunk_count": chunk_count,
                    "dimension": dimension,
                    "repetitions": repetitions,
                    "vector_store": "sqlite_blob_rust_cosine",
                    "build_mode": "release",
                },
                {"dataset_id": "deterministic-generated-vectors", "chunk_count": chunk_count},
            )
            completed = subprocess.run(
                [str(executable), "--chunks", str(chunk_count), "--dimension", str(dimension), "--repetitions", str(repetitions)],
                cwd=LOCAL_KB_TAURI,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                payload["run_info"]["status"] = "INVALID"
                payload["errors"].append({"stage": "storage_benchmark", "message": completed.stderr.strip(), "exit_code": completed.returncode})
            else:
                raw = json.loads(completed.stdout)
                for sample in raw["samples"]:
                    for stage in ("insert", "search_top5", "search_top10", "sqlite_read"):
                        payload["latency_samples"].append(
                            {
                                "sample_id": f"{sample['sample_id']}-{stage}",
                                "stage": stage,
                                "success": True,
                                "latency_ms": sample[f"{stage}_ms"],
                            }
                        )

            payload["summary"] = summarize_latency(payload["latency_samples"])
            payload["summary"]["by_stage"] = {
                stage: summarize_latency([sample for sample in payload["latency_samples"] if sample["stage"] == stage])
                for stage in ("insert", "search_top5", "search_top10", "sqlite_read")
            }
            payload["run_info"]["ended_at"] = now_iso()
            result_path, _ = write_run(session_dir / run_id, payload)
            outputs.append(result_path)
            print(f"[storage] {run_id}: {payload['run_info']['status']}", flush=True)
    return outputs


def run_functional(config: dict[str, Any], session_dir: Path) -> list[Path]:
    executable = LOCAL_KB_TAURI / "target" / "release" / "functional_verification.exe"
    if not executable.exists():
        raise FileNotFoundError(f"release functional binary not found: {executable}")

    run_id = "functional-local-closed-loop"
    run_dir = session_dir / run_id
    artifacts = run_dir / "artifacts"
    work_dir = artifacts / "workspace"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = base_payload(
        run_id,
        "functional_closed_loop",
        {
            "watcher_timeout_seconds": int(config["watcher_timeout_seconds"]),
            "embedding_runtime": config["embedding_runtime"],
            "external_service_used": False,
            "build_mode": "release",
        },
        {"dataset_id": "generated-securities-lifecycle-fixture"},
    )
    completed = subprocess.run(
        [str(executable), "--work-dir", str(work_dir)],
        cwd=LOCAL_KB_TAURI,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=max(30, int(config["watcher_timeout_seconds"]) + 15),
    )
    (artifacts / "functional.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (artifacts / "functional.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        payload["run_info"]["status"] = "INVALID"
        payload["errors"].append(
            {
                "stage": "functional_verification",
                "exit_code": completed.returncode,
                "message": completed.stderr.strip() or "functional verification failed",
            }
        )
    else:
        raw = json.loads(completed.stdout)
        payload["case_results"] = raw["case_results"]
        payload["latency_samples"] = [
            {
                "sample_id": case["case_id"],
                "stage": case["category"],
                "success": case["status"] == "PASS",
                "latency_ms": case["duration_ms"],
            }
            for case in raw["case_results"]
        ]
        payload["dataset"]["database_path"] = raw["database_path"]

    payload["summary"] = summarize_latency(payload["latency_samples"])
    payload["summary"]["by_stage"] = {
        category: summarize_latency(
            [sample for sample in payload["latency_samples"] if sample["stage"] == category]
        )
        for category in ("closed_loop", "incremental_update")
    }
    payload["run_info"]["ended_at"] = now_iso()
    result_path, _ = write_run(run_dir, payload)
    print(f"[functional] {run_id}: {payload['run_info']['status']}", flush=True)
    return [result_path]
