import { useEffect, useState } from "react";
import Dashboard from "./pages/Dashboard";
import Monitor from "./pages/Monitor";
import Prompts from "./pages/Prompts";
import Budget from "./pages/Budget";
import Library from "./pages/Library";
import Imports from "./pages/Imports";
import Knowledge from "./pages/Knowledge";
import Cards from "./pages/Cards";
import Gallery from "./pages/Gallery";
import Exports from "./pages/Exports";
import Audit from "./pages/Audit";

const PAGES = [
  { id: "painel", label: "Painel", el: <Dashboard /> },
  { id: "monitor", label: "Monitor", el: <Monitor /> },
  { id: "biblioteca", label: "Biblioteca", el: <Library /> },
  { id: "conhecimento", label: "Conhecimento", el: <Knowledge /> },
  { id: "cards", label: "Cards", el: <Cards /> },
  { id: "auditoria", label: "Auditoria", el: <Audit /> },
  { id: "galeria", label: "Galeria visual", el: <Gallery /> },
  { id: "exportacao", label: "Exportação", el: <Exports /> },
  { id: "importacao", label: "Importação", el: <Imports /> },
  { id: "prompts", label: "Prompts", el: <Prompts /> },
  { id: "orcamento", label: "Orçamento", el: <Budget /> },
] as const;

function current() {
  const h = window.location.hash.replace("#/", "").split("?")[0];
  return PAGES.some((p) => p.id === h) ? h : "painel";
}

export default function App() {
  const [page, setPage] = useState(current);
  useEffect(() => {
    const on = () => setPage(current());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return (
    <div className="shell">
      <nav className="nav" aria-label="Seções">
        <div className="brand">CardFactory</div>
        {PAGES.map((p) => (
          <a key={p.id} href={`#/${p.id}`} className={page === p.id ? "active" : ""} aria-current={page === p.id ? "page" : undefined}>
            {p.label}
          </a>
        ))}
        <div className="nav-foot">Fase 4 · dados locais</div>
      </nav>
      <main className="main">{PAGES.find((p) => p.id === page)!.el}</main>
    </div>
  );
}
