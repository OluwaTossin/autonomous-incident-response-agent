"use client";

import { FormEvent, useState } from "react";
import { Ban, Check, Copy, LoaderCircle, RadioTower, Save, ShieldCheck } from "lucide-react";
import type { AwsIntegration, AwsTrustInstructions, BrowserError } from "@/lib/types";

export function AwsIntegrationOnboarding({ initialIntegration, trust, organizationId, workspaceId, csrfToken, canManage }: { initialIntegration: AwsIntegration; trust?: AwsTrustInstructions; organizationId: string; workspaceId: string; csrfToken: string; canManage: boolean }) {
  const [integration, setIntegration] = useState(initialIntegration);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const base = `/api/organizations/${organizationId}/workspaces/${workspaceId}/integrations/aws/${integration.integration_id}`;

  async function saveRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("role"); setNotice(null);
    const form = new FormData(event.currentTarget);
    try { setIntegration(await mutate(base, "PATCH", { expected_version: integration.version, role_arn: form.get("role_arn") })); setNotice("Role configuration saved. Verification is required."); }
    catch (caught) { setNotice(message(caught)); } finally { setBusy(null); }
  }
  async function verify() {
    setBusy("verify"); setNotice(null);
    try { const next = await mutate(`${base}/verify`, "POST", { expected_version: integration.version }); setIntegration(next); setNotice(next.state === "ready" ? "AWS integration is ready." : next.verification?.summary || "Verification failed."); }
    catch (caught) { setNotice(message(caught)); } finally { setBusy(null); }
  }
  async function saveLogSources(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("logs"); setNotice(null);
    const form = new FormData(event.currentTarget);
    const logGroups = String(form.get("log_group_names") || "").split("\n").map((value) => value.trim()).filter(Boolean);
    try { setIntegration(await mutate(base, "PATCH", { expected_version: integration.version, log_group_names: logGroups })); setNotice("CloudWatch log sources saved."); }
    catch (caught) { setNotice(message(caught)); } finally { setBusy(null); }
  }
  async function disable() {
    if (!window.confirm("Disable this AWS integration? Future alert and context operations will be blocked.")) return;
    setBusy("disable"); setNotice(null);
    try { setIntegration(await mutate(`${base}/disable`, "POST", { expected_version: integration.version })); setNotice("AWS integration disabled."); }
    catch (caught) { setNotice(message(caught)); } finally { setBusy(null); }
  }
  async function mutate(url: string, method: string, body: unknown): Promise<AwsIntegration> {
    const response = await fetch(url, { method, headers: { "content-type": "application/json", "x-csrf-token": csrfToken }, body: JSON.stringify(body), cache: "no-store" });
    const payload = (await response.json()) as AwsIntegration | BrowserError;
    if (!response.ok) throw new Error(browserError(payload));
    return payload as AwsIntegration;
  }
  return <div className="integration-onboarding">
    {notice ? <div className="inline-notice" role="status">{notice}</div> : null}
    <ol className="onboarding-steps" aria-label="AWS onboarding progress"><li className="done"><Check size={15} />Account</li><li className="done"><Check size={15} />ExternalId</li><li className={integration.role_arn ? "done" : "current"}>{integration.role_arn ? <Check size={15} /> : "3"}IAM role</li><li className={integration.state === "ready" ? "done" : "current"}>{integration.state === "ready" ? <Check size={15} /> : "4"}Verify</li></ol>
    {trust ? <section className="integration-section"><div className="section-title"><div><h2>Trust relationship</h2><p>Create the customer IAM role yourself. AIRA has not changed your AWS account.</p></div><ShieldCheck aria-hidden="true" size={20} /></div><dl className="trust-facts"><div><dt>AIRA trusted principal</dt><dd>{trust.trusted_principal_arn}</dd></div><div><dt>ExternalId</dt><dd>{trust.external_id}</dd></div><div><dt>Allowed action</dt><dd>{trust.required_sts_action}</dd></div></dl><Policy title="Trust policy" value={trust.trust_policy} /><Policy title="Read-only permission policy" value={trust.permission_policy} /></section> : null}
    <section className="integration-section"><div className="section-title"><div><h2>Customer role</h2><p>The role account must match {integration.aws_account_id}.</p></div></div>{canManage && integration.state !== "disabled" ? <form className="settings-form" onSubmit={saveRole}><label>Role ARN<input name="role_arn" required maxLength={600} defaultValue={integration.role_arn || ""} placeholder={`arn:aws:iam::${integration.aws_account_id}:role/aira-read`} /></label><button className="primary-command" disabled={busy !== null} type="submit">{busy === "role" ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}Save role</button></form> : <div className="permission-note">Role configuration is read-only for your current permissions.</div>}</section>
    <section className="integration-section"><div className="section-title"><div><h2>Verification</h2><p>Bounded STS identity and read-capability probes. No resource inventory is retained.</p></div><span className={`status-badge status-${integration.state}`}>{integration.state}</span></div><Verification integration={integration} />{canManage && integration.role_arn && integration.state !== "disabled" ? <div className="integration-actions"><button className="primary-command" disabled={busy !== null} onClick={() => void verify()} type="button">{busy === "verify" ? <LoaderCircle className="spin" size={17} /> : <ShieldCheck size={17} />}Verify connection</button><button className="icon-command danger" disabled={busy !== null} onClick={() => void disable()} type="button"><Ban size={17} />Disable</button></div> : null}</section>
    <section className="integration-section"><div className="section-title"><div><h2>Incident log sources</h2><p>Exact CloudWatch log groups eligible for bounded incident-time collection.</p></div></div>{canManage && integration.state !== "disabled" ? <form className="settings-form" onSubmit={saveLogSources}><label>Log group names<textarea name="log_group_names" rows={5} maxLength={10260} defaultValue={integration.log_group_names.join("\n")} placeholder="/aws/lambda/checkout-api" /></label><button className="primary-command" disabled={busy !== null} type="submit">{busy === "logs" ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}Save sources</button></form> : <div className="permission-note">Log-source configuration is read-only for your current permissions.</div>}</section>
    <section className="integration-section"><div className="section-title"><div><h2>Alarm delivery</h2><p>{integration.state === "ready" ? "Application intake is ready for authenticated CloudWatch alarm events." : "Connection verification is required before alarm events are accepted."}</p></div><RadioTower aria-hidden="true" size={20} /></div><div className="permission-note"><strong>Deployment target pending</strong><p>The production EventBridge target and AWS delivery policy are provisioned with the hosted infrastructure.</p></div></section>
  </div>;
}

