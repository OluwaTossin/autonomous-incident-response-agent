"use client";

import { FormEvent, useState } from "react";
import { Cloud, LoaderCircle, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import type { AwsIntegration, BrowserError } from "@/lib/types";

export function AwsIntegrationCreate({ organizationId, workspaceId, csrfToken }: { organizationId: string; workspaceId: string; csrfToken: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    const form = new FormData(event.currentTarget);
    const regions = String(form.get("regions") || "").split(",").map((value) => value.trim()).filter(Boolean);
    try {
      const response = await fetch(`/api/organizations/${organizationId}/workspaces/${workspaceId}/integrations/aws`, { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": csrfToken }, body: JSON.stringify({ display_name: form.get("display_name"), aws_account_id: form.get("aws_account_id"), enabled_regions: regions }), cache: "no-store" });
      const payload = (await response.json()) as AwsIntegration | BrowserError;
      if (!response.ok) throw new Error(browserError(payload));
      router.push(`/app/orgs/${organizationId}/workspaces/${workspaceId}/integrations/aws/${(payload as AwsIntegration).integration_id}`);
    } catch (caught) { setError(message(caught)); setBusy(false); }
  }
  return <section className="integration-create"><div className="section-title"><div><h2>Connect an AWS account</h2><p>AIRA generates a unique ExternalId. No access keys are accepted.</p></div><Cloud aria-hidden="true" size={20} /></div><form className="settings-form" onSubmit={submit}><label>Display name<input name="display_name" required maxLength={200} placeholder="Production AWS" /></label><label>AWS account ID<input name="aws_account_id" required inputMode="numeric" pattern="[0-9]{12}" maxLength={12} placeholder="123456789012" /></label><label>Regions<input name="regions" required placeholder="eu-west-2, us-east-1" /><small>One to twenty explicit standard AWS regions, separated by commas.</small></label>{error ? <p className="form-error" role="alert">{error}</p> : null}<button className="primary-command" disabled={busy} type="submit">{busy ? <LoaderCircle className="spin" aria-hidden="true" size={17} /> : <Plus aria-hidden="true" size={17} />}Create integration</button></form></section>;
}
function browserError(payload: unknown): string { return payload && typeof payload === "object" && "error" in payload ? (payload as BrowserError).error.message : "The request could not be completed."; }
function message(error: unknown): string { return error instanceof Error ? error.message : "The request could not be completed."; }
