import { proxyFile } from "@/lib/api";

export const revalidate = 900;
const FILES = new Set(["catalog.jsonld", "all.jsonl"]);

export async function GET(req: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file } = await params;
  if (!FILES.has(file)) return new Response("Não encontrado", { status: 404 });
  return proxyFile(req, `/data/${file}`);
}
