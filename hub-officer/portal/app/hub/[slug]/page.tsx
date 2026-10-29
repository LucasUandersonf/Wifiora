import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Crumbs, JsonLd } from "@/components/SiteChrome";
import { fmtDate, fmtValue, getHubPage, getSite, host, label } from "@/lib/api";

export const revalidate = 3600;
export const dynamicParams = true;

export async function generateStaticParams() {
  const site = await getSite();
  return site.hubs.map((h) => ({ slug: h.slug }));
}

type Props = { params: Promise<{ slug: string }> };
const DOWNLOADS = ["data.jsonl", "data.csv", "data.json", "data.md", "data.jsonld"];

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const data = await getHubPage(slug);
  if (!data) return {};
  return {
    title: data.hub.title,
    description: data.page.meta_description,
    alternates: { canonical: `/hub/${slug}`, types: { "application/ld+json": `/hub/${slug}/data.jsonld` } },
    robots: data.hub.demo_data ? { index: false, follow: false } : { index: true, follow: true },
  };
}

export default async function HubPage({ params }: Props) {
  const { slug } = await params;
  const data = await getHubPage(slug);
  if (!data) notFound();
  const { hub, page, columns, criteria, entities, changes, rankings = [] } = data;
  return (
    <article>
      <JsonLd doc={data.jsonld} />
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Comparativos", href: "/hubs" }, { name: hub.title }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">{hub.title}</h1>
      <p className="muted mt-2 text-sm">
        {hub.niche} · {entities.length} empresas · Atualizado em <time dateTime={hub.updated_at ?? undefined}>{fmtDate(hub.updated_at)}</time>
      </p>
      {hub.demo_data && (
        <p className="notice"><strong>Dados de demonstração.</strong> Este comparativo foi gerado em modo de simulação com fornecedores fictícios e não deve ser usado como referência.</p>
      )}
      {hub.description && <p className="mt-4 max-w-prose">{hub.description}</p>}

      <section id="tabela" className="mt-8">
        <h2 className="mb-3 text-xl font-semibold">Comparativo</h2>
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
          <table className="tbl w-full min-w-[720px] text-sm">
            <thead>
              <tr>
                <th scope="col">Nome</th>
                {columns.map((c) => <th key={c} scope="col">{label(c)}</th>)}
                {criteria.length > 0 && <th scope="col" className="text-right">Critérios</th>}
                <th scope="col">Verificado em</th>
                <th scope="col">Fonte</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((e) => (
                <tr key={e.slug}>
                  <th scope="row" className="font-semibold">
                    <Link href={`/hub/${hub.slug}/${e.slug}`}>{e.name}</Link>
                    {e.human_reviewed && <div className="mt-1"><span className="seal">✓ Validado por especialista</span></div>}
                  </th>
                  {columns.map((c) => (
                    <td key={c} className={typeof e.attributes[c] === "number" ? "text-right tabular-nums" : ""}>{fmtValue(e.attributes[c])}</td>
                  ))}
                  {criteria.length > 0 && <td className="text-right tabular-nums">{e.criteria_met}/{e.criteria_total}</td>}
                  <td><time dateTime={e.verified_at ?? undefined}>{fmtDate(e.verified_at)}</time></td>
                  <td>{e.source_url ? <a href={e.source_url} rel="nofollow noopener">{host(e.source_url)}</a> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {criteria.length > 0 && (
          <p className="muted mt-3 text-sm">Critérios objetivos avaliados: {criteria.join(" · ")}. Não publicamos notas nem opiniões.</p>
        )}
      </section>

      {rankings.length > 0 && (
        <section id="rankings" className="mt-10">
          <h2 className="mb-1 text-xl font-semibold">Rankings</h2>
          <p className="muted mb-4 text-sm">Ordenações matemáticas a partir dos dados da tabela. Nenhuma empresa paga para mudar de posição.</p>
          <div className="grid gap-4 md:grid-cols-2">
            {rankings.map((r) => (
              <div key={r.key} id={`ranking-${r.key}`} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                <h3 className="font-semibold">{r.title}</h3>
                <ol className="mt-2 space-y-1 text-sm">
                  {r.items.map((it) => (
                    <li key={it.slug} className="flex gap-2">
                      <span className="w-6 shrink-0 text-right tabular-nums text-ink-soft dark:text-slate-400">{it.position}.</span>
                      <span><Link href={`/hub/${hub.slug}/${it.slug}`}>{it.name}</Link>{it.value_label && <span className="muted"> — {it.value_label}</span>}</span>
                    </li>
                  ))}
                </ol>
                <p className="muted mt-2 text-xs">{r.method}{r.missing.length > 0 && ` Sem o dado na fonte: ${r.missing.join(", ")}.`}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {page.faq.length > 0 && (
        <section id="faq" className="mt-10 max-w-prose">
          <h2 className="mb-3 text-xl font-semibold">Perguntas frequentes</h2>
          {page.faq.map((f) => (
            <div key={f.q} className="mb-4">
              <h3 className="font-semibold">{f.q}</h3>
              <p className="mt-1">{f.a}</p>
            </div>
          ))}
        </section>
      )}

      <section className="mt-10 max-w-prose">
        <h2 className="mb-2 text-xl font-semibold">Como verificamos</h2>
        <p>
          Cada valor é extraído de uma fonte oficial citada, conferido automaticamente contra o texto da fonte e revisado por um controle de qualidade antes da publicação.{" "}
          <Link href="/metodologia">Metodologia completa</Link> · <Link href={`/correcoes?hub=${hub.slug}`}>Encontrou um erro?</Link>
        </p>
      </section>

      <section id="dados" className="mt-10 max-w-prose">
        <h2 className="mb-2 text-xl font-semibold">Dados abertos</h2>
        <p>
          Baixe esta tabela inteira (licença CC BY 4.0, cite a fonte):{" "}
          {DOWNLOADS.map((f, i) => (
            <span key={f}>{i > 0 && " · "}<a href={`/hub/${hub.slug}/${f}`}>{f}</a></span>
          ))}
          . <Link href="/dados">Todos os arquivos</Link>
        </p>
      </section>

      {changes.length > 0 && (
        <section id="historico" className="mt-10">
          <h2 className="mb-2 text-xl font-semibold">Histórico de atualizações</h2>
          <ul className="space-y-1 text-sm">
            {changes.map((c, i) => (
              <li key={i}><time dateTime={c.at}>{fmtDate(c.at)}</time> — {c.entity} v{c.version}: <span className="muted">{c.fields.map(label).join(", ")}</span></li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
