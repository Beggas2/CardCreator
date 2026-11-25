import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface Summary { sets: Record<string, Record<string, number>>; eval_accesses: Record<string, number>; eval_log: { set: string; purpose: string; actor: string; at: string }[] }
interface Rate { k: number; n: number; rate: number | null; ci95: [number, number] | null }
interface Metrics { items: number; detection?: Rate; false_alarm?: Rate; missed?: string[]; detected_low_severity?: number; reference_flagged?: number; reference_noted?: number; note?: string }
interface RunRow { id: string; set: string; split: string; subject: string; provider: string; metrics: Metrics; cost_usd: string; actor: string; created_at: string }
interface Result { item_key: string; outcome: string; found: { category: string; severity: string; description: string }[] }
interface RunDetail extends RunRow { results: Result[] }
interface Project { id: string; name: string }
interface QRow { id: string; card_key: string; front: string }
interface CardData { versions: { id: string; version_no: number }[] }
interface CompRow { id: string; question: string; n: number; decided: boolean; choice: string | null; created_at: string }
interface Comp { id: string; question: string; decided: boolean; choice: string | null; justification: string; items: { label: string; front: string; back: string; origin?: string }[] }

const SUBJECTS = [
  { id: "DETERMINISTIC", label: "Varreduras determinísticas (sem custo)" },
  { id: "auditor_scientific", label: "Auditor científico (IA)" },
  { id: "auditor_pedagogical", label: "Auditor pedagógico (IA)" },
];
const OUTCOME: Record<string, string> = {
  DETECTED: "detectado", DETECTED_LOW_SEVERITY: "detectado com gravidade baixa", MISSED: "não detectado",
  KEEP_OK: "limpo, mantido", FALSE_ALARM: "falso alarme", FLAGGED: "apontado", NOTED: "observação", NO_FINDINGS: "sem achados",
};

function fmtRate(r?: Rate) {
  if (!r || r.rate === null) return "—";
  const ci = r.ci95 ? ` (IC95% ${Math.round(r.ci95[0] * 100)}–${Math.round(r.ci95[1] * 100)}%)` : "";
  return `${r.k}/${r.n} = ${Math.round(r.rate * 100)}%${ci}`;
}

function Frame({ html }: { html: string }) {
  return <iframe className="blind" sandbox="" title="card" srcDoc={`<body style="margin:8px;background:#101114;color:#E5E7EB;font-family:system-ui">${html}</body>`} />;
}

