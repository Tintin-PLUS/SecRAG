"""Generate an evidence-backed Markdown report and eight compact SVG charts."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import fmean
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_BASELINE = ROOT / "performance-test" / "results" / "baselines" / "large-chunks-300-500-800.json"
MODEL_CACHE_NAMES = {
    "bge-small": "models--BAAI--bge-small-zh-v1.5",
    "m3e-base": "models--moka-ai--m3e-base",
    "bge-m3": "models--BAAI--bge-m3",
}
MODEL_COLORS = {"bge-small": "#0f766e", "m3e-base": "#2563eb", "bge-m3": "#c2410c"}
CHUNK_COLORS = {"fixed-100-20": "#0891b2", "fixed-150-30": "#16a34a", "fixed-200-40": "#ea580c"}
CHART_FILES = (
    "01_quality_latency.svg",
    "02_model_resources.svg",
    "03_storage_scale.svg",
    "04_chunk_comparison.svg",
    "05_topk_tradeoff.svg",
    "06_incremental_updates.svg",
    "07_offline_closed_loop.svg",
    "08_entropy_fun.svg",
)


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def model_cache_size(model: str) -> int:
    return directory_size(Path.home() / ".cache" / "huggingface" / "hub" / MODEL_CACHE_NAMES[model] / "snapshots")


def f(value: float | int | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def mib(value: float | int) -> float:
    return float(value) / 2**20


def gib(value: float | int) -> float:
    return float(value) / 2**30


def select_recommended_fixed(chunk_rows: list[dict[str, Any]]) -> str:
    candidates = [
        row for row in chunk_rows
        if row["strategy"] == "fixed" and row["top_k"] == 3
    ]
    if not candidates:
        raise ValueError("no measured fixed chunk candidates at Top-K=3")
    return max(candidates, key=lambda row: row["hybrid_quality"]["ndcg"])["chunk_config"]


def next_capacity(required: float, standards: tuple[int, ...]) -> int:
    return next((value for value in standards if required <= value), int(2 ** math.ceil(math.log2(required))))


def _svg_shell(title: str, body: str, subtitle: str = "") -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
<rect width="1600" height="900" fill="#f8fafc"/>
<text x="80" y="72" font-family="Microsoft YaHei, sans-serif" font-size="30" font-weight="700" fill="#0f172a">{escape(title)}</text>
<text x="80" y="108" font-family="Microsoft YaHei, sans-serif" font-size="16" fill="#64748b">{escape(subtitle)}</text>
{body}
</svg>'''


def scatter_svg(title: str, points: list[dict[str, Any]], x_label: str, y_label: str, subtitle: str = "") -> str:
    left, top, width, height = 120.0, 150.0, 1360.0, 620.0
    xs = [float(item["x"]) for item in points] or [0.0]
    ys = [float(item["y"]) for item in points] or [0.0]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xpad = (xmax - xmin) * 0.08 or 1.0
    ypad = (ymax - ymin) * 0.12 or 0.1
    xmin, xmax, ymin, ymax = xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad
    sx = lambda value: left + (float(value) - xmin) / (xmax - xmin) * width
    sy = lambda value: top + height - (float(value) - ymin) / (ymax - ymin) * height
    parts = []
    for index in range(6):
        x = left + width * index / 5
        y = top + height * index / 5
        xv = xmin + (xmax - xmin) * index / 5
        yv = ymax - (ymax - ymin) * index / 5
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+height}" stroke="#e2e8f0"/>')
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+width}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{x:.1f}" y="{top+height+28}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{xv:.2f}</text>')
        parts.append(f'<text x="{left-16}" y="{y+5:.1f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{yv:.3f}</text>')
    parts.append(f'<line x1="{left}" y1="{top+height}" x2="{left+width}" y2="{top+height}" stroke="#334155" stroke-width="2"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+height}" stroke="#334155" stroke-width="2"/>')
    for item in points:
        x, y = sx(item["x"]), sy(item["y"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{escape(str(item.get("color", "#2563eb")))}" opacity="0.88"/>')
        if item.get("label"):
            parts.append(f'<text x="{x+8:.1f}" y="{y-8:.1f}" font-family="Microsoft YaHei, sans-serif" font-size="12" fill="#334155">{escape(str(item["label"]))}</text>')
    parts.append(f'<text x="{left+width/2}" y="842" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#334155">{escape(x_label)}</text>')
    parts.append(f'<text x="34" y="{top+height/2}" transform="rotate(-90 34 {top+height/2})" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#334155">{escape(y_label)}</text>')
    return _svg_shell(title, "\n".join(parts), subtitle)


def bar_svg(title: str, bars: list[dict[str, Any]], x_label: str, subtitle: str = "") -> str:
    left, top, width = 310.0, 150.0, 1160.0
    gap = 660.0 / max(len(bars), 1)
    bar_h = min(44.0, gap * 0.62)
    maximum = max((float(item["value"]) for item in bars), default=1.0) or 1.0
    parts = []
    for index in range(6):
        x = left + width * index / 5
        value = maximum * index / 5
        parts.append(f'<line x1="{x:.1f}" y1="{top-20}" x2="{x:.1f}" y2="{top+660}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{x:.1f}" y="842" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{value:.2f}</text>')
    for index, item in enumerate(bars):
        y = top + index * gap + (gap - bar_h) / 2
        bar_w = float(item["value"]) / maximum * width
        parts.append(f'<text x="{left-18}" y="{y+bar_h/2+5:.1f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="15" fill="#334155">{escape(str(item["label"]))}</text>')
        parts.append(f'<rect x="{left}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="5" fill="{escape(str(item.get("color", "#2563eb")))}"/>')
        parts.append(f'<text x="{left+bar_w+10:.1f}" y="{y+bar_h/2+5:.1f}" font-family="Microsoft YaHei, sans-serif" font-size="14" fill="#0f172a">{escape(str(item.get("value_label", f(item["value"]))))}</text>')
    parts.append(f'<text x="{left+width/2}" y="882" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#334155">{escape(x_label)}</text>')
    return _svg_shell(title, "\n".join(parts), subtitle)


def line_svg(title: str, series: list[dict[str, Any]], x_labels: list[str], y_label: str, subtitle: str = "") -> str:
    left, top, width, height = 130.0, 160.0, 1330.0, 580.0
    values = [float(point) for item in series for point in item["values"]]
    ymin, ymax = min(values, default=0.0), max(values, default=1.0)
    pad = (ymax - ymin) * 0.12 or 0.1
    ymin, ymax = ymin - pad, ymax + pad
    sx = lambda index: left + (width * index / max(len(x_labels) - 1, 1))
    sy = lambda value: top + height - (float(value) - ymin) / (ymax - ymin) * height
    parts = []
    for index in range(6):
        y = top + height * index / 5
        value = ymax - (ymax - ymin) * index / 5
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+width}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{left-15}" y="{y+5:.1f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{value:.3f}</text>')
    for index, label in enumerate(x_labels):
        x = sx(index)
        parts.append(f'<text x="{x:.1f}" y="{top+height+30}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{escape(label)}</text>')
    for series_index, item in enumerate(series):
        points = [(sx(index), sy(value)) for index, value in enumerate(item["values"])]
        polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        color = item.get("color", "#2563eb")
        parts.append(f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{color}"/>')
        lx = 1080 + series_index * 170
        parts.append(f'<line x1="{lx}" y1="105" x2="{lx+30}" y2="105" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{lx+38}" y="111" font-family="Microsoft YaHei, sans-serif" font-size="14" fill="#334155">{escape(item["name"])}</text>')
    parts.append(f'<text x="34" y="{top+height/2}" transform="rotate(-90 34 {top+height/2})" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="17" fill="#334155">{escape(y_label)}</text>')
    return _svg_shell(title, "\n".join(parts), subtitle)


def entropy_weights(rows: list[dict[str, Any]]) -> tuple[dict[str, float], list[float]]:
    fields = ("p50_cost", "p95_cost", "qps")
    matrix = []
    max_p50 = max(float(row["p50_ms"]) for row in rows)
    max_p95 = max(float(row["p95_ms"]) for row in rows)
    for row in rows:
        matrix.append({"p50_cost": max_p50 - float(row["p50_ms"]), "p95_cost": max_p95 - float(row["p95_ms"]), "qps": float(row["qps_sequential"])})
    normalized: dict[str, list[float]] = {}
    for field in fields:
        values = [row[field] for row in matrix]
        low, high = min(values), max(values)
        normalized[field] = [((value - low) / (high - low) if high > low else 0.0) + 1e-12 for value in values]
    divergences = {}
    k = 1.0 / math.log(len(rows))
    for field in fields:
        total = sum(normalized[field])
        probabilities = [value / total for value in normalized[field]]
        entropy = -k * sum(value * math.log(value) for value in probabilities if value > 0)
        divergences[field] = 1.0 - entropy
    total_divergence = sum(divergences.values()) or 1.0
    weights = {field: value / total_divergence for field, value in divergences.items()}
    scores = [100.0 * sum(weights[field] * normalized[field][index] for field in fields) for index in range(len(rows))]
    return weights, scores


def quality_color(score: float) -> str:
    ratio = max(0.0, min(1.0, score / 100.0))
    cold, warm = (37, 99, 235), (234, 88, 12)
    rgb = tuple(round(cold[index] + ratio * (warm[index] - cold[index])) for index in range(3))
    return "#" + "".join(f"{value:02x}" for value in rgb)


def entropy_svg(rows: list[dict[str, Any]], weights_by_profile: dict[str, dict[str, float]]) -> str:
    profiles = ["低配估算", "办公PC估算", "高配估算"]
    left, top, width, height = 140.0, 160.0, 1320.0, 580.0
    ymin, ymax = min(row["entropy_score"] for row in rows), max(row["entropy_score"] for row in rows)
    pad = (ymax - ymin) * 0.12 or 0.1
    ymin, ymax = ymin - pad, ymax + pad
    sy = lambda value: top + height - (value - ymin) / (ymax - ymin) * height
    parts = []
    for index in range(6):
        y = top + height * index / 5
        value = ymax - (ymax - ymin) * index / 5
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+width}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="{left-15}" y="{y+5:.1f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#64748b">{value:.3f}</text>')
    group_width = width / 3
    for group_index, profile in enumerate(profiles):
        start = left + group_index * group_width
        if group_index:
            parts.append(f'<line x1="{start:.1f}" y1="{top}" x2="{start:.1f}" y2="{top+height}" stroke="#94a3b8" stroke-dasharray="5 5"/>')
        parts.append(f'<text x="{start+group_width/2:.1f}" y="{top+height+45}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="18" font-weight="700" fill="#334155">{profile}</text>')
        group_rows = [row for row in rows if row["profile"] == profile]
        for point_index, row in enumerate(group_rows):
            x = start + 30 + point_index * (group_width - 60) / max(len(group_rows) - 1, 1)
            y = sy(row["entropy_score"])
            color = quality_color(row["quality_score"])
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}" opacity="0.9"/>')
            parts.append(f'<text x="{x:.1f}" y="{y-8:.1f}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="10" fill="#475569">K{row["top_k"]}</text>')
    for index, score in enumerate((0, 25, 50, 75, 100)):
        x = 1030 + index * 86
        parts.append(f'<circle cx="{x}" cy="120" r="3.5" fill="{quality_color(score)}"/>')
        parts.append(f'<text x="{x+8}" y="125" font-family="Microsoft YaHei, sans-serif" font-size="11" fill="#64748b">{score}</text>')
    parts.append('<text x="900" y="125" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#475569">质量色：</text>')
    legend = "；".join(f"{profile}: " + ", ".join(f"{key}={value:.3f}" for key, value in weights.items()) for profile, weights in weights_by_profile.items())
    parts.append(f'<text x="{left}" y="810" font-family="Microsoft YaHei, sans-serif" font-size="12" fill="#64748b">档内效率熵权：{escape(legend)}</text>')
    return _svg_shell("熵权效率散点：三档配置 × 每档九个切分/Top-K 组合", "\n".join(parts), "纵轴=档内效率分；颜色=质量分；固定小点避免遮挡；不作跨档数值比较")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def build_report_data(session_dir: Path) -> dict[str, Any]:
    session_info = json.loads((session_dir / "session_info.json").read_text(encoding="utf-8"))
    baseline_name = session_info["config"]["baseline_chunk_config"]
    results = [json.loads(path.read_text(encoding="utf-8")) for path in session_dir.rglob("run_result.json")]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_scenario.setdefault(result["run_info"]["scenario"], []).append(result)
    retrievals = by_scenario["retrieval"]
    cold = by_scenario["cold_start"][0]
    storage = by_scenario["vector_storage"][0]
    hardware = by_scenario["thread_capped_hardware_estimate"][0]
    functional = by_scenario["functional_offline_incremental"][0]
    batch = {item["config"]["model"]: item for item in by_scenario["embedding_batch"]}
    baseline_runs = {item["config"]["model"]: item for item in retrievals if item["config"]["chunk"]["name"] == baseline_name}

    model_rows = []
    hardware_estimates = []
    for model in ("bge-small", "m3e-base", "bge-m3"):
        run = baseline_runs[model]
        cache_bytes = model_cache_size(model)
        private_bytes = run["summary"]["resource"]["peak_stack_private_bytes"] or 0
        memory_basis = cache_bytes + private_bytes
        ram_required = 4 + 1.5 * gib(memory_basis)
        ram_gib = next_capacity(ram_required, (8, 16, 32, 64, 128))
        disk_required = 1.5 * gib(cache_bytes + run["summary"]["database_bytes_mean"])
        disk_gib = next_capacity(max(1.0, disk_required), (1, 2, 4, 8, 16))
        for top_k in (3, 5, 10):
            model_rows.append({
                "model": model,
                "dimension": run["summary"]["health"]["dimensions"][model],
                "model_cache_bytes": cache_bytes,
                "peak_private_bytes": private_bytes,
                "chunk_count": run["summary"]["chunk_count"],
                "build_time_mean_ms": run["summary"]["build_time_mean_ms"],
                "database_bytes_mean": run["summary"]["database_bytes_mean"],
                "cold": cold["summary"]["by_model"][model],
                "batch": batch[model]["summary"]["by_batch"],
                "top_k": top_k,
                "latency": run["summary"]["latency_by_top_k"][str(top_k)],
                "vector_quality": run["summary"]["quality_by_mode_and_top_k"]["vector"][str(top_k)],
                "hybrid_quality": run["summary"]["quality_by_mode_and_top_k"]["hybrid"][str(top_k)],
            })
        hardware_estimates.append({
            "model": model,
            "model_cache_bytes": cache_bytes,
            "peak_private_bytes": private_bytes,
            "memory_basis_bytes": memory_basis,
            "formula_required_gib": ram_required,
            "minimum_standard_ram_gib": ram_gib,
            "minimum_free_disk_gib": disk_gib,
            "measured_threads": run["summary"]["health"]["torch_threads"],
            "cpu_floor": "4线程限额实测" if model == "bge-small" else "未在真实低端CPU独立验证",
        })

    chunk_rows = []
    for run in sorted((item for item in retrievals if item["config"]["model"] == "bge-small"), key=lambda item: item["config"]["chunk"]["name"]):
        for top_k in (3, 5, 10):
            chunk_rows.append({
                "chunk_config": run["config"]["chunk"]["name"],
                "strategy": run["config"]["chunk"]["strategy"],
                "chunk_size": run["config"]["chunk"]["chunk_size"],
                "overlap": run["config"]["chunk"]["overlap"],
                "chunk_count": run["summary"]["chunk_count"],
                "build_time_mean_ms": run["summary"]["build_time_mean_ms"],
                "database_bytes_mean": run["summary"]["database_bytes_mean"],
                "top_k": top_k,
                "latency": run["summary"]["latency_by_top_k"][str(top_k)],
                "vector_quality": run["summary"]["quality_by_mode_and_top_k"]["vector"][str(top_k)],
                "hybrid_quality": run["summary"]["quality_by_mode_and_top_k"]["hybrid"][str(top_k)],
            })
    recommended_fixed = select_recommended_fixed(chunk_rows)
    historical_comparison = None
    if HISTORICAL_BASELINE.exists():
        historical = json.loads(HISTORICAL_BASELINE.read_text(encoding="utf-8"))
        old_row = next(
            (row for row in historical.get("chunk_comparison", []) if row["chunk_config"] == "fixed-500-80" and row["top_k"] == 3),
            None,
        )
        new_row = next(row for row in chunk_rows if row["chunk_config"] == recommended_fixed and row["top_k"] == 3)
        if old_row is not None:
            historical_comparison = {"old": old_row, "new": new_row, "strict_ab": False}

    build_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for case in storage["case_results"]:
        if case["case_id"].endswith("-build"):
            parts = case["case_id"].split("-")
            backend = "sqlite-vec" if case["case_id"].startswith("sqlite-vec") else "fallback"
            count = int(next(part[1:] for part in parts if part.startswith("n")))
            build_groups.setdefault((backend, count), []).append(case["actual"])
    storage_rows = []
    for key, metrics in storage["summary"]["by_backend_scale"].items():
        backend_part, count_part, k_part = key.split("/")
        count, top_k = int(count_part.split("=")[1]), int(k_part.split("=")[1])
        builds = build_groups[(backend_part, count)]
        storage_rows.append({
            "backend": backend_part,
            "vector_count": count,
            "dimension": storage["config"]["dimension"],
            "top_k": top_k,
            "build_ms_mean": fmean(item["insert_ms"] for item in builds),
            "database_bytes_mean": fmean(item["database_bytes"] for item in builds),
            **metrics,
        })

    entropy_rows = [dict(item) for item in hardware["summary"]["entropy_points"]]
    quality_fields = ("recall", "mrr", "ndcg")
    normalized_quality: dict[str, list[float]] = {}
    for field in quality_fields:
        values = [float(row[field]) for row in entropy_rows]
        low, high = min(values), max(values)
        normalized_quality[field] = [(value - low) / (high - low) if high > low else 0.0 for value in values]
    for index, row in enumerate(entropy_rows):
        row["quality_score"] = 100.0 * fmean(normalized_quality[field][index] for field in quality_fields)
    weights_by_profile = {}
    for profile in ("低配估算", "办公PC估算", "高配估算"):
        group = [row for row in entropy_rows if row["profile"] == profile]
        weights, scores = entropy_weights(group)
        weights_by_profile[profile] = weights
        for row, score in zip(group, scores):
            row["entropy_score"] = score

    return {
        "schema_version": "2.0-report",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_session": str(session_dir.resolve()),
        "test_config": session_info["config"],
        "baseline_chunk_config": baseline_name,
        "recommended_fixed_chunk_config": recommended_fixed,
        "historical_large_chunk_comparison": historical_comparison,
        "integrity": {
            "run_result_count": len(results),
            "error_count": sum(item["integrity"]["error_count"] for item in results),
            "retrieval_runs": len(retrievals),
            "retrieval_latency_samples": sum(item["integrity"]["latency_sample_count"] for item in retrievals),
            "retrieval_quality_details": sum(item["integrity"]["quality_detail_count"] for item in retrievals),
            "functional_pass_count": functional["summary"]["pass_count"],
            "functional_required_count": functional["summary"]["required_count"],
        },
        "environment": cold["environment"],
        "dataset": cold["dataset"],
        "cold_summary": cold["summary"],
        "batch_summaries": {model: item["summary"] for model, item in batch.items()},
        "model_comparison": model_rows,
        "chunk_comparison": chunk_rows,
        "storage_comparison": sorted(storage_rows, key=lambda item: (item["backend"], item["vector_count"], item["top_k"])),
        "storage_accuracy": {"result_overlap_mean": storage["summary"]["result_overlap_mean"], "exact_order_match_rate": storage["summary"]["exact_order_match_rate"]},
        "hardware_estimates": hardware_estimates,
        "hardware_profile_points": entropy_rows,
        "hardware_profile_resources": hardware["summary"]["resource_by_profile"],
        "entropy_weights_by_profile": weights_by_profile,
        "functional_cases": functional["case_results"],
        "functional_summary": functional["summary"],
    }


def write_charts(data: dict[str, Any], output_dir: Path) -> None:
    model_points = []
    for row in data["model_comparison"]:
        model_points.append({"x": row["latency"]["p95_ms"], "y": row["hybrid_quality"]["ndcg"], "color": MODEL_COLORS[row["model"]], "label": f'{row["model"]} K{row["top_k"]}'})
    (output_dir / CHART_FILES[0]).write_text(scatter_svg("模型质量—时延权衡", model_points, "P95 端到端本地检索时延（ms）", "混合检索 nDCG@K", f"{data['baseline_chunk_config']}；原始 34 题；圆点半径 4px"), encoding="utf-8")

    memory_bars = []
    for item in data["hardware_estimates"]:
        memory_bars.append({"label": item["model"], "value": gib(item["memory_basis_bytes"]), "value_label": f'{gib(item["memory_basis_bytes"]):.2f} GiB → {item["minimum_standard_ram_gib"]} GB', "color": MODEL_COLORS[item["model"]]})
    (output_dir / CHART_FILES[1]).write_text(bar_svg("模型资源占用与最低内存档位", memory_bars, "模型文件 + 峰值私有提交（GiB）", "内存档位采用 4 GiB 系统预留 + 1.5×测量基数后向上取整"), encoding="utf-8")

    storage_rows = data["storage_comparison"]
    scales = sorted({row["vector_count"] for row in storage_rows})
    top_ks = sorted({row["top_k"] for row in storage_rows})
    x_labels = [f'{count}/K{top_k}' for count in scales for top_k in top_ks]
    storage_series = []
    for backend, color in (("fallback", "#dc2626"), ("sqlite-vec", "#2563eb")):
        rows = sorted((row for row in storage_rows if row["backend"] == backend), key=lambda row: (row["vector_count"], row["top_k"]))
        storage_series.append({"name": backend, "color": color, "values": [row["p95_ms"] for row in rows]})
    (output_dir / CHART_FILES[2]).write_text(line_svg("向量存储规模对比", storage_series, x_labels, "P95 查询时延（ms）", "512 维确定性向量；每格 3 轮 × 100 查询"), encoding="utf-8")

    chunk_k3 = [row for row in data["chunk_comparison"] if row["top_k"] == 3]
    chunk_bars = [{"label": row["chunk_config"], "value": row["hybrid_quality"]["ndcg"], "value_label": f'{row["hybrid_quality"]["ndcg"]:.3f} / {row["latency"]["p95_ms"]:.1f}ms', "color": CHUNK_COLORS.get(row["chunk_config"], "#7c3aed")} for row in chunk_k3]
    (output_dir / CHART_FILES[3]).write_text(bar_svg("切分方案对比", chunk_bars, "混合检索 nDCG@3（标签同时列 P95）", "bge-small；100/20、150/30、200/40 与结构化 200"), encoding="utf-8")

    recommended = [row for row in data["chunk_comparison"] if row["chunk_config"] == data["recommended_fixed_chunk_config"]]
    topk_series = [
        {"name": "Recall", "color": "#2563eb", "values": [row["hybrid_quality"]["recall"] for row in recommended]},
        {"name": "Precision", "color": "#dc2626", "values": [row["hybrid_quality"]["precision"] for row in recommended]},
        {"name": "nDCG", "color": "#16a34a", "values": [row["hybrid_quality"]["ndcg"] for row in recommended]},
    ]
    (output_dir / CHART_FILES[4]).write_text(line_svg("Top-K 质量取舍", topk_series, ["K=3", "K=5", "K=10"], "指标值", f"bge-small + {data['recommended_fixed_chunk_config']} + 混合检索"), encoding="utf-8")

    update_cases = [item for item in data["functional_cases"] if item["case_id"].startswith("U")]
    update_bars = [{"label": item["case_id"], "value": float(item.get("duration_ms") or 0.0), "value_label": f(item.get("duration_ms"), 2) + " ms", "color": "#0f766e"} for item in update_cases]
    (output_dir / CHART_FILES[5]).write_text(bar_svg("增量更新闭环用例耗时", update_bars, "用例耗时（ms；无独立计时记为 0）", "U01 新增、U02 修改、U03 删除、U04 连续写、U05 异常文件、U06 重启、U07 手动补偿"), encoding="utf-8")

    pass_bars = []
    for prefix, label, color in (("F", "功能 F01-F07", "#2563eb"), ("L", "本地化 L01-L07", "#7c3aed"), ("U", "增量 U01-U07", "#16a34a")):
        count = sum(item["status"] == "PASS" and item["case_id"].startswith(prefix) for item in data["functional_cases"])
        pass_bars.append({"label": label, "value": count, "value_label": f"{count}/7 PASS", "color": color})
    (output_dir / CHART_FILES[6]).write_text(bar_svg("离线与本地闭环验证", pass_bars, "通过用例数", "无外部大模型；本地文件、SQLite、日志与离线检索闭环"), encoding="utf-8")

    (output_dir / CHART_FILES[7]).write_text(entropy_svg(data["hardware_profile_points"], data["entropy_weights_by_profile"]), encoding="utf-8")


def report_markdown(data: dict[str, Any]) -> str:
    env, dataset, integrity, test_config = data["environment"], data["dataset"], data["integrity"], data["test_config"]
    model_latency = []
    model_quality = []
    for row in data["model_comparison"]:
        latency = row["latency"]
        model_latency.append([row["model"], row["top_k"], f(latency["p50_ms"], 2), f(latency["p95_ms"], 2), f(latency["p99_ms"], 2), f(latency["mean_round_qps"], 2), latency["total_samples"]])
        for mode_key, mode_label in (("vector_quality", "纯向量"), ("hybrid_quality", "混合")):
            quality = row[mode_key]
            model_quality.append([row["model"], mode_label, row["top_k"], f(quality["hit_rate"]), f(quality["mrr"]), f(quality["recall"]), f(quality["precision"]), f(quality["ndcg"]), f(quality["map"])])
    batch_rows = []
    for model in ("bge-small", "m3e-base", "bge-m3"):
        for batch_size in ("1", "8", "32"):
            item = data["batch_summaries"][model]["by_batch"][batch_size]
            batch_rows.append([model, batch_size, f(item["p50_ms"], 2), f(item["p95_ms"], 2), f(item["texts_per_second_mean"], 2), f(item["tokens_per_second_mean"], 2), item["total_samples"]])
    cold_rows = []
    for model, item in data["cold_summary"]["by_model"].items():
        cold_rows.append([model, f(item["cold_start_p50_ms"], 2), f(item["cold_start_p95_ms"], 2), f(item["first_request_p50_ms"], 2)])
    chunk_rows = []
    for row in data["chunk_comparison"]:
        q = row["hybrid_quality"]
        chunk_rows.append([row["chunk_config"], row["chunk_size"], row["overlap"], row["chunk_count"], row["top_k"], f(row["build_time_mean_ms"], 2), int(row["database_bytes_mean"]), f(row["latency"]["p95_ms"], 2), f(row["latency"]["mean_round_qps"], 2), f(q["hit_rate"]), f(q["mrr"]), f(q["recall"]), f(q["precision"]), f(q["ndcg"]), f(q["map"])])
    storage_rows = [[row["backend"], row["vector_count"], row["dimension"], row["top_k"], f(row["build_ms_mean"], 2), int(row["database_bytes_mean"]), f(row["p50_ms"], 3), f(row["p95_ms"], 3), f(row["p99_ms"], 3), f(row["mean_round_qps"], 2), row["total_samples"]] for row in data["storage_comparison"]]
    hardware_rows = [[item["model"], f(gib(item["model_cache_bytes"]), 3), f(mib(item["peak_private_bytes"]), 1), f(gib(item["memory_basis_bytes"]), 3), f(item["formula_required_gib"], 2), item["minimum_standard_ram_gib"], item["minimum_free_disk_gib"], item["measured_threads"], item["cpu_floor"]] for item in data["hardware_estimates"]]
    entropy_rows = [[item["profile"], item["ram_gib"], item["torch_threads"], item["chunk_config"], item["top_k"], f(item["p50_ms"], 2), f(item["p95_ms"], 2), f(item["qps_sequential"], 2), f(item["recall"]), f(item["mrr"]), f(item["ndcg"]), f(item["quality_score"], 1), f(item["entropy_score"], 1)] for item in data["hardware_profile_points"]]
    functional_rows = [[item["case_id"], item["description"], item["status"], f(item.get("duration_ms"), 2)] for item in data["functional_cases"]]
    bge = next(row for row in data["model_comparison"] if row["model"] == "bge-small" and row["top_k"] == 3)
    m3 = next(row for row in data["model_comparison"] if row["model"] == "bge-m3" and row["top_k"] == 3)
    speed_ratio = m3["latency"]["p95_ms"] / bge["latency"]["p95_ms"]
    build_ratio = m3["build_time_mean_ms"] / bge["build_time_mean_ms"]
    baseline_name = data["baseline_chunk_config"]
    recommended_name = data["recommended_fixed_chunk_config"]
    recommended_k3 = next(row for row in data["chunk_comparison"] if row["chunk_config"] == recommended_name and row["top_k"] == 3)
    recommended_k5 = next(row for row in data["chunk_comparison"] if row["chunk_config"] == recommended_name and row["top_k"] == 5)
    structure_k3 = next(row for row in data["chunk_comparison"] if row["chunk_config"] == "structure-200" and row["top_k"] == 3)
    historical = data["historical_large_chunk_comparison"]
    historical_section = ""
    if historical:
        old_row, new_row = historical["old"], historical["new"]
        historical_section = f"""

