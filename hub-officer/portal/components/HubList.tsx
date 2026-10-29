import Link from "next/link";
import { type HubCard, fmtDate } from "@/lib/api";

export function HubList({ hubs }: { hubs: HubCard[] }) {
  if (!hubs.length) return <p className="muted">Nenhum comparativo publicado ainda.</p>;
  return (
    <ul className="grid gap-4 sm:grid-cols-2">
      {hubs.map((h) => (
        <li key={h.slug} className="rounded-xl border border-slate-200 p-5 dark:border-slate-800">
          <p className="muted text-xs uppercase tracking-wide">{h.niche}</p>
          <h2 className="mt-1 text-lg font-semibold">
            <Link href={`/hub/${h.slug}`}>{h.title}</Link>
          </h2>
          {h.description && <p className="muted mt-2 text-sm">{h.description}</p>}
          <p className="muted mt-3 text-xs">
            Atualizado em {fmtDate(h.updated_at)}
            {h.demo_data && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-amber-900 dark:bg-amber-950 dark:text-amber-200">demonstração</span>}
          </p>
        </li>
      ))}
    </ul>
  );
}
