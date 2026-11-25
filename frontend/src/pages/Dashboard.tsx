import { fmtBRL, fmtDate, type Dashboard as D } from "../api";
import { Badge, Card, CountList, ErrorLine, Stat } from "../components";
import { usePoll } from "../hooks";

const sum = (c: Record<string, number>) => Object.values(c).reduce((a, b) => a + b, 0);

export default function Dashboard() {
  const { data, error } = usePoll<D>("/api/dashboard", 4000);
  if (!data) return <><h1>Painel</h1><ErrorLine error={error} />{!error && <p className="muted">Carregando…</p>}</>;
  const root = data.budgets[0];
  return (
    <>
      <h1>Painel</h1>
      <ErrorLine error={error} />
      {!data.openrouter_configured && (
        <p className="notice">
          Nenhuma chave do OpenRouter configurada: o app funciona apenas com o provedor simulado, sem custo.
        </p>
      )}
      <div className="stats">
        <Stat label="Projetos" value={data.projects} />
        <Stat label="Produções" value={data.productions} />
        <Stat label="Cards" value={sum(data.cards)} hint={data.cards_mock ? `${data.cards_mock} simulados` : undefined} />
        <Stat label="Chamadas de IA" value={sum(data.calls)} />
        <Stat label="Pendentes de reconciliação" value={data.pending_reconciliation} />
        <Stat
          label="Orçamento principal disponível"
          value={root ? fmtBRL(root.available_brl) : "—"}
          hint={root ? `de ${fmtBRL(root.limit_brl)} (${root.label})` : "nenhum orçamento"}
        />
      </div>
      <div className="grid2">
        <Card title="Cards por estado"><CountList counts={data.cards} /></Card>
        <Card title="Tarefas por estado"><CountList counts={data.tasks} /></Card>
        <Card title="Chamadas por estado"><CountList counts={data.calls} empty="nenhuma" /></Card>
        <Card title="Câmbio">
          {data.fx ? (
            <p>
              US$ 1 = R$ {data.fx.rate} · margem {Number(data.fx.margin) * 100}% · {data.fx.source} ({data.fx.valid_on})
            </p>
          ) : (
            <p className="muted">Câmbio não configurado. Chamadas pagas ficam bloqueadas até configurar.</p>
          )}
        </Card>
      </div>
      <Card title="Execuções recentes">
        {data.recent_runs.length ? (
          <table>
            <thead><tr><th>Tema</th><th>Modo</th><th>Provedor</th><th>Estado</th><th>Criada</th></tr></thead>
            <tbody>
              {data.recent_runs.map((r) => (
                <tr key={r.id}>
                  <td><a href={`#/monitor?run=${r.id}`}>{r.theme}</a></td>
                  <td>{r.mode}</td><td>{r.provider}</td><td><Badge state={r.state} /></td><td>{fmtDate(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">Nenhuma execução ainda. Crie uma no Monitor.</p>}
      </Card>
      <p className="disclaimer">Aprovação automática não é certificação médica.</p>
    </>
  );
}
