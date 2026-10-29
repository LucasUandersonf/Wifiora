import Link from "next/link";
import type { Site } from "@/lib/api";

export function Header({ site }: { site: Site }) {
  return (
    <header className="border-b border-slate-200 dark:border-slate-800">
      <div className="wrap flex flex-wrap items-center justify-between gap-3 py-3">
        <Link href="/" className="flex items-center gap-2 font-bold text-ink no-underline dark:text-slate-100">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md bg-verified text-xs text-white">{"{ }"}</span>
          {site.brand}
        </Link>
        <nav aria-label="Principal" className="flex gap-4 text-sm">
          <Link href="/hubs">Comparativos</Link>
          <Link href="/conceitos">Empresas e conceitos</Link>
          <Link href="/dados">Dados abertos</Link>
          <Link href="/metodologia">Metodologia</Link>
        </nav>
      </div>
    </header>
  );
}

export function Footer({ site }: { site: Site }) {
  return (
    <footer className="mt-16 border-t border-slate-200 py-8 text-sm dark:border-slate-800">
      <div className="wrap flex flex-col gap-3">
        <p className="muted">{site.brand} · Dados abertos sob licença CC BY 4.0 · Cada valor com fonte oficial e data de verificação.</p>
        <nav aria-label="Institucional" className="flex flex-wrap gap-x-4 gap-y-1">
          {site.footer_links.map((l) => (
            <Link key={l.href} href={l.href}>{l.label}</Link>
          ))}
          <Link href="/sobre">Sobre</Link>
          <a href="/llms.txt">llms.txt</a>
          <a href="/knowledge-graph.jsonld">Grafo (JSON-LD)</a>
        </nav>
      </div>
    </footer>
  );
}

export function Crumbs({ items }: { items: { name: string; href?: string }[] }) {
  return (
    <nav aria-label="Navegação" className="muted mb-4 text-sm">
      {items.map((it, i) => (
        <span key={i}>
          {i > 0 && " › "}
          {it.href ? <Link href={it.href} className="text-ink-soft dark:text-slate-400">{it.name}</Link> : it.name}
        </span>
      ))}
    </nav>
  );
}

export function JsonLd({ doc }: { doc: unknown }) {
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(doc).replace(/</g, "\\u003c") }} />;
}
