import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { call } from "./api/tauri";
import type {
  Benchmark, ChunkView, Dashboard, DocumentView, EmbeddingIndexResult,
  EmbeddingModelInfo, EmbeddingServiceStatus, KnowledgeBase, Profile,
  RagResponse, SearchHit, Settings,
} from "./types";

type Page = "dashboard" | "knowledge" | "files" | "embedding" | "search" | "rag" | "settings" | "benchmark";
type Runner = <T>(operation: () => Promise<T>, success?: string) => Promise<T | undefined>;
const nav: [Page, string][] = [["dashboard", "总览"], ["knowledge", "知识库"], ["files", "文件"], ["embedding", "Embedding"], ["search", "向量检索"], ["rag", "RAG 问答"], ["settings", "设置"], ["benchmark", "性能测试"]];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const active = useMemo(() => kbs.find((kb) => kb.id === selected), [kbs, selected]);
  const refreshKbs = useCallback(async () => {
    const rows = await call<KnowledgeBase[]>("list_knowledge_bases");
    setKbs(rows);
    setSelected((current) => current && rows.some((kb) => kb.id === current) ? current : (rows[0]?.id ?? ""));
  }, []);
  useEffect(() => { refreshKbs().catch((reason) => setError(String(reason))); }, [refreshKbs]);
  const run: Runner = async (operation, success) => {
    setBusy(true); setError("");
    try { const result = await operation(); if (success) setMessage(success); return result; }
    catch (reason) { setError(String(reason)); return undefined; }
    finally { setBusy(false); }
  };
  return <div className="shell"><aside><div className="brand"><span>LK</span><div><strong>Local KB</strong><small>证券端侧知识库</small></div></div><nav>{nav.map(([id, label]) => <button className={page === id ? "active" : ""} key={id} onClick={() => setPage(id)}>{label}</button>)}</nav><div className="mock-note">支持 Python SentenceTransformer Sidecar；Mock 仍仅用于工程链路验证。</div></aside>
    <main><header><div><h1>{nav.find((item) => item[0] === page)?.[1]}</h1><p>{active ? `当前知识库：${active.name}` : "请先创建知识库"}</p></div><select value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">未选择</option>{kbs.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}</select></header>
      {(message || error) && <div className={error ? "toast error" : "toast"} onClick={() => { setMessage(""); setError(""); }}>{error || message}</div>}
      {page === "dashboard" && <DashboardPage busy={busy} />}{page === "knowledge" && <KnowledgePage kbs={kbs} selected={selected} setSelected={setSelected} refresh={refreshKbs} run={run} />}{page === "files" && <FilesPage kb={active} run={run} />}{page === "embedding" && <EmbeddingPage kbId={selected} run={run} />}{page === "search" && <SearchPage kbId={selected} run={run} />}{page === "rag" && <RagPage kbId={selected} run={run} />}{page === "settings" && <SettingsPage />}{page === "benchmark" && <BenchmarkPage run={run} />}{busy && <div className="busy">处理中…</div>}
    </main></div>;
}

function DashboardPage({ busy }: { busy: boolean }) {
  const [data, setData] = useState<Dashboard>();
  useEffect(() => { call<Dashboard>("get_dashboard").then(setData); }, [busy]);
  if (!data) return <Empty text="加载中…" />;
  return <section><div className="stats">{[["知识库", data.knowledge_bases], ["文档", data.documents], ["Chunks", data.chunks], ["Vectors", data.vectors]].map(([label, value]) => <article key={label}><small>{label}</small><b>{value}</b></article>)}</div><div className="grid two"><Card title="向量存储"><p>{data.vector_store}</p><Tag value={data.index_status} /></Card><Card title="Embedding"><p>当前状态：{data.embedding_status}</p><p className="muted">可使用 Rust Mock、Python Sidecar 或外部 Vector JSON。</p></Card></div></section>;
}

