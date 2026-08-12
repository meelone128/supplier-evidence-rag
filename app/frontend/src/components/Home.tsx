import { FormEvent, useEffect, useState } from "react";
import clsx from "clsx";

import { ThemeToggle } from "./ThemeToggle";
import type { ColorScheme } from "../hooks/useColorScheme";

type HomeProps = { scheme: ColorScheme; onThemeChange: (scheme: ColorScheme) => void };
type Citation = { evidence_id: string; source_title: string; source_location: string };
type Finding = { code: string; severity: "info" | "medium" | "high"; message: string; citations: Citation[]; metadata?: { field?: string; values?: Record<string, string[]> } };
type EvidenceChunk = { chunk_id: string; doc_id: string; text: string; metadata: Record<string, unknown> };
type Report = {
  review: { evidence_score: number; risk_score: number; decision: string; missing_materials: string[]; conflicts: Finding[]; findings: Finding[]; evidence_score_breakdown: Record<string, number> };
  retrieved_evidence: Array<{ evidence_id: string; source_title: string; source_location: string; evidence_type: string; lexical_rank: number | null; vector_rank: number | null; fused_rank: number }>;
  output_gate_passed: boolean; output_gate_reason: string; retrieval_mode: string; rerank_mode: string;
  generated_report: { summary: string; recommended_actions: string[]; cited_evidence_ids: string[] } | null;
  generated_report_status: string;
};
type Evaluation = { total: number; passed: number; pass_rate: number; metrics: Record<string, { passed: number; total: number; rate: number }> };
type TedQueueItem = { id: string; status: string; target_supplier: string; matched_supplier_name: string; score: number; notice: Record<string, unknown> };
type IndexStatus = { ready: boolean; source_files: number; vector_points: number; collection: string };

const API_BASE = import.meta.env.VITE_SUPPLIER_EVIDENCE_API_BASE ?? "/supplier-evidence";
const materialNames: Record<string, string> = { business_license: "营业执照", iso_9001: "ISO 9001 证书", quality_inspection: "质量检验报告" };

function severityClass(severity: Finding["severity"]) {
  return severity === "high" ? "border-rose-200 bg-rose-50 text-rose-900" : severity === "medium" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-sky-200 bg-sky-50 text-sky-900";
}

