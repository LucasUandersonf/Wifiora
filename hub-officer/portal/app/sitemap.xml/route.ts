import { proxyText } from "@/lib/api";

export const revalidate = 3600;
export const GET = () => proxyText("/sitemap.xml", "application/xml; charset=utf-8");
