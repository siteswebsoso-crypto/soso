// API de l'espace parents et de la synchronisation du Mac : /api/*
import { bearer, httpError, internalSignature, login, verify } from "../lib/auth.mjs";
import {
  addHomework, addNote, createJob, deleteHomework, forMac, pendingJobs, photo, receiveFromMac, removeNote,
  saveJobResult, state, updateHomework,
} from "../lib/homework.mjs";
import { notifyAll, subscribe, vapidKeys } from "../lib/push.mjs";
import { readJSON } from "../lib/store.mjs";

const MAX_PHOTOS = 6;
const MAX_PHOTO_BYTES = 4_500_000;

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

export async function route(req, { triggerBackground } = {}) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api\/?/, "").replace(/\/$/, "");
  const parts = path.split("/");
  const method = req.method;

  if (method === "POST" && path === "login") {
    const ip = req.headers.get("x-nf-client-connection-ip") || req.headers.get("x-forwarded-for") || "inconnue";
    return json(await login(await req.json(), ip));
  }
  if (method === "GET" && path === "push/key") return json({ publicKey: (await vapidKeys()).publicKey });

  const me = await verify(bearer(req));
  if (!me) throw httpError(401, "Veuillez vous reconnecter.");

  // ---------------------------------------------------------------- site des parents
  if (method === "GET" && path === "state") return json(await state(me));
  if (method === "POST" && path === "homework") return json(await addHomework(await req.json(), me.name));
  if (parts[0] === "homework" && parts[1]) {
    if (method === "PATCH") return json(await updateHomework(parts[1], await req.json()));
    if (method === "DELETE") return json(await deleteHomework(parts[1]) ?? { ok: true });
  }
  if (method === "POST" && path === "notes") {
    const { child, text } = await req.json();
    return json(await addNote(child, text, me.name));
  }
  if (method === "DELETE" && parts[0] === "notes" && parts[1]) {
    await removeNote(parts[1]);
    return json({ ok: true });
  }
  if (method === "POST" && path === "photos") {
    const form = await req.formData();
    const files = form.getAll("photo").filter((f) => typeof f === "object" && f.size);
    if (!files.length) throw httpError(400, "Aucune photo reçue.");
    if (files.length > MAX_PHOTOS) throw httpError(400, `${MAX_PHOTOS} photos maximum à la fois.`);
    const photos = [];
    for (const f of files) {
      if (f.size > MAX_PHOTO_BYTES) throw httpError(413, "Photo trop lourde.");
      const type = /^image\/(jpeg|png|webp|gif)$/.test(f.type) ? f.type : "image/jpeg";
      photos.push({ bytes: new Uint8Array(await f.arrayBuffer()), type });
    }
    const job = await createJob({ photos, caption: form.get("caption") || "", child: form.get("child") || "", by: me.name });
    if (triggerBackground) await triggerBackground(job.id, url.origin);
    return json({ id: job.id, status: job.status }, 202);
  }
  if (method === "GET" && parts[0] === "jobs" && parts[1]) {
    const job = await readJSON(`jobs/${parts[1]}`, null);
    if (!job) throw httpError(404, "Tâche introuvable.");
    return json(job);
  }
  if (method === "GET" && parts[0] === "photo") {
    const p = await photo(parts.slice(1).join("/"));
    if (!p) throw httpError(404, "Photo introuvable.");
    return new Response(p.data, { headers: { "content-type": p.type, "cache-control": "private, max-age=86400" } });
  }
  if (method === "POST" && path === "push/subscribe") {
    await subscribe(me.name, (await req.json()).subscription);
    return json({ ok: true });
  }
  if (method === "POST" && path === "push/test") {
    const sent = await notifyAll({ title: "🔔 Jarvis Junior", body: "Les notifications fonctionnent !", url: "/" });
    return json({ sent });
  }

  // ---------------------------------------------------------------- Mac
  if (path === "sync") {
    if (method === "GET") return json(await forMac());
    if (method === "POST") return json(await receiveFromMac(await req.json()));
  }
  if (method === "GET" && path === "jobs") {
    return json(await pendingJobs(Number(url.searchParams.get("older") || 0)));
  }
  if (method === "POST" && parts[0] === "jobs" && parts[2] === "result") {
    return json(await saveJobResult(parts[1], await req.json()));
  }
  throw httpError(404, "Route inconnue.");
}

async function triggerBackground(jobId, origin) {
  try {
    await fetch(`${origin}/.netlify/functions/extract-background`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-jarvis-signature": internalSignature(jobId) },
      body: JSON.stringify({ id: jobId }),
    });
  } catch (err) {
    console.error("déclenchement de la lecture impossible (le Mac prendra le relais)", err);
  }
}

export default async (req) => {
  try {
    return await route(req, { triggerBackground });
  } catch (err) {
    if (!err.status) console.error(err);
    return json({ error: err.status ? err.message : "Erreur interne du serveur." }, err.status || 500);
  }
};

export const config = { path: "/api/*" };