export default function Lab() {
  const summary = usePoll<Summary>("/api/bench/summary");
  const runs = usePoll<RunRow[]>("/api/bench/runs");
  const act = useAction();
  const [setName, setSetName] = useState("KNOWN_DEFECTS");
  const [split, setSplit] = useState("dev");
  const [subject, setSubject] = useState("DETERMINISTIC");
  const [actor, setActor] = useState("");
  const [purpose, setPurpose] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const detail = usePoll<RunDetail>(sel ? `/api/bench/runs/${sel}` : null);

  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const queue = usePoll<QRow[]>(project ? `/api/review/queue?project_id=${project}&include_done=true` : null);
  const [pick, setPick] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const comps = usePoll<CompRow[]>("/api/bench/comparisons");
  const [comp, setComp] = useState<string | null>(null);
  const compData = usePoll<Comp>(comp ? `/api/bench/comparisons/${comp}` : null);
  const [choice, setChoice] = useState("");
  const [why, setWhy] = useState("");

  useEffect(() => { if (!project && projects.data?.length) setProject(projects.data[0].id); }, [projects.data, project]);

  const loaded = summary.data && Object.keys(summary.data.sets).length > 0;
  const run = () => act.run(async () => {
    const r = await api.post<{ run_id: string }>("/api/bench/runs", { set_name: setName, split, subject, actor, purpose });
    runs.reload(); summary.reload(); setSel(r.run_id);
  });
  const createComp = () => act.run(async () => {
    const vids = await Promise.all(pick.map(async (id) => {
      const c = await api.get<CardData>(`/api/cards/${id}`);
      return c.versions[c.versions.length - 1].id;
    }));
    const r = await api.post<{ id: string }>("/api/bench/comparisons", { question, card_version_ids: vids });
    setComp(r.id); setPick([]); comps.reload();
  });

  return (
    <>
      <h1>Laboratório</h1>
      <ErrorLine error={act.error || summary.error} />
      <Card title="Conjuntos">
        <p className="muted small">
          Defeitos conhecidos: cards fictícios com um defeito plantado e gabarito, mais os 12 exemplos limpos.
          Referência: os 40 cards enviados pela proprietária, sem gabarito (não se presume que estejam corretos).
          O split eval é selado: cada uso pede nome e finalidade e fica registrado.
        </p>
        {loaded ? (
          <table>
            <thead><tr><th>Conjunto</th><th>dev</th><th>eval</th><th>Consultas ao eval</th></tr></thead>
            <tbody>{Object.entries(summary.data!.sets).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td>{v.dev ?? 0}</td><td>{v.eval ?? 0}</td><td>{summary.data!.eval_accesses[k] ?? 0}</td></tr>))}</tbody>
          </table>
        ) : <button disabled={act.busy} onClick={() => act.run(async () => { await api.post("/api/bench/sets/load"); summary.reload(); })}>Carregar conjuntos</button>}
      </Card>

      <Card title="Executar">
        <div className="row">
          <label>Conjunto<select value={setName} onChange={(e) => setSetName(e.target.value)}>
            <option value="KNOWN_DEFECTS">Defeitos conhecidos</option><option value="REFERENCE">Referência (40 cards)</option>
          </select></label>
          <label>Split<select value={split} onChange={(e) => setSplit(e.target.value)}><option>dev</option><option>eval</option></select></label>
          <label>Sujeito<select value={subject} onChange={(e) => setSubject(e.target.value)}>
            {SUBJECTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select></label>
          <label>Seu nome<input value={actor} onChange={(e) => setActor(e.target.value)} /></label>
          {split === "eval" && <label className="grow">Finalidade (obrigatória no eval)<input value={purpose} onChange={(e) => setPurpose(e.target.value)} /></label>}
        </div>
        <p className="muted small">Aqui os auditores de IA usam o provedor simulado (sem custo). Medir modelos reais exige autorização de gasto.</p>
        <button disabled={!loaded || !actor.trim() || (split === "eval" && !purpose.trim()) || act.busy} onClick={run}>Executar</button>
      </Card>

      <Card title="Execuções">
        {runs.data?.length ? (
          <table>
            <thead><tr><th>Data</th><th>Conjunto</th><th>Sujeito</th><th>Detecção</th><th>Falso alarme</th><th>Custo</th></tr></thead>
            <tbody>{runs.data.map((r) => (
              <tr key={r.id} className={sel === r.id ? "selected" : ""} onClick={() => setSel(r.id)}>
                <td><button className="link" onClick={() => setSel(r.id)}>{fmtDate(r.created_at)}</button></td>
                <td>{r.set} · {r.split}</td><td>{r.subject} {r.provider && `· ${r.provider}`}</td>
                <td>{r.metrics.detection ? fmtRate(r.metrics.detection) : r.metrics.reference_flagged !== undefined ? `${r.metrics.reference_flagged} apontado(s)` : "—"}</td>
                <td>{fmtRate(r.metrics.false_alarm)}</td><td>US$ {r.cost_usd}</td>
              </tr>))}</tbody>
          </table>
        ) : <p className="muted">Nenhuma execução.</p>}
        {detail.data && (
          <>
            <h3>Itens</h3>
            {detail.data.metrics.note && <p className="muted small">{detail.data.metrics.note}</p>}
            <ul className="plain small">{detail.data.results.map((x) => (
              <li key={x.item_key}><span className="mono">{x.item_key}</span> · {OUTCOME[x.outcome] ?? x.outcome}
                {x.found.length ? <span className="muted"> · {x.found.map((f) => `${f.severity} ${f.category}`).join("; ")}</span> : null}</li>))}</ul>
          </>)}
      </Card>

      <Card title="Comparação cega">
        <p className="muted small">Os cards aparecem com rótulos aleatórios. A origem só é revelada depois que a escolha e a justificativa são gravadas.</p>
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => setProject(e.target.value)}>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label className="grow">Pergunta ao avaliador<input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Qual card ensina melhor o objetivo?" /></label>
        </div>
        {queue.data?.length ? (
          <fieldset className="plain">
            <legend className="small muted">Escolha 2 ou mais cards</legend>
            {queue.data.slice(0, 30).map((q) => (
              <label key={q.id} className="check small"><input type="checkbox" checked={pick.includes(q.id)}
                onChange={(e) => setPick(e.target.checked ? [...pick, q.id] : pick.filter((x) => x !== q.id))} />{q.front || q.card_key}</label>))}
          </fieldset>) : null}
        <button disabled={pick.length < 2 || !question.trim() || act.busy} onClick={createComp}>Criar comparação</button>
        {comps.data?.length ? (
          <ul className="plain small">{comps.data.map((c) => (
            <li key={c.id}><button className="link" onClick={() => { setComp(c.id); setChoice(""); setWhy(""); }}>{c.question}</button>
              {" "}· {c.n} cards · {c.decided ? `escolhido ${c.choice}` : "aguardando"}</li>))}</ul>) : null}
        {compData.data && (
          <div className="stack">
            <h3>{compData.data.question}</h3>
            <div className="blind-grid">{compData.data.items.map((it) => (
              <div key={it.label} className="blind-item">
                <b>{it.label}</b>{it.origin !== undefined && <span className="muted small"> · origem: {it.origin || "não informada"}</span>}
                <Frame html={`${it.front}<hr>${it.back}`} />
              </div>))}</div>
            {compData.data.decided ? <p className="small">Escolha: {compData.data.choice} · {compData.data.justification}</p> : (
              <div className="row">
                <label>Escolha<select value={choice} onChange={(e) => setChoice(e.target.value)}>
                  <option value="">—</option>{compData.data.items.map((it) => <option key={it.label}>{it.label}</option>)}<option value="TIE">empate</option>
                </select></label>
                <label className="grow">Justificativa<input value={why} onChange={(e) => setWhy(e.target.value)} /></label>
                <button disabled={!choice || !why.trim() || !actor.trim() || act.busy} onClick={() => act.run(async () => {
                  await api.post(`/api/bench/comparisons/${compData.data!.id}/decision`, { choice, actor, justification: why });
                  compData.reload(); comps.reload(); })}>Gravar escolha</button>
              </div>)}
          </div>)}
      </Card>
    </>
  );
}
