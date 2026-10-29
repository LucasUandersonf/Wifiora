// Cliente da API pública do backend (FastAPI). Todas as páginas são geradas a partir destes payloads,
// com cache ISR: regeneradas a cada hora ou na hora em que o escritório publica (POST /api/revalidate).

export const API_URL = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
export const SITE_URL = (process.env.SITE_URL || "http://localhost:3000").replace(/\/$/, "");
export const REVALIDATE_SECONDS = 3600;

export type FooterLink = { label: string; href: string };
export type HubCard = { slug: string; title: string; niche: string; description: string; demo_data: boolean; updated_at: string };
export type Site = { brand: string; base_url: string; footer_links: FooterLink[]; hubs: HubCard[]; institutional: string[] };

export type HubInfo = { slug: string; title: string; niche: string; description: string; demo_data: boolean; updated_at: string | null; published_at: string | null };
export type EntitySummary = {
  slug: string;
  name: string;
  attributes: Record<string, unknown>;
  source_url: string | null;
  verified_at: string | null;
  human_reviewed: boolean;
  grounding_ratio: number;
  criteria_met: number;
  criteria_total: number;
  version: number;
};
export type HubPage = {
  hub: HubInfo;
  page: { meta_description: string; faq: { q: string; a: string }[]; sections: string[] };
  columns: string[];
  criteria: string[];
  entities: EntitySummary[];
  changes: { entity: string; version: number; fields: string[]; at: string }[];
  rankings: Ranking[];
  jsonld: Record<string, unknown>;
};
export type Ranking = {
  key: string;
  title: string;
  order: "asc" | "desc";
  method: string;
  items: { position: number; slug: string; name: string; value_label: string }[];
  missing: string[];
};
export type EntityPage = {
  hub: HubInfo;
  entity: EntitySummary & {
    schema_type: string;
    sources: { url: string; quote?: string; retrieved_at?: string }[];
    provider: { razao_social?: string; nome_fantasia?: string; cnpj?: string; municipio?: string; uf?: string };
    org_slug: string | null;
    human_reviewed_by: string | null;
    human_reviewed_at: string | null;
    criteria: { label: string; passed: boolean | null }[];
  };
  versions: { version: number; fields: string[]; at: string }[];
  jsonld: Record<string, unknown>;
};
export type InstitutionalPage = {
  slug: string;
  title: string;
  description: string;
  draft?: boolean;
  form?: "correction";
  company_configured: boolean;
  sections: { h?: string; p?: string[]; list?: string[] }[];
};

