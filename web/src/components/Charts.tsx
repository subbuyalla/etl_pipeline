type Point = { label?: string; value: number };

function normalize(values: number[]): number[] {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return values.map(() => 0.5);
  return values.map((v) => (v - min) / (max - min));
}

export function Sparkline({
  points,
  width = 220,
  height = 56,
  stroke = "var(--accent, #2a6f6a)",
}: {
  points: Point[];
  width?: number;
  height?: number;
  stroke?: string;
}) {
  const values = points.map((p) => p.value).filter((v) => Number.isFinite(v));
  if (values.length < 2) {
    return <div className="chart-empty">Not enough points</div>;
  }
  const norm = normalize(values);
  const pad = 4;
  const coords = norm.map((n, i) => {
    const x = pad + (i / (norm.length - 1)) * (width - pad * 2);
    const y = height - pad - n * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const area = `M ${coords[0]} L ${coords.join(" L ")} L ${width - pad},${height - pad} L ${pad},${height - pad} Z`;
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img">
      <path d={area} fill="color-mix(in srgb, var(--accent, #2a6f6a) 16%, transparent)" />
      <polyline fill="none" stroke={stroke} strokeWidth="2" points={coords.join(" ")} />
    </svg>
  );
}

export function BarChart({
  points,
  height = 120,
  color = "var(--accent, #2a6f6a)",
}: {
  points: Point[];
  height?: number;
  color?: string;
}) {
  if (!points.length) return <div className="chart-empty">No data</div>;
  const max = Math.max(...points.map((p) => p.value), 1);
  return (
    <div className="bar-chart" style={{ height }}>
      {points.map((p, i) => {
        const pct = Math.max(4, (p.value / max) * 100);
        return (
          <div key={`${p.label ?? i}`} className="bar-col" title={`${p.label ?? ""}: ${p.value}`}>
            <div className="bar-fill" style={{ height: `${pct}%`, background: color }} />
            <span className="bar-label">{p.label ?? ""}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Donut({
  segments,
  size = 88,
}: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = 36;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox="0 0 100 100" className="donut">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--line)" strokeWidth="12" />
        {segments.map((seg) => {
          const len = (seg.value / total) * c;
          const el = (
            <circle
              key={seg.label}
              cx="50"
              cy="50"
              r={r}
              fill="none"
              stroke={seg.color}
              strokeWidth="12"
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 50 50)"
            />
          );
          offset += len;
          return el;
        })}
        <text x="50" y="54" textAnchor="middle" className="donut-center">
          {total}
        </text>
      </svg>
      <ul className="donut-legend">
        {segments.map((s) => (
          <li key={s.label}>
            <span className="swatch" style={{ background: s.color }} />
            {s.label}: {s.value}
          </li>
        ))}
      </ul>
    </div>
  );
}
