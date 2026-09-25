import { describe, expect, it } from "vitest";
import {
  constantTimeEqual,
  decryptJson,
  encryptJson,
  pkceChallenge,
  safeReturnPath,
  sha256,
} from "@/lib/security";

describe("browser security primitives", () => {
  it("encrypts session payloads and rejects a different key", () => {
    const key = Buffer.alloc(32, 7);
    const encrypted = encryptJson({ accessToken: "secret-token" }, key);
    expect(encrypted.toString("utf8")).not.toContain("secret-token");
    expect(decryptJson(encrypted, key)).toEqual({ accessToken: "secret-token" });
    expect(() => decryptJson(encrypted, Buffer.alloc(32, 8))).toThrow();
  });

  it("creates an RFC 7636 S256 challenge", () => {
    expect(
      pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });

  it("allows only local hosted application return paths", () => {
    expect(safeReturnPath("/app?run=1")).toBe("/app?run=1");
    expect(safeReturnPath("https://hostile.example")).toBe("/app");
    expect(safeReturnPath("//hostile.example/path")).toBe("/app");
    expect(safeReturnPath("/%2fhostile.example")).toBe("/app");
    expect(safeReturnPath("/configuration")).toBe("/app");
  });

  it("compares hashed values without accepting prefixes", () => {
    expect(constantTimeEqual(sha256("state"), sha256("state"))).toBe(true);
    expect(constantTimeEqual(sha256("state"), sha256("state2"))).toBe(false);
  });
});
