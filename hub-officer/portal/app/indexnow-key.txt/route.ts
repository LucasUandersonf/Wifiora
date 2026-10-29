import { proxyText } from "@/lib/api";

export const revalidate = 3600;
export const GET = () => proxyText("/indexnow-key.txt", "text/plain; charset=utf-8");
