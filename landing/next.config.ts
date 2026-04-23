import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

function normalizeBasePath(raw: string | undefined): string {
  const v = String(raw || "").trim();
  if (!v) return "";
  const prefixed = v.startsWith("/") ? v : `/${v}`;
  return prefixed.replace(/\/+$/, "");
}

const basePath = normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);
const configDir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: "export",
  outputFileTracingRoot: path.join(configDir, ".."),
  trailingSlash: true,
  basePath: basePath || undefined,
  assetPrefix: basePath || undefined,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
