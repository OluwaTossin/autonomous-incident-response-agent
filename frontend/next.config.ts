import type { NextConfig } from "next";

/** Static export for S3 + CloudFront (no Node server). */
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
