import "server-only";

import { isIP } from "node:net";

const blockedNames = new Set([
  "localhost",
  "localhost.localdomain",
  "metadata",
  "metadata.google.internal",
]);

export function publicHttpsUrl(name: string, value: string): string {
  const parsed = new URL(value);
  if (parsed.protocol !== "https:") throw new Error(`${name} must use HTTPS`);
  if (parsed.username || parsed.password) {
    throw new Error(`${name} must not contain user information`);
  }
  if (parsed.port && parsed.port !== "443") {
    throw new Error(`${name} must use the default HTTPS port`);
  }
  const hostname = parsed.hostname.replace(/^\[|\]$/g, "").replace(/\.$/, "").toLowerCase();
  if (blockedNames.has(hostname) || hostname.endsWith(".localhost")) {
    throw new Error(`${name} must not target a local host`);
  }
  if (isIP(hostname) && !isPublicIp(hostname)) {
    throw new Error(`${name} must not target a private, local, or reserved address`);
  }
  return parsed.toString().replace(/\/$/, "");
}

function isPublicIp(hostname: string): boolean {
  if (isIP(hostname) === 4) {
    const octets = hostname.split(".").map(Number);
    const [a, b] = octets;
    return !(
      a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 0) ||
      (a === 192 && b === 168) ||
      (a === 198 && (b === 18 || b === 19 || b === 51)) ||
      (a === 203 && b === 0)
    );
  }
  const normalized = hostname.toLowerCase();
  return !(
    normalized === "::" || normalized === "::1" ||
    normalized.startsWith("::ffff:") ||
    normalized.startsWith("fc") || normalized.startsWith("fd") ||
    /^fe[89ab]/.test(normalized) || normalized.startsWith("ff") ||
    normalized.startsWith("2001:db8")
  );
}
