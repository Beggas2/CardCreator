import type { ReactNode } from "react";

const STATE_TONE: Record<string, string> = {
  SUCCEEDED: "ok", COMPLETED: "ok", SKIPPED_REUSED: "ok", RECONCILED: "ok",
  RUNNING: "info", READY: "info", SENT: "info", RESERVED: "info",
  PENDING: "muted", DRAFT: "muted", GENERATED: "muted",
  PAUSED: "warn", PAUSED_BUDGET: "warn", AWAITING_HUMAN: "warn", TRUNCATED: "warn", INVALID_OUTPUT: "warn",
  VERIFIED: "ok", RETRIEVED: "info", FOUND: "muted", PARTIALLY_READ: "warn", UNAVAILABLE: "bad", OUTDATED: "bad",
  VALIDITY_UNCERTAIN: "warn", IMPORTED: "info", QUARANTINE: "bad",
  FAILED: "bad", FAILED_BILLED: "bad", CANCELLED: "muted", UNCERTAIN: "bad", FAILED_UNBILLED: "muted",
};

const STATE_LABEL: Record<string, string> = {
  SUCCEEDED: "concluída", COMPLETED: "concluída", SKIPPED_REUSED: "dispensada", RUNNING: "executando",
  READY: "pronta", PENDING: "aguardando", PAUSED: "pausada", PAUSED_BUDGET: "pausada (orçamento)",
  AWAITING_HUMAN: "aguardando revisão", VERIFIED: "conferido", RETRIEVED: "recuperado", FOUND: "encontrado",
  PARTIALLY_READ: "lido em parte", UNAVAILABLE: "indisponível", OUTDATED: "desatualizado",
  VALIDITY_UNCERTAIN: "vigência incerta", IMPORTED: "importado", QUARANTINE: "quarentena", FAILED: "falhou", CANCELLED: "cancelada", UNCERTAIN: "incerta",
};

export function Badge({ state }: { state: string }) {
  return (
    <span className={`badge tone-${STATE_TONE[state] ?? "muted"}`} title={state}>
      {STATE_LABEL[state] ?? state}
    </span>
  );
}

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      <header>
        <h2>{title}</h2>
        {actions && <div className="actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function ErrorLine({ error }: { error: string | null }) {
  return error ? <p className="error" role="alert">{error}</p> : null;
}

export function CountList({ counts, empty = "nenhum" }: { counts: Record<string, number>; empty?: string }) {
  const entries = Object.entries(counts);
  if (!entries.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="counts">
      {entries.map(([k, v]) => (
        <li key={k}>
          <Badge state={k} /> <strong>{v}</strong>
        </li>
      ))}
    </ul>
  );
}
