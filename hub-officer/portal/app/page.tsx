import Link from "next/link";
import { HubList } from "@/components/HubList";
import { JsonLd } from "@/components/SiteChrome";
import { SITE_URL, getSite } from "@/lib/api";

export const revalidate = 3600;

export default async function Home() {
  const site = await getSite();
  const org = { "@context": "https://schema.org", "@graph": [
    { "@type": "Organization", "@id": `${SITE_URL}/#org`, name: site.brand, url: `${SITE_URL}/` },
    { "@type": "WebSite", "@id": `${SITE_URL}/#website`, name: site.brand, url: `${SITE_URL}/`, inLanguage: "pt-BR", publisher: { "@id": `${SITE_URL}/#org` } },
  ] };
  return (
    <>
      <JsonLd doc={org} />
      <section className="max-w-prose py-6">
        <h1 className="text-3xl font-bold leading-tight sm:text-4xl">Comparativos B2B com dados que você pode conferir</h1>
        <p className="muted mt-4 text-lg">
          Preços, recursos e regras de software e serviços para empresas brasileiras. Cada número traz a fonte oficial, a data em que foi verificado e o histórico de alterações.
        </p>
        <p className="mt-4 text-sm"><Link href="/metodologia">Como verificamos os dados</Link></p>
      </section>
      <section className="mt-6">
        <h2 className="mb-4 text-xl font-semibold">Comparativos</h2>
        <HubList hubs={site.hubs} />
      </section>
    </>
  );
}