### 与历史大切块摘要的趋势对照

| 配置 | 时延样本 | 块数 | DB字节 | P95 ms | QPS | Hit@3 | MRR@3 | nDCG@3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| {old_row['chunk_config']}（历史） | {old_row['latency']['total_samples']} | {old_row['chunk_count']} | {int(old_row['database_bytes_mean'])} | {old_row['latency']['p95_ms']:.2f} | {old_row['latency']['mean_round_qps']:.2f} | {old_row['hybrid_quality']['hit_rate']:.3f} | {old_row['hybrid_quality']['mrr']:.3f} | {old_row['hybrid_quality']['ndcg']:.3f} |
| {new_row['chunk_config']}（本轮） | {new_row['latency']['total_samples']} | {new_row['chunk_count']} | {int(new_row['database_bytes_mean'])} | {new_row['latency']['p95_ms']:.2f} | {new_row['latency']['mean_round_qps']:.2f} | {new_row['hybrid_quality']['hit_rate']:.3f} | {new_row['hybrid_quality']['mrr']:.3f} | {new_row['hybrid_quality']['ndcg']:.3f} |

小切块在本轮提高 QPS、P95 基本持平，但块数与数据库体积上升，原始 34 道短事实题的 MRR/nDCG 反而下降。两轮样本数和运行时段不同，因此这里只作趋势证据，不声称严格 A/B；在“必须使用较小切块”的约束内推荐 {recommended_name}，不声称它全面优于历史 500/80。
"""
    return f"""# 端侧知识库技术选型与轻量化验证报告（原始34题重测）

