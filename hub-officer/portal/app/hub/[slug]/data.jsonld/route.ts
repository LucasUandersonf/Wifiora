import { getHubPage } from "@/lib/api";

export const revalidate = 3600;

export async function GET(_req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const data = await getHubPage(slug);
  if (!data) return new Response("Não encontrado", { status: 404 });
  return new Response(JSON.stringify(data.jsonld), { headers: { "Content-Type": "application/ld+json; charset=utf-8", "Cache-Control": "public, max-age=300" } });
}
