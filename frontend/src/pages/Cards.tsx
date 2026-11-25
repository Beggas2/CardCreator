import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Badge, Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";
import { CardPreview, Findings, type Finding, type Rendered } from "../preview";

interface Project { id: string; name: string }
interface Row {
  id: string; card_key: string; state: string; origin: string; version_no: number; deck_path: string;
  layout: string | null; cognitive_type: string | null; schema_version: string; front_text: string;
  open_findings: number; open_errors: number; created_at: string;
}
interface Version { version_no: number; author_type: string; note: string; created_at: string; restored_from_version: number | null }
interface Op { kind: string; from: number | null; to: number | null; actor: string; justification: string; created_at: string }
interface Media { id: string; status: string; finding: string; purpose: string; file_name: string | null; license: string }
interface Detail {
  id: string; card_key: string; anki_guid: string | null; state: string; origin: string; schema_version: string;
  deck_path: string; tags: string[]; content: Record<string, unknown>; versions: Version[]; findings: Finding[];
  operations: Op[]; media: Media[]; rendered: Rendered | null;
}

const STATES = ["", "DRAFT", "GENERATED", "PENDING_HUMAN", "HUMAN_APPROVED", "IMPORTED", "QUARANTINE", "REJECTED"];

export default function Cards() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const [state, setState] = useState("");
  const q = new URLSearchParams({ ...(project && { project_id: project }), ...(state && { state }) });
  const list = usePoll<Row[]>(`/api/cards?${q}`);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);

  return (
    <>
      <h1>Cards</h1>
      <ErrorLine error={list.error || projects.error} />
      <Card title="Filtro">
        <div className="row">
          <label>Projeto<select value={project} onChange={(e) => { setProject(e.target.value); setSel(null); }}>
            <option value="">todos</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></label>
          <label>Estado<select value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((s) => <option key={s} value={s}>{s || "todos"}</option>)}
          </select></label>
        </div>
      </Card>
      <div className="split wide">
        <Card title={`Lista (${list.data?.length ?? 0})`}>
          {list.data?.length ? (
            <table className="clickable">
              <thead><tr><th>Frente</th><th>Tipo</th><th>Estado</th><th>v</th><th>Achados</th></tr></thead>
              <tbody>{list.data.map((c) => (
                <tr key={c.id} className={sel === c.id ? "selected" : ""} onClick={() => setSel(c.id)} tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && setSel(c.id)}>
                  <td className="detail">{c.front_text || "(sem frente)"}<div className="muted small">{c.deck_path}</div></td>
                  <td>{c.schema_version === "2.1" ? `${c.cognitive_type} · ${c.layout}` : "legado"}</td>
                  <td><Badge state={c.state} /></td>
                  <td>{c.version_no}</td>
                  <td>{c.open_errors ? <span className="badge tone-bad">{c.open_errors} erro(s)</span> : null}
                    {c.open_findings - c.open_errors > 0 && <span className="badge tone-warn">{c.open_findings - c.open_errors} alerta(s)</span>}</td>
                </tr>))}</tbody>
            </table>
          ) : <p className="muted">Nenhum card. Gere cards numa produção (Monitor) ou importe um export do Anki.</p>}
        </Card>
        {sel ? <CardDetail id={sel} onChange={list.reload} /> : <Card title="Detalhe"><p className="muted">Selecione um card.</p></Card>}
      </div>
    </>
  );
}

