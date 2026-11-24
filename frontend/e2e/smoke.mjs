// Smoke test da interface: sobe o backend com dados temporários e provedor simulado,
// percorre Painel, Monitor (execução simulada até a revisão humana), Prompts e Orçamento.
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const root = resolve(import.meta.dirname, "..", "..");
const port = 18765 + Math.floor(Math.random() * 1000);
const dataDir = mkdtempSync(join(tmpdir(), "cf-smoke-"));
const shots = process.env.SMOKE_SHOTS || join(dataDir, "shots");
mkdirSync(shots, { recursive: true });
const env = { ...process.env, CARDFACTORY_DATA_DIR: dataDir };
delete env.OPENROUTER_API_KEY;

const server = spawn("uv", ["run", "--project", join(root, "backend"), "cardfactory", "serve", "--port", String(port)], {
  env, stdio: ["ignore", "pipe", "pipe"],
});
let log = "";
server.stdout.on("data", (d) => (log += d));
server.stderr.on("data", (d) => (log += d));

const base = `http://127.0.0.1:${port}`;
async function waitUp() {
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("servidor não subiu:\n" + log);
}

let failed = false;
let page;
const browser = await chromium.launch();
try {
  await waitUp();
  page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto(`${base}/#/painel`);
  await page.getByRole("heading", { name: "Painel" }).waitFor();
  await page.getByText("Nenhuma chave do OpenRouter configurada").waitFor();
  await page.screenshot({ path: join(shots, "1-painel.png") });

  await page.getByRole("link", { name: "Monitor" }).click();
  await page.getByLabel("Tema").fill("Hipertensão arterial (teste)");
  await page.getByRole("button", { name: "Criar e iniciar" }).click();
  await page.getByText("aguardando revisão").first().waitFor({ timeout: 30000 });
  await page.getByRole("cell", { name: "EXPORT", exact: true }).waitFor();
  await page.screenshot({ path: join(shots, "2-monitor.png"), fullPage: true });

  await page.getByRole("link", { name: "Prompts" }).click();
  await page.getByText("Todos os papéis contêm os requisitos obrigatórios").waitFor();
  await page.getByRole("button", { name: /role:creator/ }).click();
  await page.getByText("Versão ativa 1").waitFor();
  await page.screenshot({ path: join(shots, "3-prompts.png") });

  await page.getByRole("link", { name: "Orçamento" }).click();
  await page.getByLabel("Taxa").fill("5.20");
  await page.getByRole("button", { name: "Registrar" }).click();
  await page.getByText("US$ 1 = R$ 5.2").waitFor();
  await page.getByText("Nenhuma autorização ativa").waitFor();
  await page.screenshot({ path: join(shots, "4-orcamento.png"), fullPage: true });

  if (errors.length) throw new Error("erros no console: " + errors.join("\n"));
  console.log(`smoke OK · capturas em ${shots}`);
} catch (e) {
  failed = true;
  console.error(e);
  if (page) await page.screenshot({ path: join(shots, "falha.png"), fullPage: true }).catch(() => {});
  console.error(log.slice(-3000));
} finally {
  await browser.close();
  server.kill();
}
process.exit(failed ? 1 : 0);
