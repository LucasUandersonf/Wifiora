import { proxyFile } from "@/lib/api";

export const revalidate = 900;

export async function GET(req: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return proxyFile(req, `/hub/${encodeURIComponent(slug)}/data.jsonl`, [`hub:${slug}`, "graph"]);
}