async function get<T>(path: string, tags: string[] = []): Promise<T | null> {
  const res = await fetch(API_URL + path, { next: { revalidate: REVALIDATE_SECONDS, tags } });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status} em ${path}`);
  return (await res.json()) as T;
}

const FALLBACK_SITE: Site = {
  brand: "Hub Semântico",
  base_url: SITE_URL,
  footer_links: [
    { label: "Sobre", href: "/sobre" },
    { label: "Metodologia", href: "/metodologia" },
    { label: "Política editorial", href: "/politica-editorial" },
    { label: "Solicitar correção", href: "/correcoes" },
    { label: "Termos de uso", href: "/termos" },
    { label: "Privacidade", href: "/privacidade" },
  ],
  hubs: [],
  institutional: ["sobre", "metodologia", "politica-editorial", "termos", "privacidade", "correcoes"],
};

/** Dados do site. Se o backend estiver fora do ar no build, usa o básico (as páginas se regeneram depois). */
export async function getSite(): Promise<Site> {
  try {
    return (await get<Site>("/api/public/site", ["site"])) ?? FALLBACK_SITE;
  } catch {
    return FALLBACK_SITE;
  }
}

export const getHubPage = (slug: string) => get<HubPage>(`/api/public/pages/hub/${encodeURIComponent(slug)}`, [`hub:${slug}`]);
export const getEntityPage = (slug: string, entity: string) =>
  get<EntityPage>(`/api/public/pages/entity/${encodeURIComponent(slug)}/${encodeURIComponent(entity)}`, [`hub:${slug}`]);
export type ProductRef = { hub: string; hub_title: string; slug: string; name: string; url: string; demo_data: boolean };
export type OrgPage = {
  org: { slug: string; name: string; legal_name: string | null; cnpj: string | null; city: string | null; uf: string | null; site: string | null; wikidata: string | null };
  products: ProductRef[];
  concepts: string[];
  integrations: string[];
  demo_data: boolean;
  jsonld: Record<string, unknown>;
};
export type Concept = { slug: string; label: string; kind: "concept" | "integration"; products: ProductRef[]; orgs: string[] };
export type ConceptsPage = { concepts: Concept[]; integrations: Concept[]; orgs: { slug: string; name: string; products: number }[]; jsonld: Record<string, unknown> };
export type DataFile = { name: string; url: string; format: string };
export type DataPage = {
  license: string;
  site_files: DataFile[];
  hubs: { slug: string; title: string; records: number; demo_data: boolean; updated_at: string | null; files: DataFile[] }[];
  jsonld: Record<string, unknown>;
};

// Páginas do grafo dependem de todos os hubs: tag "graph" é invalidada a cada publicação.
export const getOrgPage = (slug: string) => get<OrgPage>(`/api/public/pages/org/${encodeURIComponent(slug)}`, ["graph"]);
export const getConceptsPage = () => get<ConceptsPage>("/api/public/pages/concepts", ["graph"]);
export const getDataPage = () => get<DataPage>("/api/public/pages/data", ["graph"]);
export const slugify = (text: string) =>
  text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "item";

export const getInstitutional = (slug: string) => get<InstitutionalPage>(`/api/public/pages/institutional/${encodeURIComponent(slug)}`, ["institutional"]);

/** Proxy de arquivos de texto do backend (sitemap, llms.txt, robots). */
export async function proxyText(path: string, contentType: string): Promise<Response> {
  try {
    const res = await fetch(API_URL + path, { next: { revalidate: REVALIDATE_SECONDS } });
    if (!res.ok) return new Response("Indisponível", { status: res.status });
    return new Response(await res.text(), { headers: { "Content-Type": contentType, "Cache-Control": "public, max-age=300" } });
  } catch {
    return new Response("Backend indisponível", { status: 503 });
  }
}

/** Arquivos de dados em lote (JSON, JSONL, CSV, JSON-LD): repassa ETag/licença/CORS e responde 304. */
export async function proxyFile(req: Request, path: string, tags: string[] = ["graph"]): Promise<Response> {
  try {
    const res = await fetch(API_URL + path, { next: { revalidate: 900, tags } });
    if (!res.ok) return new Response(res.status === 404 ? "Não encontrado" : "Indisponível", { status: res.status });
    const headers = new Headers({
      "Content-Type": res.headers.get("content-type") || "application/octet-stream",
      "Cache-Control": "public, max-age=900, stale-while-revalidate=86400",
      "Access-Control-Allow-Origin": "*",
      Link: '<https://creativecommons.org/licenses/by/4.0/>; rel="license"',
    });
    for (const h of ["etag", "last-modified"]) {
      const v = res.headers.get(h);
      if (v) headers.set(h, v);
    }
    const etag = headers.get("etag");
    if (etag && (req.headers.get("if-none-match") || "").split(",").map((t) => t.trim()).includes(etag)) {
      return new Response(null, { status: 304, headers });
    }
    return new Response(await res.arrayBuffer(), { headers });
  } catch {
    return new Response("Backend indisponível", { status: 503 });
  }
}

// ------------------------------------------------------------------ formatação pt-BR
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (typeof v === "number") return v.toLocaleString("pt-BR", { maximumFractionDigits: 2, minimumFractionDigits: Number.isInteger(v) ? 0 : 2 });
  return String(v);
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
}
export const label = (field: string) => field.replace(/_/g, " ");
export const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};
/** Serializa JSON-LD com segurança para dentro de <script>. */
export const jsonLd = (doc: unknown) => JSON.stringify(doc).replace(/</g, "\\u003c");