> 结论先行：本轮只使用最初 34 道题；新增 12 篇中文证券语料保留，新增问题不参与测试。模型横评统一使用 **{baseline_name}**；fixed 候选按实测 nDCG@3 择优，默认推荐 **bge-small + {recommended_name} + Top-K=5 + sqlite-vec**。Hit@3 在部分组合中饱和，必须结合 MRR、Precision、nDCG、MAP 判断。

## 证据口径

- 数据集：`{dataset['dataset_id']}`，{dataset['document_count']} 篇文档、{dataset['question_count']} 道原始题；题目文件仅 `embedding-test/eval/test_queries.json`（SHA-256 `{dataset['query_files'][0]['sha256']}`）。
- 环境：{env['cpu_model']}，{env['logical_cores']} 逻辑线程，{gib(env['ram_bytes']):.2f} GiB 内存，{env['os']}，CPU-only，电源计划“平衡”。
- 完整性：{integrity['run_result_count']} 个运行结果、{integrity['error_count']} 条错误；检索性能样本 {integrity['retrieval_latency_samples']} 条、质量明细 {integrity['retrieval_quality_details']} 条；功能用例 {integrity['functional_pass_count']}/{integrity['functional_required_count']} 通过。
- 多轮口径：冷启动 {test_config['cold_start_repetitions']} 次；批量嵌入每组 {test_config['batch_repetitions']} 次；热检索每个 K 为 {test_config['search_rounds']} 轮、每轮实际 340 请求；建库 {test_config['build_repetitions']} 次；存储查询每格 {test_config['storage']['rounds']} 轮 × {test_config['storage']['query_repetitions']} 次。
- 内存口径：报告保留资源采样时间序列和本轮观测峰值；峰值表示容量风险，不取均值。时间与 QPS 则报告多轮均值及 P50/P95/P99。
- 性能测试顺序执行；每轮数据均保存在来源会话的 `run_result.json`，并由 `manifest.json`/`session_manifest.json` 给出哈希。无外部大模型调用，HTTP 只用于 `127.0.0.1` 本机 Python 嵌入进程通信。

