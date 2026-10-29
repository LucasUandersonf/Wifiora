import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { LeadForm } from "@/components/Forms";
import { Crumbs, JsonLd } from "@/components/SiteChrome";
import { fmtDate, fmtValue, getEntityPage, label } from "@/lib/api";

export const revalidate = 3600;
export const dynamicParams = true;
// Nenhuma ficha pré-gerada no build: cada uma é gerada na 1ª visita e fica em cache (ISR).
export function generateStaticParams() {
  return [];
}

type Props = { params: Promise<{ slug: string; entity: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, entity } = await params;
  const data = await getEntityPage(slug, entity);
  if (!data) return {};
  return {
    title: `${data.entity.name} — ${data.hub.title}`,
    description: `${data.entity.name}: dados verificados com fontes oficiais, critérios objetivos e histórico de versões.`,
    alternates: { canonical: `/hub/${slug}/${entity}` },
    robots: data.hub.demo_data ? { index: false, follow: false } : { index: true, follow: true },
  };
}

export default async function EntityPage({ params }: Props) {
  const { slug, entity } = await params;
  const data = await getEntityPage(slug, entity);
  if (!data) notFound();
  const { hub, entity: e, versions } = data;
  const company = e.provider.razao_social || e.provider.nome_fantasia;
  return (
    <article>
      <JsonLd doc={data.jsonld} />
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Comparativos", href: "/hubs" }, { name: hub.title, href: `/hub/${hub.slug}` }, { name: e.name }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">{e.name}</h1>
      <p className="muted mt-2 text-sm">
        Verificado em <time dateTime={e.verified_at ?? undefined}>{fmtDate(e.verified_at)}</time> · versão {e.version} ·{" "}
        {Math.round(e.grounding_ratio * 100)}% dos valores confirmados literalmente na fonte
      </p>
      {e.human_reviewed_by && (
        <p className="mt-2 text-sm"><span className="seal">✓ Validado por especialista</span> <span className="muted">{e.human_reviewed_by}, em {fmtDate(e.human_reviewed_at)}</span></p>
      )}
      {hub.demo_data && <p className="notice"><strong>Dados de demonstração</strong> (fornecedor fictício).</p>}

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section>
          <h2 className="mb-3 text-xl font-semibold">Dados verificados</h2>
          <table className="tbl w-full text-sm">
            <tbody>
              {Object.entries(e.attributes).map(([k, v]) => (
                <tr key={k}><th scope="row" className="w-1/2 font-medium text-ink-soft dark:text-slate-400">{label(k)}</th><td>{fmtValue(v)}</td></tr>
              ))}
              {company && (
                <tr><th scope="row" className="font-medium text-ink-soft dark:text-slate-400">empresa</th>
                  <td>{e.org_slug ? <Link href={`/empresa/${e.org_slug}`}>{company}</Link> : company}{e.provider.municipio ? ` — ${e.provider.municipio}/${e.provider.uf}` : ""}{e.provider.cnpj ? ` · CNPJ ${e.provider.cnpj}` : ""}</td></tr>
              )}
            </tbody>
          </table>
        </section>
        {e.criteria.length > 0 && (
          <section>
            <h2 className="mb-3 text-xl font-semibold">Critérios objetivos</h2>
            <ul className="space-y-2">
              {e.criteria.map((c) => (
                <li key={c.label} className="flex items-start gap-2">
                  <span aria-hidden className={c.passed ? "text-verified dark:text-verified-dark" : "muted"}>{c.passed === true ? "✓" : c.passed === false ? "✗" : "?"}</span>
                  <span>{c.label}{c.passed === null && <span className="muted"> (dado não disponível)</span>}</span>
                </li>
              ))}
            </ul>
            <p className="muted mt-3 text-sm">Calculados a partir dos dados verificados. Não é uma recomendação de compra.</p>
          </section>
        )}
      </div>

      <section className="mt-10">
        <h2 className="mb-3 text-xl font-semibold">Fontes</h2>
        <ul className="space-y-3 text-sm">
          {e.sources.map((s, i) => (
            <li key={i}>
              <a href={s.url} rel="nofollow noopener" className="break-all">{s.url}</a>
              {s.quote && <q className="muted mt-1 block">{s.quote}</q>}
              {s.retrieved_at && <span className="muted text-xs">coletado em {fmtDate(s.retrieved_at)}</span>}
            </li>
          ))}
        </ul>
      </section>

      <section id="demonstracao" className="mt-10">
        <h2 className="mb-3 text-xl font-semibold">Solicitar demonstração</h2>
        <LeadForm hubSlug={hub.slug} entitySlug={e.slug} entityName={e.name} />
      </section>

      <section className="mt-10">
        <h2 className="mb-2 text-xl font-semibold">Versões</h2>
        <ul className="space-y-1 text-sm">
          {versions.map((v) => <li key={v.version}>v{v.version} — <time dateTime={v.at}>{fmtDate(v.at)}</time>: <span className="muted">{v.fields.map(label).join(", ")}</span></li>)}
        </ul>
        <p className="muted mt-4 text-sm">Algum dado errado? <Link href={`/correcoes?hub=${hub.slug}&empresa=${e.slug}`}>Solicitar correção</Link></p>
      </section>
    </article>
  );
}