function CardDetail({ id, onChange }: { id: string; onChange: () => void }) {
  const d = usePoll<Detail>(`/api/cards/${id}`);
  const act = useAction();
  const [author, setAuthor] = useState("");
  const [reason, setReason] = useState("");
  const [json, setJson] = useState("");
  const [justify, setJustify] = useState<{ f: Finding; text: string } | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const c = d.data;

  useEffect(() => {
    if (c) setJson(JSON.stringify(c.content, null, 2));
  }, [c?.versions.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const after = () => { d.reload(); onChange(); };
  if (!c) return <Card title="Detalhe"><ErrorLine error={d.error} /></Card>;
  const legacy = c.schema_version !== "2.1";
  const need = !author.trim();

  return (
    <div className="stack">
      <Card title={`Card ${c.card_key}`} actions={<Badge state={c.state} />}>
        <ErrorLine error={act.error} />
        <p className="muted small">GUID do Anki: {c.anki_guid ?? "nota nova (o Anki gera na importação)"} · deck {c.deck_path} · tags {c.tags.join(" ") || "—"}</p>
        {c.rendered ? <CardPreview rendered={c.rendered} reveal /> : (
          <div className="legacy">
            <p className="muted">Card legado importado do Anki (HTML original, mostrado como texto).</p>
            <pre>{String((c.content as Record<string, string>).front_html ?? "")}</pre>
            <pre>{String((c.content as Record<string, string>).back_html ?? "")}</pre>
          </div>
        )}
        <div className="row">
          <label>Seu nome<input value={author} onChange={(e) => setAuthor(e.target.value)} /></label>
          <label className="grow">Motivo<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        </div>
        <div className="row">
          {["HUMAN_APPROVED", "QUARANTINE", "REJECTED"].map((s) => (
            <button key={s} disabled={need || !reason.trim() || act.busy || (legacy && s === "HUMAN_APPROVED")}
              onClick={() => act.run(() => api.post(`/api/cards/${id}/state`, { state: s, author, reason })).then(after)}>
              {s === "HUMAN_APPROVED" ? "Aprovar para exportação" : s === "QUARANTINE" ? "Quarentena" : "Rejeitar"}
            </button>))}
        </div>
        <p className="muted small">A mesa de revisão completa (motivos tipificados, fila e tempo de revisão) chega na Fase 5.</p>
      </Card>
      <Card title="Validação">
        <Findings findings={c.findings} onJustify={(f) => setJustify({ f, text: "" })} />
        {justify && (
          <div className="row">
            <label className="grow">Justificativa para {justify.f.code}
              <input value={justify.text} onChange={(e) => setJustify({ ...justify, text: e.target.value })} /></label>
            <button disabled={need || !justify.text.trim()} onClick={() => act.run(() => api.post(
              `/api/findings/${justify.f.id}/justify`, { justification: justify.text, author })).then(() => { setJustify(null); after(); })}>
              Registrar</button>
            <button onClick={() => setJustify(null)}>Cancelar</button>
          </div>
        )}
        {need && justify && <p className="muted small">Informe seu nome acima.</p>}
      </Card>
      {!legacy && (
        <Card title="Editar (card.v2)">
          <p className="muted small">Edite o JSON estruturado. O HTML é sempre derivado pelo renderizador; HTML no texto é recusado.</p>
          <textarea className="code" rows={14} value={json} onChange={(e) => setJson(e.target.value)} aria-label="JSON do card" />
          <div className="row">
            <button disabled={need || act.busy} onClick={() => act.run(async () => {
              await api.post(`/api/cards/${id}/versions`, { card: JSON.parse(json), author, note: reason });
            }).then(after)}>Salvar nova versão</button>
          </div>
        </Card>
      )}
      <Card title="Versões">
        <table>
          <thead><tr><th>v</th><th>Autor</th><th>Nota</th><th>Data</th><th></th></tr></thead>
          <tbody>{c.versions.slice().reverse().map((v) => (
            <tr key={v.version_no}>
              <td>{v.version_no}{v.restored_from_version ? ` (← v${v.restored_from_version})` : ""}</td>
              <td>{v.author_type}</td><td className="detail">{v.note}</td><td>{fmtDate(v.created_at)}</td>
              <td><div className="actions">
                {v.version_no > 1 && <button className="tlink" onClick={() => act.run(async () => {
                  const r = await api.get<{ unified: string }>(`/api/cards/${id}/diff?a=${v.version_no - 1}&b=${v.version_no}`);
                  setDiff(r.unified || "(sem diferença de conteúdo)");
                })}>diff</button>}
                {v.version_no !== c.versions.length && <button className="tlink" disabled={need || !reason.trim()}
                  onClick={() => act.run(() => api.post(`/api/cards/${id}/rollback`, { version_no: v.version_no, author, reason })).then(after)}>
                  restaurar</button>}
              </div></td>
            </tr>))}</tbody>
        </table>
        {diff && <pre className="diff">{diff}</pre>}
      </Card>
      <Card title="Histórico de operações">
        <ul className="plain">{c.operations.map((o, i) => (
          <li key={i}><code>{o.kind}</code> {o.from ? `v${o.from} → ` : ""}{o.to ? `v${o.to}` : ""} · {o.actor} · {fmtDate(o.created_at)}
            {o.justification && <span className="muted"> · {o.justification}</span>}</li>))}</ul>
      </Card>
      {c.media.length > 0 && (
        <Card title="Mídia">
          <ul className="plain">{c.media.map((m) => (
            <li key={m.id}><Badge state={m.status} /> {m.finding} {m.file_name && <code>{m.file_name}</code>}
              {m.status === "PENDING" && <span className="muted"> · envie a imagem com licença e direitos verificados</span>}</li>))}</ul>
        </Card>
      )}
    </div>
  );
}
