import type { Metadata } from "next";
import { HubList } from "@/components/HubList";
import { Crumbs } from "@/components/SiteChrome";
import { getSite } from "@/lib/api";

export const revalidate = 3600;
export const metadata: Metadata = { title: "Comparativos", alternates: { canonical: "/hubs" } };

export default async function Hubs() {
  const site = await getSite();
  return (
    <>
      <Crumbs items={[{ name: "Início", href: "/" }, { name: "Comparativos" }]} />
      <h1 className="mb-6 text-2xl font-bold">Todos os comparativos</h1>
      <HubList hubs={site.hubs} />
    </>
  );
}
