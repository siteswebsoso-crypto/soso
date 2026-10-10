// Notifications sur le téléphone (Web Push). Les clés VAPID sont créées automatiquement au premier usage.
import webpush from "web-push";
import { mutate, readJSON, writeJSON } from "./store.mjs";

let sender = null; // remplaçable en test

export function setTestSender(fn) {
  sender = fn;
}

export async function vapidKeys() {
  let keys = await readJSON("config/vapid", null);
  if (!keys) {
    keys = webpush.generateVAPIDKeys();
    await writeJSON("config/vapid", keys);
  }
  return keys;
}

export async function subscribe(name, subscription) {
  if (!subscription?.endpoint) throw new Error("Abonnement invalide");
  await mutate("push", [], (subs) => {
    const i = subs.findIndex((s) => s.subscription.endpoint === subscription.endpoint);
    const entry = { name, subscription, added: new Date().toISOString() };
    if (i >= 0) subs[i] = entry;
    else subs.push(entry);
  });
}

/** Envoie une notification à tous les téléphones abonnés (sauf, éventuellement, ceux de `exceptName`). */
export async function notifyAll({ title, body, url = "/" }, exceptName = null) {
  const subs = await readJSON("push", []);
  const targets = subs.filter((s) => s.name !== exceptName);
  if (!targets.length) return 0;
  const keys = await vapidKeys();
  const subject = process.env.VAPID_SUBJECT || "mailto:parents@jarvis-junior.app";
  const payload = JSON.stringify({ title, body, url });
  const dead = [];
  let sent = 0;
  await Promise.all(targets.map(async (s) => {
    try {
      if (sender) await sender(s.subscription, payload);
      else {
        await webpush.sendNotification(s.subscription, payload, {
          vapidDetails: { subject, publicKey: keys.publicKey, privateKey: keys.privateKey },
          TTL: 86400,
        });
      }
      sent += 1;
    } catch (err) {
      if (err?.statusCode === 404 || err?.statusCode === 410) dead.push(s.subscription.endpoint);
      else console.error("push", err?.statusCode, err?.body || err?.message);
    }
  }));
  if (dead.length) await mutate("push", [], (all) => { all.splice(0, all.length, ...all.filter((s) => !dead.includes(s.subscription.endpoint))); });
  return sent;
}
