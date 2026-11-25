import { useEffect, useState } from "react";
import { api, fmtDate, type RunRow, type TaskRow } from "../api";
import { Badge, Card, CountList, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface RunDetail extends RunRow {
  active: boolean;
  task_list: TaskRow[];
}

interface CallRow {
  id: string;
  task_id: string | null;
  stage: string;
  requested_model: string;
  served_model: string | null;
  state: string;
  cost_usd: string | null;
  estimated_max_usd: string;
  latency_ms: number | null;
  prompt_hash: string;
}

function runFromHash() {
  const q = window.location.hash.split("?")[1];
  return q ? new URLSearchParams(q).get("run") : null;
}

export default function Monitor() {
  const runs = usePoll<RunRow[]>("/api/runs", 3000);
  const [selected, setSelected] = useState<string | null>(runFromHash());
  const detail = usePoll<RunDetail>(selected ? `/api/runs/${selected}` : null, 1500);
  const calls = usePoll<CallRow[]>(selected ? `/api/calls?limit=200&run_id=${selected}` : null, 1500);
  const act = useAction();
  const [theme, setTheme] = useState("");
  const [cards, setCards] = useState(3);

  useEffect(() => {
    if (!selected && runs.data?.length) setSelected(runs.data[0].id);
  }, [runs.data, selected]);

  const refresh = () => {
    runs.reload();
    detail.reload();
    calls.reload();
  };
  const doRun = (path: string, body: unknown = {}) => act.run(() => api.post(path, body)).then(refresh);

  const create = () =>
    act.run(async () => {
      const r = await api.post<{ run_id: string }>("/api/productions", { theme, target_cards: cards, provider: "mock" });
      await api.post(`/api/runs/${r.run_id}/start`);
      setSelected(r.run_id);
      setTheme("");
    }).then(refresh);

  const d = detail.data;
  const runCalls = calls.data ?? [];

  useEffect(() => {
    runs.reload();
  }, [d?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <h1>Monitor de execução</h1>
      <ErrorLine error={act.error || runs.error} />
      <Card title="Nova execução simulada">
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            if (theme.trim()) create();
          }}
        >
          <label>
            Tema
            <input value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="ex.: Hipertensão arterial" required />
          </label>
          <label>
            Cards
            <input type="number" min={1} max={50} value={cards} onChange={(e) => setCards(Number(e.target.value))} />
          </label>
          <button type="submit" disabled={act.busy || !theme.trim()}>Criar e iniciar</button>
        </form>
        <p className="muted small">
          Usa o provedor simulado: percorre as 16 etapas sem custo e sem gerar conteúdo médico real.
        </p>
      </Card>

      <div className="split">
        <Card title="Execuções">
          <ul className="list">
            {(runs.data ?? []).map((r) => (
              <li key={r.id}>
                <button className={`link ${selected === r.id ? "sel" : ""}`} onClick={() => setSelected(r.id)}>
                  <span>{r.theme || r.id}</span> <Badge state={r.state} />
                </button>
              </li>
            ))}
            {runs.data && !runs.data.length && <li className="muted">Nenhuma execução.</li>}
          </ul>
        </Card>

        {d && (
          <Card
            title={d.theme}
            actions={
              <>
                {d.state === "PENDING" && <button onClick={() => doRun(`/api/runs/${d.id}/start`)}>Iniciar</button>}
                {d.state === "RUNNING" && <button onClick={() => doRun(`/api/runs/${d.id}/pause`)}>Pausar</button>}
                {["PAUSED", "PAUSED_BUDGET", "FAILED"].includes(d.state) && (
                  <button onClick={() => doRun(`/api/runs/${d.id}/resume`)}>Retomar</button>
                )}
                {!["COMPLETED", "CANCELLED"].includes(d.state) && (
                  <button className="danger" onClick={() => doRun(`/api/runs/${d.id}/cancel`)}>Cancelar</button>
                )}
              </>
            }
          >
            <p>
              <Badge state={d.state} /> {d.active && <span className="muted">processando…</span>} {d.note && <span className="note">{d.note}</span>}
            </p>
            <CountList counts={d.tasks} />
            <table className="tasks">
              <thead><tr><th>Etapa</th><th>Estado</th><th>Tentativas</th><th>Detalhe</th><th></th></tr></thead>
              <tbody>
                {d.task_list.map((t) => (
                  <tr key={t.id} className={t.required ? "" : "optional"}>
                    <td>{t.key}</td>
                    <td><Badge state={t.state} /></td>
                    <td>{t.attempts}/{t.max_attempts}</td>
                    <td className="detail">{t.last_error ?? (t.output ? summarize(t.output) : "")}</td>
                    <td><div className="actions">
                      {["FAILED", "UNCERTAIN", "CANCELLED", "SUCCEEDED"].includes(t.state) && (
                        <button className="small" onClick={() => doRun(`/api/tasks/${t.id}/reprocess`)}>Reprocessar</button>
                      )}
                      {["AWAITING_HUMAN", "UNCERTAIN", "FAILED"].includes(t.state) && (
                        <button
                          className="small"
                          onClick={() => {
                            const reason = window.prompt("Motivo da decisão (fica registrado):");
                            if (reason) doRun(`/api/tasks/${t.id}/skip`, { reason });
                          }}
                        >
                          Dispensar
                        </button>
                      )}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Chamadas de IA desta execução</h3>
            {runCalls.length ? (
              <table>
                <thead><tr><th>Etapa</th><th>Modelo</th><th>Estado</th><th>Custo (US$)</th><th>Teto (US$)</th><th>Prompt</th></tr></thead>
                <tbody>
                  {runCalls.map((c) => (
                    <tr key={c.id}>
                      <td>{c.stage}</td>
                      <td>{c.served_model ?? c.requested_model}</td>
                      <td><Badge state={c.state} /></td>
                      <td>{c.cost_usd ?? "pendente"}</td>
                      <td>{c.estimated_max_usd}</td>
                      <td><code>{c.prompt_hash.slice(0, 10)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muted">Nenhuma chamada registrada.</p>}
            <p className="muted small">Iniciada {fmtDate(d.started_at)} · concluída {fmtDate(d.finished_at)}</p>
          </Card>
        )}
      </div>
    </>
  );
}

function summarize(o: Record<string, unknown>): string {
  const parts: string[] = [];
  if (Array.isArray(o.card_ids)) parts.push(`${o.card_ids.length} cards`);
  if (typeof o.cards === "number") parts.push(`${o.cards} cards no manifesto`);
  if (typeof o.checked === "number") parts.push(`${o.checked} verificados`);
  if (Array.isArray(o.limitations) && o.limitations.length) parts.push(String(o.limitations[0]));
  return parts.join(" · ");
}
