import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Badge, Card, CountList, ErrorLine, Stat } from "../components";
import { useAction, usePoll } from "../hooks";

interface Project { id: string; name: string }
interface Prod { id: string; project_id: string; mode: string; theme: string; provider: string; created_at: string }
interface Batch { id: string; filename: string; created_at: string; report: { notes_read?: number } }
interface Defect {
  id: string; card_id: string | null; card_key: string | null; category: string; severity: string; description: string;
  status: string; origin: string; correction_attempts: number; resolution_note: string;
}
interface Sim { id: string; card_a: string; card_b: string; layer: string; score: string; kind: string | null; proposal: string | null; rationale: string; status: string }
interface Verdict { status: string; detail: { open_by_severity?: Record<string, number> } }
interface Report {
  cards: { total: number; by_state: Record<string, number> };
  defects: { total: number; open: number; by_severity_open: Record<string, number>; by_category: Record<string, number>; by_status: Record<string, number> };
  claims: { total: number; by_verdict: Record<string, number> };
  operations: Record<string, number>;
  magnitude: { changed_cards: number; fraction: number; warning: boolean; note: string };
  final_state: { original: number; created: number; proposed_deletions: number; reconciled: boolean; note: string };
  verdicts: Record<string, Record<string, Verdict>>;
  disclaimer: string;
}

const DIM: Record<string, string> = { scientific: "Científica", pedagogical: "Pedagógica", coverage: "Cobertura", technical: "Técnica" };
const VERDICT: Record<string, string> = {
  NO_OPEN_DEFECTS: "sem defeitos abertos", WITH_PENDING: "com pendências", BLOCKED: "bloqueada", NOT_VERIFIED: "não verificada",
};
const SEV_TONE: Record<string, string> = { CRITICAL: "bad", HIGH: "bad", MEDIUM: "warn", LOW: "muted", OBSERVATION: "muted" };

