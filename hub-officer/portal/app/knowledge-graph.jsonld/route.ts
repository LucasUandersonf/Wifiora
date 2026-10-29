import { proxyFile } from "@/lib/api";

export const revalidate = 900;
export const GET = (req: Request) => proxyFile(req, "/knowledge-graph.jsonld");
