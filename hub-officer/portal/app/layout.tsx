import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Footer, Header } from "@/components/SiteChrome";
import { SITE_URL, getSite } from "@/lib/api";

export async function generateMetadata(): Promise<Metadata> {
  const site = await getSite();
  return {
    metadataBase: new URL(SITE_URL),
    title: { default: site.brand, template: `%s · ${site.brand}` },
    description: "Comparativos B2B do mercado brasileiro com dados estruturados e verificados: cada valor com fonte oficial, data de verificação e histórico.",
    openGraph: { siteName: site.brand, locale: "pt_BR", type: "website" },
  };
}

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#0f141a" }, { color: "#ffffff" }] };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const site = await getSite();
  return (
    <html lang="pt-BR">
      <body className="flex min-h-screen flex-col font-sans">
        <Header site={site} />
        <main className="wrap flex-1 py-8">{children}</main>
        <Footer site={site} />
      </body>
    </html>
  );
}