export default function Audit() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const prods = usePoll<Prod[]>(project ? `/api/productions?project_id=${project}` : null, 5000);
  const batches = usePoll<Batch[]>(project ? `/api/imports?project_id=${project}` : null);
  const [prod, setProd] = useState("");
  const report = usePoll<Report>(prod ? `/api/productions/${prod}/audit-report` : null, 5000);
  const defects = usePoll<Defect[]>(prod ? `/api/defects?production_id=${prod}` : null, 5000);
  const sims = usePoll<Sim[]>(project ? `/api/similarity?project_id=${project}` : null, 5000);
  const act = useAction();
  const [theme, setTheme] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [actor, setActor] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);
  useEffect(() => {
    if (!prod && prods.data?.length) setProd(prods.data[0].id);
  }, [prods.data, prod]);

  const projectName = projects.data?.find((p) => p.id === project)?.name ?? "";
  const startAudit = () => act.run(async () => {
    const r = await api.post<{ production_id: string; run_id: string }>("/api/productions", {
      project_name: projectName, theme, mode: "FULL_AUDIT", import_batch_ids: picked, provider: "mock" });
    await api.post(`/api/runs/${r.run_id}/start`);
    setProd(r.production_id);
    prods.reload();
  });
  const setStatus = (d: Defect, status: string) => act.run(async () => {
    await api.post(`/api/defects/${d.id}/status`, { status, note: notes[d.id] ?? "", actor });
    defects.reload();
    report.reload();
  });

  const r = report.data;
  return (
    <>
      <h1>Auditoria</h1>
      <ErrorLine error={act.error || report.error || defects.error} />
      <Card title="Auditar um deck existente">
        <p className="muted small">
          Os cards escolhidos passam pelas mesmas auditorias independentes da criação: científica, pedagógica, de
          segurança e de cobertura, mais varreduras determinísticas. Cada defeito recebe no máximo 2 correções
          automáticas e depois vai para você. Nada é excluído; duplicatas e contradições viram propostas.
          Aqui a execução usa o provedor simulado (sem custo). Auditoria real exige autorização de gasto.
        </p>
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => { setProject(e.target.value); setProd(""); setPicked([]); }}>
            <option value="">—</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>Tema<input value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="ex.: Escabiose" /></label>
        </div>
        {batches.data?.length ? (
          <fieldset className="plain">
            <legend className="small muted">Lotes importados</legend>
            {batches.data.map((b) => (
              <label key={b.id} className="check">
                <input type="checkbox" checked={picked.includes(b.id)}
                  onChange={(e) => setPicked(e.target.checked ? [...picked, b.id] : picked.filter((x) => x !== b.id))} />
                {b.filename || b.id} · {b.report?.notes_read ?? "?"} notas · {fmtDate(b.created_at)}
              </label>))}
          </fieldset>
        ) : <p className="muted small">Nenhum lote importado neste projeto (use Importação).</p>}
        <button disabled={!project || !theme.trim() || !picked.length || act.busy} onClick={startAudit}>Iniciar auditoria</button>
      </Card>

      <Card title="Relatório" actions={
        <select aria-label="Produção" value={prod} onChange={(e) => setProd(e.target.value)}>
          {prods.data?.map((p) => <option key={p.id} value={p.id}>{p.mode === "FULL_AUDIT" ? "Auditoria" : "Criação"} · {p.theme} · {fmtDate(p.created_at)}</option>)}
        </select>}>
        {r ? (
          <>
            <div className="stats">
              <Stat label="cards" value={r.cards.total} />
              <Stat label="defeitos abertos" value={r.defects.open} hint={`${r.defects.total} no total`} />
              <Stat label="afirmações auditadas" value={r.claims.total} />
              <Stat label="cards alterados" value={`${Math.round(r.magnitude.fraction * 100)}%`} hint={r.magnitude.warning ? "acima de 30%" : undefined} />
            </div>
            {r.magnitude.note && <p className="warn small">{r.magnitude.note}</p>}
            <h3>Veredito por dimensão</h3>
            <p className="muted small">Nunca há média entre dimensões; o original e o corrigido aparecem separados.</p>
            <table>
              <thead><tr><th>Dimensão</th><th>Original</th><th>Corrigido</th></tr></thead>
              <tbody>{Object.entries(DIM).map(([k, label]) => (
                <tr key={k}><td>{label}</td>
                  {["ORIGINAL", "CORRECTED"].map((t) => {
                    const v = r.verdicts[k]?.[t];
                    return <td key={t}>{v ? VERDICT[v.status] ?? v.status : "—"}</td>;
                  })}
                </tr>))}</tbody>
            </table>
            <div className="grid2">
              <div><h3>Cards por estado</h3><CountList counts={r.cards.by_state} /></div>
              <div><h3>Afirmações por veredito</h3><CountList counts={r.claims.by_verdict} /></div>
              <div><h3>Defeitos por categoria</h3><CountList counts={r.defects.by_category} /></div>
              <div><h3>Operações</h3><CountList counts={r.operations} /></div>
            </div>
            <p className="muted small">{r.final_state.note}. {r.final_state.proposed_deletions} exclusão(ões) proposta(s).</p>
            <p className="muted small">{r.disclaimer}</p>
          </>
        ) : <p className="muted">Escolha uma produção.</p>}
      </Card>

      <Card title="Defeitos">
        <div className="row"><label>Seu nome (para justificar ou marcar corrigido)<input value={actor} onChange={(e) => setActor(e.target.value)} /></label></div>
        {defects.data?.length ? (
          <table>
            <thead><tr><th>Card</th><th>Gravidade</th><th>Categoria</th><th>Descrição</th><th>Estado</th><th>Decisão</th></tr></thead>
            <tbody>{defects.data.map((d) => (
              <tr key={d.id}>
                <td className="mono small">{d.card_key ?? "produção"}</td>
                <td><span className={`badge tone-${SEV_TONE[d.severity] ?? "muted"}`}>{d.severity}</span></td>
                <td>{d.category}<div className="muted small">{d.origin === "DETERMINISTIC" ? "varredura" : "auditor"} · {d.correction_attempts} correção(ões)</div></td>
                <td>{d.description}{d.resolution_note && <div className="muted small">{d.resolution_note}</div>}</td>
                <td><Badge state={d.status} /></td>
                <td>{d.status === "OPEN" || d.status === "ESCALATED" ? (
                  <div className="stack">
                    <input aria-label="Nota" placeholder="nota obrigatória" value={notes[d.id] ?? ""}
                      onChange={(e) => setNotes({ ...notes, [d.id]: e.target.value })} />
                    <div className="row">
                      {d.severity !== "CRITICAL" && <button disabled={!actor.trim() || !(notes[d.id] ?? "").trim() || act.busy}
                        onClick={() => setStatus(d, "JUSTIFIED")}>Justificar</button>}
                      <button disabled={!actor.trim() || !(notes[d.id] ?? "").trim() || act.busy}
                        onClick={() => setStatus(d, "FIXED")}>Corrigido</button>
                    </div>
                  </div>) : null}</td>
              </tr>))}</tbody>
          </table>
        ) : <p className="muted">Nenhum defeito registrado.</p>}
      </Card>

      <Card title="Semelhanças e contradições">
        {sims.data?.length ? (
          <table>
            <thead><tr><th>Cards</th><th>Camada</th><th>Classificação</th><th>Proposta</th><th>Motivo</th></tr></thead>
            <tbody>{sims.data.map((p) => (
              <tr key={p.id}><td className="mono small">{p.card_a}<br />{p.card_b}</td><td>{p.layer}{p.score ? ` (${p.score})` : ""}</td>
                <td>{p.kind ?? "não classificado"}</td><td>{p.proposal ?? "—"}</td><td className="small">{p.rationale}</td></tr>))}</tbody>
          </table>
        ) : <p className="muted">Nenhum par candidato.</p>}
      </Card>
    </>
  );
}