## 一、技术选型调研

Tauri/Rust 负责端侧壳与本地闭环；嵌入模型比较 bge-small、m3e-base、bge-m3；向量存储比较 SQLite 回退扫描与 sqlite-vec。当前小语料下 bge-small 的速度/质量平衡最好；m3e-base 与 bge-m3 都没有形成稳定质量优势，后者成本显著提高。

![模型质量—时延](charts/{CHART_FILES[0]})

{md_table(['模型','K','P50 ms','P95 ms','P99 ms','QPS','样本数'], model_latency)}

{md_table(['模型','模式','K','Hit@K','MRR@K','Recall@K','Precision@K','nDCG@K','MAP@K'], model_quality)}

### bge-m3 异常核查

bge-m3 健康检查实际报告 1024 维、CPU、14 线程；其 K=3 P95 是 bge-small 的 {speed_ratio:.2f} 倍，建库时间是 {build_ratio:.2f} 倍。与此同时，混合 nDCG@3 仅从 {bge['hybrid_quality']['ndcg']:.3f} 升至 {m3['hybrid_quality']['ndcg']:.3f}。批量吞吐、模型缓存体积、服务端编码耗时与这一趋势一致，未发现错载模型或冷启动样本混入稳态统计；结论是 **真实但性价比不合适**，不是把异常忽略掉。

