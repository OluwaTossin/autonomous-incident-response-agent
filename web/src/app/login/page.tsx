import { ArrowRight, ShieldCheck } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; loggedOut?: string }>;
}) {
  const query = await searchParams;
  return (
    <main className="login-page">
      <section className="login-content" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true">A</div>
        <span className="eyebrow">AIRA hosted operations</span>
        <h1 id="login-title">Incident intelligence, ready for the first response.</h1>
        <p>
          Sign in through your organization identity to create incidents, follow durable
          triage runs, and inspect the evidence behind each result.
        </p>
        {query.error ? (
          <div className="auth-message error" role="alert">
            Authentication could not be completed. Start a fresh sign-in.
          </div>
        ) : null}
        {query.loggedOut ? (
          <div className="auth-message" role="status">Your AIRA session has ended.</div>
        ) : null}
        <a className="primary-command login-command" href="/auth/login?returnTo=%2Fapp">
          Sign in securely <ArrowRight aria-hidden="true" size={18} />
        </a>
        <div className="login-assurance">
          <ShieldCheck aria-hidden="true" size={18} />
          <span>Tokens remain on the AIRA server. This browser receives an opaque session cookie.</span>
        </div>
      </section>
      <aside className="signal-rail" aria-label="AIRA triage stages">
        <div><span>01</span><strong>Intake</strong><small>Durable incident record</small></div>
        <div><span>02</span><strong>Reason</strong><small>Workspace evidence and policy</small></div>
        <div><span>03</span><strong>Review</strong><small>Human-controlled response</small></div>
      </aside>
    </main>
  );
}
