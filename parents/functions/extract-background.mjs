// Fonction de fond Netlify (jusqu'à 15 min) : lit les photos de devoirs avec Claude.
import { timingSafeEqual } from "node:crypto";
import { internalSignature } from "../lib/auth.mjs";
import { processJob } from "../lib/homework.mjs";

export default async (req) => {
  const { id } = await req.json();
  const given = Buffer.from(req.headers.get("x-jarvis-signature") || "");
  const expected = Buffer.from(internalSignature(String(id)));
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return new Response("refusé", { status: 403 });
  }
  await processJob(String(id));
  return new Response("ok");
};