function KnowledgePage({ kbs, selected, setSelected, refresh, run }: { kbs: KnowledgeBase[]; selected: string; setSelected: (value: string) => void; refresh: () => Promise<void>; run: Runner }) {
  const [name, setName] = useState("示例金融知识库");
  const [path, setPath] = useState("D:\\Workspace\\local-kb\\sample_docs");
  const [size, setSize] = useState(500); const [overlap, setOverlap] = useState(80);
  const create = () => run(async () => { const kb = await call<KnowledgeBase>("create_knowledge_base", { name, rootPath: path, chunkSize: size, chunkOverlap: overlap }); await refresh(); setSelected(kb.id); }, "知识库已创建");
  return <section className="grid two"><Card title="创建知识库"><Field label="名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field><Field label="本地目录"><input value={path} onChange={(event) => setPath(event.target.value)} /></Field><div className="row"><Field label="Chunk 字符数"><input type="number" value={size} onChange={(event) => setSize(+event.target.value)} /></Field><Field label="Overlap"><input type="number" value={overlap} onChange={(event) => setOverlap(+event.target.value)} /></Field></div><button className="primary" onClick={create}>创建</button></Card><Card title="知识库列表">{kbs.length === 0 ? <Empty /> : kbs.map((kb) => <div className={`list-item ${selected === kb.id ? "selected" : ""}`} key={kb.id} onClick={() => setSelected(kb.id)}><div><strong>{kb.name}</strong><small>{kb.root_path}</small><small>Chunk {kb.chunk_size} / Overlap {kb.chunk_overlap}</small></div><button className="danger" onClick={(event) => { event.stopPropagation(); run(async () => { await call("delete_knowledge_base", { knowledgeBaseId: kb.id }); await refresh(); }, "知识库已删除"); }}>删除</button></div>)}</Card></section>;
}

function FilesPage({ kb, run }: { kb?: KnowledgeBase; run: Runner }) {
  const [docs, setDocs] = useState<DocumentView[]>([]); const [filePath, setFilePath] = useState("");
  const refresh = useCallback(() => kb ? call<DocumentView[]>("list_documents", { knowledgeBaseId: kb.id }).then(setDocs) : Promise.resolve(setDocs([])), [kb]);
  useEffect(() => { refresh(); }, [refresh]);
  if (!kb) return <Empty text="请先选择知识库" />;
  const action = (command: string, args: Record<string, unknown>, message: string) => run(async () => { await call(command, args); await refresh(); }, message);
  return <section><div className="toolbar"><button className="primary" onClick={() => action("scan_knowledge_base", { knowledgeBaseId: kb.id }, "增量扫描完成")}>重新扫描</button><button onClick={() => run(() => call("open_directory", { path: kb.root_path }), "目录已打开")}>打开目录</button><button onClick={() => action("start_watcher", { knowledgeBaseId: kb.id }, "文件监听已启动")}>启动监听</button><button onClick={() => action("stop_watcher", { knowledgeBaseId: kb.id }, "文件监听已停止")}>停止监听</button><input placeholder="单个 .md/.txt 绝对路径" value={filePath} onChange={(event) => setFilePath(event.target.value)} /><button onClick={() => action("add_file", { knowledgeBaseId: kb.id, filePath }, "文件已解析")}>添加文件</button></div><div className="table-wrap"><table><thead><tr><th>文件</th><th>Hash</th><th>更新时间</th><th>Chunk / Vector</th><th>状态</th><th /></tr></thead><tbody>{docs.map((doc) => <tr key={doc.id}><td><b>{doc.file_name}</b><small>{doc.file_path}</small></td><td className="mono">{doc.file_hash.slice(0, 12)}</td><td>{new Date(doc.updated_at).toLocaleString()}</td><td>{doc.chunk_count} / {doc.vector_count}</td><td><Tag value={doc.status} /></td><td><button onClick={() => action("reparse_document", { documentId: doc.id }, "文档已重新解析")}>重建</button><button className="danger" onClick={() => action("delete_document", { documentId: doc.id }, "文档记录已删除")}>删除</button></td></tr>)}</tbody></table>{docs.length === 0 && <Empty text="点击重新扫描以导入 Markdown / TXT" />}</div></section>;
}

