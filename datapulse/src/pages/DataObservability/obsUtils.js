/**
 * Shared helpers for Data Observability command screens.
 * Values always come from the live API — never invent demo numbers.
 */

export function dash(v) {
  return v == null || v === '' ? '—' : v;
}

export function kpiMapFrom(list) {
  if (!list) return {};
  if (Array.isArray(list)) {
    const map = {};
    list.forEach((k) => {
      if (k?.id) map[k.id] = k;
    });
    return map;
  }
  if (typeof list === 'object') {
    return list;
  }
  return {};
}

export function statusTone(status) {
  const s = String(status || '').toLowerCase();
  if (['good', 'healthy', 'fresh', 'success', 'pass', 'passed', 'ok'].includes(s)) return 'good';
  if (['warning', 'warn', 'delayed', 'degraded'].includes(s)) return 'warn';
  if (['critical', 'stale', 'failed', 'fail', 'poor', 'error', 'unhealthy'].includes(s)) return 'crit';
  return 'neutral';
}

export function buildDateParams(headerDatePreset, customDateRange) {
  const params = {};
  // Always send preset — volume (and quality) treat missing preset as a short
  // default window that can look empty, while preset=all returns full history.
  if (headerDatePreset === 'custom' && customDateRange) {
    params.start_date = customDateRange.start;
    params.end_date = customDateRange.end;
  } else if (headerDatePreset) {
    params.preset = headerDatePreset;
  } else {
    params.preset = 'all';
  }
  return params;
}

/** Short axis labels for volume / quality time series. */
export function formatSeriesTick(ts) {
  if (!ts) return '';
  const s = String(ts);
  // "2026-09-02" or "2026-09-09 14:00:00"
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) {
    const d = s.slice(5, 10); // MM-DD
    const t = s.length > 10 ? s.slice(11, 16) : '';
    return t && t !== '00:00' ? `${d} ${t}` : d;
  }
  return s;
}

export function formatBytes(n) {
  if (n == null || Number.isNaN(Number(n))) return null;
  const v = Number(n);
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  if (v < 1024 * 1024 * 1024) return `${(v / (1024 * 1024)).toFixed(1)} MB`;
  return `${(v / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function handleDateChange(setPreset, setRange, val) {
  if (typeof val === 'string') {
    setPreset(val);
    setRange(null);
  } else if (val?.start && val?.end) {
    setPreset('custom');
    setRange(val);
  }
}

export function lagPct(lagHours, slaHours) {
  if (lagHours == null || !slaHours) return null;
  return Math.min(220, Math.round((Number(lagHours) / Number(slaHours)) * 100));
}

function isDarkTheme() {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
}

/** Recharts tooltip styles — follows light/dark at render time */
export const TOOLTIP_STYLE = {
  get contentStyle() {
    const dark = isDarkTheme();
    return {
      background: dark ? '#141A30' : '#FFFFFF',
      border: `1px solid ${dark ? 'rgba(255,255,255,0.12)' : '#E2E8F0'}`,
      borderRadius: 8,
      fontSize: 12,
      boxShadow: dark ? '0 4px 12px rgba(0,0,0,0.45)' : '0 4px 12px rgba(0,0,0,0.08)',
      color: dark ? '#F8FAFC' : '#0F172A',
    };
  },
  get itemStyle() {
    return { color: isDarkTheme() ? '#F8FAFC' : '#0F172A' };
  },
  get labelStyle() {
    return { color: isDarkTheme() ? '#94A3B8' : '#64748B', fontWeight: 600 };
  },
};
