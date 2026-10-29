import { API_URL } from "@/lib/api";

/** Repassa um formulário ao backend preservando o IP do visitante (usado no limite anti-spam). */
export async function forward(req: Request, path: string): Promise<Response> {
  const body = await req.text();
  if (body.length > 20_000) return Response.json({ detail: "envio grande demais" }, { status: 413 });
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "";
  try {
    const res = await fetch(API_URL + path, { method: "POST", headers: { "Content-Type": "application/json", ...(ip ? { "X-Forwarded-For": ip } : {}) }, body, cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? "Confira os campos e tente de novo." : data.detail;
    return Response.json(res.ok ? { ok: true } : { detail }, { status: res.status });
  } catch {
    return Response.json({ detail: "Serviço indisponível. Tente de novo em instantes." }, { status: 503 });
  }
}
