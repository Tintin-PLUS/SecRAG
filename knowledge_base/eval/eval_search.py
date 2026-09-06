#!/usr/bin/env python3
"""
知识库检索质量评估脚本（内容相关性版）

评估方式：不依赖chunk的position，而是判断返回的内容是否真正包含回答问题所需的信息。
一个chunk被判定为"相关"的条件：
  1. 包含所有 must_contain 中的词
  2. 至少包含一个 any_of 中的词

指标（只保留3个各有意义的）：
  1. Hit@3   — top-3中至少有一个相关chunk的问题占比（系统能不能找到答案）
  2. MRR     — 第一个相关chunk的排名倒数的平均值（正确答案排在第几）
  3. Latency — 每次检索平均耗时（系统有多快）

用法: python3 eval/eval_search.py bge-small
      python3 eval/eval_search.py
"""

import json
import sys
import time
import urllib.request
import glob

API = "http://127.0.0.1:8901"
TOP_K = 3


def call_api(path, method="GET", data=None):
    url = f"{API}{path}"
    headers = {"Content-Type": "application/json"}
    if data:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    with opener.open(req) as resp:
        return json.loads(resp.read().decode())


def is_relevant(chunk_content, must_contain, any_of):
    """
    判断一个chunk是否"相关"：
    - 必须包含 must_contain 中的所有词
    - 至少包含 any_of 中的一个词
    """
    for term in must_contain:
        if term not in chunk_content:
            return False
    if any_of:
        found = any(term in chunk_content for term in any_of)
        if not found:
            return False
    return True


def find_first_relevant_rank(chunks, must_contain, any_of):
    """返回第一个相关chunk的排名（1-based），没有返回0"""
    for i, chunk in enumerate(chunks):
        content = chunk.get("content", "")
        if is_relevant(content, must_contain, any_of):
            return i + 1
    return 0


def evaluate(model_name, test_queries, top_k=TOP_K):
    results = []

    for q in test_queries:
        query = q["query"]
        must_contain = q.get("must_contain", [])
        any_of = q.get("any_of", [])

        try:
            search_data = {"query": query, "top_k": top_k, "model": model_name}
            t0 = time.time()
            resp = call_api("/api/search", "POST", search_data)
            latency = (time.time() - t0) * 1000

            chunks = resp.get("chunks", [])
        except Exception as e:
            print(f"  查询失败: {query} -> {e}")
            continue

        rank = find_first_relevant_rank(chunks, must_contain, any_of)
        hit = 1 if rank > 0 else 0
        rr = 1.0 / rank if rank > 0 else 0.0

        # 记录命中片段的前80字用于人工核查
        hit_preview = ""
        if rank > 0 and rank <= len(chunks):
            hit_preview = chunks[rank - 1].get("content", "")[:80]

        results.append({
            "query": query,
            "hit": hit,
            "rank": rank,
            "rr": rr,
            "latency_ms": round(latency),
            "hit_preview": hit_preview,
            "num_returned": len(chunks),
        })

    return results


