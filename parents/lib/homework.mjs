// Devoirs, consignes, rapports, lecture des photos et synchronisation avec le Mac.
import Anthropic from "@anthropic-ai/sdk";
import { db, mutate, newId, nowIso, readJSON, writeJSON } from "./store.mjs";
import { notifyAll } from "./push.mjs";

export const DEFAULT_CHILDREN = [
  { id: "amine", name: "Amine", grade: "CM2", level: "CM2 (cycle 3, école élémentaire)", avatar: "🦁", color: "#ff8a3d" },
  { id: "ibrahim", name: "Ibrahim", grade: "5e", level: "5e (cycle 4, collège)", avatar: "🚀", color: "#3d8bff" },
];
const KINDS = ["exercice", "leçon", "récitation", "lecture", "rédaction", "révision contrôle", "autre"];
const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const TOMBSTONE_DAYS = 30;

export const children = () => readJSON("children", DEFAULT_CHILDREN);

export async function childById(ref) {
  const r = String(ref || "").trim().toLowerCase();
  return (await children()).find((c) => c.id === r || c.name.toLowerCase() === r) || null;
}

const isoDate = (v) => (/^\d{4}-\d{2}-\d{2}$/.test(v || "") ? v : null);

function cleanItem(fields, by) {
  const now = nowIso();
  return {
    id: fields.id || newId(),
    child: String(fields.child || "inconnu"),
    subject: String(fields.subject || "").slice(0, 80),
    task: String(fields.task || "").slice(0, 500),
    due: isoDate(fields.due),
    minutes: Math.max(1, Math.min(240, parseInt(fields.minutes, 10) || 15)),
    kind: KINDS.includes(fields.kind) ? fields.kind : "exercice",
    status: ["à faire", "fait", "partiel"].includes(fields.status) ? fields.status : "à faire",
    comment: String(fields.comment || ""),
    photo: fields.photo || null,
    by: by || fields.by || "",
    added: fields.added || now,
    updated_at: now,
    status_at: fields.status_at || now,
    done_at: fields.done_at || null,
    deleted: false,
  };
}

// ------------------------------------------------------------------ devoirs

export async function addHomework(fields, by) {
  if (!fields.subject || !fields.task) throw Object.assign(new Error("Matière et consigne obligatoires"), { status: 400 });
  const item = cleanItem(fields, by);
  await mutate("homework", [], (list) => { list.push(item); });
  return item;
}

export async function updateHomework(id, fields) {
  return mutate("homework", [], (list) => {
    const h = list.find((x) => x.id === id && !x.deleted);
    if (!h) throw Object.assign(new Error("Devoir introuvable"), { status: 404 });
    for (const k of ["child", "subject", "task", "comment"]) if (k in fields) h[k] = String(fields[k]);
    if ("due" in fields) h.due = isoDate(fields.due);
    if ("minutes" in fields) h.minutes = Math.max(1, Math.min(240, parseInt(fields.minutes, 10) || h.minutes));
    if ("kind" in fields && KINDS.includes(fields.kind)) h.kind = fields.kind;
    if ("status" in fields && ["à faire", "fait", "partiel"].includes(fields.status)) {
      h.status = fields.status;
      h.status_at = nowIso();
      h.done_at = fields.status === "fait" ? nowIso() : null;
    }
    h.updated_at = nowIso();
    return h;
  });
}

export async function deleteHomework(id) {
  return mutate("homework", [], (list) => {
    const h = list.find((x) => x.id === id);
    if (!h) throw Object.assign(new Error("Devoir introuvable"), { status: 404 });
    Object.assign(h, { deleted: true, updated_at: nowIso() });
  });
}

// ------------------------------------------------------------------ consignes

export async function addNote(child, text, by) {
  if (!String(text || "").trim()) throw Object.assign(new Error("Consigne vide"), { status: 400 });
  const note = { id: newId(), child: child || "tous", text: String(text).slice(0, 500), author: by, date: nowIso(), active: true };
  await mutate("notes", [], (list) => { list.push(note); });
  return note;
}

export async function removeNote(id) {
  await mutate("notes", [], (list) => {
    const n = list.find((x) => x.id === id);
    if (n) Object.assign(n, { active: false, updated_at: nowIso() });
  });
}

// ------------------------------------------------------------------ état pour le site

export async function state(me) {
  const [kids, homework, notes, reports, difficulties, mac] = await Promise.all([
    children(), readJSON("homework", []), readJSON("notes", []), readJSON("reports", []),
    readJSON("difficulties", []), readJSON("mac", null),
  ]);
  return {
    me,
    children: kids,
    homework: homework.filter((h) => !h.deleted && (h.status !== "fait" || recent(h.done_at, 3))),
    notes: notes.filter((n) => n.active),
    reports: reports.slice(-60).reverse(),
    difficulties: difficulties.slice(-100).reverse(),
    mac_seen: mac?.seen || null,
  };
}

