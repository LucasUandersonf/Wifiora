import { proxyText } from "@/lib/api";

export const revalidate = 3600;
export const GET = () => proxyText("/llms.txt", "text/plain; charset=utf-8");
