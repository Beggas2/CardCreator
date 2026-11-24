import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface Project { id: string; name: string }
interface Batch { id: string; kind: string; filename: string; format: string; created_by: string; created_at: string;
  report: Record<string, unknown> }

export default function Imports() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const batches = usePoll<Batch[]>(project ? `/api/imports?project_id=${project}` : null);
  const act = useAction();
  const [newName, setNewName] = useState("");
  const [author, setAuthor] = useState("");
  const [pct, setPct] = useState(20);
  const [last, setLast] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);

  const upload = (kind: "anki" | "questions", file: File) => act.run(async () => {
    const p = new URLSearchParams({ project_id: project, filename: file.name, author });
    if (kind === "questions") p.set("evaluation_pct", String(pct));
    setLast(await api.upload(`/api/imports/${kind}?${p}`, file));
  }).then(batches.reload);

  return (
    <>
      <h1>Importação</h1>
      <ErrorLine error={act.error || projects.error} />
      <Card title="Projeto">
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">—</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>Novo projeto<input value={newName} onChange={(e) => setNewName(e.target.value)} /></label>
          <button disabled={!newName.trim() || act.busy} onClick={() => act.run(async () => {
            const r = await api.post<{ id: string }>("/api/projects", { name: newName });
            setProject(r.id);
            setNewName("");
          }).then(projects.reload)}>Criar</button>
          <label>Seu nome (registrado na importação)<input value={author} onChange={(e) => setAuthor(e.target.value)} /></label>
        </div>
      </Card>
      <div className="grid2">
        <Card title="Export do Anki (.txt)">
          <p className="muted small">Exporte no Anki como “Notas em texto simples”, com GUID, tipo de nota, baralho e etiquetas.
            Nenhuma nota é descartada: linhas com problema ficam em quarentena com o motivo.</p>
          <input type="file" accept=".txt,.tsv,.csv" disabled={!project || act.busy} aria-label="Arquivo do Anki"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload("anki", f); e.target.value = ""; }} />
        </Card>
        <Card title="Questões de prova (CSV ou JSON)">
          <p className="muted small">Colunas aceitas: banca, ano, instituição, prova, número, enunciado, alternativas, gabarito,
            gabarito_definitivo, anulada, fonte. Parte das questões fica reservada para avaliação e não entra no planejamento.</p>
          <div className="row">
            <label>% reservado para avaliação<input type="number" min={0} max={90} value={pct} onChange={(e) => setPct(Number(e.target.value))} /></label>
            <input type="file" accept=".csv,.json" disabled={!project || act.busy} aria-label="Arquivo de questões"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload("questions", f); e.target.value = ""; }} />
          </div>
        </Card>
      </div>
      {last && <Card title="Resultado da última importação"><Report r={last} /></Card>}
      <Card title="Histórico">
        {batches.data?.length ? (
          <table>
            <thead><tr><th>Data</th><th>Tipo</th><th>Arquivo</th><th>Formato</th><th>Resumo</th></tr></thead>
            <tbody>{batches.data.map((b) => (
              <tr key={b.id}><td>{fmtDate(b.created_at)}</td><td>{b.kind === "ANKI_EXPORT" ? "Anki" : "Questões"}</td>
                <td>{b.filename}</td><td>{b.format}</td><td className="detail">{summary(b.report)}</td></tr>))}</tbody>
          </table>
        ) : <p className="muted">Nenhuma importação neste projeto.</p>}
      </Card>
    </>
  );
}

function summary(r: Record<string, unknown>): string {
  if ("notes_read" in r) return `${r.notes_read} notas · ${r.created} novas · ${r.updated} atualizadas · ${r.unchanged} iguais · ${r.quarantined} em quarentena`;
  if ("read" in r) return `${r.read} lidas · ${r.created} novas · ${r.duplicates} duplicadas · ${(r.problems as unknown[]).length} problemas`;
  return "";
}

function Report({ r }: { r: Record<string, unknown> }) {
  const rows = (r.problem_rows as { line: number; guid: string | null; problems: string[] }[]) ?? [];
  const qprob = (r.problems as { item: number; problem: string }[]) ?? [];
  return (
    <>
      <p>{summary(r)}</p>
      {Array.isArray(r.file_problems) && r.file_problems.length > 0 && <p className="note">{(r.file_problems as string[]).join("; ")}</p>}
      {typeof r.aviso === "string" && <p className="note">{r.aviso}</p>}
      {rows.length > 0 && (
        <table><thead><tr><th>Linha</th><th>GUID</th><th>Problemas</th></tr></thead>
          <tbody>{rows.slice(0, 100).map((p) => <tr key={p.line}><td>{p.line}</td><td><code>{p.guid ?? "—"}</code></td><td>{p.problems.join("; ")}</td></tr>)}</tbody>
        </table>)}
      {qprob.length > 0 && <ul>{qprob.map((p, i) => <li key={i}>item {p.item}: {p.problem}</li>)}</ul>}
    </>
  );
}