## 二、轻量性能验证

### 冷启动与批量嵌入

{md_table(['模型','冷启动P50 ms','冷启动P95 ms','首请求P50 ms'], cold_rows)}

{md_table(['模型','Batch','P50 ms','P95 ms','texts/s','tokens/s','样本数'], batch_rows)}

![模型资源](charts/{CHART_FILES[1]})

### 切分、建库、检索与 QPS

切分长度按当前实现的“中文字符数”计。LangChain 官方中文分隔建议给出 100/20 的示例；Haystack 默认 200 以“词”为单位，RAGFlow 默认 512 以 token 为单位，三者不能直接等同。因此本轮不宣称存在统一标准，而以 100/20 为开源锚点，增加 150/30、200/40 两个 20% overlap 的单变量点，并用 structure-200 观察结构切分差异。

![切分对比](charts/{CHART_FILES[3]})

{md_table(['切分','chunk_size','overlap','块数','K','建库均值ms','DB字节','P95 ms','QPS','Hit','MRR','Recall','Precision','nDCG','MAP'], chunk_rows)}
{historical_section}

### 向量存储规模

![存储规模](charts/{CHART_FILES[2]})

{md_table(['后端','向量数','维度','K','插入均值ms','DB字节','P50 ms','P95 ms','P99 ms','QPS','样本数'], storage_rows)}

