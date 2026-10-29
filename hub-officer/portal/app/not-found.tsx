import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16">
      <h1 className="text-2xl font-bold">Página não encontrada</h1>
      <p className="muted mt-2">O endereço pode ter mudado. Veja <Link href="/hubs">todos os comparativos</Link>.</p>
    </div>
  );
}
