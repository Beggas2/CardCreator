// Smoke test da interface: sobe o backend com dados temporários e provedor simulado,
// percorre todas as telas: execução simulada até a revisão humana, cards, exportação, auditoria, galeria, prompts e orçamento.
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

  await page.getByRole("link", { name: "Biblioteca" }).click();
  await page.getByText("[SIMULADO] Documento de teste").first().waitFor();
  await page.getByLabel("Termos").fill("fármaco dose");
  await page.getByRole("button", { name: "Buscar" }).click();
  await page.locator("mark").first().waitFor();
  await page.screenshot({ path: join(shots, "5-biblioteca.png"), fullPage: true });

  await page.getByRole("link", { name: "Conhecimento" }).click();
  await page.getByRole("button", { name: /Condição X/ }).click();
  await page.getByText("Integração clínica").waitFor();
  await page.getByRole("button", { name: "[SIMULADO] Objetivo 1" }).click();
  await page.locator("blockquote").first().waitFor();
  await page.screenshot({ path: join(shots, "6-conhecimento.png"), fullPage: true });

  await page.getByRole("link", { name: "Importação" }).click();
  await page.getByLabel("Arquivo do Anki").setInputFiles({
    name: "teste.txt", mimeType: "text/plain",
    buffer: Buffer.from("#separator:tab\n#guid column:1\n#deck column:2\ng1\tIGOR::T\tFrente\tVerso\ng2\tIGOR::T\tSó frente\n"),
  });
  await page.getByText("2 notas · 2 novas").first().waitFor();
  await page.screenshot({ path: join(shots, "7-importacao.png"), fullPage: true });

  // Fase 3: cards, prévia, aprovação humana mínima, exportação e galeria visual.
  await page.getByRole("link", { name: "Cards", exact: true }).click();
  await page.getByText("[SIMULADO] Pergunta 1").first().click();
  const frame = page.frameLocator("iframe").first();
  await frame.getByText("[SIMULADO] Pergunta 1").waitFor();
  await page.getByRole("button", { name: "Claro" }).first().click();
  const bg = await page.locator("iframe").first().evaluate((f) => getComputedStyle(f.contentDocument.body).backgroundColor);
  if (bg !== "rgb(255, 255, 255)") throw new Error("prévia clara não aplicou fundo branco: " + bg);
  await page.getByLabel("Seu nome").fill("Revisora de teste");
  await page.getByLabel("Motivo").fill("conferido no smoke");
  await page.getByRole("button", { name: "Aprovar para exportação" }).click();
  await page.getByText("aprovado").first().waitFor();
  await page.screenshot({ path: join(shots, "8-cards.png"), fullPage: true });

  await page.getByRole("link", { name: "Exportação" }).click();
  await page.getByRole("button", { name: "Exportar" }).click();
  await page.getByText("pronta").first().waitFor();
  await page.getByRole("link", { name: /DECK_anki_tsv_v2_v1\.txt/ }).waitFor();
  await page.screenshot({ path: join(shots, "9-exportacao.png"), fullPage: true });

  // Fase 4: auditoria integral do lote importado (provedor simulado) e relatório por dimensão.
  await page.getByRole("link", { name: "Auditoria" }).click();
  await page.getByLabel("Tema").fill("Teste de auditoria");
  await page.getByLabel(/teste\.txt/).check();
  await page.getByRole("button", { name: "Iniciar auditoria" }).click();
  await page.getByRole("combobox", { name: "Produção" }).locator("option", { hasText: "Auditoria · Teste de auditoria" })
    .waitFor({ state: "attached", timeout: 15000 });
  await page.getByText("Veredito por dimensão").waitFor();
  await page.getByText("importado").first().waitFor({ timeout: 30000 });
  await page.getByRole("cell", { name: /sem defeitos abertos|com pendências|bloqueada|não verificada/ }).first()
    .waitFor({ timeout: 30000 });
  await page.screenshot({ path: join(shots, "11-auditoria.png"), fullPage: true });
  await page.setViewportSize({ width: 412, height: 900 });
  const pageOver = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (pageOver > 0) throw new Error(`Auditoria rola na horizontal em celular (${pageOver}px)`);
  await page.setViewportSize({ width: 1280, height: 860 });

  await page.setViewportSize({ width: 412, height: 900 });
  await page.getByRole("link", { name: "Galeria visual" }).click();
  await page.getByText("L · Integração").waitFor();
  await page.waitForFunction(() => document.querySelectorAll("iframe").length === 12);
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() => [...document.querySelectorAll("iframe")].map((f) => {
    const d = f.contentDocument.documentElement;
    return { title: f.title, over: d.scrollWidth - d.clientWidth };
  }).filter((x) => x.over > 0));
  if (overflow.length) throw new Error("rolagem horizontal em largura de celular: " + JSON.stringify(overflow));
  await page.screenshot({ path: join(shots, "10-galeria-celular.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 860 });

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
