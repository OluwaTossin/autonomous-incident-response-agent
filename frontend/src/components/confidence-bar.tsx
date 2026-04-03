"use client";

/**
 * Same thresholds / colors as `app/ui/triage_display.py` `confidence_bar`.
 */

type Props = {
  confidence: number;
};

export function ConfidenceBar({ confidence }: Props) {
  const c = Math.max(0, Math.min(1, Number(confidence) || 0));
  const pct = Math.round(c * 100);

  let barGradient: string;
  let labelClass: string;
  if (c < 0.45) {
    barGradient = "linear-gradient(90deg,#ef4444,#f97316)";
    labelClass = "text-red-700 dark:text-red-400";
  } else if (c < 0.75) {
    barGradient = "linear-gradient(90deg,#f59e0b,#eab308)";
    labelClass = "text-amber-800 dark:text-amber-300";
  } else {
    barGradient = "linear-gradient(90deg,#22c55e,#16a34a)";
    labelClass = "text-green-800 dark:text-green-400";
  }

  return (
    <div className="my-3 font-sans">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[13px] font-semibold text-zinc-600 dark:text-zinc-400">
          Confidence
        </span>
        <span className={`text-sm font-bold ${labelClass}`}>{pct}%</span>
      </div>
      <div
        className="h-3.5 overflow-hidden rounded-[10px] bg-zinc-200 dark:bg-zinc-600"
        style={{ boxShadow: "inset 0 1px 2px rgba(0,0,0,0.06)" }}
      >
        <div
          className="h-full rounded-[10px] transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%`, background: barGradient }}
        />
      </div>
    </div>
  );
}