const recent = (iso, days) => iso && Date.now() - Date.parse(iso) < days * 86_400_000;

// ------------------------------------------------------------------ photos → devoirs

export const EXTRACTION_SCHEMA = {
  type: "object",
  properties: {
    child: { type: "string", description: "Identifiant de l'enfant concerné, ou 'inconnu'" },
    confidence: { type: "string", enum: ["sûr", "probable", "incertain"] },
    items: {
      type: "array",
      items: {
        type: "object",
        properties: {
          subject: { type: "string", description: "Matière, ex : Mathématiques, Français, Anglais" },
          task: { type: "string", description: "Consigne précise, avec pages et numéros d'exercices" },
          due: { type: "string", description: "Date de rendu AAAA-MM-JJ, ou chaîne vide si inconnue" },
          minutes: { type: "integer", description: "Durée estimée pour un élève de ce niveau" },
          kind: { type: "string", enum: KINDS },
        },
        required: ["subject", "task", "due", "minutes", "kind"],
        additionalProperties: false,
      },
    },
    remarks: { type: "string", description: "Ce qui est illisible ou ambigu, sinon chaîne vide" },
  },
  required: ["child", "confidence", "items", "remarks"],
  additionalProperties: false,
};

export function extractionPrompt(kids, caption, today = new Date()) {
  const list = kids.map((c) => `- id « ${c.id} » : ${c.name}, classe de ${c.level || c.grade}`).join("\n");
  const d = today.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris" });
  return `Voici une ou plusieurs photos des devoirs d'un enfant (cahier de textes, agenda, Pronote, ENT, fiche de la maîtresse…). Nous sommes le ${WEEKDAYS[today.getDay()]} ${d}.

Enfants de la famille :
${list}

Légende écrite par le parent : « ${caption || "aucune"} »

1. Détermine l'enfant concerné : d'abord d'après la légende ; sinon d'après le niveau des devoirs (programme de CM2 ou de collège, nom de professeur, format Pronote…). Si tu ne peux pas trancher, mets « inconnu ».
2. Liste chaque devoir séparément, avec la consigne exacte (pages, numéros d'exercices, titre de la poésie…). Convertis les dates relatives (« pour jeudi ») en dates AAAA-MM-JJ à venir.
3. Estime une durée réaliste pour un enfant de ce niveau qui travaille sérieusement.
4. Ignore ce qui est déjà barré ou coché comme fait.`;
}

let testClient = null;
export function setTestClient(c) {
  testClient = c;
}

export async function extractWithClaude(images, caption) {
  const client = testClient ?? new Anthropic();
  const kids = await children();
  const response = await client.beta.messages.create({
    model: process.env.CLAUDE_MODEL || "claude-opus-5-5",
    max_tokens: 8000,
    messages: [{
      role: "user",
      content: [
        ...images.map((img) => ({ type: "image", source: { type: "base64", media_type: img.type, data: img.data } })),
        { type: "text", text: extractionPrompt(kids, caption) },
      ],
    }],
    output_config: { effort: "medium", format: { type: "json_schema", schema: EXTRACTION_SCHEMA } },
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
  });
  if (response.stop_reason === "refusal") throw new Error("Claude n'a pas pu analyser cette image.");
  const text = response.content.find((b) => b.type === "text")?.text;
  return JSON.parse(text);
}

export async function createJob({ photos, caption, child, by }) {
  const id = newId(6);
  const keys = [];
  for (const [i, p] of photos.entries()) {
    const key = `photos/${id}-${i}`;
    await db().set(key, p.bytes, { metadata: { type: p.type } });
    await writeJSON(`${key}.meta`, { type: p.type });
    keys.push(key);
  }
  const job = { id, by, caption: caption || "", child: child || "", photos: keys, status: "pending", created: nowIso() };
  await writeJSON(`jobs/${id}`, job);
  await mutate("jobs-index", [], (ids) => { ids.push(id); ids.splice(0, Math.max(0, ids.length - 100)); });
  return job;
}

export async function photo(key) {
  const meta = await readJSON(`${key}.meta`, { type: "image/jpeg" });
  const data = await db().get(key, { type: "arrayBuffer" });
  return data ? { data, type: meta.type } : null;
}

export async function pendingJobs(olderThanSeconds = 0) {
  const ids = await readJSON("jobs-index", []);
  const jobs = await Promise.all(ids.map((id) => readJSON(`jobs/${id}`, null)));
  const limit = Date.now() - olderThanSeconds * 1000;
  return jobs.filter((j) => j && j.status === "pending" && Date.parse(j.created) <= limit);
}

