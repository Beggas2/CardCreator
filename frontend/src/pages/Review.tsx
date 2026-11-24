import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";
import { CardPreview, type Rendered } from "../preview";

interface Project { id: string; name: string }
interface QRow {
  id: string; card_key: string; state: string; quarantine: boolean; deck_path: string; version_no: number;
  schema_version: string; layout: string | null; front: string; open_defects: Record<string, number>; pending_proposals: number;
}
interface Reason { code: string; label: string }
interface Defect { id: string; category: string; severity: string; description: string; status: string; origin: string }
interface Claim { claim_id: string; text: string; criticality: string; verdict: string | null; evidence_ids: string[] }
interface Proposal { id: string; kind: string; actor_type: string; justification: string; decision: string | null }
interface Decision { id: string; decision: string; reasons: string[]; note: string; actor: string; created_at: string; undoes_id: string | null }
interface Detail { blockers: string[]; defects: Defect[]; claims: Claim[]; proposals: Proposal[]; decisions: Decision[] }
interface CardData { content: Record<string, unknown>; rendered: Rendered | null; version_no?: number; versions: { version_no: number }[] }
interface Insights {
  decisions: Record<string, number>; judged: number; approval_rate: number | null; approved_with_edit: number;
  median_review_seconds: number | null; reasons: { code: string; label: string; count: number }[]; note: string;
}
interface Lesson { id: string; text: string; status: string; actor: string }

const STATES = ["", "PENDING_HUMAN", "QUARANTINE", "CORRECTED", "AUTO_APPROVED", "IMPORTED", "DRAFT"];
const DECISION_LABEL: Record<string, string> = {
  APPROVE: "aprovou", REJECT: "rejeitou", REQUEST_CHANGES: "pediu alteração", RELEASE_QUARANTINE: "retirou da quarentena",
  ACCEPT: "aceitou a proposta", DECLINE: "recusou a proposta", UNDO: "desfez",
};

