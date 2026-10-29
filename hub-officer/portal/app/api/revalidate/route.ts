import { revalidatePath, revalidateTag } from "next/cache";
import { timingSafeEqual } from "node:crypto";

// Chamado pelo backend quando o escritório publica/atualiza um hub (ISR sob demanda).
export async function POST(req: Request) {
  const secret = process.env.REVALIDATE_SECRET || "";
  const given = req.headers.get("x-revalidate-secret") || "";
  const ok = secret.length > 0 && given.length === secret.length && timingSafeEqual(Buffer.from(given), Buffer.from(secret));
  if (!ok) return Response.json({ ok: false }, { status: 401 });
  const body = (await req.json().catch(() => ({}))) as { paths?: unknown };
  const paths = Array.isArray(body.paths) ? body.paths.filter((p): p is string => typeof p === "string" && p.startsWith("/")).slice(0, 500) : [];
  // Invalida a página e também os dados em cache por trás dela (tags usadas em lib/api.ts).
  const tags = new Set<string>(["site", "graph"]);
  for (const p of paths) {
    revalidatePath(p);
    const m = p.match(/^\/hub\/([^/]+)/);
    if (m) tags.add(`hub:${m[1]}`);
    if (!p.startsWith("/hub")) tags.add("institutional");
  }
  for (const t of tags) revalidateTag(t);
  return Response.json({ ok: true, revalidated: paths.length, tags: [...tags] });
}