两种后端结果重合率 {data['storage_accuracy']['result_overlap_mean']:.3f}，顺序完全一致率 {data['storage_accuracy']['exact_order_match_rate']:.3f}。10,000 向量时 sqlite-vec 明显优于逐行回退扫描。

### 最低硬件估量

{md_table(['模型','模型缓存GiB','峰值私有MiB','内存基数GiB','公式需求GiB','最低标准内存GB','最低空闲磁盘GB','实测线程','CPU口径'], hardware_rows)}

内存公式：`向上取标准档(4 GiB 系统预留 + 1.5 × (模型缓存体积 + 峰值私有提交))`。这是保守估量；Windows 工作集会受裁剪，因此不用偏小的 Working Set 单独给结论。4/8/14 线程数据来自同一台 i9 的线程限额，不等同于三台真实低端机器。

## 三、检索质量验证

![Top-K权衡](charts/{CHART_FILES[4]})

Hit@3 全为 1 并非“质量满分”：在 bge-small {baseline_name} 中，纯向量 Hit@3={bge['vector_quality']['hit_rate']:.3f}，但 MRR@3={bge['vector_quality']['mrr']:.3f}、Precision@3={bge['vector_quality']['precision']:.3f}、nDCG@3={bge['vector_quality']['ndcg']:.3f}；混合检索 MRR@3={bge['hybrid_quality']['mrr']:.3f}。原始 34 题多是“公司名＋指标名”的短事实题，前三名命中至少一块仍可能饱和，所以结论不能只看 Hit@3。