function EmbeddingPage({ kbId, run }: { kbId: string; run: Runner }) {
  const [profiles, setProfiles] = useState<Profile[]>([]); const [chunks, setChunks] = useState<ChunkView[]>([]);
  const [models, setModels] = useState<EmbeddingModelInfo[]>([]); const [status, setStatus] = useState<EmbeddingServiceStatus>();
  const [modelId, setModelId] = useState("bge-small"); const [json, setJson] = useState("");
  const refresh = useCallback(async () => {
    const [newProfiles, newChunks, newModels, newStatus] = await Promise.all([call<Profile[]>("list_embedding_profiles", { knowledgeBaseId: kbId || null }), kbId ? call<ChunkView[]>("list_chunks", { knowledgeBaseId: kbId }) : Promise.resolve([]), call<EmbeddingModelInfo[]>("list_embedding_models"), call<EmbeddingServiceStatus>("get_embedding_service_status")]);
    setProfiles(newProfiles); setChunks(newChunks); setModels(newModels.filter((model) => model.runtime !== "rust-mock")); setStatus(newStatus);
  }, [kbId]);
  useEffect(() => { refresh(); }, [refresh]);
  if (!kbId) return <Empty text="请先选择知识库" />;
  const start = () => run(async () => { await call("start_embedding_service"); await refresh(); }, "Embedding 服务已启动");
  const stop = () => run(async () => { await call("stop_embedding_service"); await refresh(); }, "Embedding 服务已停止");
  const index = () => run(async () => { const result = await call<EmbeddingIndexResult>("index_with_embedding", { knowledgeBaseId: kbId, modelId }); await refresh(); return result; }, "真实 Embedding 索引已构建");
  return <section className="grid two"><Card title="Python Embedding Sidecar"><div className="service-status"><Tag value={status?.reachable ? "RUNNING" : "STOPPED"} /><span>{status?.managed ? `由应用管理 · PID ${status.pid}` : "外部服务或未启动"}</span></div><dl className="settings"><dt>URL</dt><dd>{status?.base_url}</dd><dt>协议</dt><dd>{status?.protocol_version || "未连接"}</dd><dt>Python 依赖</dt><dd>{status?.dependency_available ? "已安装" : "未检测到"}</dd><dt>离线模式</dt><dd>{status?.offline === undefined ? "未知" : status.offline ? "开启" : "关闭"}</dd><dt>Python</dt><dd>{status?.python}</dd><dt>Script</dt><dd>{status?.script}</dd><dt>已加载</dt><dd>{status?.loaded_models.join(", ") || "无（模型按需加载）"}</dd></dl>{status?.error && <p className="warning">{status.error}</p>}<div className="row"><button className="primary" onClick={start}>启动服务</button><button onClick={stop}>停止托管服务</button><button onClick={() => refresh()}>刷新状态</button></div></Card>
    <Card title="建立真实向量索引"><Field label="Embedding 模型"><select value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((model) => <option key={model.model_id} value={model.model_id}>{model.model_name} · {model.dimension}d</option>)}</select></Field><p className="muted">按当前 Chunk 批量调用 Sidecar，校验模型空间后写入 SQLite。第一次推理需要先准备好对应模型。</p><button className="primary" disabled={!status?.reachable || !status.dependency_available || chunks.length === 0} onClick={index}>为全部 Chunk 建立索引</button></Card>
    <Card title="Embedding Profiles"><button onClick={() => run(async () => { await call("mock_index", { knowledgeBaseId: kbId }); await refresh(); }, "Mock 向量索引已构建")}>生成 Mock Index</button>{profiles.map((profile) => <div className="profile" key={profile.id}><div><strong>{profile.model_name}</strong><Tag value={profile.status} /></div><dl><dt>model_id</dt><dd>{profile.model_id}</dd><dt>dimension</dt><dd>{profile.dimension}</dd><dt>config_hash</dt><dd>{profile.config_hash}</dd><dt>runtime</dt><dd>{profile.runtime}</dd><dt>vectors</dt><dd>{profile.vector_count}</dd></dl></div>)}</Card>
    <Card title="导入外部 Vector JSON"><p className="muted">离线生成仍可通过标准 JSON 导入，所有维度和 Chunk 归属会先校验。</p><textarea rows={14} value={json} onChange={(event) => setJson(event.target.value)} placeholder='{"knowledge_base_id":"...","model_info":{...},"vectors":[...]}' /><button onClick={() => run(async () => { await call("import_embedding_vectors", { json }); await refresh(); }, "外部向量导入成功")}>校验并导入</button></Card>
    <div className="full"><Card title={`待对接 Chunks（${chunks.length}）`}><div className="chunk-list">{chunks.slice(0, 50).map((chunk) => <div key={chunk.id}><code>{chunk.id}</code><span>{chunk.file_name} · #{chunk.chunk_index}</span><p>{chunk.text.slice(0, 100)}</p></div>)}</div>{chunks.length > 50 && <p className="muted">界面仅展示前 50 条。</p>}</Card></div></section>;
}

function SearchPage({ kbId, run }: { kbId: string; run: Runner }) {
  const [mode, setMode] = useState<"mock" | "sidecar" | "raw">("sidecar"); const [query, setQuery] = useState("银行风险管理有哪些要求？"); const [raw, setRaw] = useState(""); const [topK, setTopK] = useState(5); const [hits, setHits] = useState<SearchHit[]>([]); const [profiles, setProfiles] = useState<Profile[]>([]); const [models, setModels] = useState<EmbeddingModelInfo[]>([]); const [profileId, setProfileId] = useState(""); const [modelId, setModelId] = useState("bge-small");
  useEffect(() => { if (kbId) call<Profile[]>("list_embedding_profiles", { knowledgeBaseId: kbId }).then((items) => { setProfiles(items); setProfileId((value) => value || items[0]?.id || ""); }); call<EmbeddingModelInfo[]>("list_embedding_models").then((items) => setModels(items.filter((model) => model.runtime !== "rust-mock"))); }, [kbId]);
  if (!kbId) return <Empty text="请先选择知识库" />;
  const search = () => run(async () => { const result = mode === "mock" ? await call<SearchHit[]>("search_mock", { knowledgeBaseId: kbId, query, topK }) : mode === "sidecar" ? await call<SearchHit[]>("search_with_embedding", { knowledgeBaseId: kbId, modelId, query, topK }) : await call<SearchHit[]>("search_by_vector", { knowledgeBaseId: kbId, embeddingProfileId: profileId, queryVector: raw.split(/[\s,]+/).filter(Boolean).map(Number), topK }); setHits(result); }, "检索完成");
  return <section><Card title="检索条件"><div className="tabs"><button className={mode === "sidecar" ? "active" : ""} onClick={() => setMode("sidecar")}>真实 Embedding</button><button className={mode === "mock" ? "active" : ""} onClick={() => setMode("mock")}>Mock Query</button><button className={mode === "raw" ? "active" : ""} onClick={() => setMode("raw")}>Raw Query Vector</button></div>{mode === "raw" ? <><select value={profileId} onChange={(event) => setProfileId(event.target.value)}>{profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.model_name} · {profile.dimension}d</option>)}</select><textarea rows={5} value={raw} onChange={(event) => setRaw(event.target.value)} placeholder="0.12, -0.03, ..." /></> : <><textarea rows={3} value={query} onChange={(event) => setQuery(event.target.value)} />{mode === "sidecar" && <select value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((model) => <option value={model.model_id} key={model.model_id}>{model.model_name} · {model.dimension}d</option>)}</select>}</>}<div className="row end"><Field label="Top-K"><input type="number" min={1} max={50} value={topK} onChange={(event) => setTopK(+event.target.value)} /></Field><button className="primary" onClick={search}>搜索</button></div></Card><Results hits={hits} /></section>;
}

