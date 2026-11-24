import { useEffect, useState } from "react";
import { Card, ErrorLine } from "../components";
import { usePoll } from "../hooks";

interface Project { id: string; name: string }
interface Entity { id: string; name: string; synonyms: string[]; home_deck_path: string; map_states: Record<string, number>;
  objectives: number; decision_points: number }
interface Objective { id: string; entity_id: string | null; description: string; knowledge_level: string; necessity: string;
  coverage_state: string; purpose: string; planned_cards: number }
interface Dim { name: string; state: string; justification: string }
interface Evidence { id: string; quote: string; title: string; section_path: string; page: number | null; tier: string; validity: string }
interface ClaimRow { id: string; text: string; component: string; criticality: string; evidence: Evidence[] }

const MAP_LABEL: Record<string, string> = { APPLICABLE_COVERED: "contemplada", APPLICABLE_PENDING: "pendente",
  NOT_APPLICABLE: "não se aplica", COVERED_ELSEWHERE: "outro deck", NOT_VERIFIABLE: "não verificável" };
const COV_LABEL: Record<string, string> = { COMPLETE: "completo", PARTIAL: "parcial", INFERABLE: "inferível", ABSENT: "ausente",
  INCORRECT: "incorreto", OUTDATED: "desatualizado", NOT_VERIFIABLE: "não verificável", COVERED_ELSEWHERE: "outro deck",
  NOT_APPLICABLE: "não aplicável" };

export default function Knowledge() {
  const projects = usePoll<Project[]>("/api/projects");
  const [project, setProject] = useState("");
  const entities = usePoll<Entity[]>(project ? `/api/knowledge/entities?project_id=${project}` : null);
  const objectives = usePoll<Objective[]>(project ? `/api/knowledge/objectives?project_id=${project}` : null);
  const [entity, setEntity] = useState<string | null>(null);
  const map = usePoll<Record<string, Dim>>(entity ? `/api/knowledge/entities/${entity}/map` : null);
  const [obj, setObj] = useState<string | null>(null);
  const claims = usePoll<ClaimRow[]>(obj ? `/api/knowledge/claims?objective_id=${obj}` : null);

  useEffect(() => {
    if (!project && projects.data?.length) setProject(projects.data[0].id);
  }, [projects.data, project]);

  const objs = (objectives.data ?? []).filter((o) => !entity || o.entity_id === entity);

  return (
    <>
      <h1>Conhecimento</h1>
      <ErrorLine error={projects.error || entities.error} />
      <div className="row">
        <label>Projeto<select value={project} onChange={(e) => { setProject(e.target.value); setEntity(null); setObj(null); }}>
          <option value="">—</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      </div>
      <div className="split">
        <Card title="Entidades">
          {entities.data?.length ? (
            <ul className="list">{entities.data.map((e) => (
              <li key={e.id}>
                <button className={`link ${entity === e.id ? "sel" : ""}`} onClick={() => setEntity(entity === e.id ? null : e.id)}>
                  <span>{e.name}</span><span className="muted small">{e.objectives} objetivos</span>
                </button>
              </li>))}</ul>
          ) : <p className="muted">Nenhuma entidade. Elas surgem do planejamento de uma produção.</p>}
        </Card>
        <div>
          {entity && map.data && (
            <Card title="Mapa ideal (57 dimensões)">
              <table className="compact">
                <thead><tr><th>#</th><th>Dimensão</th><th>Estado</th><th>Justificativa</th></tr></thead>
                <tbody>{Object.entries(map.data).map(([code, d]) => (
                  <tr key={code} className={d.state === "NOT_APPLICABLE" ? "optional" : ""}>
                    <td>{code}</td><td>{d.name}</td><td>{MAP_LABEL[d.state] ?? d.state}</td><td className="detail">{d.justification}</td>
                  </tr>))}</tbody>
              </table>
            </Card>
          )}
          <Card title={`Objetivos de aprendizagem (${objs.length})`}>
            {objs.length ? (
              <table>
                <thead><tr><th>Objetivo</th><th>Nível</th><th>Necessidade</th><th>Cobertura</th><th>Cards</th></tr></thead>
                <tbody>{objs.map((o) => (
                  <tr key={o.id} className={obj === o.id ? "selected" : ""}>
                    <td><button className="link" onClick={() => setObj(obj === o.id ? null : o.id)}>{o.description}</button></td>
                    <td>{o.knowledge_level}</td><td>{o.necessity}</td><td>{COV_LABEL[o.coverage_state] ?? o.coverage_state}</td><td>{o.planned_cards}</td>
                  </tr>))}</tbody>
              </table>
            ) : <p className="muted">Nenhum objetivo.</p>}
          </Card>
          {obj && (
            <Card title="Afirmações e evidências do objetivo">
              {claims.data?.length ? claims.data.map((c) => (
                <div key={c.id} className="claim">
                  <div><strong>{c.text}</strong> <span className="muted small">{c.component} · {c.criticality}</span></div>
                  {c.evidence.map((e) => (
                    <blockquote key={e.id}>“{e.quote}”<div className="muted small">{e.title} · {e.section_path}{e.page ? ` · p. ${e.page}` : ""} · {e.validity}</div></blockquote>
                  ))}
                  {!c.evidence.length && <p className="note small">Sem evidência vinculada.</p>}
                </div>)) : <p className="muted">Nenhuma afirmação vinculada.</p>}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