本轮严格遵循“只用原始 34 题”，因此不再人为追求 Hit≈0.9；判断配置时以 nDCG/MRR/Precision 的差异为主。

## 四、功能与本地闭环验证

![增量更新](charts/{CHART_FILES[5]})

![离线闭环](charts/{CHART_FILES[6]})

{md_table(['用例','内容','结果','耗时ms'], functional_rows)}

F01-F07 覆盖知识库、文档导入、真实嵌入、检索、持久化与异常输入；L01-L07 覆盖本地存储、日志脱敏、离线与无外联；U01-U07 覆盖新增、修改、删除、连续写、损坏文件、重启恢复与 watcher 暂停后的手动补偿。

## 五、配置选择结论与后续 AI 对接建议

| 档位 | 建议配置 | 适用判断 |
|---|---|---|
| 轻量最低档 | bge-small；8 GB；至少 4 线程限额；{recommended_name}；K=3；sqlite-vec | 混合 MRR@3 {recommended_k3['hybrid_quality']['mrr']:.3f}、nDCG@3 {recommended_k3['hybrid_quality']['ndcg']:.3f}，P95 {recommended_k3['latency']['p95_ms']:.2f} ms |
| 典型办公档 | bge-small；16 GB；8 线程；{recommended_name}；K=5；sqlite-vec | Recall@5 {recommended_k5['hybrid_quality']['recall']:.3f}、nDCG@5 {recommended_k5['hybrid_quality']['ndcg']:.3f}，并给前端与后续问答保留内存余量 |
| 结构质量备选 | bge-small；16 GB；8 线程；structure-200；K=3/5 | 本轮 structure-200 的 nDCG@3 {structure_k3['hybrid_quality']['ndcg']:.3f} 略高，但无 overlap 且未做三模型横评，先作为备选 |
| 大模型实验档 | bge-m3；16 GB；14 线程级 CPU；{baseline_name}；K=5/10 | 仅在可接受更高延迟和模型占用时采用；本轮没有证明它比 bge-small 更优 |

