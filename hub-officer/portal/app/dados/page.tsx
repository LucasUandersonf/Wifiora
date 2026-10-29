import type { Metadata } from "next";
import Link from "next/link";
import { Crumbs, JsonLd } from "@/components/SiteChrome";
import { fmtDate, getDataPage } from "@/lib/api";

export const revalidate = 3600;
export const metadata: Metadata = {
  title: "Dados abertos",
  description: "Baixe os dados verificados em JSON, JSONL, CSV, Markdown e JSON-LD. Licença CC BY 4.0.",
  alternates: { canonical: "/dados" },
};

const fileName = (url: string) => url.split("/").pop();

export default async function Data() {
  const data = await getDataPage();
  return (
    <>
      {data && <JsonLd doc={data.jsonld} />}
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Dados abertos" }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">Dados abertos</h1>
      <p className="mt-3 max-w-prose">
        Todo o conteúdo verificado pode ser baixado em lote, de graça, sob a licença{" "}
        <a href="https://creativecommons.org/licenses/by/4.0/deed.pt_BR">CC BY 4.0</a>: use à vontade, citando a fonte. Para histórico de versões,
        busca entre comparativos e filtro por data de atualização, use a API (com chave).
      </p>
      {data && (
        <>
          <section className="mt-8">
            <h2 className="mb-2 text-xl font-semibold">Site inteiro</h2>
            <ul className="list-disc space-y-1 pl-5">
              {data.site_files.map((f) => <li key={f.url}><a href={new URL(f.url).pathname}>{f.name}</a> <span className="muted text-sm">({f.format})</span></li>)}
            </ul>
          </section>
          <section className="mt-8">
            <h2 className="mb-3 text-xl font-semibold">Por comparativo</h2>
            {data.hubs.length === 0 && <p className="muted">Nenhum comparativo publicado ainda.</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              {data.hubs.map((h) => (
                <div key={h.slug} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
                  <h3 className="font-semibold"><Link href={`/hub/${h.slug}`}>{h.title}</Link></h3>
                  <p className="muted text-sm">{h.records} registros · atualizado em {fmtDate(h.updated_at)}{h.demo_data ? " · demonstração" : ""}</p>
                  <ul className="mt-2 space-y-1 text-sm">
                    {h.files.map((f) => <li key={f.url}><a href={new URL(f.url).pathname}>{fileName(f.url)}</a> <span className="muted">— {f.name}</span></li>)}
                  </ul>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}
