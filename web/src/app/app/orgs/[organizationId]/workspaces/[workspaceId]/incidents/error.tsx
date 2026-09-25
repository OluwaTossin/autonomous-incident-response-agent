"use client";

import { AlertCircle, RefreshCw } from "lucide-react";

export default function IncidentHistoryError({ reset }: { error: Error; reset: () => void }) {
  return <main className="route-state" role="alert">
    <AlertCircle aria-hidden="true" size={24} />
    <h1>Incident history is unavailable</h1>
    <p>The authenticated request could not be completed. Try again or return later.</p>
    <button className="primary-command" type="button" onClick={reset}><RefreshCw aria-hidden="true" size={17} />Try again</button>
  </main>;
}
