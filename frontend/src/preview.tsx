import { useEffect, useRef, useState } from "react";

export interface Rendered {
  dark: { front: string; back: string };
  light: { front: string; back: string };
}

const THEME = {
  dark: { bg: "#101114", fg: "#E5E7EB", hr: "#30343B" },
  light: { bg: "#FFFFFF", fg: "#1F2937", hr: "#CBD5E1" },
};

/**
 * Prévia como no Anki (VIS-013): frente, revelação do verso, tema escuro/claro e largura de celular/desktop.
 * O HTML vem do renderizador do backend e roda num iframe sem scripts (sandbox sem allow-scripts).
 */
export function CardPreview({ rendered, initialTheme = "dark", initialWidth = "mobile", reveal = false, label }: {
  rendered: Rendered;
  initialTheme?: "dark" | "light";
  initialWidth?: "mobile" | "desktop";
  reveal?: boolean;
  label?: string;
}) {
  const [theme, setTheme] = useState(initialTheme);
  const [width, setWidth] = useState(initialWidth);
  const [shown, setShown] = useState(reveal);
  const [height, setHeight] = useState(120);
  const ref = useRef<HTMLIFrameElement>(null);
  const t = THEME[theme];
  const html = rendered[theme];
  const doc = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>html,body{margin:0}body{background:${t.bg};color:${t.fg};font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:18px;text-align:center;padding:16px;overflow-wrap:break-word}
hr#answer{border:0;border-top:1px solid ${t.hr};margin:1em 0}</style></head>
<body>${html.front}${shown ? `<hr id="answer">${html.back}` : ""}</body></html>`;

  useEffect(() => {
    const f = ref.current;
    if (!f) return;
    const measure = () => {
      const d = f.contentDocument;
      if (d?.body) setHeight(Math.max(80, d.documentElement.scrollHeight));
    };
    f.addEventListener("load", measure);
    return () => f.removeEventListener("load", measure);
  }, []);

  return (
    <div className="preview" data-theme={theme} data-width={width}>
      <div className="preview-bar">
        {label && <strong>{label}</strong>}
        <div className="seg" role="group" aria-label="Tema">
          <button className={theme === "dark" ? "on" : ""} onClick={() => setTheme("dark")}>Escuro</button>
          <button className={theme === "light" ? "on" : ""} onClick={() => setTheme("light")}>Claro</button>
        </div>
        <div className="seg" role="group" aria-label="Largura">
          <button className={width === "mobile" ? "on" : ""} onClick={() => setWidth("mobile")}>Celular</button>
          <button className={width === "desktop" ? "on" : ""} onClick={() => setWidth("desktop")}>Desktop</button>
        </div>
        <button onClick={() => setShown(!shown)}>{shown ? "Ocultar verso" : "Mostrar verso"}</button>
      </div>
      <iframe
        ref={ref}
        title={label ? `Prévia: ${label}` : "Prévia do card"}
        sandbox="allow-same-origin"
        srcDoc={doc}
        style={{ width: width === "mobile" ? 360 : 720, height, maxWidth: "100%" }}
      />
      {theme === "light" && <p className="muted small">Modo claro só na prévia: a exportação usa a paleta escura (AMB-01).</p>}
    </div>
  );
}

export interface Finding { level: string; code: string; message: string; status?: string; id?: string; justification?: string }

export function Findings({ findings, onJustify }: { findings: Finding[]; onJustify?: (f: Finding) => void }) {
  if (!findings.length) return <p className="muted">Nenhum achado de validação.</p>;
  return (
    <ul className="findings">
      {findings.map((f, i) => (
        <li key={f.id ?? i} className={f.level === "ERROR" ? "f-error" : "f-warn"}>
          <span className="f-level">{f.level === "ERROR" ? "Erro" : "Alerta"}</span>
          <code>{f.code}</code> {f.message}
          {f.status && f.status !== "OPEN" && <em> · {f.status === "JUSTIFIED" ? `justificado: ${f.justification}` : "corrigido"}</em>}
          {onJustify && f.level === "WARNING" && f.status === "OPEN" && (
            <button className="tlink" onClick={() => onJustify(f)}>justificar</button>
          )}
        </li>
      ))}
    </ul>
  );
}
