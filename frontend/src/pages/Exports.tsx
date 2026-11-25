import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Badge, Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface Project { id: string; name: string }
interface FileRow { name: string; sha256: string; kind: string; notes?: number; bytes?: number }
interface ExportRow {
  id: string; format: string; version_label: string; state: string; mode: string; files: FileRow[];
  round_trip_ok: boolean; import_tested: string; created_at: string;
  report: { exported?: number; new_notes?: number; updates?: number; skipped?: number; blocked?: number; errors?: string[]; warnings?: number };
}

const FORMATS = [
  { id: "anki_tsv_v2", label: "Principal (com GUID, deck e tags)" },
  { id: "anki_tsv_noguid", label: "Sem GUID (só notas novas)" },
  { id: "anki_simple", label: "Simplificado Frente;Verso (cards avulsos)" },
];

export default function Exports() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const list = usePoll<ExportRow[]>(project ? `/api/exports?project_id=${project}` : null);
  const act = useAction();
  const [fmt, setFmt] = useState("anki_tsv_v2");
  const [preview, setPreview] = useState(false);
  const [testImport, setTestImport] = useState(false);
  const [author, setAuthor] = useState("");

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);

  return (
    <>
      <h1>Exportação</h1>
      <ErrorLine error={act.error || list.error} />
      <Card title="Nova exportação">
        <p className="muted small">
          Só entram cards aprovados por revisão humana e sem erro de validação aberto. Notas novas vão com GUID vazio
          (o Anki gera o GUID); notas existentes mantêm o GUID original. Nada é excluído e o agendamento não é tocado.
          Antes de liberar, o arquivo é relido e comparado campo a campo.
        </p>
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">—</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>Formato<select value={fmt} onChange={(e) => setFmt(e.target.value)}>
            {FORMATS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select></label>
          <label>Seu nome<input value={author} onChange={(e) => setAuthor(e.target.value)} /></label>
        </div>
        <div className="row">
          <label className="check"><input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} />
            Prévia sem revisão (arquivos rotulados PREVIA_NAO_REVISADA)</label>
          <label className="check"><input type="checkbox" checked={testImport} onChange={(e) => setTestImport(e.target.checked)} />
            Testar importação numa coleção Anki descartável (requer o pacote “anki”)</label>
          <button disabled={!project || act.busy} onClick={() => act.run(() => api.post("/api/exports", {
            project_id: project, format: fmt, preview, author, test_import: testImport })).then(list.reload)}>Exportar</button>
        </div>
      </Card>
      <Card title="Exportações">
        {list.data?.length ? (
          <table>
            <thead><tr><th>Data</th><th>Versão</th><th>Formato</th><th>Estado</th><th>Notas</th><th>Verificações</th><th>Arquivos</th></tr></thead>
            <tbody>{list.data.map((e) => (
              <tr key={e.id}>
                <td>{fmtDate(e.created_at)}</td><td>{e.version_label}</td><td>{e.format}</td>
                <td><Badge state={e.state === "READY" ? "SUCCEEDED" : "FAILED"} /> {e.state === "READY" ? "pronta" : "bloqueada"}</td>
                <td>{e.report.exported ?? 0} ({e.report.new_notes ?? 0} novas, {e.report.updates ?? 0} atualizações)
                  {e.report.skipped ? <div className="muted small">{e.report.skipped} fora do recorte</div> : null}</td>
                <td>{e.round_trip_ok ? "releitura ok" : "sem releitura"} · importação: {
                  { NOT_TESTED: "não testada", PASSED: "testada ok", FAILED: "falhou" }[e.import_tested] ?? e.import_tested}
                  {e.report.errors?.length ? <ul className="plain error small">{e.report.errors.slice(0, 5).map((x, i) => <li key={i}>{x}</li>)}</ul> : null}</td>
                <td><ul className="plain">{e.files.map((f) => (
                  <li key={f.name}><a href={`/api/exports/${e.id}/files/${encodeURIComponent(f.name)}`} download>{f.name}</a></li>))}</ul></td>
              </tr>))}</tbody>
          </table>
        ) : <p className="muted">Nenhuma exportação neste projeto.</p>}
      </Card>
    </>
  );
}
