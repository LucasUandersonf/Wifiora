import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Crumbs, JsonLd } from "@/components/SiteChrome";
import { getOrgPage, slugify } from "@/lib/api";

export const revalidate = 3600;
export const dynamicParams = true;
export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const data = await getOrgPage(slug);
  if (!data) return {};
  return {
    title: data.org.name,
    description: `${data.org.name}: produtos, integrações e dados cadastrais verificados.`,
    alternates: { canonical: `/empresa/${slug}` },
    robots: data.demo_data ? { index: false, follow: false } : { index: true, follow: true },
  };
}

export default async function OrgPage({ params }: Props) {
  const { slug } = await params;
  const data = await getOrgPage(slug);
  if (!data) notFound();
  const { org, products, concepts, integrations } = data;
  const rows: [string, React.ReactNode][] = [
    ["Razão social", org.legal_name],
    ["CNPJ", org.cnpj],
    ["Sede", org.city || org.uf ? `${org.city ?? ""}${org.uf ? "/" + org.uf : ""}` : null],
    ["Site oficial", org.site ? <a href={org.site} rel="nofollow noopener">{org.site}</a> : null],
    ["Wikidata", org.wikidata ? <a href={`https://www.wikidata.org/wiki/${org.wikidata}`} rel="noopener">{org.wikidata}</a> : null],
  ];
  return (
    <article>
      <JsonLd doc={data.jsonld} />
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Empresas e conceitos", href: "/conceitos" }, { name: org.name }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">{org.name}</h1>
      {data.demo_data && <p className="notice"><strong>Dados de demonstração</strong> (empresa fictícia).</p>}
      <table className="tbl mt-6 w-full max-w-2xl text-sm">
        <tbody>
          {rows.filter(([, v]) => v).map(([k, v]) => (
            <tr key={k}><th scope="row" className="w-1/3 font-medium text-ink-soft dark:text-slate-400">{k}</th><td>{v}</td></tr>
          ))}
        </tbody>
      </table>
      <section className="mt-8">
        <h2 className="mb-2 text-xl font-semibold">Produtos</h2>
        <ul className="list-disc space-y-1 pl-5">
          {products.map((p) => (
            <li key={p.url}><Link href={`/hub/${p.hub}/${p.slug}`}>{p.name}</Link> <span className="muted text-sm">— {p.hub_title}</span></li>
          ))}
        </ul>
      </section>
      {integrations.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-2 text-xl font-semibold">Integrações</h2>
          <p>{integrations.map((i, n) => <span key={i}>{n > 0 && " · "}<Link href={`/conceitos#${slugify(i)}`}>{i}</Link></span>)}</p>
        </section>
      )}
      {concepts.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-2 text-xl font-semibold">Conceitos</h2>
          <p>{concepts.map((c, n) => <span key={c}>{n > 0 && " · "}<Link href={`/conceitos#${slugify(c)}`}>{c}</Link></span>)}</p>
        </section>
      )}
      <p className="muted mt-8 text-sm">
        Dados cadastrais da Receita Federal (via BrasilAPI) e do site oficial. <Link href={`/correcoes?empresa=${org.slug}`}>Pedir correção</Link>
      </p>
    </article>
  );
}
