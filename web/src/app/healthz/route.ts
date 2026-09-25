import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json(
    { status: "ok", service: "aira-hosted-web" },
    { headers: { "cache-control": "no-store" } },
  );
}