export default function Home({ scheme, onThemeChange }: HomeProps) {
  const [supplierName, setSupplierName] = useState("Northstar Components GmbH");
  const [category, setCategory] = useState("industrial_components");
  const [region, setRegion] = useState("EU");
  const [question, setQuestion] = useState("核验必需材料、资质有效期与跨文档信息是否一致？");
  const [report, setReport] = useState<Report | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<{ evidence: Record<string, unknown>; source_text: string | null; chunks: EvidenceChunk[]; chunkStatus: string } | null>(null);
  const [conflictResolutions, setConflictResolutions] = useState<Record<string, { status: string; note: string }>>({});
  const [loading, setLoading] = useState(false);
  const [generateSummary, setGenerateSummary] = useState(false);
  const [enableRerank, setEnableRerank] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [tedQueue, setTedQueue] = useState<TedQueueItem[]>([]);
  const [tedNotice, setTedNotice] = useState<string | null>(null);
  const [tedSyncing, setTedSyncing] = useState(false);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [pendingUploads, setPendingUploads] = useState<Array<{ id: string; original_name: string; size_bytes: number; status: string; metadata?: { supplier_name: string; source_title: string } }>>([]);
  const [auditEvents, setAuditEvents] = useState<Array<{ timestamp: string; action: string; subject_id?: string; details: Record<string, unknown> }>>([]);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const [uploadSupplier, setUploadSupplier] = useState("Northstar Components GmbH");
  const [uploadTitle, setUploadTitle] = useState("补充供应商材料");
  const [uploadType, setUploadType] = useState("qualification");
  const [containsPersonalData, setContainsPersonalData] = useState(false);
  const [maskingConfirmed, setMaskingConfirmed] = useState(false);
  const [annotationNote, setAnnotationNote] = useState("");
  const [indexing, setIndexing] = useState(false);

  useEffect(() => {
    void fetch(`${API_BASE}/evaluations/latest`)
      .then((response) => response.ok ? response.json() as Promise<Evaluation> : null)
      .then((payload) => setEvaluation(payload))
      .catch(() => setEvaluation(null));
    void fetch(`${API_BASE}/ted/review-queue`)
      .then((response) => response.ok ? response.json() as Promise<{ items: TedQueueItem[] }> : null)
      .then((payload) => setTedQueue(payload?.items ?? []))
      .catch(() => setTedQueue([]));
    void fetch(`${API_BASE}/index/status`).then((response) => response.ok ? response.json() as Promise<IndexStatus> : null).then(setIndexStatus).catch(() => setIndexStatus(null));
    void fetch(`${API_BASE}/uploads/pending`).then((response) => response.ok ? response.json() as Promise<{ items: Array<{ id: string; original_name: string; size_bytes: number; status: string; metadata?: { supplier_name: string; source_title: string } }> }> : null).then((payload) => setPendingUploads(payload?.items ?? [])).catch(() => setPendingUploads([]));
    void fetch(`${API_BASE}/audit/events`).then((response) => response.ok ? response.json() as Promise<{ items: Array<{ timestamp: string; action: string; subject_id?: string; details: Record<string, unknown> }> }> : null).then((payload) => setAuditEvents(payload?.items ?? [])).catch(() => setAuditEvents([]));
    void fetch(`${API_BASE}/conflicts/resolutions`).then((response) => response.ok ? response.json() as Promise<{ items: Record<string, { status: string; note: string }> }> : null).then((payload) => setConflictResolutions(payload?.items ?? {})).catch(() => setConflictResolutions({}));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError(null);
    try {
      const response = await fetch(`${API_BASE}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ supplier_name: supplierName, category, region, question, generate_summary: generateSummary, enable_rerank: enableRerank }) });
      if (!response.ok) throw new Error("核验服务暂时不可用");
      setReport(await response.json() as Report);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "请求失败，请稍后重试");
    } finally { setLoading(false); }
  }

  async function openEvidence(evidenceId: string) {
    try {
      const [response, chunksResponse] = await Promise.all([fetch(`${API_BASE}/evidence/${evidenceId}`), fetch(`${API_BASE}/evidence/${evidenceId}/chunks`)]);
      if (!response.ok) throw new Error("无法加载证据详情");
      const detail = await response.json() as { evidence: Record<string, unknown>; source_text: string | null };
      const chunkPayload = chunksResponse.ok ? await chunksResponse.json() as { chunks: EvidenceChunk[]; duplicate_points_collapsed?: number } : { chunks: [] };
      const duplicateNote = chunkPayload.duplicate_points_collapsed ? `，已折叠 ${chunkPayload.duplicate_points_collapsed} 个历史重复点` : "";
      setSelectedEvidence({ ...detail, chunks: chunkPayload.chunks, chunkStatus: chunksResponse.ok ? `已从 Qdrant 读取${duplicateNote}` : "分片暂不可用或尚未入库" });
    } catch (detailError) { setError(detailError instanceof Error ? detailError.message : "无法加载证据详情"); }
  }

  function conflictId(finding: Finding) { return `${finding.metadata?.field ?? finding.code}:${finding.citations.map((item) => item.evidence_id).sort().join("|")}`; }
  async function updateConflict(finding: Finding, status: string, note: string) {
    const conflict_id = conflictId(finding);
    const response = await fetch(`${API_BASE}/conflicts/resolutions`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ conflict_id, status, note }) });
    if (!response.ok) { setError("无法保存冲突处置状态"); return; }
    setConflictResolutions((items) => ({ ...items, [conflict_id]: { status, note } }));
  }

  const riskItems = report ? [...report.review.conflicts, ...report.review.findings] : [];
  async function stageFile(file: File | undefined) {
    if (!file) return;
    setUploadNotice(null);
    const form = new FormData(); form.append("file", file); form.append("supplier_name", uploadSupplier); form.append("category", "industrial_components"); form.append("region", "EU"); form.append("evidence_type", uploadType); form.append("source_title", uploadTitle); form.append("source_version", "v1"); form.append("authority", "internal"); form.append("contains_personal_data", String(containsPersonalData)); form.append("masking_confirmed", String(maskingConfirmed)); form.append("annotation_note", annotationNote);
    const response = await fetch(`${API_BASE}/uploads/stage`, { method: "POST", body: form });
    const payload = await response.json() as { detail?: string; notice?: string; scan?: { scanned: boolean; matches: Record<string, number>; requires_confirmation: boolean }; item?: { id: string; original_name: string; size_bytes: number } };
    if (!response.ok) { setUploadNotice(payload.detail ?? "上传失败"); return; }
    if (payload.item) setPendingUploads((items) => [...items, payload.item!]);
    const scanMessage = payload.scan?.requires_confirmation ? ` 检测到可能的敏感字段：${Object.entries(payload.scan.matches).map(([key, count]) => `${key} ${count}`).join("、")}，请人工确认已脱敏。` : "";
    setUploadNotice((payload.notice ?? "文件已进入待入库区") + scanMessage);
  }

  async function rebuildApprovedIndex() {
    setIndexing(true); setUploadNotice(null);
    try {
      const response = await fetch(`${API_BASE}/index/rebuild-approved`, { method: "POST" });
      const payload = await response.json() as { notice?: string; detail?: string };
      setUploadNotice(payload.notice ?? payload.detail ?? "重建索引完成");
      if (response.ok) setPendingUploads((items) => items.map((item) => item.status === "approved_for_index" ? { ...item, status: "indexed" } : item));
    } catch { setUploadNotice("无法启动重建索引"); } finally { setIndexing(false); }
  }

  async function approveUpload(uploadId: string) {
    setUploadNotice(null);
    try {
      const response = await fetch(`${API_BASE}/uploads/pending/${uploadId}/approve`, { method: "POST" });
      const payload = await response.json() as { notice?: string; detail?: string };
      setUploadNotice(payload.notice ?? payload.detail ?? "审批完成");
      if (response.ok) setPendingUploads((items) => items.map((item) => item.id === uploadId ? { ...item, status: "approved_for_index" } : item));
    } catch { setUploadNotice("无法批准该文件"); }
  }

  async function syncTed() {
    setTedSyncing(true); setTedNotice(null);
    try {
      const response = await fetch(`${API_BASE}/ted/sync`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ supplier_name: supplierName, category, region, limit: 5 }) });
      const payload = await response.json() as { notice?: string; detail?: string };
      setTedNotice(payload.notice ?? payload.detail ?? "TED 同步完成");
      if (response.ok) {
        const queueResponse = await fetch(`${API_BASE}/ted/review-queue`);
        const queuePayload = await queueResponse.json() as { items: TedQueueItem[] };
        setTedQueue(queuePayload.items);
      }
    } catch { setTedNotice("无法连接 TED 公开接口"); } finally { setTedSyncing(false); }
  }

  async function confirmTed(reviewId: string) {
    setTedNotice(null);
    try {
      const response = await fetch(`${API_BASE}/ted/review-queue/${reviewId}/confirm`, { method: "POST" });
      const payload = await response.json() as { next_step?: string; detail?: string };
      setTedNotice(payload.next_step ?? payload.detail ?? "候选已确认");
      if (response.ok) setTedQueue((items) => items.map((item) => item.id === reviewId ? { ...item, status: "confirmed" } : item));
    } catch { setTedNotice("无法确认该候选记录"); }
  }

  function exportCurrentReport() {
    if (!report) return;
    const findings = [...report.review.conflicts, ...report.review.findings];
    const lines = [
      "# SupplierEvidence 供应商核验报告",
      "",
      `- 生成时间：${new Date().toLocaleString("zh-CN")}`,
      `- 检索模式：${report.retrieval_mode}`,
      `- 重排状态：${report.rerank_mode}`,
      "",
      "## 准入建议",
      report.review.decision,
      "",
      "## 评分",
      `- 证据分：${report.review.evidence_score}/100`,
      `- 规则风险分：${report.review.risk_score}/100`,
      ...Object.entries(report.review.evidence_score_breakdown).map(([key, value]) => `- ${scoreLabel(key)}：${value > 0 ? "+" : ""}${value}`),
      "",
      "## 缺失材料",
      ...(report.review.missing_materials.length ? report.review.missing_materials.map((item) => `- ${materialNames[item] ?? item}`) : ["- 无"]),
      "",
      "## 风险与冲突",
      ...(findings.length ? findings.map((item) => `- [${item.severity}] ${item.message}`) : ["- 无"]),
      "",
      "## 引用证据",
      ...report.retrieved_evidence.map((item) => `- ${item.evidence_id}｜${item.source_title}｜${item.source_location}`),
      "",
      "## 输出门禁",
      `- ${report.output_gate_passed ? "通过" : "拦截"}：${report.output_gate_reason}`,
    ];
    if (report.generated_report) {
      lines.push("", "## AI 核验说明", report.generated_report.summary, "", "### 建议动作", ...report.generated_report.recommended_actions.map((item) => `- ${item}`), "", `引用证据：${report.generated_report.cited_evidence_ids.join("、")}`);
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = "supplier-evidence-report.md"; link.click();
    URL.revokeObjectURL(url);
  }
  return <main className={clsx("min-h-screen transition-colors duration-300", scheme === "dark" ? "bg-slate-950 text-slate-100" : "bg-slate-50 text-slate-950")}>
    <div className="mx-auto min-h-screen max-w-7xl px-5 py-7 sm:px-8">
      <header className="mb-8 flex flex-col gap-5 border-b border-slate-200 pb-7 dark:border-slate-800 md:flex-row md:items-start md:justify-between">
        <div><p className="mb-2 text-xs font-bold uppercase tracking-[0.22em] text-teal-700 dark:text-teal-400">Evidence-grounded procurement RAG</p><h1 className="text-3xl font-bold tracking-tight sm:text-4xl">SupplierEvidence</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">供应商准入与采购证据核验平台 · 用可追溯证据辅助人工准入复核，不对企业作自动信用或法律判断。</p></div>
        <ThemeToggle value={scheme} onChange={onThemeChange} />
      </header>
      {evaluation && <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="flex flex-wrap items-baseline justify-between gap-2"><div><p className="text-sm font-bold">固定回归评测</p><p className="mt-1 text-xs text-slate-500">项目内 {evaluation.total} 条固定用例；不使用 LLM 裁判，结果可重复。</p></div><p className="text-sm font-semibold text-teal-700 dark:text-teal-400">{evaluation.passed} / {evaluation.total} 通过</p></div><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6"><EvalMetric label="证据召回" value={evaluation.metrics.evidence} /><EvalMetric label="材料缺失" value={evaluation.metrics.missing_materials} /><EvalMetric label="冲突识别" value={evaluation.metrics.conflicts} /><EvalMetric label="有效期识别" value={evaluation.metrics.findings} /><EvalMetric label="规则决策" value={evaluation.metrics.decision} /><EvalMetric label="输出门禁" value={evaluation.metrics.output_gate} /></div></section>}
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="flex flex-wrap items-baseline justify-between gap-3"><div><p className="text-sm font-bold">TED 公开采购候选审核</p><p className="mt-1 text-xs text-slate-500">按当前供应商名称拉取不超过 5 条公开公告；名称匹配仅作为候选，确认后才会纳入本地证据目录。</p></div><div className="flex items-center gap-2"><span className="rounded-full bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800">{tedQueue.filter((item) => item.status === "pending").length} 待确认</span><button type="button" disabled={tedSyncing} onClick={() => void syncTed()} className="rounded-lg border border-teal-700 px-3 py-1.5 text-xs font-semibold text-teal-700 disabled:opacity-50 dark:text-teal-400">{tedSyncing ? "正在拉取…" : "拉取 TED 公告"}</button></div></div>{tedNotice && <p className="mt-3 text-sm text-teal-700 dark:text-teal-400">{tedNotice}</p>}{tedQueue.length === 0 ? <p className="mt-4 rounded-xl bg-slate-100 p-3 text-sm text-slate-500 dark:bg-slate-800">暂无待确认公告。拉取结果不会自动并入供应商档案或向量索引。</p> : <div className="mt-4 space-y-2">{tedQueue.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-100 p-3 text-sm dark:bg-slate-800"><div><strong>{item.target_supplier}</strong><span className="mx-2 text-slate-400">←</span>{item.matched_supplier_name}<span className="ml-3 text-xs text-slate-500">匹配分 {Math.round(item.score * 100)} · {item.status}</span></div>{item.status === "pending" && <button type="button" onClick={() => void confirmTed(item.id)} className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700">确认纳入证据目录</button>}</div>)}</div>}</section>
      {indexStatus && <section className="mb-6 grid gap-3 sm:grid-cols-3"><Metric label="知识源文件" value={`${indexStatus.source_files}`} /><Metric label="Qdrant 向量片段" value={`${indexStatus.vector_points}`} /><Metric label="索引状态" value={indexStatus.ready ? "可用于混合检索" : "未连接"} /></section>}
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="flex items-baseline justify-between gap-3"><div><p className="text-sm font-bold">数据操作审计</p><p className="mt-1 text-xs text-slate-500">仅记录动作、时间与文件标识，不记录原文、手机号或其他敏感内容。</p></div><span className="text-xs text-slate-500">最近 {auditEvents.length} 条</span></div>{auditEvents.length === 0 ? <p className="mt-3 text-sm text-slate-500">尚未产生上传、审批、索引或 TED 审核操作。</p> : <ul className="mt-3 divide-y divide-slate-100 text-xs dark:divide-slate-800">{auditEvents.slice(0, 5).map((item, index) => <li key={`${item.timestamp}-${index}`} className="flex flex-wrap justify-between gap-2 py-2"><span className="font-medium">{auditActionLabel(item.action)}</span><span className="text-slate-500">{new Date(item.timestamp).toLocaleString("zh-CN")} {item.subject_id ? `· ${item.subject_id.slice(0, 8)}` : ""}</span></li>)}</ul>}</section>
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"><p className="text-sm font-bold">脱敏资料暂存与人工标注</p><p className="mt-1 text-xs text-slate-500">先标注资料范围和隐私状态，再上传。暂存文件不会参与检索、不会自动发给模型；需批准并显式重建索引。</p><div className="mt-4 grid gap-3 sm:grid-cols-3"><input className="input mt-0" value={uploadSupplier} onChange={(e) => setUploadSupplier(e.target.value)} aria-label="供应商" /><input className="input mt-0" value={uploadTitle} onChange={(e) => setUploadTitle(e.target.value)} aria-label="来源标题" /><select className="input mt-0" value={uploadType} onChange={(e) => setUploadType(e.target.value)} aria-label="证据类型"><option value="qualification">资质材料</option><option value="contract">合同材料</option><option value="historical_review">历史评审</option></select></div><textarea className="input mt-3 resize-none" value={annotationNote} onChange={(e) => setAnnotationNote(e.target.value)} rows={2} placeholder="人工标注：例如已核验有效期、注册地址字段来源或需复核事项" aria-label="人工标注说明" /><div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-600 dark:text-slate-300"><label className="inline-flex items-center gap-2"><input type="checkbox" checked={containsPersonalData} onChange={(e) => setContainsPersonalData(e.target.checked)} />资料可能含个人信息</label><label className="inline-flex items-center gap-2"><input type="checkbox" checked={maskingConfirmed} onChange={(e) => setMaskingConfirmed(e.target.checked)} />已完成脱敏确认</label></div><div className="mt-4 flex flex-wrap gap-3"><label className="inline-flex cursor-pointer rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-900">选择资料<input type="file" accept=".md,.txt,.csv,.pdf,.docx" className="hidden" onChange={(event) => void stageFile(event.target.files?.[0])} /></label><button type="button" disabled={indexing || !pendingUploads.some((item) => item.status === "approved_for_index")} onClick={() => void rebuildApprovedIndex()} className="rounded-lg border border-teal-700 px-4 py-2 text-sm font-semibold text-teal-700 disabled:cursor-not-allowed disabled:opacity-40 dark:text-teal-400">{indexing ? "正在重建索引…" : "确认重建已批准资料"}</button></div>{uploadNotice && <p className="mt-3 text-sm text-teal-700 dark:text-teal-400">{uploadNotice}</p>}{pendingUploads.length > 0 && <ul className="mt-4 divide-y divide-slate-100 text-sm dark:divide-slate-800">{pendingUploads.map((item) => <li key={item.id} className="flex justify-between gap-3 py-2"><span>{item.original_name}<small className="ml-2 text-slate-500">{item.metadata?.supplier_name ?? ""}</small></span><span className="flex flex-wrap items-center justify-end gap-2 text-slate-500">{item.status === "pending_index" && <button type="button" onClick={() => void approveUpload(item.id)} className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700">批准纳入知识源</button>}{item.status === "approved_for_index" ? "已纳入知识源，待重建索引" : item.status === "indexed" ? "已进入向量索引" : "待管理员批准"} · {Math.ceil(item.size_bytes / 1024)} KB</span></li>)}</ul>}</section>
      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="h-fit rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          <h2 className="text-lg font-bold">发起供应商核验</h2><p className="mt-1 text-sm text-slate-500">演示数据包含 Northstar 与 Eurofast 两家供应商。</p>
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <Label title="供应商"><input value={supplierName} onChange={(e) => setSupplierName(e.target.value)} className="input" /></Label>
            <Label title="采购品类"><select value={category} onChange={(e) => setCategory(e.target.value)} className="input"><option value="industrial_components">工业零部件</option></select></Label>
            <Label title="地区"><select value={region} onChange={(e) => setRegion(e.target.value)} className="input"><option value="EU">EU</option></select></Label>
            <Label title="核验问题"><textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={4} className="input resize-none" /></Label>
            <label className="flex items-start gap-2 text-xs leading-5 text-slate-600 dark:text-slate-300"><input type="checkbox" checked={generateSummary} onChange={(e) => setGenerateSummary(e.target.checked)} className="mt-1" />同时生成带引用的 AI 核验说明（仅在证据门禁通过后调用模型）</label>
            <label className="flex items-start gap-2 text-xs leading-5 text-slate-600 dark:text-slate-300"><input type="checkbox" checked={enableRerank} onChange={(e) => setEnableRerank(e.target.checked)} className="mt-1" />对 RRF 候选做 AI 重排序（仅允许调整当前候选的顺序）</label>
            <button disabled={loading} className="w-full rounded-lg bg-teal-700 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60">{loading ? "正在检索与核验…" : "生成证据档案"}</button>
          </form>
          {error && <p className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
          <div className="mt-6 rounded-xl bg-slate-100 p-3 text-xs leading-5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">处理链路：范围过滤 → BM25 / 向量召回 → RRF 融合 → Evidence Gate → 带引用报告。</div>
        </aside>
        <section className="space-y-6">
          {!report && <div className="grid min-h-[470px] place-items-center rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center dark:border-slate-700 dark:bg-slate-900"><div><p className="text-xl font-bold">等待发起核验</p><p className="mt-2 max-w-md text-sm text-slate-500">输入供应商、采购品类和地区后，系统会先检索证据，再检查材料完整性、有效期和字段冲突。</p></div></div>}
          {report && <>
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="text-sm font-semibold text-teal-700 dark:text-teal-400">准入建议</p><h2 className="mt-1 text-2xl font-bold">{report.review.decision}</h2></div><div className="flex items-center gap-2"><button type="button" onClick={exportCurrentReport} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold dark:border-slate-700">导出 Markdown</button><span className={clsx("rounded-full px-3 py-1 text-sm font-semibold", report.output_gate_passed ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800")}>{report.output_gate_passed ? "输出门禁通过" : "输出门禁拦截"}</span></div></div><p className="mt-4 text-sm text-slate-500">{report.output_gate_reason}</p><div className="mt-3 flex flex-wrap gap-2"><span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">检索：{report.retrieval_mode === "hybrid_bm25_vector_rrf" ? "BM25 + 向量 + RRF" : "BM25 降级"}</span><span className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">重排：{report.rerank_mode}</span></div><div className="mt-5 grid grid-cols-2 gap-3 sm:max-w-md"><Metric label="证据分" value={`${report.review.evidence_score} / 100`} /><Metric label="规则风险分" value={`${report.review.risk_score} / 100`} /></div><div className="mt-4 grid gap-2 text-xs text-slate-600 sm:grid-cols-3 dark:text-slate-300">{Object.entries(report.review.evidence_score_breakdown).map(([key, value]) => <div key={key} className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800"><span>{scoreLabel(key)}</span><strong className="float-right">{value > 0 ? "+" : ""}{value}</strong></div>)}</div></div>
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"><div className="flex items-center justify-between gap-4"><h3 className="text-lg font-bold">AI 核验说明</h3><span className="text-xs text-slate-500">{report.generated_report_status}</span></div>{report.generated_report ? <><p className="mt-3 text-sm leading-6 text-slate-700 dark:text-slate-200">{report.generated_report.summary}</p>{report.generated_report.recommended_actions.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600 dark:text-slate-300">{report.generated_report.recommended_actions.map((action, index) => <li key={index}>{action}</li>)}</ul>}<p className="mt-3 text-xs text-slate-500">引用证据：{report.generated_report.cited_evidence_ids.join("、") || "无"}</p></> : <p className="mt-3 text-sm text-slate-500">勾选“生成带引用的 AI 核验说明”后按需生成；引用不在当前检索结果中时会被系统拦截。</p>}</div>
            <div className="grid gap-6 xl:grid-cols-2"><Panel title="缺失材料" empty="当前未发现缺失的必需材料。">{report.review.missing_materials.map((item) => <li key={item}>{materialNames[item] ?? item}</li>)}</Panel><Panel title="风险与冲突" empty="当前未发现需要人工确认的风险项。">{riskItems.map((finding, index) => { const id = conflictId(finding); const resolution = conflictResolutions[id]; return <li key={`${finding.code}-${index}`} className={clsx("rounded-lg border p-3", severityClass(finding.severity))}><div className="flex flex-wrap items-start justify-between gap-2"><p className="font-semibold">{finding.message}</p>{finding.code === "conflicting_evidence" && <span className="rounded-full bg-white/70 px-2 py-1 text-xs">{resolution?.status === "resolved" ? "已解决" : resolution?.status === "confirmed" ? "已确认" : "待确认"}</span>}</div>{finding.metadata?.field && <div className="mt-2 rounded bg-white/60 p-2 text-xs"><p>冲突字段：{finding.metadata.field}</p>{Object.entries(finding.metadata.values ?? {}).map(([value, ids]) => <p key={value} className="mt-1">“{value}” ← {ids.join("、")}</p>)}</div>}{finding.citations.length > 0 && <p className="mt-2 text-xs opacity-80">来源：{finding.citations.map((citation) => citation.source_title).join("；")}</p>}{finding.code === "conflicting_evidence" && <div className="mt-3 flex flex-wrap gap-2"><select value={resolution?.status ?? "pending"} onChange={(event) => void updateConflict(finding, event.target.value, resolution?.note ?? "")} className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700"><option value="pending">待确认</option><option value="confirmed">已确认冲突</option><option value="resolved">已解决</option></select><input value={resolution?.note ?? ""} onChange={(event) => setConflictResolutions((items) => ({ ...items, [id]: { status: resolution?.status ?? "pending", note: event.target.value } }))} onBlur={(event) => void updateConflict(finding, resolution?.status ?? "pending", event.target.value)} placeholder="填写人工处理说明" className="min-w-40 flex-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700" /></div>}</li>})}</Panel></div>
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"><h3 className="text-lg font-bold">检索到的证据</h3><div className="mt-4 divide-y divide-slate-100 dark:divide-slate-800">{report.retrieved_evidence.map((item) => <button type="button" onClick={() => void openEvidence(item.evidence_id)} key={item.evidence_id} className="block w-full py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-800/60"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">{item.source_title}</p><span className="rounded bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800">融合排序 #{item.fused_rank}</span></div><p className="mt-1 text-xs text-slate-500">{item.evidence_type} · {item.source_location} · BM25 #{item.lexical_rank ?? "-"} · 向量 #{item.vector_rank ?? "未接入"}</p></button>)}</div></div>
          </>}
        </section>
      </div>
      {selectedEvidence && <div className="fixed inset-0 z-20 grid place-items-center bg-slate-950/45 p-4" role="dialog" aria-modal="true"><div className="max-h-[85vh] w-full max-w-4xl overflow-auto rounded-2xl bg-white p-6 shadow-2xl dark:bg-slate-900"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-wider text-teal-700">Evidence detail</p><h3 className="mt-1 text-xl font-bold">{String(selectedEvidence.evidence.source_title ?? "证据详情")}</h3></div><button type="button" onClick={() => setSelectedEvidence(null)} className="rounded-lg border px-3 py-1 text-sm">关闭</button></div><dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">{["evidence_id", "evidence_type", "source_version", "source_location", "authority", "issued_on", "expires_on"].map((key) => <div key={key} className="rounded-lg bg-slate-100 p-3 dark:bg-slate-800"><dt className="text-xs text-slate-500">{key}</dt><dd className="mt-1 font-medium">{String(selectedEvidence.evidence[key] ?? "-")}</dd></div>)}</dl><div className="mt-4 rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800"><p className="text-xs text-slate-500">结构化字段</p><pre className="mt-2 overflow-auto whitespace-pre-wrap font-sans">{JSON.stringify(selectedEvidence.evidence.fields ?? {}, null, 2)}</pre></div><div className="mt-5"><div className="flex items-center justify-between gap-3"><p className="text-sm font-semibold">Qdrant 已入库分片</p><span className="text-xs text-slate-500">{selectedEvidence.chunkStatus} · {selectedEvidence.chunks.length} 个</span></div>{selectedEvidence.chunks.length ? <div className="mt-3 space-y-3">{selectedEvidence.chunks.map((chunk, index) => <article key={chunk.chunk_id} className="rounded-lg border border-teal-100 bg-teal-50/40 p-3 text-sm dark:border-teal-950 dark:bg-teal-950/20"><div className="flex flex-wrap justify-between gap-2 text-xs text-slate-500"><span>Chunk #{index + 1} · {chunk.chunk_id.slice(0, 10)}</span><span>{chunk.metadata.evidence_id ? `证据：${String(chunk.metadata.evidence_id)}` : ""}</span></div><pre className="mt-2 whitespace-pre-wrap font-sans leading-6">{chunk.text}</pre></article>)}</div> : <p className="mt-2 text-sm text-slate-500">该演示证据尚未在当前 Qdrant 集合中发现可展示分片。</p>}</div><div className="mt-5"><p className="text-sm font-semibold">原始材料</p><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 p-4 text-sm leading-6 dark:border-slate-700">{selectedEvidence.source_text ?? "原始材料不可用"}</pre></div></div></div>}
    </div>
  </main>;
}

function Label({ title, children }: { title: string; children: React.ReactNode }) { return <label className="block text-sm font-semibold">{title}{children}</label>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-xl bg-slate-100 p-4 dark:bg-slate-800"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-bold">{value}</p></div>; }
function EvalMetric({ label, value }: { label: string; value: { passed: number; total: number; rate: number } | undefined }) { return <div className="rounded-xl bg-slate-100 p-3 dark:bg-slate-800"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-base font-bold">{value ? `${value.passed}/${value.total}` : "-"}</p></div>; }
function scoreLabel(key: string) { return ({ base_score: "基础分", document_coverage: "文档覆盖", material_coverage: "材料覆盖", authority_bonus: "权威来源", conflict_penalty: "冲突扣分", missing_material_penalty: "缺失扣分" } as Record<string, string>)[key] ?? key; }
function auditActionLabel(action: string) { return ({ upload_staged: "资料暂存", upload_approved: "资料批准", approved_uploads_indexed: "已批准资料完成索引", ted_sync: "TED 公告同步", ted_candidate_confirmed: "TED 候选确认", conflict_resolution_updated: "冲突处置更新" } as Record<string, string>)[action] ?? action; }
function Panel({ title, empty, children }: { title: string; empty: string; children: React.ReactNode }) { const items = Array.isArray(children) ? children : [children]; return <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"><h3 className="text-lg font-bold">{title}</h3>{items.filter(Boolean).length ? <ul className="mt-4 space-y-2 text-sm">{children}</ul> : <p className="mt-4 text-sm text-slate-500">{empty}</p>}</div>; }