export default function Review() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const [state, setState] = useState("");
  const [deck, setDeck] = useState("");
  const qs = new URLSearchParams({ ...(project && { project_id: project }), ...(state && { state }), ...(deck && { deck }) });
  const queue = usePoll<QRow[]>(project ? `/api/review/queue?${qs}` : null);
  const reasons = usePoll<Reason[]>("/api/review/reasons");
  const [idx, setIdx] = useState(0);
  const current = queue.data?.[idx];
  const card = usePoll<CardData>(current ? `/api/cards/${current.id}` : null);
  const detail = usePoll<Detail>(current ? `/api/review/cards/${current.id}` : null);
  const insights = usePoll<Insights>(project ? `/api/review/insights?project_id=${project}` : null);
  const lessons = usePoll<Lesson[]>("/api/review/lessons");
  const act = useAction();
  const [actor, setActor] = useState(() => { try { return localStorage.getItem("cf-reviewer") ?? ""; } catch { return ""; } });
  const [picked, setPicked] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [lesson, setLesson] = useState("");
  const started = useRef(Date.now());
  const startedVersion = useRef<number | null>(null);

  useEffect(() => { if (!project && projects.data?.length) setProject(projects.data[0].id); }, [projects.data, project]);
  useEffect(() => { try { localStorage.setItem("cf-reviewer", actor); } catch { /* sem armazenamento */ } }, [actor]);
  useEffect(() => {
    started.current = Date.now();
    startedVersion.current = current?.version_no ?? null;
    setPicked([]);
    setNote("");
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (queue.data && idx >= queue.data.length) setIdx(Math.max(0, queue.data.length - 1)); }, [queue.data, idx]);

  const refresh = useCallback(() => { queue.reload(); detail.reload(); insights.reload(); }, [queue, detail, insights]);
  const decide = useCallback((decision: string) => current && act.run(async () => {
    await api.post(`/api/review/cards/${current.id}/decision`, {
      decision, actor, reasons: picked, note, duration_ms: Date.now() - started.current, started_version_no: startedVersion.current });
    refresh();
  }), [current, act, actor, picked, note, refresh]);
  const undo = useCallback(() => current && act.run(async () => {
    await api.post(`/api/review/cards/${current.id}/undo`, { actor });
    refresh();
  }), [current, act, actor, refresh]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      const n = queue.data?.length ?? 0;
      if (e.key === "j") setIdx((i) => Math.min(n - 1, i + 1));
      else if (e.key === "k") setIdx((i) => Math.max(0, i - 1));
      else if (e.key === "a" && actor.trim()) decide("APPROVE");
      else if (e.key === "u" && actor.trim()) undo();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue.data, decide, undo, actor]);

  const d = detail.data;
  const need = !actor.trim();
  return (
    <>
      <h1>Revisão</h1>
      <ErrorLine error={act.error || queue.error} />
      <Card title="Fila de revisão">
        <p className="muted small">
          Atalhos: <kbd>j</kbd>/<kbd>k</kbd> navegam, <kbd>a</kbd> aprova, <kbd>u</kbd> desfaz a última decisão do card.
          Aprovar exige o card sem bloqueio. Rejeitar e pedir alteração exigem motivo. Nada é apagado: rejeitar só tira o card das exportações.
        </p>
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => { setProject(e.target.value); setIdx(0); }}>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>Estado<select value={state} onChange={(e) => { setState(e.target.value); setIdx(0); }}>
            {STATES.map((s) => <option key={s} value={s}>{s ? s : "todos pendentes"}</option>)}
          </select></label>
          <label>Deck<input value={deck} placeholder="IGOR::..." onChange={(e) => { setDeck(e.target.value); setIdx(0); }} /></label>
          <label>Seu nome<input value={actor} onChange={(e) => setActor(e.target.value)} /></label>
        </div>
        {queue.data?.length ? (
          <div className="review-grid">
            <ol className="queue" aria-label="Cards na fila">
              {queue.data.map((r, i) => (
                <li key={r.id}>
                  <button className={i === idx ? "active" : ""} aria-current={i === idx} onClick={() => setIdx(i)}>
                    <Badge state={r.state} /> <span className="small">{r.front || r.card_key}</span>
                    {(r.open_defects.CRITICAL || r.open_defects.HIGH) ? <span className="badge tone-bad">bloqueio</span> : null}
                    {r.pending_proposals ? <span className="badge tone-warn">{r.pending_proposals} proposta(s)</span> : null}
                  </button>
                </li>))}
            </ol>
            {current && (
              <div className="stack">
                <p className="muted small mono">{current.card_key} · v{current.version_no} · {current.deck_path} · {current.layout ?? "legado"}</p>
                {card.data?.rendered ? <CardPreview rendered={card.data.rendered} reveal /> : card.data ? (
                  <div className="legacy">
                    <p className="muted small">Card legado (HTML original como texto).</p>
                    <pre>{String(card.data.content.front_html ?? "")}</pre>
                    <pre>{String(card.data.content.back_html ?? "")}</pre>
                  </div>) : null}
                {d && (
                  <>
                    {d.blockers.length ? <ul className="plain error small">{d.blockers.map((b) => <li key={b}>Bloqueio: {b}</li>)}</ul>
                      : <p className="small tone-ok">Sem bloqueios.</p>}
                    {d.defects.filter((x) => x.status === "OPEN" || x.status === "ESCALATED").length > 0 && (
                      <ul className="plain small">{d.defects.filter((x) => x.status === "OPEN" || x.status === "ESCALATED").map((x) => (
                        <li key={x.id}><b>{x.severity}</b> {x.category}: {x.description} <span className="muted">({x.origin})</span></li>))}</ul>)}
                    {d.claims.length > 0 && (
                      <details><summary className="small">Afirmações ({d.claims.length})</summary>
                        <ul className="plain small">{d.claims.map((c) => (
                          <li key={c.claim_id}>{c.verdict ?? "sem veredito"} · {c.criticality} · {c.text}
                            {c.evidence_ids.length ? <span className="muted"> · {c.evidence_ids.length} trecho(s)</span> : null}</li>))}</ul>
                      </details>)}
                    {d.proposals.map((p) => (
                      <div key={p.id} className="proposal">
                        <span className="small"><b>Proposta {p.kind}</b> ({p.actor_type}): {p.justification}</span>
                        {p.decision ? <span className="muted small"> · {DECISION_LABEL[p.decision]}</span> : (
                          <span className="row">
                            <button disabled={need || act.busy} onClick={() => act.run(async () => {
                              await api.post(`/api/review/proposals/${p.id}`, { accept: true, actor, note }); refresh(); })}>Aceitar</button>
                            <button disabled={need || act.busy} onClick={() => act.run(async () => {
                              await api.post(`/api/review/proposals/${p.id}`, { accept: false, actor, note }); refresh(); })}>Recusar</button>
                          </span>)}
                      </div>))}
                  </>)}
                <fieldset className="plain reasons">
                  <legend className="small muted">Motivos (para rejeitar ou pedir alteração)</legend>
                  {reasons.data?.map((r) => (
                    <label key={r.code} className="check small">
                      <input type="checkbox" checked={picked.includes(r.code)}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, r.code] : picked.filter((x) => x !== r.code))} />{r.label}
                    </label>))}
                </fieldset>
                <label>Nota<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <div className="row">
                  <button disabled={need || act.busy || !!d?.blockers.length} onClick={() => decide("APPROVE")}>Aprovar</button>
                  <button disabled={need || act.busy || !picked.length} onClick={() => decide("REQUEST_CHANGES")}>Pedir alteração</button>
                  <button disabled={need || act.busy || !picked.length} onClick={() => decide("REJECT")}>Rejeitar</button>
                  {current.quarantine && <button disabled={need || act.busy || !note.trim()} onClick={() => decide("RELEASE_QUARANTINE")}>Retirar da quarentena</button>}
                  <button disabled={need || act.busy} onClick={undo}>Desfazer</button>
                </div>
                {d?.decisions.length ? (
                  <ul className="plain muted small">{d.decisions.map((x) => (
                    <li key={x.id}>{x.actor} {DECISION_LABEL[x.decision] ?? x.decision}{x.reasons.length ? ` (${x.reasons.map((c) => reasons.data?.find((r) => r.code === c)?.label ?? c).join("; ")})` : ""}{x.note ? `: ${x.note}` : ""}</li>))}</ul>) : null}
              </div>)}
          </div>
        ) : <p className="muted">Nenhum card pendente com esses filtros.</p>}
      </Card>

      <Card title="Aprendizado editorial">
        {insights.data && (
          <>
            <p className="small">
              {insights.data.judged} decisão(ões) · aprovação {insights.data.approval_rate === null ? "—" : `${Math.round(insights.data.approval_rate * 100)}%`}
              {" "}· aprovadas com edição {insights.data.approved_with_edit} · tempo mediano {insights.data.median_review_seconds ?? "—"} s
            </p>
            {insights.data.reasons.length ? (
              <ul className="plain small">{insights.data.reasons.map((r) => <li key={r.code}>{r.label}: {r.count}</li>)}</ul>
            ) : <p className="muted small">Nenhum motivo registrado ainda.</p>}
            <p className="muted small">{insights.data.note}</p>
          </>)}
        <div className="row">
          <label className="grow">Nova lição<input value={lesson} onChange={(e) => setLesson(e.target.value)} placeholder="regra geral, sem copiar um card" /></label>
          <button disabled={need || !lesson.trim() || act.busy} onClick={() => act.run(async () => {
            await api.post("/api/review/lessons", { text: lesson, actor }); setLesson(""); lessons.reload(); })}>Registrar</button>
          <button disabled={need || act.busy || !lessons.data?.some((l) => l.status === "ACCEPTED")} onClick={() => act.run(async () => {
            await api.post("/api/review/lessons/promote", { actor }); lessons.reload(); })}>Incorporar aceitas ao prompt</button>
        </div>
        {lessons.data?.length ? (
          <ul className="plain small">{lessons.data.map((l) => (
            <li key={l.id}>{l.text} <span className="muted">· {l.status.toLowerCase()} · {l.actor}</span>
              {l.status === "PROPOSED" && (
                <>
                  {" "}<button className="link" disabled={need} onClick={() => act.run(async () => {
                    await api.post(`/api/review/lessons/${l.id}/status`, { status: "ACCEPTED", actor }); lessons.reload(); })}>aceitar</button>
                  {" "}<button className="link" disabled={need} onClick={() => act.run(async () => {
                    await api.post(`/api/review/lessons/${l.id}/status`, { status: "DISCARDED", actor }); lessons.reload(); })}>descartar</button>
                </>)}
            </li>))}</ul>) : null}
        <p className="muted small">Incorporar cria uma versão nova da política editorial, que pode ser revertida na tela Prompts.</p>
      </Card>
    </>
  );
}
