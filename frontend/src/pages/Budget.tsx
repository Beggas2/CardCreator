import { useState } from "react";
import { api, fmtBRL, fmtDate, type BudgetStatus } from "../api";
import { Card, ErrorLine } from "../components";
import { useAction, usePoll } from "../hooks";

interface BudgetsResp {
  budgets: BudgetStatus[];
  fx: { rate: string; margin: string; source: string; valid_on: string } | null;
  authorizations: { id: string; budget_id: string; amount_brl: string; granted_by: string; note: string }[];
  pending_reconciliation: { id: string; state: string; requested_model: string; estimated_max_usd: string }[];
}

interface Ledger {
  id: string;
  budget_id: string;
  call_id: string | null;
  kind: string;
  amount_usd: string;
  amount_brl: string;
  note: string;
  created_at: string;
}

export default function Budget() {
  const b = usePoll<BudgetsResp>("/api/budgets", 5000);
  const ledger = usePoll<Ledger[]>("/api/ledger?limit=100", 5000);
  const act = useAction();
  const [fx, setFx] = useState({ rate: "", margin: "0.10" });
  const [nb, setNb] = useState({ scope_ref: "", limit_brl: "100", label: "" });
  const [auth, setAuth] = useState({ budget_id: "", amount_brl: "", granted_by: "", note: "" });
  const reload = () => {
    b.reload();
    ledger.reload();
  };
  const label = (id: string) => b.data?.budgets.find((x) => x.budget_id === id)?.label ?? id;

  return (
    <>
      <h1>Orçamento</h1>
      <ErrorLine error={act.error || b.error} />
      <p className="notice">
        Nenhuma chamada paga acontece sem câmbio configurado, orçamento disponível e uma autorização de gasto registrada.
      </p>
      <Card title="Orçamentos">
        {b.data?.budgets.length ? (
          <table>
            <thead><tr><th>Orçamento</th><th>Limite</th><th>Confirmado</th><th>Reservado</th><th>Disponível</th><th></th></tr></thead>
            <tbody>
              {b.data.budgets.map((x) => (
                <tr key={x.budget_id}>
                  <td>{x.label}</td>
                  <td>{fmtBRL(x.limit_brl)}</td>
                  <td>{fmtBRL(x.confirmed_brl)}</td>
                  <td>{fmtBRL(x.reserved_brl)}</td>
                  <td><strong>{fmtBRL(x.available_brl)}</strong></td>
                  <td>
                    {x.scope === "PROJECT" && x.scope_ref !== "mock" &&
                      !b.data!.budgets.some((c) => c.parent_budget_id === x.budget_id) && (
                      <button className="small" onClick={() => act.run(() => api.post(`/api/budgets/${x.budget_id}/seed-experiment`)).then(reload)}>
                        Criar divisão do experimento (R$100)
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">Nenhum orçamento.</p>}
        <form className="row" onSubmit={(e) => {
          e.preventDefault();
          act.run(() => api.post("/api/budgets", { scope: "PROJECT", ...nb })).then(reload);
        }}>
          <label>Identificador<input value={nb.scope_ref} onChange={(e) => setNb({ ...nb, scope_ref: e.target.value })} required /></label>
          <label>Nome<input value={nb.label} onChange={(e) => setNb({ ...nb, label: e.target.value })} /></label>
          <label>Limite (R$)<input value={nb.limit_brl} onChange={(e) => setNb({ ...nb, limit_brl: e.target.value })} inputMode="decimal" required /></label>
          <button type="submit" disabled={act.busy}>Criar orçamento</button>
        </form>
      </Card>

      <div className="grid2">
        <Card title="Câmbio USD → BRL">
          {b.data?.fx ? (
            <p>US$ 1 = R$ {b.data.fx.rate} · margem {Number(b.data.fx.margin) * 100}% · {b.data.fx.valid_on}</p>
          ) : <p className="muted">Não configurado.</p>}
          <form className="row" onSubmit={(e) => {
            e.preventDefault();
            act.run(() => api.post("/api/fx", fx)).then(reload);
          }}>
            <label>Taxa<input value={fx.rate} onChange={(e) => setFx({ ...fx, rate: e.target.value })} inputMode="decimal" required /></label>
            <label>Margem<input value={fx.margin} onChange={(e) => setFx({ ...fx, margin: e.target.value })} inputMode="decimal" /></label>
            <button type="submit" disabled={act.busy}>Registrar</button>
          </form>
        </Card>
        <Card title="Autorizações de gasto">
          {b.data?.authorizations.length ? (
            <ul className="list">
              {b.data.authorizations.map((a) => (
                <li key={a.id} className="row">
                  <span>{fmtBRL(a.amount_brl)} em {label(a.budget_id)} · por {a.granted_by}</span>
                  <button className="small danger" onClick={() => act.run(() => api.del(`/api/authorizations/${a.id}`)).then(reload)}>Revogar</button>
                </li>
              ))}
            </ul>
          ) : <p className="muted">Nenhuma autorização ativa: chamadas pagas estão bloqueadas.</p>}
          <form className="row" onSubmit={(e) => {
            e.preventDefault();
            act.run(() => api.post("/api/authorizations", auth)).then((ok) => {
              if (ok) setAuth({ budget_id: "", amount_brl: "", granted_by: "", note: "" });
              reload();
            });
          }}>
            <label>Orçamento
              <select value={auth.budget_id} onChange={(e) => setAuth({ ...auth, budget_id: e.target.value })} required>
                <option value="">—</option>
                {b.data?.budgets.map((x) => <option key={x.budget_id} value={x.budget_id}>{x.label}</option>)}
              </select>
            </label>
            <label>Valor (R$)<input value={auth.amount_brl} onChange={(e) => setAuth({ ...auth, amount_brl: e.target.value })} inputMode="decimal" required /></label>
            <label>Quem autoriza<input value={auth.granted_by} onChange={(e) => setAuth({ ...auth, granted_by: e.target.value })} required /></label>
            <button type="submit" disabled={act.busy}>Autorizar</button>
          </form>
        </Card>
      </div>

      <Card title="Chamadas pendentes de reconciliação">
        {b.data?.pending_reconciliation.length ? (
          <table>
            <thead><tr><th>Chamada</th><th>Estado</th><th>Modelo</th><th>Teto reservado (US$)</th></tr></thead>
            <tbody>{b.data.pending_reconciliation.map((p) => (
              <tr key={p.id}><td><code>{p.id}</code></td><td>{p.state}</td><td>{p.requested_model}</td><td>{p.estimated_max_usd}</td></tr>
            ))}</tbody>
          </table>
        ) : <p className="muted">Nenhuma.</p>}
      </Card>

      <Card title="Razão (últimos lançamentos)">
        {ledger.data?.length ? (
          <table>
            <thead><tr><th>Data</th><th>Orçamento</th><th>Tipo</th><th>US$</th><th>R$</th><th>Nota</th></tr></thead>
            <tbody>{ledger.data.map((e) => (
              <tr key={e.id}><td>{fmtDate(e.created_at)}</td><td>{label(e.budget_id)}</td><td>{e.kind}</td><td>{e.amount_usd}</td><td>{fmtBRL(e.amount_brl)}</td><td>{e.note}</td></tr>
            ))}</tbody>
          </table>
        ) : <p className="muted">Sem lançamentos.</p>}
      </Card>
    </>
  );
}
