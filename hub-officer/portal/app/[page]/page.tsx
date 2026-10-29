import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { CorrectionForm } from "@/components/Forms";
import { Crumbs } from "@/components/SiteChrome";
import { getInstitutional } from "@/lib/api";

const PAGES = ["sobre", "metodologia", "politica-editorial", "termos", "privacidade", "correcoes"];
export const revalidate = 3600;
export const dynamicParams = false;
export function generateStaticParams() {
  return PAGES.map((page) => ({ page }));
}

type Props = { params: Promise<{ page: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { page } = await params;
  const data = await getInstitutional(page).catch(() => null);
  return data ? { title: data.title, description: data.description, alternates: { canonical: `/${page}` } } : {};
}

export default async function Institutional({ params }: Props) {
  const { page } = await params;
  const data = await getInstitutional(page).catch(() => null);
  if (!data) notFound();
  return (
    <article className="max-w-prose">
      <Crumbs items={[{ name: "Início", href: "/" }, { name: data.title }]} />
      <h1 className="text-2xl font-bold sm:text-3xl">{data.title}</h1>
      <p className="muted mt-2">{data.description}</p>
      {data.draft && <p className="notice"><strong>Minuta.</strong> Texto-base que precisa de revisão jurídica antes do lançamento.</p>}
      {data.sections.map((s, i) => (
        <section key={i} className="mt-6">
          {s.h && <h2 className="mb-2 text-lg font-semibold">{s.h}</h2>}
          {s.p?.map((p, j) => <p key={j} className="mt-2">{p}</p>)}
          {s.list && <ul className="mt-2 list-disc space-y-1 pl-5">{s.list.map((li, j) => <li key={j}>{li}</li>)}</ul>}
        </section>
      ))}
      {data.form === "correction" && (
        <Suspense fallback={null}>
          <CorrectionForm />
        </Suspense>
      )}
    </article>
  );
}
