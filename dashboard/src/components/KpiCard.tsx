import { useEffect, useRef } from "react";
import type { Kpi, KpiDef } from "../api";
import { MiniSpark } from "./charts";

type Props = {
  kpi: Kpi;
  def?: KpiDef;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
};

export function KpiCard({ kpi, def, open, onToggle, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open, onClose]);

  const delta = kpi.delta;
  const deltaCls = delta == null ? "" : delta > 0 ? "up" : delta < 0 ? "down" : "";

  return (
    <article ref={ref} className={`kpi-card tone-${kpi.tone}`}>
      <div className="kpi-head">
        <span>{kpi.title}</span>
        <button type="button" className="info-btn" onClick={onToggle} aria-label={`Explain ${kpi.title}`}>
          i
        </button>
      </div>
      <div className="kpi-value">{kpi.display}</div>
      <div className="kpi-foot">
        {delta != null && kpi.delta_label ? (
          <span className={`delta ${deltaCls}`}>
            {delta > 0 ? "▲" : delta < 0 ? "▼" : "•"} {Math.abs(delta)} {kpi.delta_label}
          </span>
        ) : (
          <span className="muted">from metadata</span>
        )}
        <MiniSpark values={kpi.sparkline} tone={kpi.tone} />
      </div>
      {open && def ? (
        <div className="kpi-pop" role="dialog">
          <strong>{def.title}</strong>
          <p>{def.meaning}</p>
          <p className="formula">{def.formula}</p>
          <p className="muted">Tables: {def.tables}</p>
        </div>
      ) : null}
    </article>
  );
}