function RagPage({ kbId, run }: { kbId: string; run: Runner }) {
  const [mode, setMode] = useState<"mock" | "sidecar">("sidecar"); const [models, setModels] = useState<EmbeddingModelInfo[]>([]); const [modelId, setModelId] = useState("bge-small"); const [question, setQuestion] = useState("投资组合的主要风险控制原则是什么？"); const [topK, setTopK] = useState(5); const [result, setResult] = useState<RagResponse>();
  useEffect(() => { call<EmbeddingModelInfo[]>("list_embedding_models").then((items) => setModels(items.filter((model) => model.runtime !== "rust-mock"))); }, []);
  if (!kbId) return <Empty text="请先选择知识库" />;
  const submit = () => run(async () => setResult(mode === "mock" ? await call<RagResponse>("rag_query", { knowledgeBaseId: kbId, question, topK }) : await call<RagResponse>("rag_query_with_embedding", { knowledgeBaseId: kbId, question, topK, modelId })), "RAG 调用完成");
  return <section className="grid rag-grid"><Card title="提问"><div className="tabs"><button className={mode === "sidecar" ? "active" : ""} onClick={() => setMode("sidecar")}>真实 Embedding</button><button className={mode === "mock" ? "active" : ""} onClick={() => setMode("mock")}>Mock</button></div>{mode === "sidecar" && <select value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((model) => <option value={model.model_id} key={model.model_id}>{model.model_name}</option>)}</select>}<textarea rows={6} value={question} onChange={(event) => setQuestion(event.target.value)} /><div className="row end"><Field label="Top-K"><input type="number" value={topK} onChange={(event) => setTopK(+event.target.value)} /></Field><button className="primary" onClick={submit}>发送</button></div>{mode === "mock" && <div className="warning">Mock 模式只验证工程编排，不代表语义质量。</div>}</Card><Card title="回答">{result ? <><p className="answer">{result.answer}</p>{result.warning && <p className="warning">{result.warning}</p>}</> : <Empty text="尚未提问" />}</Card>{result && <div className="full"><Results hits={result.sources} /></div>}</section>;
}