function Policy({ title, value }: { title: string; value: Record<string, unknown> }) { const text = JSON.stringify(value, null, 2); return <div className="policy-block"><div><h3>{title}</h3><button className="icon-command" type="button" title={`Copy ${title}`} onClick={() => void navigator.clipboard.writeText(text)}><Copy size={15} /><span>Copy</span></button></div><pre><code>{text}</code></pre></div>; }
function Verification({ integration }: { integration: AwsIntegration }) { const verification = integration.verification; if (!verification) return <div className="quiet-empty">Verification has not run for this configuration.</div>; return <div className="verification-grid"><div><strong>AssumeRole</strong><span>{verification.assume_role_passed ? "Passed" : "Failed"}</span></div><div><strong>AWS account identity</strong><span>{verification.account_identity_passed ? "Passed" : "Failed"}</span></div>{verification.checks.map((check) => <div key={`${check.region}-${check.capability}`}><strong>{label(check.capability)}</strong><span>{check.region} · {check.passed ? "Passed" : check.summary}</span></div>)}</div>; }
function label(value: string): string { return value.replace("aws_cloudwatch_", "CloudWatch ").replaceAll("_", " "); }
function browserError(payload: unknown): string { return payload && typeof payload === "object" && "error" in payload ? (payload as BrowserError).error.message : "The request could not be completed."; }
function message(error: unknown): string { return error instanceof Error ? error.message : "The request could not be completed."; }
