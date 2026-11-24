import { usePoll } from "../hooks";
import { Card, ErrorLine } from "../components";
import { CardPreview, Findings, type Finding, type Rendered } from "../preview";

interface Sample { layout: string; card: { cognitive_type: string }; rendered: Rendered; findings: Finding[] }
interface Pal { [k: string]: string | Record<string, number> }

const LAYOUT_LABEL: Record<string, string> = {
  direct: "A · Resposta direta", list: "B · Lista", criteria: "C · Critérios", comparison: "D · Comparação",
  score: "E · Escore", mechanism: "F · Mecanismo", algorithm: "G · Conduta/algoritmo", pharmacology: "H · Farmacologia",
  case: "I · Caso clínico", negative: "J · Negativa", image: "K · Imagem", integration: "L · Integração",
};

export default function Gallery() {
  const { data, error } = usePoll<Sample[]>("/api/render/samples");
  const pals = usePoll<Record<string, Pal>>("/api/render/palettes");
  return (
    <>
      <h1>Galeria visual</h1>
      <p className="muted">
        Um card de exemplo por tipo cognitivo, renderizado pelo mesmo motor da exportação. Conteúdo fictício,
        só para inspeção visual em largura de celular (VIS-014).
      </p>
      <ErrorLine error={error} />
      {pals.data && (
        <Card title="Contraste das paletas (mínimo 4,5:1)">
          <table>
            <thead><tr><th>Paleta</th><th>Texto</th><th>Complemento</th><th>Azul</th><th>Âmbar</th><th>Vermelho</th></tr></thead>
            <tbody>
              {Object.entries(pals.data).map(([name, p]) => {
                const c = p.contrast as Record<string, number>;
                return (
                  <tr key={name}>
                    <td>{name === "dark" ? "Escura (exportação)" : "Clara (só prévia)"}</td>
                    {["text", "complement", "blue", "amber", "red"].map((k) => (
                      <td key={k}><span className="swatch" style={{ background: p[k] as string }} /> {c[k].toFixed(1)}:1</td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
      <div className="gallery">
        {(data ?? []).map((s) => (
          <Card key={s.layout} title={LAYOUT_LABEL[s.layout] ?? s.layout}>
            <CardPreview rendered={s.rendered} reveal label={s.layout} />
            <details>
              <summary>Achados ({s.findings.length})</summary>
              <Findings findings={s.findings} />
            </details>
          </Card>
        ))}
      </div>
    </>
  );
}
