import type { Metadata } from "next";
import Link from "next/link";
import { Crumbs, JsonLd } from "@/components/SiteChrome";
import { getConceptsPage, type Concept } from "@/lib/api";

export const revalidate = 3600;
export const metadata: Metadata = {
  title: "Empresas e conceitos",
  description: "Mapa dos conceitos, integrações e empresas cobertos pelos comparativos, com links para cada produto.",
  alternates: { canonical: "/conceitos" },
};

function Terms({ title, items }: { title: string; items: Concept[] }) {
  if (!items.length) return null;
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-xl font-semibold">{title}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {items.map((c) => (
          <div key={c.slug} id={c.slug} className="scroll-mt-20 rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <h3 className="font-semibold">{c.label} <span className="muted text-sm font-normal">· {c.products.length} produto(s)</span></h3>
            <p className="mt-1 text-sm">{c.products.map((p, i) => <span key={p.url}>{i > 0 && " · "}<Link href={`/hub/${p.hub}/${p.slug}`}>{p.name}</Link></span>)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default async function Concepts() {
  const data = await getConceptsPage();
  return (
    <>
      {data && <JsonLd doc={data.jsonld} />}
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Empresas e conceitos" }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">Empresas e conceitos</h1>
      <p className="muted mt-2 max-w-prose">
        Cada termo liga os produtos que o oferecem. Os mesmos identificadores aparecem no <a href="/knowledge-graph.jsonld">grafo completo</a>.
      </p>
      {!data || (!data.concepts.length && !data.integrations.length && !data.orgs.length) ? (
        <p className="muted mt-6">Nada publicado ainda.</p>
      ) : (
        <>
          <Terms title="Integrações" items={data.integrations} />
          <Terms title="Conceitos" items={data.concepts} />
          {data.orgs.length > 0 && (
            <section className="mt-8">
              <h2 className="mb-3 text-xl font-semibold">Empresas</h2>
              <ul className="list-disc space-y-1 pl-5">
                {data.orgs.map((o) => <li key={o.slug}><Link href={`/empresa/${o.slug}`}>{o.name}</Link> <span className="muted text-sm">— {o.products} produto(s)</span></li>)}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  );
}