/** Lit les photos d'une tâche avec Claude (fonction de fond Netlify). */
export async function processJob(id) {
  const job = await readJSON(`jobs/${id}`, null);
  if (!job || job.status !== "pending") return job;
  try {
    const images = [];
    for (const key of job.photos) {
      const p = await photo(key);
      images.push({ type: p.type, data: Buffer.from(p.data).toString("base64") });
    }
    const caption = [job.child && `enfant : ${job.child}`, job.caption].filter(Boolean).join(" — ");
    return await saveJobResult(id, await extractWithClaude(images, caption));
  } catch (err) {
    console.error("extraction", err);
    job.status = "error";
    job.message = `Je n'ai pas réussi à lire la photo (${err.message}).`;
    await writeJSON(`jobs/${id}`, job);
    return job;
  }
}

/** Enregistre le résultat d'une lecture (faite par Netlify ou, en secours, par le Mac). */
export async function saveJobResult(id, result) {
  const job = await readJSON(`jobs/${id}`, null);
  if (!job) throw Object.assign(new Error("Tâche introuvable"), { status: 404 });
  if (job.status === "done") return job;
  const forced = job.child && (await childById(job.child));
  const child = forced || (await childById(result.child));
  const items = [];
  for (const it of result.items || []) {
    items.push(cleanItem({ ...it, child: child ? child.id : "inconnu", photo: job.photos[0] }, job.by));
  }
  if (items.length) await mutate("homework", [], (list) => { list.push(...items); });
  Object.assign(job, {
    status: "done",
    finished: nowIso(),
    child: child ? child.id : "inconnu",
    guessed: !forced && result.confidence !== "sûr" && !job.caption,
    remarks: result.remarks || "",
    items: items.map((h) => h.id),
  });
  await writeJSON(`jobs/${id}`, job);
  if (items.length) {
    const who = child ? de(child.name) : "d'un des enfants";
    const total = items.reduce((s, h) => s + h.minutes, 0);
    await notifyAll({
      title: `📚 Devoirs ${who}`,
      body: `${job.by} a envoyé ${items.length} devoir${items.length > 1 ? "s" : ""} (~${total} min) : ${items.map((h) => h.subject).join(", ")}`,
      url: "/#devoirs",
    }, job.by);
  }
  return job;
}

export const de = (name) => (/^[aeiouyhéèêâîôû]/i.test(name) ? `d'${name}` : `de ${name}`);

// ------------------------------------------------------------------ synchronisation avec le Mac

/**
 * Le Mac envoie : enfants, changements d'état des devoirs, devoirs créés sur le Mac, rapports, difficultés.
 * Règle : pour l'état d'un devoir, le changement le plus récent (status_at) l'emporte.
 */
export async function receiveFromMac(body) {
  if (Array.isArray(body.children) && body.children.length) {
    await writeJSON("children", body.children.map((c) => ({
      id: String(c.id), name: String(c.name), grade: String(c.grade || ""), level: String(c.level || c.grade || ""),
      avatar: String(c.avatar || "🙂"), color: String(c.color || "#7c5cff"),
    })));
  }
  await mutate("homework", [], (list) => {
    for (const u of body.status_updates || []) {
      const h = list.find((x) => x.id === u.id);
      if (h && (!h.status_at || u.status_at > h.status_at)) {
        Object.assign(h, { status: u.status, comment: u.comment || "", done_at: u.done_at || null, status_at: u.status_at, updated_at: nowIso() });
      }
    }
    for (const n of body.new_homework || []) {
      if (!list.some((x) => x.id === n.id)) list.push(cleanItem(n, n.by || "Mac"));
    }
    for (const id of body.deleted || []) {
      const h = list.find((x) => x.id === id);
      if (h) Object.assign(h, { deleted: true, updated_at: nowIso() });
    }
    const cutoff = Date.now() - TOMBSTONE_DAYS * 86_400_000;
    list.splice(0, list.length, ...list.filter((h) => !(h.deleted || h.status === "fait") || Date.parse(h.updated_at) > cutoff));
  });
  if (body.difficulties?.length) {
    await mutate("difficulties", [], (list) => {
      for (const d of body.difficulties) if (!list.some((x) => x.id === d.id)) list.push(d);
      list.splice(0, Math.max(0, list.length - 500));
    });
  }
  const fresh = [];
  if (body.reports?.length) {
    await mutate("reports", [], (list) => {
      for (const r of body.reports) {
        if (!list.some((x) => x.id === r.id)) {
          list.push(r);
          fresh.push(r);
        }
      }
      list.splice(0, Math.max(0, list.length - 300));
    });
  }
  const kids = await children();
  for (const r of fresh) {
    const name = kids.find((c) => c.id === r.child)?.name || r.child;
    await notifyAll({ title: `📚 Rapport de devoirs — ${name}`, body: r.text.split("\n")[0], url: `/#rapport-${r.id}` });
  }
  await writeJSON("mac", { seen: nowIso() });
  return forMac();
}

export async function forMac() {
  const [homework, notes] = await Promise.all([readJSON("homework", []), readJSON("notes", [])]);
  return { homework, notes, server_time: nowIso() };
}
