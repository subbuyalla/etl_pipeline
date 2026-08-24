import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function MiniSpark({ values, tone }: { values: number[]; tone: string }) {
  if (!values.length) return <span className="spark-empty" />;
  const max = Math.max(...values, 1);
  const w = 72;
  const h = 28;
  const pts = values
    .map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * w;
      const y = h - (v / max) * (h - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
  const color = tone === "bad" ? "#f87171" : tone === "warn" ? "#fb923c" : "#4ade80";
  return (
    <svg width={w} height={h} className="spark" aria-hidden>
      <polyline fill="none" stroke={color} strokeWidth="2" points={pts} />
    </svg>
  );
}

const tooltipStyle = {
  background: "#151a24",
  border: "1px solid #2a3344",
  borderRadius: 8,
  fontSize: 12,
};

export function RunsChart({ data }: { data: Record<string, string | number>[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1f2736" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#8b95a7", fontSize: 11 }} tickFormatter={shortDate} />
        <YAxis tick={{ fill: "#8b95a7", fontSize: 11 }} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend />
        <Line type="monotone" dataKey="success" stroke="#4ade80" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="failed" stroke="#f87171" strokeWidth={2} dot={false} />
        {"running" in (data[0] || {}) ? (
          <Line type="monotone" dataKey="running" stroke="#60a5fa" strokeWidth={2} dot={false} />
        ) : null}
        {"cancelled" in (data[0] || {}) ? (
          <Line type="monotone" dataKey="cancelled" stroke="#94a3b8" strokeWidth={2} dot={false} />
        ) : null}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function DurationChart({ data }: { data: Record<string, string | number>[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1f2736" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#8b95a7", fontSize: 11 }} tickFormatter={shortDate} />
        <YAxis tick={{ fill: "#8b95a7", fontSize: 11 }} />
        <Tooltip contentStyle={tooltipStyle} />
        <Line type="monotone" dataKey="avg_duration_minutes" name="minutes" stroke="#a78bfa" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ThroughputChart({ data }: { data: Record<string, string | number>[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1f2736" vertical={false} />
        <XAxis dataKey="date" tick={{ fill: "#8b95a7", fontSize: 11 }} tickFormatter={shortDate} />
        <YAxis tick={{ fill: "#8b95a7", fontSize: 11 }} />
        <Tooltip contentStyle={tooltipStyle} />
        <Area type="monotone" dataKey="rows_per_sec" name="rows/sec" stroke="#60a5fa" fill="#1d4ed8" fillOpacity={0.35} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function HBarChart({
  data,
  nameKey,
  valueKey,
  color,
}: {
  data: Record<string, string | number>[];
  nameKey: string;
  valueKey: string;
  color: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="#1f2736" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#8b95a7", fontSize: 11 }} />
        <YAxis type="category" dataKey={nameKey} width={110} tick={{ fill: "#c5cdd8", fontSize: 11 }} />
        <Tooltip contentStyle={tooltipStyle} />
        <Bar dataKey={valueKey} fill={color} radius={[0, 6, 6, 0]} barSize={14} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function shortDate(value: string) {
  if (!value) return "";
  return String(value).slice(5, 10);
}
