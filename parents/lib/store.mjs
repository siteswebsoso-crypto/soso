// Stockage : Netlify Blobs (cohérence forte). Remplaçable en test par un store en mémoire.
import { getStore } from "@netlify/blobs";

let override = null;

export function setTestStore(store) {
  override = store;
}

export function db() {
  return override ?? getStore({ name: "jarvis-junior", consistency: "strong" });
}

export async function readJSON(key, fallback) {
  const value = await db().get(key, { type: "json" });
  return value ?? fallback;
}

export async function writeJSON(key, value) {
  await db().setJSON(key, value);
}

/** Lecture-modification-écriture d'un document JSON. `fn` modifie la valeur et peut renvoyer un résultat. */
export async function mutate(key, fallback, fn) {
  const value = await readJSON(key, fallback);
  const result = await fn(value);
  await writeJSON(key, value);
  return result;
}

export function newId(bytes = 4) {
  return [...crypto.getRandomValues(new Uint8Array(bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function nowIso() {
  return new Date().toISOString();
}

/** Store en mémoire avec la même interface (tests et développement local). */
export class MemoryStore {
  constructor() {
    this.data = new Map();
  }
  async get(key, { type } = {}) {
    if (!this.data.has(key)) return null;
    const v = this.data.get(key);
    if (type === "json") return JSON.parse(v);
    if (type === "arrayBuffer") return v instanceof Uint8Array ? v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength) : v;
    return v;
  }
  async setJSON(key, value) {
    this.data.set(key, JSON.stringify(value));
  }
  async set(key, value) {
    this.data.set(key, value instanceof ArrayBuffer ? new Uint8Array(value) : value);
  }
  async delete(key) {
    this.data.delete(key);
  }
  async list({ prefix = "" } = {}) {
    return { blobs: [...this.data.keys()].filter((k) => k.startsWith(prefix)).map((key) => ({ key })) };
  }
}
