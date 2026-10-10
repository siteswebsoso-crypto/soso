// Connexion par mot de passe familial (variable PARENT_PASSWORD) et jetons signés HMAC.
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { readJSON, writeJSON } from "./store.mjs";

const TOKEN_DAYS = 180;
const MAX_FAILS = 8;
const LOCK_MINUTES = 15;

async function secret() {
  let s = await readJSON("config/secret", null);
  if (!s) {
    s = { value: randomBytes(32).toString("hex") };
    await writeJSON("config/secret", s);
  }
  return s.value;
}

const b64 = (s) => Buffer.from(s).toString("base64url");

export async function sign(payload) {
  const body = b64(JSON.stringify(payload));
  const mac = createHmac("sha256", await secret()).update(body).digest("base64url");
  return `${body}.${mac}`;
}

export async function verify(token) {
  if (!token || !token.includes(".")) return null;
  const [body, mac] = token.split(".");
  const expected = createHmac("sha256", await secret()).update(body).digest("base64url");
  const a = Buffer.from(mac);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;
  const payload = JSON.parse(Buffer.from(body, "base64url").toString());
  return payload.exp > Date.now() ? payload : null;
}

function samePassword(given) {
  const expected = process.env.PARENT_PASSWORD || "";
  if (!expected) return false;
  const a = Buffer.from(String(given));
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/** Renvoie { token, name, role } ou lance une erreur avec un message lisible. */
export async function login({ name, password, device }, ip = "inconnue") {
  if (!process.env.PARENT_PASSWORD) {
    throw httpError(500, "Le mot de passe familial n'est pas configuré sur Netlify (variable PARENT_PASSWORD).");
  }
  const key = `ratelimit/${ip.replace(/[^\w.:-]/g, "_")}`;
  const rl = await readJSON(key, { fails: 0, until: 0 });
  if (rl.until > Date.now()) throw httpError(429, "Trop d'essais. Réessayez dans un quart d'heure.");
  if (!samePassword(password)) {
    rl.fails += 1;
    if (rl.fails >= MAX_FAILS) Object.assign(rl, { fails: 0, until: Date.now() + LOCK_MINUTES * 60_000 });
    await writeJSON(key, rl);
    throw httpError(401, "Mot de passe incorrect.");
  }
  await writeJSON(key, { fails: 0, until: 0 });
  const cleanName = String(name || "Parent").trim().slice(0, 30) || "Parent";
  const role = device ? "mac" : "parent";
  const token = await sign({ name: cleanName, role, exp: Date.now() + TOKEN_DAYS * 86_400_000 });
  return { token, name: cleanName, role };
}

/** Signature des appels internes vers la fonction de fond. */
export const internalSignature = (jobId) =>
  createHmac("sha256", process.env.PARENT_PASSWORD || "").update(`job:${jobId}`).digest("hex");

export function bearer(req) {
  const h = req.headers.get("authorization") || "";
  if (h.startsWith("Bearer ")) return h.slice(7);
  return new URL(req.url).searchParams.get("t");
}

export function httpError(status, message) {
  return Object.assign(new Error(message), { status });
}
