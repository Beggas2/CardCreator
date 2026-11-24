export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const raw = body instanceof Blob;
  const r = await fetch(url, {
    method,
    headers: raw ? { "Content-Type": (body as Blob).type || "application/octet-stream" }
      : body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: raw ? (body as Blob) : body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || `HTTP ${r.status}`);
  return data as T;
}

export const api = {
  get: <T,>(url: string) => req<T>("GET", url),
  post: <T,>(url: string, body: unknown = {}) => req<T>("POST", url, body),
  upload: <T,>(url: string, file: Blob) => req<T>("POST", url, file),
  patch: <T,>(url: string, body: unknown) => req<T>("PATCH", url, body),
  put: <T,>(url: string, body: unknown) => req<T>("PUT", url, body),
  del: <T,>(url: string) => req<T>("DELETE", url),
};

export type Counts = Record<string, number>;

export interface BudgetStatus {
  budget_id: string;
  label: string;
  limit_brl: string;
  confirmed_brl: string;
  reserved_brl: string;
  available_brl: string;
  scope?: string;
  scope_ref?: string;
  parent_budget_id?: string | null;
}

export interface RunRow {
  id: string;
  mode: string;
  state: string;
  note: string;
  theme: string;
  provider: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  tasks: Counts;
}

export interface TaskRow {
  id: string;
  key: string;
  stage: string;
  kind: string;
  state: string;
  attempts: number;
  max_attempts: number;
  required: boolean;
  last_error: string | null;
  output: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Dashboard {
  projects: number;
  productions: number;
  runs: Counts;
  tasks: Counts;
  cards: Counts;
  cards_mock: number;
  calls: Counts;
  budgets: BudgetStatus[];
  pending_reconciliation: number;
  fx: { rate: string; margin: string; source: string; valid_on: string } | null;
  openrouter_configured: boolean;
  recent_runs: RunRow[];
}

export interface PromptRow {
  key: string;
  kind: string;
  description: string;
  active_version_id: string | null;
  version: number | null;
  hash: string | null;
  req_ids: string[];
}

export interface PromptVersion {
  id: string;
  version: number;
  hash: string;
  created_by: string;
  created_at: string | null;
  note: string;
  req_ids: string[];
  active: boolean;
  body: string;
}

export const fmtBRL = (v: string | number) =>
  Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 4 });

export const fmtDate = (v: string | null) => (v ? new Date(v).toLocaleString("pt-BR") : "—");
