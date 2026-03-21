import type { NextConfig } from "next";
import path from "path";

function normalizeBasePath(raw: string | undefined): string {
  const v = String(raw || "").trim();
  if (!v) return "";
  const prefixed = v.startsWith("/") ? v : `/${v}`;
  return prefixed.replace(/\/+$/, "");
}

const basePath = normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  basePath: basePath || undefined,
  assetPrefix: basePath ? `${basePath}/` : undefined,
  images: {
    unoptimized: true,
  },
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
