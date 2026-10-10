// Serveur local qui imite Netlify (site + /api + fonction de fond), stockage en mémoire.
//   PARENT_PASSWORD=test node tests/dev-server.mjs        (lecture des photos simulée si DEMO=1)
import { readFile } from "node:fs/promises";
import http from "node:http";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import handler from "../functions/api.mjs";
import background from "../functions/extract-background.mjs";
import { setTestClient } from "../lib/homework.mjs";
import { setTestSender } from "../lib/push.mjs";
import { MemoryStore, setTestStore } from "../lib/store.mjs";

const root = join(fileURLToPath(new URL(".", import.meta.url)), "..", "public");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".webmanifest": "application/manifest+json" };

setTestStore(new MemoryStore());
setTestSender(async (sub, payload) => console.log("[push]", sub.endpoint, payload));
if (process.env.DEMO) {
  setTestClient({ beta: { messages: { create: async () => {
    await new Promise((r) => setTimeout(r, 1500));
    return { stop_reason: "end_turn", content: [{ type: "text", text: JSON.stringify({
      child: "amine", confidence: "probable", remarks: "La dernière ligne est en partie cachée.",
      items: [
        { subject: "Mathématiques", task: "Exercices 3 et 4 page 52 (fractions décimales)", due: tomorrow(), minutes: 20, kind: "exercice" },
        { subject: "Français", task: "Apprendre la poésie « Le Corbeau et le Renard » (2 strophes)", due: tomorrow(), minutes: 15, kind: "récitation" },
        { subject: "Histoire", task: "Relire la leçon sur la Révolution française", due: inDays(4), minutes: 10, kind: "leçon" },
      ] }) }] };
  } } } });
}
function inDays(n) { const d = new Date(Date.now() + n * 86_400_000); return d.toISOString().slice(0, 10); }
function tomorrow() { return inDays(1); }

async function toRequest(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  return new Request(`http://${req.headers.host}${req.url}`, { method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body });
}

async function send(res, response) {
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(Buffer.from(await response.arrayBuffer()));
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.url.startsWith("/api/")) return send(res, await handler(await toRequest(req)));
    if (req.url.startsWith("/.netlify/functions/extract-background")) {
      const r = await toRequest(req);
      res.writeHead(202).end();
      if (process.env.NO_BACKGROUND) return; // simule un hébergement sans fonctions de fond
      return void background(r);
    }
    const path = req.url.split("?")[0].replace(/\/$/, "/index.html");
    const file = await readFile(join(root, path));
    res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }).end(file);
  } catch (err) {
    res.writeHead(404).end(String(err.message));
  }
});

const port = Number(process.env.PORT || 8888);
server.listen(port, () => console.log(`Espace parents local : http://localhost:${port}`));
export default server;