function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(); useEffect(() => { call<Settings>("get_settings").then(setSettings); }, []); if (!settings) return <Empty />;
  return <section className="grid two"><Card title="本地运行"><dl className="settings"><dt>SQLite Path</dt><dd>{settings.database_path}</dd><dt>Vector Store</dt><dd>{settings.vector_store}</dd><dt>Chunk Size</dt><dd>{settings.chunk_size}</dd><dt>Overlap</dt><dd>{settings.chunk_overlap}</dd><dt>Providers</dt><dd>{settings.registered_providers.join(", ")}</dd></dl></Card><Card title="Embedding Sidecar"><dl className="settings"><dt>Base URL</dt><dd>{settings.embedding_base_url}</dd><dt>Python</dt><dd>{settings.embedding_python}</dd><dt>Script</dt><dd>{settings.embedding_script}</dd><dt>Batch Size</dt><dd>{settings.embedding_batch_size}</dd></dl></Card><Card title="DeepSeek API"><dl className="settings"><dt>Provider</dt><dd>{settings.llm_provider}</dd><dt>Base URL</dt><dd>{settings.llm_base_url}</dd><dt>Model</dt><dd>{settings.llm_model}</dd><dt>Thinking</dt><dd>{settings.llm_thinking ? `enabled · ${settings.llm_reasoning_effort}` : "disabled"}</dd><dt>Timeout</dt><dd>{settings.llm_timeout_secs}s</dd><dt>API Key</dt><dd><Tag value={settings.llm_api_key_configured ? "CONFIGURED" : "NOT_CONFIGURED"} /></dd></dl><p className="muted">通过项目根目录 .env 配置；API Key 不写入 SQLite 或返回前端。</p></Card></section>;
}

function BenchmarkPage({ run }: { run: Runner }) {
  const [count, setCount] = useState(100); const [dimension, setDimension] = useState(64); const [result, setResult] = useState<Benchmark>();
  return <section className="grid two"><Card title="可重复微基准"><Field label="Chunk 数量"><select value={count} onChange={(event) => setCount(+event.target.value)}><option>100</option><option>1000</option><option>10000</option></select></Field><Field label="Vector 维度"><input type="number" value={dimension} onChange={(event) => setDimension(+event.target.value)} /></Field><button className="primary" onClick={() => run(async () => setResult(await call<Benchmark>("run_benchmark", { chunkCount: count, dimension })), "Benchmark 完成")}>运行</button><p className="muted">使用隔离的内存 SQLite，不污染业务数据。</p></Card><Card title="结果（毫秒）">{result ? <dl className="settings"><dt>Vector Insert</dt><dd>{result.insert_ms.toFixed(2)}</dd><dt>Search Top-5</dt><dd>{result.search_top5_ms.toFixed(2)}</dd><dt>Search Top-10</dt><dd>{result.search_top10_ms.toFixed(2)}</dd><dt>SQLite Read</dt><dd>{result.sqlite_read_ms.toFixed(3)}</dd></dl> : <Empty text="尚未运行" />}</Card></section>;
}

function Card({ title, children }: { title: string; children: ReactNode }) { return <article className="card"><h2>{title}</h2>{children}</article>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function Tag({ value }: { value: string }) { return <span className={`tag ${value.toLowerCase()}`}>{value}</span>; }
function Empty({ text = "暂无数据" }: { text?: string }) { return <div className="empty">{text}</div>; }
function Results({ hits }: { hits: SearchHit[] }) { return <div className="results">{hits.map((hit, index) => <article key={hit.chunk_id}><div className="result-head"><b>#{index + 1} · {hit.file_name}</b><span>{hit.score.toFixed(4)}</span></div><p>{hit.text}</p><small>{hit.chunk_id} · chunk {hit.chunk_index}</small></article>)}{hits.length === 0 && <Empty text="暂无检索结果" />}</div>; }