def print_report(model_name, results, top_k):
    n = len(results)
    if n == 0:
        print("无有效结果")
        return None

    hit_rate = sum(r["hit"] for r in results) / n
    mrr = sum(r["rr"] for r in results) / n
    avg_latency = sum(r["latency_ms"] for r in results) / n

    print(f"\n{'=' * 70}")
    print(f"  模型: {model_name}  |  TOP-K: {top_k}  |  问题数: {n}  |  文档数: 自动导入")
    print(f"{'=' * 70}")
    print()
    print(f"  ┌──────────────────────────────────────────────────────────┐")
    print(f"  │ Hit@{top_k}   (找到答案比例)     {hit_rate:>8.1%}   │")
    print(f"  │ MRR     (正确答案平均排名)   {mrr:>8.4f}   │")
    print(f"  │ Latency (平均检索耗时)     {avg_latency:>6.0f}ms   │")
    print(f"  └──────────────────────────────────────────────────────────┘")
    print()
    print(f"  {'问题':<24} {'命中':>4} {'排名':>4} {'RR':>6} {'ms':>7}  命中片段预览")
    print(f"  {'-'*24} {'-'*4} {'-'*4} {'-'*6} {'-'*7}  {'-'*30}")

    for r in results:
        q_short = r["query"][:22]
        rank_str = str(r["rank"]) if r["rank"] > 0 else "-"
        hit_str = "Y" if r["hit"] else "N"
        preview = r["hit_preview"][:30] if r["hit_preview"] else ""
        print(f"  {q_short:<24} {hit_str:>4} {rank_str:>4} {r['rr']:>6.2f} {r['latency_ms']:>7}  {preview}")

    print()
    print(f"  {'='*70}")

    return {
        "model": model_name,
        "top_k": top_k,
        "num_queries": n,
        "hit_rate": hit_rate,
        "mrr": mrr,
        "avg_latency_ms": avg_latency,
    }


def main():
    with open("eval/test_queries.json", "r", encoding="utf-8") as f:
        test_queries = json.load(f)

    if len(sys.argv) > 1:
        models = [sys.argv[1]]
    else:
        models = ["bge-small", "m3e-base", "bge-m3"]

    try:
        call_api("/api/health")
        print(f"知识库服务在线，开始评估...")
        print(f"测试题集: {len(test_queries)} 道题")
    except Exception:
        print("错误: 知识库服务未启动，请先运行 cargo run")
        sys.exit(1)

    all_summaries = []

    for model in models:
        print(f"\n{'─'*70}")
        print(f"正在评估模型: {model}")
        print(f"正在重新导入文档（使用 {model}）...")

        import sqlite3
        conn = sqlite3.connect("data/knowledge.db")
        conn.execute("DELETE FROM chunks;")
        conn.execute("DELETE FROM documents;")
        conn.commit()
        conn.close()

        doc_files = sorted(glob.glob("test_docs/*.md") + glob.glob("test_docs/*.txt") + glob.glob("test_docs/*.pdf"))
        total_chunks = 0
        for doc_file in doc_files:
            try:
                resp = call_api("/api/ingest", "POST", {"file_path": doc_file, "model": model})
                chunks = resp.get("chunk_count", 0)
                total_chunks += chunks
                print(f"  导入 {doc_file}: {resp.get('status', '?')} ({chunks} 块)")
            except Exception as e:
                print(f"  导入失败 {doc_file}: {e}")
        print(f"  共导入 {len(doc_files)} 份文档，{total_chunks} 个文本块")

        results = evaluate(model, test_queries, TOP_K)
        summary = print_report(model, results, TOP_K)
        if summary:
            summary["total_chunks"] = total_chunks
            all_summaries.append(summary)

    if len(all_summaries) > 1:
        print(f"\n\n{'='*70}")
        print(f"  三模型对比总览")
        print(f"{'='*70}")
        print()
        print(f"  {'指标':<28}", end="")
        for s in all_summaries:
            print(f"  | {s['model']:<14}", end="")
        print()
        print(f"  {'-'*28}", end="")
        for _ in all_summaries:
            print(f"  {'-'*17}", end="")
        print()

        for metric, label, fmt in [
            ("hit_rate", "Hit@3 (找到答案比例)", "percent"),
            ("mrr", "MRR (正确答案排名)", "float"),
            ("avg_latency_ms", "Latency (平均耗时)", "int"),
            ("total_chunks", "总文本块数", "int"),
        ]:
            print(f"  {label:<28}", end="")
            for s in all_summaries:
                val = s[metric]
                if fmt == "percent":
                    print(f"  | {val:>10.1%}   ", end="")
                elif fmt == "float":
                    print(f"  | {val:>10.4f}   ", end="")
                else:
                    print(f"  | {val:>10.0f}   ", end="")
            print()

        print()
        print(f"  {'='*70}")


if __name__ == "__main__":
    main()
