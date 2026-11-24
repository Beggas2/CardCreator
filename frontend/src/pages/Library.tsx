import { useState } from "react";
import { api } from "../api";
import { Badge, Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface Doc { id: string; access_state: string; mime: string | null; pages: number | null; size_bytes: number | null;
  fetch_url: string | null; origin: string; pending_reason: string | null }
interface Version { id: string; version_label: string; published_at: string | null; validity_status: string;
  effective_from: string | null; effective_to: string | null; population: string; documents: Doc[] }
interface Source { id: string; title_claimed: string; title_confirmed: string | null; institution: string;
  source_tier: string; doc_type: string; url: string | null; notes: string; versions: Version[] }
interface Hit { section_id: string; document_id: string; snip: string; path: string; page_from: number | null;
  title: string; institution: string; source_tier: string; validity_status: string; published_at: string | null }
interface Section { id: string; path: string; kind: string; page_from: number | null; parse_quality: string; text: string }

const TIERS = ["BR_OFFICIAL", "BR_SOCIETY", "INTL_SOCIETY", "SYSTEMATIC_REVIEW", "PRIMARY_STUDY", "SECONDARY_CLINICAL",
  "NOT_ACCEPTED", "UNCLASSIFIED"];
const TIER_LABEL: Record<string, string> = { BR_OFFICIAL: "oficial BR", BR_SOCIETY: "sociedade BR",
  INTL_SOCIETY: "internacional", SYSTEMATIC_REVIEW: "revisão sistemática", PRIMARY_STUDY: "estudo primário",
  SECONDARY_CLINICAL: "secundária", NOT_ACCEPTED: "não aceita", UNCLASSIFIED: "não classificada" };
const DOC_STATE: Record<string, string> = { FOUND: "encontrado", RETRIEVED: "recuperado", PARTIALLY_READ: "lido em parte",
  VERIFIED: "conferido", UNAVAILABLE: "indisponível", OUTDATED: "desatualizado", VALIDITY_UNCERTAIN: "vigência incerta" };

export default function Library() {
  const sources = usePoll<Source[]>("/api/library/sources");
  const act = useAction();
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [form, setForm] = useState({ title_claimed: "", institution: "", source_tier: "BR_OFFICIAL", url: "",
    published_at: "", validity_status: "CURRENT" });
  const [file, setFile] = useState<File | null>(null);
  const [doc, setDoc] = useState<string | null>(null);
  const sections = usePoll<Section[]>(doc ? `/api/library/documents/${doc}/sections` : null);
  const [msg, setMsg] = useState<string | null>(null);

  const search = () => act.run(async () => {
    const p = new URLSearchParams({ q });
    if (tier) p.set("tier", tier);
    setHits(await api.get<Hit[]>(`/api/library/search?${p}`));
  });

  const add = () => act.run(async () => {
    const { published_at, validity_status, url, ...src } = form;
    const s = await api.post<{ id: string }>("/api/library/sources", { ...src, url: url || null });
    const v = await api.post<{ id: string }>(`/api/library/sources/${s.id}/versions`,
      { published_at: published_at || null, validity_status });
    let r: { state: string; sections: number; warnings: string[] } | null = null;
    if (file) r = await api.upload(`/api/library/versions/${v.id}/upload?filename=${encodeURIComponent(file.name)}`, file);
    else if (url) r = await api.post(`/api/library/versions/${v.id}/fetch`, { url });
    setMsg(r ? `Documento ${DOC_STATE[r.state] ?? r.state}: ${r.sections} seções${r.warnings.length ? ` · ${r.warnings.join("; ")}` : ""}`
      : "Fonte registrada sem documento.");
    setForm({ ...form, title_claimed: "", url: "" });
    setFile(null);
  }).then(sources.reload);

  return (
    <>
      <h1>Biblioteca científica</h1>
      <ErrorLine error={act.error || sources.error} />
      <Card title="Buscar nas fontes lidas">
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (q.trim()) search(); }}>
          <label>Termos<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ex.: dose losartana" /></label>
          <label>Nível<select value={tier} onChange={(e) => setTier(e.target.value)}>
            <option value="">todos</option>{TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
          </select></label>
          <button type="submit" disabled={act.busy || !q.trim()}>Buscar</button>
        </form>
        {hits && (hits.length ? (
          <ul className="hits">{hits.map((h) => (
            <li key={h.section_id}>
              <div><strong>{h.title}</strong> <span className="muted small">{h.institution} · {TIER_LABEL[h.source_tier]} · {h.published_at ?? "s/ data"} · {h.validity_status}</span></div>
              <div className="muted small">{h.path}{h.page_from ? ` · p. ${h.page_from}` : ""}</div>
              <div className="snip">{h.snip.split(/(\[[^\]]*\])/).map((part, i) =>
                part.startsWith("[") && part.endsWith("]") ? <mark key={i}>{part.slice(1, -1)}</mark> : part)}</div>
            </li>))}</ul>
        ) : <p className="muted">Nada encontrado.</p>)}
      </Card>

      <Card title="Adicionar fonte">
        <form className="row" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <label>Título<input value={form.title_claimed} onChange={(e) => setForm({ ...form, title_claimed: e.target.value })} required /></label>
          <label>Instituição<input value={form.institution} onChange={(e) => setForm({ ...form, institution: e.target.value })} /></label>
          <label>Nível<select value={form.source_tier} onChange={(e) => setForm({ ...form, source_tier: e.target.value })}>
            {TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}</select></label>
          <label>Publicação (AAAA-MM-DD)<input value={form.published_at} onChange={(e) => setForm({ ...form, published_at: e.target.value })} placeholder="2024-05" /></label>
          <label>Vigência<select value={form.validity_status} onChange={(e) => setForm({ ...form, validity_status: e.target.value })}>
            <option value="CURRENT">vigente</option><option value="UNCERTAIN">incerta</option>
            <option value="SUPERSEDED">substituída</option><option value="REVOKED">revogada</option></select></label>
          <label>Arquivo (PDF, HTML, TXT)<input type="file" accept=".pdf,.html,.htm,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <label>ou URL pública<input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://..." /></label>
          <button type="submit" disabled={act.busy || !form.title_claimed.trim()}>Adicionar</button>
        </form>
        {msg && <p className="notice">{msg}</p>}
        <p className="muted small">Uma fonte só sustenta afirmações depois que o documento é lido. O download aceita apenas endereços públicos.</p>
      </Card>

      <div className="split">
        <Card title={`Fontes (${sources.data?.length ?? 0})`}>
          {sources.data?.length ? (
            <ul className="list">{sources.data.map((s) => (
              <li key={s.id} className="source">
                <div><strong>{s.title_confirmed || s.title_claimed}</strong></div>
                <div className="muted small">{s.institution || "instituição não informada"} · {TIER_LABEL[s.source_tier] ?? s.source_tier}</div>
                {s.versions.map((v) => (
                  <div key={v.id} className="small">
                    {v.published_at ?? "s/ data"} · {v.validity_status}
                    {v.documents.map((d) => (
                      <button key={d.id} className={`link small ${doc === d.id ? "sel" : ""}`} onClick={() => setDoc(d.id)}>
                        <span>documento</span> <Badge state={d.access_state} />
                      </button>))}
                    {v.documents.filter((d) => d.pending_reason).map((d) => <div key={d.id} className="note small">{d.pending_reason}</div>)}
                  </div>))}
              </li>))}</ul>
          ) : <p className="muted">Nenhuma fonte ainda.</p>}
        </Card>
        {doc && (
          <Card title="Seções do documento">
            {sections.data?.map((s) => (
              <details key={s.id}>
                <summary>{s.path} {s.kind !== "TEXT" && <span className="muted small">({s.kind})</span>} {s.parse_quality !== "OK" && <Badge state={s.parse_quality === "FAILED" ? "FAILED" : "PAUSED"} />}</summary>
                <pre className="section-text">{s.text || "(sem texto extraível)"}</pre>
              </details>))}
          </Card>
        )}
      </div>
    </>
  );
}