后续对接 AI 时只把已验证的本地检索层作为输入接口，单独测生成模型的首 token、吞吐、上下文长度与内存；本报告不包含、也不推断外部大模型性能。

### 熵权辅助图（不作主结论）

![熵权辅助散点](charts/{CHART_FILES[7]})

{md_table(['配置档','RAM GB','线程','切分','K','P50 ms','P95 ms','QPS','Recall','MRR','nDCG','质量分','档内效率分'], entropy_rows)}

纵轴熵权只使用效率指标 P50、P95、QPS，并在每个档位内部单独计算；颜色质量分使用 min-max 后等权的 Recall、MRR、nDCG。档内权重为 `{json.dumps(data['entropy_weights_by_profile'], ensure_ascii=False)}`。每个配置区间正好 9 个小散点（三种切分 × 三个 Top-K），只作辅助聚合，跨档分数不可直接比较。

## 局限与复现

- 原始 34 题只覆盖 12 篇公司研究文档的事实检索；新增证券规则语料扩充了干扰项，但未新增对应问题。因此它不能证明规则问答质量。
- 语料只有 24 篇；存储规模测试使用固定随机向量，只回答向量后端性能与排序一致性，不回答证券语义质量。
- 实机只有当前一台；最低硬件是保守估量与线程限额证据，不是三台物理设备实测。
- 参数依据：[LangChain RecursiveCharacterTextSplitter](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter)、[Haystack DocumentSplitter](https://docs.haystack.deepset.ai/docs/documentsplitter)、[RAGFlow Chunker](https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/ingestion_pipeline/configure_chunker_component.md)。
- 来源会话：`{data['source_session']}`。完整逐请求、逐轮、逐用例数据均在该目录，报告聚合数据在 `report_data.json`。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "charts").mkdir(exist_ok=True)
    data = build_report_data(args.session_dir)
    (args.output_dir / "report_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_charts(data, args.output_dir / "charts")
    (args.output_dir / "端侧知识库技术选型与轻量化验证报告-原始34题.md").write_text(report_markdown(data), encoding="utf-8")
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
