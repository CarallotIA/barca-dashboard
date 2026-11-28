// Intermediari d'àudio per a la descàrrega sense connexió dels podcasts que no permeten baixar-los des del navegador (CORS).
// Només serveix fitxers d'àudio dels servidors de la llista blanca, i només a aquesta web. No desa res.
export const config = { runtime: "edge" };

const ALLOWED_HOSTS = ["traffic.omny.fm"];                       // RAC1 · Tu diràs
const ALLOWED_ORIGINS = ["barca-dashboard-bay.vercel.app", "localhost", "127.0.0.1"];

export default async function handler(req) {
  const url = new URL(req.url);
  const origin = req.headers.get("origin") || req.headers.get("referer") || "";
  let oh = "";
  try { oh = new URL(origin).hostname; } catch (_) {}
  if (oh && !ALLOWED_ORIGINS.includes(oh)) return new Response("Forbidden", { status: 403 });

  let target;
  try { target = new URL(url.searchParams.get("u") || ""); } catch (_) { return new Response("Bad request", { status: 400 }); }
  if (target.protocol !== "https:" || !ALLOWED_HOSTS.includes(target.hostname)) return new Response("Host not allowed", { status: 403 });

  const headers = {};
  const range = req.headers.get("range");
  if (range) headers["range"] = range;
  const up = await fetch(target.toString(), { headers, redirect: "follow" });
  const out = new Headers();
  for (const h of ["content-type", "content-length", "accept-ranges", "content-range", "etag", "last-modified"]) {
    const v = up.headers.get(h);
    if (v) out.set(h, v);
  }
  out.set("access-control-allow-origin", oh ? origin.replace(/\/$/, "").split("/").slice(0, 3).join("/") : "*");
  out.set("access-control-expose-headers", "content-length, content-range, accept-ranges");
  out.set("vary", "origin");
  out.set("cache-control", "private, no-store");
  return new Response(up.body, { status: up.status, headers: out });
}
