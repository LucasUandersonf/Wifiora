import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

// Avisa o backend quando um robô de IA lê o portal (painel "Dados para IAs"). Não atrasa a resposta.
const AI_BOTS = /GPTBot|OAI-SearchBot|ChatGPT-User|ClaudeBot|Claude-SearchBot|Claude-User|PerplexityBot|Perplexity-User|Google-Extended|Google-CloudVertexBot|Googlebot|bingbot|Applebot|meta-externalagent|FacebookBot|Amazonbot|Bytespider|CCBot|cohere-ai|DuckAssistBot|MistralAI-User/i;

export function middleware(req: NextRequest, event: NextFetchEvent) {
  const ua = req.headers.get("user-agent") || "";
  const secret = process.env.REVALIDATE_SECRET;
  const api = (process.env.API_URL || "").replace(/\/$/, "");
  if (secret && api && AI_BOTS.test(ua)) {
    event.waitUntil(
      fetch(`${api}/api/public/bot-hit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Beacon-Secret": secret },
        body: JSON.stringify({ user_agent: ua.slice(0, 500), path: req.nextUrl.pathname.slice(0, 300) }),
      }).catch(() => undefined),
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/|api/|favicon.ico).*)"],
};
