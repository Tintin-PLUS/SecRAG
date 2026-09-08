"""Small shared helpers for SecRAG benchmark result files."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any


REQUIRED_SECTIONS = (
    "schema_version",
    "run_info",
    "environment",
    "config",
    "dataset",
    "latency_samples",
    "resource_samples",
    "quality_details",
    "case_results",
    "errors",
    "summary",
    "integrity",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def summarize_latency(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [
        float(sample["latency_ms"])
        for sample in samples
        if sample.get("success") is True and sample.get("latency_ms") is not None
    ]
    total = len(samples)
    success_count = len(successful)
    result = {
        "total_samples": total,
        "successful_samples": success_count,
        "failed_samples": total - success_count,
        "mean_ms": fmean(successful) if successful else None,
        "min_ms": min(successful) if successful else None,
        "max_ms": max(successful) if successful else None,
        "p50_ms": percentile(successful, 0.50),
        "p95_ms": percentile(successful, 0.95),
        "p99_ms": percentile(successful, 0.99) if len(successful) >= 1000 else None,
    }
    return {key: round(value, 6) if isinstance(value, float) else value for key, value in result.items()}


def validate_run(payload: dict[str, Any]) -> list[str]:
    errors = [f"missing section: {key}" for key in REQUIRED_SECTIONS if key not in payload]
    if errors:
        return errors

    run_id = payload["run_info"].get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("run_info.run_id must be a non-empty string")

    samples = payload["latency_samples"]
    if not isinstance(samples, list):
        errors.append("latency_samples must be a list")
        return errors

    actual = summarize_latency(samples)
    for key in ("total_samples", "successful_samples", "failed_samples"):
        if payload["summary"].get(key) != actual[key]:
            errors.append(f"summary.{key} does not match latency_samples")
    if actual["successful_samples"] + actual["failed_samples"] != actual["total_samples"]:
        errors.append("successful_samples + failed_samples must equal total_samples")
    return errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_run(run_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    problems = validate_run(payload)
    if problems:
        raise ValueError("invalid run result: " + "; ".join(problems))

    payload["integrity"] = {
        **payload.get("integrity", {}),
        "latency_sample_count": len(payload["latency_samples"]),
        "resource_sample_count": len(payload["resource_samples"]),
        "quality_detail_count": len(payload["quality_details"]),
        "case_result_count": len(payload["case_results"]),
        "error_count": len(payload["errors"]),
        "generated_at": now_iso(),
    }
    result_path = run_dir / "run_result.json"
    atomic_write_json(result_path, payload)

    files = []
    for file_path in sorted(path for path in run_dir.rglob("*") if path.is_file()):
        if file_path.name == "manifest.json" or file_path.suffix == ".tmp":
            continue
        files.append(
            {
                "path": file_path.relative_to(run_dir).as_posix(),
                "size_bytes": file_path.stat().st_size,
                "sha256": sha256_file(file_path),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "run_id": payload["run_info"]["run_id"],
        "generated_at": now_iso(),
        "files": files,
    }
    manifest_path = run_dir / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    return result_path, manifest_path
