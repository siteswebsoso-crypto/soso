import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import handler, { route } from "../functions/api.mjs";
import background from "../functions/extract-background.mjs";
import { internalSignature } from "../lib/auth.mjs";
import { processJob, setTestClient } from "../lib/homework.mjs";
import { setTestSender } from "../lib/push.mjs";
import { MemoryStore, readJSON, setTestStore } from "../lib/store.mjs";

const BASE = "https://famille.netlify.app";
let pushes;

beforeEach(() => {
  process.env.PARENT_PASSWORD = "secret-famille";
  setTestStore(new MemoryStore());
  pushes = [];
  setTestSender(async (sub, payload) => pushes.push({ to: sub.endpoint, ...JSON.parse(payload) }));
  setTestClient({
    beta: {
      messages: {
        create: async (params) => {
          assert.equal(params.model, "claude-opus-5-5");
          assert.equal(params.fallbacks, "default");
          assert.equal(params.output_config.format.type, "json_schema");
          assert.equal(params.messages[0].content[0].type, "image");
          return {
            stop_reason: "end_turn",
            content: [{ type: "text", text: JSON.stringify({
              child: "amine", confidence: "probable", remarks: "",
              items: [
                { subject: "Mathématiques", task: "Ex 3 et 4 p. 52", due: "2026-10-13", minutes: 20, kind: "exercice" },
                { subject: "Français", task: "Poésie strophe 1", due: "", minutes: 15, kind: "récitation" },
              ],
            }) }],
          };
        },
      },
    },
  });
});

async function call(method, path, { token, body, form, headers = {} } = {}) {
  const init = { method, headers: { ...headers } };
  if (token) init.headers.authorization = `Bearer ${token}`;
  if (form) init.body = form;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers["content-type"] = "application/json";
  }
  const res = await handler(new Request(`${BASE}/api/${path}`, init));
  return { status: res.status, data: res.headers.get("content-type")?.includes("json") ? await res.json() : await res.arrayBuffer() };
}

async function loginAs(name, device = false) {
  const r = await call("POST", "login", { body: { name, password: "secret-famille", device } });
  assert.equal(r.status, 200);
  return r.data.token;
}

test("connexion : mot de passe, jeton, limitation des essais", async () => {
  assert.equal((await call("GET", "state")).status, 401);
  assert.equal((await call("POST", "login", { body: { name: "Papa", password: "faux" } })).status, 401);
  const token = await loginAs("Papa");
  const s = await call("GET", "state", { token });
  assert.equal(s.status, 200);
  assert.equal(s.data.me.name, "Papa");
  assert.deepEqual(s.data.children.map((c) => c.name), ["Amine", "Ibrahim"]);
  assert.equal((await call("GET", "state", { token: token.slice(0, -2) + "xx" })).status, 401);
  for (let i = 0; i < 8; i++) await call("POST", "login", { body: { password: "nope" } });
  const locked = await call("POST", "login", { body: { name: "Papa", password: "secret-famille" } });
  assert.equal(locked.status, 429);
});

test("devoirs et consignes : ajout, modification, suppression", async () => {
  const token = await loginAs("Maman");
  const h = (await call("POST", "homework", { token, body: { child: "ibrahim", subject: "SVT", task: "Leçon 3", due: "2026-10-14", minutes: 15 } })).data;
  assert.equal(h.by, "Maman");
  const upd = await call("PATCH", `homework/${h.id}`, { token, body: { due: "2026-10-15", status: "fait" } });
  assert.equal(upd.data.due, "2026-10-15");
  assert.equal(upd.data.status, "fait");
  await call("DELETE", `homework/${h.id}`, { token });
  assert.equal((await call("GET", "state", { token })).data.homework.length, 0);
  assert.equal((await call("POST", "homework", { token, body: { child: "amine" } })).status, 400);

  const note = (await call("POST", "notes", { token, body: { child: "amine", text: "Insiste sur les tables de 7" } })).data;
  assert.equal((await call("GET", "state", { token })).data.notes[0].text, "Insiste sur les tables de 7");
  await call("DELETE", `notes/${note.id}`, { token });
  assert.equal((await call("GET", "state", { token })).data.notes.length, 0);
});

