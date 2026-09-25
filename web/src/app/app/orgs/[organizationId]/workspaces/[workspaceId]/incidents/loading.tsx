export default function IncidentHistoryLoading() {
  return <main className="route-state" aria-live="polite" aria-busy="true">
    <span className="eyebrow">Investigation history</span>
    <h1>Loading incidents</h1>
    <div className="loading-lines" aria-hidden="true"><span /><span /><span /></div>
  </main>;
}
