import { useEffect, useState } from "react";
import { api, fmtDate, type PromptRow, type PromptVersion } from "../api";
import { Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface PromptsResp {
  prompts: PromptRow[];
  coverage: Record<string, string[]>;
  roles: Record<string, { policies: string[]; contract: string; required: string[]; normative: string | null }>;
}

export default function Prompts() {
  const list = usePoll<PromptsResp>("/api/prompts");
  const [key, setKey] = useState<string | null>(null);
  const versions = usePoll<PromptVersion[]>(key ? `/api/prompts/${encodeURIComponent(key)}/versions` : null);
  const [draft, setDraft] = useState("");
  const [author, setAuthor] = useState("");
  const [note, setNote] = useState("");
  const [diff, setDiff] = useState<string | null>(null);
  const [cmpA, setCmpA] = useState<string>("");
  const act = useAction();

  useEffect(() => {
    if (!key && list.data?.prompts.length) setKey(list.data.prompts[0].key);
  }, [list.data, key]);
  const active = versions.data?.find((v) => v.active);
  useEffect(() => {
    if (active) setDraft(active.body);
    setDiff(null);
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const reload = () => {
    list.reload();
    versions.reload();
  };
  const save = () =>
    act.run(() => api.put(`/api/prompts/${encodeURIComponent(key!)}`, { body: draft, author, note })).then((ok) => {
      if (ok) setNote("");
      reload();
    });

  const missing = list.data ? Object.entries(list.data.coverage).filter(([, m]) => m.length) : [];

  return (
    <>
      <h1>Prompts</h1>
      <ErrorLine error={act.error || list.error} />
      {list.data && (
        <p className={missing.length ? "error" : "notice ok"}>
          {missing.length
            ? `Cobertura incompleta: ${missing.map(([r, m]) => `${r} (faltam ${m.join(", ")})`).join("; ")}`
            : "Todos os papéis contêm os requisitos obrigatórios do manifesto."}
        </p>
      )}
      <div className="split">
        <Card title="Políticas e papéis">
          <ul className="list">
            {list.data?.prompts.map((p) => (
              <li key={p.key}>
                <button className={`link ${key === p.key ? "sel" : ""}`} onClick={() => setKey(p.key)}>
                  <span>{p.key}</span> <span className="muted small">v{p.version}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        {key && (
          <Card title={key}>
            {active && (
              <p className="muted small">
                Versão ativa {active.version} · hash <code>{active.hash.slice(0, 12)}</code> · requisitos: {active.req_ids.join(", ") || "nenhum"}
              </p>
            )}
            <label className="block">
              Conteúdo (salvar cria uma nova versão; as anteriores não mudam)
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={16} spellCheck={false} />
            </label>
            <div className="row">
              <label>Autor<input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="seu nome" /></label>
              <label>Nota<input value={note} onChange={(e) => setNote(e.target.value)} placeholder="motivo da mudança" /></label>
              <button disabled={act.busy || !author.trim() || draft === active?.body} onClick={save}>Salvar nova versão</button>
              <button
                disabled={act.busy || !author.trim()}
                onClick={() => {
                  const nk = window.prompt("Chave da cópia (ex.: role:creator_exp):");
                  if (nk) act.run(() => api.post(`/api/prompts/${encodeURIComponent(key)}/duplicate`, { author, new_key: nk })).then(reload);
                }}
              >
                Duplicar
              </button>
            </div>
            <h3>Histórico</h3>
            <table>
              <thead><tr><th>Versão</th><th>Autor</th><th>Data</th><th>Nota</th><th></th></tr></thead>
              <tbody>
                {versions.data?.map((v) => (
                  <tr key={v.id}>
                    <td>v{v.version}{v.active && " (ativa)"}</td>
                    <td>{v.created_by}</td>
                    <td>{fmtDate(v.created_at)}</td>
                    <td>{v.note}</td>
                    <td><div className="actions">
                      <button
                        className="small"
                        onClick={() => {
                          if (!cmpA) return setCmpA(v.id);
                          act.run(async () => {
                            const r = await api.get<{ diff: string }>(`/api/prompts-diff?a=${cmpA}&b=${v.id}`);
                            setDiff(r.diff || "(sem diferenças)");
                            setCmpA("");
                          });
                        }}
                      >
                        {cmpA === v.id ? "selecionada" : cmpA ? "comparar com esta" : "comparar"}
                      </button>
                      {!v.active && (
                        <button
                          className="small"
                          disabled={!author.trim()}
                          title={author.trim() ? "" : "informe o autor"}
                          onClick={() => act.run(() => api.post(`/api/prompts/${encodeURIComponent(key)}/restore/${v.id}`, { author })).then(reload)}
                        >
                          Restaurar
                        </button>
                      )}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {diff !== null && <pre className="diff">{diff.split("\n").map((l, i) => <span key={i} className={l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}>{l + "\n"}</span>)}</pre>}
          </Card>
        )}
      </div>
    </>
  );
}