test("photo → lecture en fond → devoirs + notification à l'autre parent", async () => {
  const papa = await loginAs("Papa");
  const maman = await loginAs("Maman");
  await call("POST", "push/subscribe", { token: papa, body: { subscription: { endpoint: "https://push/papa" } } });
  await call("POST", "push/subscribe", { token: maman, body: { subscription: { endpoint: "https://push/maman" } } });

  const triggered = [];
  const form = new FormData();
  form.append("photo", new Blob([new Uint8Array([0xff, 0xd8, 1, 2, 3])], { type: "image/jpeg" }), "devoirs.jpg");
  form.append("caption", "");
  const res = await route(new Request(`${BASE}/api/photos`, { method: "POST", body: form, headers: { authorization: `Bearer ${papa}` } }),
    { triggerBackground: async (id, origin) => triggered.push({ id, origin }) });
  assert.equal(res.status, 202);
  const { id } = await res.json();
  assert.deepEqual(triggered, [{ id, origin: BASE }]);
  assert.equal((await call("GET", `jobs/${id}`, { token: papa })).data.status, "pending");

  // La fonction de fond refuse un appel non signé, accepte l'appel signé
  const bad = await background(new Request(`${BASE}/x`, { method: "POST", body: JSON.stringify({ id }) }));
  assert.equal(bad.status, 403);
  const ok = await background(new Request(`${BASE}/x`, {
    method: "POST", body: JSON.stringify({ id }), headers: { "x-jarvis-signature": internalSignature(id) },
  }));
  assert.equal(ok.status, 200);

  const job = (await call("GET", `jobs/${id}`, { token: papa })).data;
  assert.equal(job.status, "done");
  assert.equal(job.child, "amine");
  assert.equal(job.guessed, true);
  const hw = (await call("GET", "state", { token: papa })).data.homework;
  assert.deepEqual(hw.map((h) => [h.child, h.subject, h.due]), [["amine", "Mathématiques", "2026-10-13"], ["amine", "Français", null]]);
  assert.equal(pushes.length, 1);
  assert.equal(pushes[0].to, "https://push/maman");
  assert.match(pushes[0].title, /Devoirs d'Amine/);

  // La photo est consultable (jeton dans l'URL pour les balises <img>)
  const img = await handler(new Request(`${BASE}/api/photo/${job.photos[0]}?t=${papa}`));
  assert.equal(img.headers.get("content-type"), "image/jpeg");
  assert.equal(new Uint8Array(await img.arrayBuffer())[0], 0xff);
  // Une deuxième exécution ne duplique rien
  await processJob(id);
  assert.equal((await readJSON("homework", [])).length, 2);
});

test("le choix d'enfant du parent l'emporte sur la devinette", async () => {
  const papa = await loginAs("Papa");
  const form = new FormData();
  form.append("photo", new Blob([new Uint8Array([1])], { type: "image/png" }), "a.png");
  form.append("child", "ibrahim");
  const res = await route(new Request(`${BASE}/api/photos`, { method: "POST", body: form, headers: { authorization: `Bearer ${papa}` } }), {});
  const { id } = await res.json();
  await processJob(id);
  const job = await readJSON(`jobs/${id}`, null);
  assert.equal(job.child, "ibrahim");
  assert.equal(job.guessed, false);
});

test("synchronisation du Mac : états, rapports, secours de lecture", async () => {
  const papa = await loginAs("Papa");
  await call("POST", "push/subscribe", { token: papa, body: { subscription: { endpoint: "https://push/papa" } } });
  const mac = await loginAs("Mac", true);
  const h = (await call("POST", "homework", { token: papa, body: { child: "amine", subject: "Maths", task: "ex 1", minutes: 10 } })).data;

  const later = new Date(Date.now() + 1000).toISOString();
  const out = await call("POST", "sync", { token: mac, body: {
    children: [{ id: "amine", name: "Amine", grade: "CM2", avatar: "🐯", color: "#f00" }],
    status_updates: [{ id: h.id, status: "fait", comment: "réussi", status_at: later, done_at: later }],
    new_homework: [{ id: "mac1", child: "amine", subject: "Anglais", task: "vocabulaire", minutes: 10 }],
    reports: [{ id: "r1", child: "amine", date: later, text: "✅ Amine a terminé ses devoirs (30 min).\n…" }],
    difficulties: [{ id: "d1", child: "amine", subject: "Maths", topic: "fractions", detail: "x", date: later }],
  } });
  assert.equal(out.status, 200);
  const synced = out.data.homework.find((x) => x.id === h.id);
  assert.equal(synced.status, "fait");
  assert.ok(out.data.homework.some((x) => x.id === "mac1"));
  assert.equal(pushes.length, 1);
  assert.match(pushes[0].title, /Rapport de devoirs — Amine/);
  // Un rapport renvoyé deux fois n'est notifié qu'une fois
  await call("POST", "sync", { token: mac, body: { reports: [{ id: "r1", child: "amine", date: later, text: "x" }] } });
  assert.equal(pushes.length, 1);
  // Un état plus ancien n'écrase pas le plus récent
  await call("POST", "sync", { token: mac, body: { status_updates: [{ id: h.id, status: "à faire", status_at: "2000-01-01T00:00:00Z" }] } });
  assert.equal((await readJSON("homework", [])).find((x) => x.id === h.id).status, "fait");

  const st = (await call("GET", "state", { token: papa })).data;
  assert.equal(st.children[0].avatar, "🐯");
  assert.equal(st.reports[0].id, "r1");
  assert.ok(st.mac_seen);

  // Secours : le Mac récupère les lectures en attente et renvoie le résultat
  const form = new FormData();
  form.append("photo", new Blob([new Uint8Array([1])], { type: "image/jpeg" }), "a.jpg");
  const { id } = await (await route(new Request(`${BASE}/api/photos`, { method: "POST", body: form, headers: { authorization: `Bearer ${papa}` } }), {})).json();
  const pending = (await call("GET", "jobs?older=0", { token: mac })).data;
  assert.deepEqual(pending.map((j) => j.id), [id]);
  const done = await call("POST", `jobs/${id}/result`, { token: mac, body: {
    child: "ibrahim", confidence: "sûr", remarks: "", items: [{ subject: "Histoire", task: "leçon", due: "", minutes: 10, kind: "leçon" }],
  } });
  assert.equal(done.data.status, "done");
  assert.equal((await call("GET", "jobs?older=0", { token: mac })).data.length, 0);
});

test("erreurs propres", async () => {
  const token = await loginAs("Papa");
  assert.equal((await call("GET", "nimporte", { token })).status, 404);
  assert.equal((await call("PATCH", "homework/zzz", { token, body: {} })).status, 404);
  delete process.env.PARENT_PASSWORD;
  const r = await call("POST", "login", { body: { password: "x" } });
  assert.equal(r.status, 500);
  assert.match(r.data.error, /PARENT_PASSWORD/);
});
