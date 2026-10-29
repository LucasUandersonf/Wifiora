"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

type State = { status: "idle" | "sending" | "done" | "error"; message?: string };

async function send(url: string, body: Record<string, unknown>): Promise<State> {
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.ok) return { status: "done" };
    const data = await res.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : "Confira os campos e tente de novo.";
    return { status: "error", message: res.status === 429 ? "Muitos envios seguidos. Tente de novo em alguns minutos." : detail };
  } catch {
    return { status: "error", message: "Sem conexão. Tente de novo." };
  }
}

function formData(form: HTMLFormElement) {
  const data: Record<string, unknown> = {};
  new FormData(form).forEach((v, k) => (data[k] = typeof v === "string" ? v.trim() || null : null));
  return data;
}

export function LeadForm({ hubSlug, entitySlug, entityName }: { hubSlug: string; entitySlug: string; entityName: string }) {
  const [state, setState] = useState<State>({ status: "idle" });
  if (state.status === "done")
    return <p className="rounded-lg bg-verified-soft px-4 py-3 text-verified dark:bg-verified-darksoft dark:text-verified-dark">Pedido enviado. Vamos encaminhá-lo a {entityName}.</p>;
  return (
    <form
      className="grid max-w-xl gap-3 rounded-xl border border-slate-200 p-5 dark:border-slate-800"
      onSubmit={async (ev) => {
        ev.preventDefault();
        setState({ status: "sending" });
        const data = formData(ev.currentTarget);
        setState(await send("/api/lead", { ...data, hub_slug: hubSlug, entity_slug: entitySlug, consent: data.consent === "1" }));
      }}
    >
      <input type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden className="absolute -left-[9999px]" />
      <label className="grid gap-1 text-sm">Nome<input id="lead-name" name="name" required maxLength={160} autoComplete="name" className="field" /></label>
      <label className="grid gap-1 text-sm">E-mail profissional<input id="lead-email" name="email" type="email" required maxLength={200} autoComplete="email" className="field" /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm">Telefone (opcional)<input id="lead-phone" name="phone" maxLength={40} autoComplete="tel" className="field" /></label>
        <label className="grid gap-1 text-sm">Porte da empresa
          <select id="lead-size" name="company_size" className="field" defaultValue="">
            <option value="">—</option><option>1-10</option><option>11-50</option><option>51-200</option><option>201-1000</option><option>1000+</option>
          </select>
        </label>
      </div>
      <label className="grid gap-1 text-sm">Empresa<input id="lead-company" name="company" maxLength={200} autoComplete="organization" className="field" /></label>
      <label className="grid gap-1 text-sm">Mensagem (opcional)<textarea id="lead-message" name="message" rows={3} maxLength={2000} className="field" /></label>
      <label className="flex items-start gap-2 text-sm">
        <input id="lead-consent" type="checkbox" name="consent" value="1" required className="mt-1" />
        <span>Autorizo o envio dos meus dados a {entityName} para contato comercial, conforme a <a href="/privacidade">Política de privacidade</a>.</span>
      </label>
      {state.status === "error" && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{state.message}</p>}
      <button className="btn justify-self-start" disabled={state.status === "sending"}>{state.status === "sending" ? "Enviando…" : "Solicitar demonstração"}</button>
    </form>
  );
}

export function CorrectionForm() {
  // Lido no navegador: a página é estática e o link "Solicitar correção" traz ?hub=...&empresa=...
  const params = useSearchParams();
  const hubSlug = params.get("hub") || undefined;
  const entitySlug = params.get("empresa") || undefined;
  const [state, setState] = useState<State>({ status: "idle" });
  if (state.status === "done")
    return <p className="rounded-lg bg-verified-soft px-4 py-3 text-verified dark:bg-verified-darksoft dark:text-verified-dark">Pedido recebido. Vamos analisar e responder pelo e-mail informado.</p>;
  return (
    <form
      className="mt-6 grid max-w-xl gap-3 rounded-xl border border-slate-200 p-5 dark:border-slate-800"
      onSubmit={async (ev) => {
        ev.preventDefault();
        setState({ status: "sending" });
        setState(await send("/api/correction", { ...formData(ev.currentTarget), hub_slug: hubSlug || null, entity_slug: entitySlug || null }));
      }}
    >
      <input type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden className="absolute -left-[9999px]" />
      <label className="grid gap-1 text-sm">Nome<input id="corr-name" name="name" required maxLength={160} autoComplete="name" className="field" /></label>
      <label className="grid gap-1 text-sm">E-mail<input id="corr-email" name="email" type="email" required maxLength={200} autoComplete="email" className="field" /></label>
      <label className="grid gap-1 text-sm">Empresa (opcional)<input id="corr-company" name="company" maxLength={200} autoComplete="organization" className="field" /></label>
      <label className="grid gap-1 text-sm">O que está errado?
        <textarea id="corr-message" name="message" rows={4} required minLength={5} maxLength={4000} className="field" defaultValue={entitySlug ? `Ficha: ${entitySlug} — ` : ""} />
      </label>
      <label className="grid gap-1 text-sm">Link da fonte oficial<input id="corr-url" name="evidence_url" type="url" maxLength={500} placeholder="https://" className="field" /></label>
      {state.status === "error" && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{state.message}</p>}
      <button className="btn justify-self-start" disabled={state.status === "sending"}>{state.status === "sending" ? "Enviando…" : "Enviar correção"}</button>
    </form>
  );
}
