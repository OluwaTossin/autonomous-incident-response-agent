import { describe, expect, it } from "vitest";
import { publicHttpsUrl } from "@/lib/outbound-security";

describe("server outbound destination policy", () => {
  it.each([
    "http://provider.example",
    "https://localhost/token",
    "https://api.localhost/token",
    "https://127.0.0.1/token",
    "https://[::1]/token",
    "https://[::ffff:127.0.0.1]/token",
    "https://[2001:db8::1]/token",
    "https://10.0.0.1/token",
    "https://169.254.169.254/latest/meta-data/",
    "https://198.51.100.2/token",
    "https://203.0.113.2/token",
    "https://user:secret@provider.example/token",
    "https://provider.example:8443/token",
  ])("rejects unsafe destination %s", (value) => {
    expect(() => publicHttpsUrl("TEST_URL", value)).toThrow();
  });

  it("accepts a public HTTPS destination", () => {
    expect(publicHttpsUrl("TEST_URL", "https://login.example/path/")).toBe(
      "https://login.example/path",
    );
  });
});
