import { useEffect, useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Clock, CheckCircle2, AlertTriangle, XCircle, Search, GitBranch,
  ArrowUpRight, Activity, Zap, RotateCcw, Timer, TrendingUp,
} from 'lucide-react';
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { TableSkeleton } from '../components/SkeletonLoaders';
import { fetchMetrics, fetchOverviewCharts, fetchFilters } from '../api/client';

const STATUS_CONFIG = {
  success: { label: 'Success', color: '#10B981', bg: '#ECFDF5', border: '#A7F3D0' },
  failed: { label: 'Failed', color: '#EF4444', bg: '#FEF2F2', border: '#FECACA' },
  running: { label: 'Running', color: '#F59E0B', bg: '#FFFBEB', border: '#FDE68A' },
  cancelled: { label: 'Cancelled', color: '#94A3B8', bg: '#F1F5F9', border: '#E2E8F0' },
};

function asList(val) {
  if (val == null) return [];
  if (Array.isArray(val)) return val;
  return [val];
}

function dash(v) {
  return v == null || v === '' ? '—' : v;
}

function kpiMapFrom(list) {
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

function buildDateParams(headerDatePreset, customDateRange) {
  const params = {};
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

function handleDateChange(setPreset, setRange, val) {
  if (typeof val === 'string') {
    setPreset(val);
    setRange(null);
  } else if (val?.start && val?.end) {
    setPreset('custom');
    setRange(val);
  }
}

function statusPillClass(statusKey, status) {
  const s = String(statusKey || status || '').toLowerCase();
  if (['healthy', 'success', 'good', 'ok'].includes(s)) return 'good';
  if (['failed', 'error', 'critical'].includes(s)) return 'critical';
  if (['degraded', 'warning', 'warn', 'running'].includes(s)) return 'warning';
  return 'info';
}

function TimelineTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{
      background: 'var(--bg-card, #FFFFFF)',
      border: '1px solid var(--border)',
      boxShadow: '0 4px 14px rgba(0,0,0,0.12)',
      borderRadius: 8,
      padding: '8px 14px',
      fontSize: 12,
    }}>
      <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
        {p.date || p.shortDate}
      </div>
      {payload.map((entry, idx) => (
        <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: entry.stroke || entry.color || entry.fill }} />
          <span style={{ color: 'var(--text-secondary)' }}>{entry.name}:</span>
          <strong style={{ color: 'var(--text-primary)' }}>
            {entry.value}{entry.name.includes('%') || entry.name.includes('Rate') ? '%' : entry.name.includes('Latency') || entry.name.includes('Duration') ? 's' : ''}
          </strong>
        </div>
      ))}
    </div>
  );
}

export default function Metrics() {
  // API State
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [metricsData, setMetricsData] = useState(null);
  const [overviewCharts, setOverviewCharts] = useState(null);

  // Filter Catalog State (populated directly from GET /api/v1/filters)
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [toolOptions, setToolOptions] = useState([]);
  const [statusOptions, setStatusOptions] = useState([]);

  // Active Filter State
  const [search, setSearch] = useState('');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [toolFilter, setToolFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [page, setPage] = useState(1);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  // Load filter catalog from API
  useEffect(() => {
    let active = true;
    fetchFilters()
      .then((res) => {
        if (!active || !res) return;
        const pipes = asList(res.pipelines || res.items);
        const seen = new Set();
        setPipelineOptions(pipes.filter((p) => {
          const id = p?.pipeline_id || p?.id || p;
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        }));
        setToolOptions(asList(res.tools || res.tool_options || []).filter(Boolean));
        setStatusOptions(asList(res.statuses || []).filter(Boolean));
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  // Build query parameters for GET /api/v1/metrics
  const queryParams = useCallback(() => {
    const params = buildDateParams(headerDatePreset, customDateRange);
    if (pipelineFilter && pipelineFilter !== 'All') {
      const match = pipelineOptions.find((p) => (p.pipeline_id === pipelineFilter || p.pipeline_name === pipelineFilter || p === pipelineFilter));
      params.pipeline_id = match?.pipeline_id || match?.id || pipelineFilter;
      params.pipeline_name = match?.pipeline_name || match?.name || pipelineFilter;
    }
    if (toolFilter && toolFilter !== 'All') {
      params.tool = toolFilter;
    }
    if (statusFilter && statusFilter !== 'All') {
      params.status = statusFilter;
    }
    params.page = page;
    params.page_size = 20;
    return params;
  }, [headerDatePreset, customDateRange, pipelineFilter, toolFilter, statusFilter, pipelineOptions, page]);

  // Load live metrics and continuous overview timeline charts
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qParams = queryParams();
      const timelinePreset = headerDatePreset === 'all' ? '30d' : headerDatePreset;
      const chartParams = { ...qParams, preset: timelinePreset };

      const [mRes, cRes] = await Promise.all([
        fetchMetrics(qParams),
        fetchOverviewCharts(chartParams).catch(() => null),
      ]);

      if (mRes && mRes.ok !== false) {
        setMetricsData(mRes);
      } else {
        setError(mRes?.error || 'Failed to load metrics');
      }

      if (cRes && cRes.charts) {
        setOverviewCharts(cRes);
      }
    } catch (err) {
      console.error('Metrics fetch error:', err);
      setError(err?.response?.data?.detail || err.message || 'Error connecting to metrics API');
    } finally {
      setLoading(false);
    }
  }, [queryParams, headerDatePreset]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Base data directly from API response
  const kpiMap = useMemo(() => kpiMapFrom(metricsData?.kpis), [metricsData]);
  const summary = metricsData?.summary || {};
  const itemsList = useMemo(() => asList(metricsData?.items), [metricsData]);

  // Client-level filter synchronization across Search and Status
  const filteredItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    const stFilter = statusFilter.toLowerCase();
    return itemsList.filter((item) => {
      const st = String(item.status_key || item.status || '').toLowerCase();
      if (statusFilter !== 'All') {
        if (stFilter === 'failed' && !['failed', 'error', 'critical'].includes(st)) return false;
        if (stFilter === 'success' && !['success', 'healthy', 'good', 'ok'].includes(st)) return false;
        if (stFilter === 'running' && st !== 'running') return false;
        if (stFilter === 'cancelled' && st !== 'cancelled') return false;
        if (!['failed', 'success', 'running', 'cancelled'].includes(stFilter) && st !== stFilter) return false;
      }
      if (!q) return true;
      const hay = [item.pipeline_name, item.tool, item.status, item.status_key].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [itemsList, search, statusFilter]);

  const hasActiveFilters = Boolean(search || pipelineFilter !== 'All' || toolFilter !== 'All' || statusFilter !== 'All');
  const isZeroMatching = hasActiveFilters && filteredItems.length === 0;

  const resetFilters = useCallback(() => {
    setSearch('');
    setPipelineFilter('All');
    setToolFilter('All');
    setStatusFilter('All');
    setPage(1);
  }, []);

  // Synchronized KPIs: when active filters produce 0 matches, the WHOLE dashboard reflects 0
  const totalRuns = isZeroMatching ? 0 : Number(kpiMap.runs?.value ?? summary.total_runs ?? 0);
  const failedRuns = isZeroMatching ? 0 : Number(kpiMap.failed_runs?.value ?? summary.failed_runs ?? 0);
  const avgDurationDisplay = isZeroMatching ? '—' : (kpiMap.avg_duration?.display || '—');
  const successRateDisplay = isZeroMatching ? '—' : (kpiMap.success_rate?.display || (totalRuns > 0 ? '100.0%' : '—'));
  const avgFreshnessDisplay = isZeroMatching ? '—' : (kpiMap.avg_freshness?.display || (kpiMap.avg_freshness?.value != null ? `${kpiMap.avg_freshness.value}h` : '—'));
  const runFrequencyDisplay = isZeroMatching ? '0.0 runs/hr' : (kpiMap.run_frequency?.display || (kpiMap.run_frequency?.value != null ? `${kpiMap.run_frequency.value} runs/hr` : '—'));

  // Synchronized timeline chart data
  const timelineData = useMemo(() => {
    if (isZeroMatching) return [];

    const charts = overviewCharts?.charts;
    const labels = asList(charts?.labels);
    const rates = asList(charts?.success_rate_over_time);
    const durations = asList(metricsData?.series?.duration);

    if (!labels.length) {
      return durations.map((d, i) => {
        const ts = d.timestamp || d.time || '';
        const short = ts.length >= 10 ? ts.substring(5, 10) : ts;
        return {
          date: ts,
          shortDate: short || `Run ${i + 1}`,
          duration: Number(d.duration_seconds) || 0,
          rate: 100,
        };
      });
    }

    return labels.map((lbl, idx) => {
      const short = lbl.length >= 10 ? lbl.substring(5, 10) : lbl;
      const dMatch = durations.find((d) => (d.timestamp && d.timestamp.startsWith(lbl)) || d.time?.startsWith(lbl));
      const durSec = dMatch ? Number(dMatch.duration_seconds) || 0 : 0;
      const rateVal = rates[idx] != null ? Math.round(Number(rates[idx])) : 0;

      return {
        date: lbl,
        shortDate: short,
        duration: durSec,
        rate: rateVal,
      };
    });
  }, [overviewCharts, metricsData, isZeroMatching]);

  // Synchronized Status breakdown directly from charts.runs_by_status
  const statusCounts = useMemo(() => {
    if (isZeroMatching) {
      return {
        rows: [
          { key: 'success', name: 'Success', value: 0, ...STATUS_CONFIG.success },
          { key: 'failed', name: 'Failed', value: 0, ...STATUS_CONFIG.failed },
          { key: 'running', name: 'Running', value: 0, ...STATUS_CONFIG.running },
          { key: 'cancelled', name: 'Cancelled', value: 0, ...STATUS_CONFIG.cancelled },
        ],
        total: 0,
      };
    }

    const raw = metricsData?.charts?.runs_by_status || {};
    const successVal = Number(raw.success ?? summary.success_runs) || 0;
    const failedVal = Number(raw.failed ?? summary.failed_runs) || 0;
    const runningVal = Number(raw.running) || 0;
    const cancelledVal = Number(raw.cancelled) || 0;

    const rows = [
      { key: 'success', name: 'Success', value: successVal, ...STATUS_CONFIG.success },
      { key: 'failed', name: 'Failed', value: failedVal, ...STATUS_CONFIG.failed },
      { key: 'running', name: 'Running', value: runningVal, ...STATUS_CONFIG.running },
      { key: 'cancelled', name: 'Cancelled', value: cancelledVal, ...STATUS_CONFIG.cancelled },
    ];
    const total = rows.reduce((acc, r) => acc + r.value, 0);
    return { rows, total };
  }, [metricsData, summary, isZeroMatching]);

  // Synchronized Top pipelines by duration
  const topByDuration = useMemo(() => {
    if (isZeroMatching) return [];
    const rows = asList(metricsData?.charts?.top_by_duration);
    if (!rows.length) return [];

    // Filter to items that match the active filters
    const matchingIds = new Set(filteredItems.map((i) => i.pipeline_id || i.pipeline_name));
    const matchingRows = hasActiveFilters ? rows.filter((r) => matchingIds.has(r.pipeline_id) || matchingIds.has(r.pipeline_name)) : rows;
    if (!matchingRows.length) return [];

    const maxSec = Math.max(...matchingRows.map((r) => Number(r.avg_duration_seconds) || 0), 1);
    return matchingRows.map((r, idx) => {
      const sec = Number(r.avg_duration_seconds) || 0;
      return {
        ...r,
        rank: idx + 1,
        seconds: sec,
        pct: Math.round((sec / maxSec) * 100),
      };
    });
  }, [metricsData, filteredItems, hasActiveFilters, isZeroMatching]);

  return (
    <div className="fade-in" style={{ padding: '0 0 40px 0' }}>
      {/* 1. Header with date preset and export */}
      <PageHeader
        title="Metrics"
        subtitle="Real-time pipeline execution performance, reliability, and runtime latency telemetry"
        datePreset={headerDatePreset}
        customStart={customDateRange?.start || ''}
        customEnd={customDateRange?.end || ''}
        onDateChange={(val) => {
          handleDateChange(setHeaderDatePreset, setCustomDateRange, val);
          setPage(1);
        }}
        onRefresh={loadData}
      />

      <div className="page-body">
        {/* 2. TOP FILTERS BAR (Fully wired to API and dashboard state) */}
        <div className="filters-bar" style={{ marginBottom: 18 }}>
          <div className="search-box" style={{ minWidth: 260, flex: 1, maxWidth: 360 }}>
            <Search size={14} />
            <input
              placeholder="Search pipelines, connectors, or status…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>

          <div className="filter-select">
            <label>Pipeline</label>
            <select
              className="select-control"
              value={pipelineFilter}
              onChange={(e) => {
                setPipelineFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="All">All Pipelines</option>
              {pipelineOptions.map((p) => {
                const id = p.pipeline_id || p.id || p;
                const name = p.pipeline_name || p.name || id;
                return (
                  <option key={id} value={id}>
                    {name}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="filter-select">
            <label>Tool / Connector</label>
            <select
              className="select-control"
              value={toolFilter}
              onChange={(e) => {
                setToolFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="All">All Tools</option>
              {toolOptions.map((t) => {
                const id = typeof t === 'object' ? t.id : t;
                const label = typeof t === 'object' ? t.label || t.id : t;
                return (
                  <option key={id} value={id}>
                    {label}
                  </option>
                );
              })}
            </select>
          </div>

          <div className="filter-select">
            <label>Status</label>
            <select
              className="select-control"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
            >
              <option value="All">All Statuses</option>
              {statusOptions.length > 0 ? (
                statusOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label || s.id}
                  </option>
                ))
              ) : (
                <>
                  <option value="success">Success</option>
                  <option value="failed">Failed</option>
                  <option value="running">Running</option>
                  <option value="cancelled">Cancelled</option>
                </>
              )}
            </select>
          </div>

          {hasActiveFilters && (
            <button className="clear-filters-btn" onClick={resetFilters} title="Reset all filters">
              <RotateCcw size={12} style={{ display: 'inline', marginRight: 4 }} />
              Reset Filters
            </button>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="obs-alert is-bad" style={{ marginBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle size={18} />
              <div><strong>Failed to load metrics telemetry:</strong> {error}</div>
            </div>
            <button type="button" className="btn btn-secondary btn-sm" onClick={loadData}>
              Retry
            </button>
          </div>
        )}

        {/* 3. Executive KPI Summary Bar (100% Synchronized with Filters) */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}>
          {/* 1. Average Duration */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: '3px solid #0284C7' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Average Duration
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 6, background: '#E0F2FE', color: '#0284C7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Clock size={15} />
              </div>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1 }}>
              {avgDurationDisplay}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'No matching scope' : (kpiMap.avg_duration?.delta_label || 'Calculated runtime')}
            </div>
          </div>

          {/* 2. Total Runs */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: '3px solid #10B981' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Runs
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 6, background: 'var(--brand-dim)', color: 'var(--brand)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Activity size={15} />
              </div>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1 }}>
              {totalRuns}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'Matching active filters' : (kpiMap.runs?.delta_label || 'Runs in selected scope')}
            </div>
          </div>

          {/* 3. Failed Runs */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: `3px solid ${failedRuns > 0 ? '#EF4444' : '#94A3B8'}` }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Failed Runs
              </span>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: failedRuns > 0 ? '#FEF2F2' : '#F8FAFC',
                color: failedRuns > 0 ? '#DC2626' : '#64748B',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <XCircle size={15} />
              </div>
            </div>
            <div style={{
              fontSize: 26,
              fontWeight: 800,
              color: failedRuns > 0 ? '#DC2626' : 'var(--text-primary)',
              lineHeight: 1.1,
            }}>
              {failedRuns}
            </div>
            <div style={{ fontSize: 11.5, color: failedRuns > 0 ? '#DC2626' : 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'Matching active filters' : failedRuns > 0 ? 'Failures detected' : (kpiMap.failed_runs?.delta_label || 'Zero failures observed')}
            </div>
          </div>

          {/* 4. Success Rate */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: '3px solid #10B981' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Success Rate
              </span>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: '#ECFDF5',
                color: '#059669',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <CheckCircle2 size={15} />
              </div>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1 }}>
              {successRateDisplay}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'No runs in scope' : (kpiMap.success_rate?.delta_label || 'Terminal run reliability')}
            </div>
          </div>

          {/* 5. Avg Freshness */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: '3px solid #F59E0B' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Avg Freshness
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 6, background: '#FFFBEB', color: '#D97706', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Timer size={15} />
              </div>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1 }}>
              {avgFreshnessDisplay}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'No pipelines in scope' : (kpiMap.avg_freshness?.delta_label || 'Across active pipelines')}
            </div>
          </div>

          {/* 6. Run Frequency / Throughput */}
          <div className="card kpi-card" style={{ padding: '16px 18px', borderLeft: '3px solid #A855F7' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Run Frequency
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 6, background: '#F3E8FF', color: '#9333EA', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Zap size={15} />
              </div>
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1.1 }}>
              {runFrequencyDisplay}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 6 }}>
              {isZeroMatching ? 'No activity in scope' : (kpiMap.run_frequency?.delta_label || 'Execution cadence')}
            </div>
          </div>
        </div>

        {/* 4. Rich Timeline Area Charts (100% Synchronized with Filters) */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))', gap: 16, marginBottom: 20 }}>
          {/* Chart 1: Execution Latency Trend */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-header" style={{ padding: '16px 18px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <div>
                <span className="card-title" style={{ fontSize: 15 }}>Execution Latency Over Time</span>
                <span className="card-subtitle">Runtime duration in seconds across execution timeline</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#0284C7', fontSize: 12, fontWeight: 600 }}>
                <Clock size={14} />
                <span>Current: {avgDurationDisplay}</span>
              </div>
            </div>

            <div style={{ padding: '16px 18px', flex: 1, minHeight: 250, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              {isZeroMatching || timelineData.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 30 }}>
                  <AlertTriangle size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
                  <div>No execution latency data matching active filters</div>
                  {hasActiveFilters && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={resetFilters} style={{ marginTop: 10 }}>
                      Reset Filters
                    </button>
                  )}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={230}>
                  <AreaChart data={timelineData} margin={{ top: 12, right: 16, left: -10, bottom: 4 }}>
                    <defs>
                      <linearGradient id="latencyAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.45} />
                        <stop offset="95%" stopColor="#0284C7" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                    <XAxis
                      dataKey="shortDate"
                      tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                      axisLine={{ stroke: 'var(--border)' }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                      axisLine={false}
                      tickLine={false}
                      unit="s"
                    />
                    <Tooltip content={<TimelineTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="duration"
                      name="Latency"
                      stroke="#F59E0B"
                      strokeWidth={2.5}
                      fillOpacity={1}
                      fill="url(#latencyAreaGrad)"
                      dot={false}
                      activeDot={{ r: 5, fill: '#F59E0B' }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Chart 2: Reliability & Success Rate Trend */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-header" style={{ padding: '16px 18px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <div>
                <span className="card-title" style={{ fontSize: 15 }}>Reliability & Success Rate Trend</span>
                <span className="card-subtitle">Execution success percentage across timeline</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#2563EB', fontSize: 12, fontWeight: 600 }}>
                <TrendingUp size={14} />
                <span>{successRateDisplay}</span>
              </div>
            </div>

            <div style={{ padding: '16px 18px', flex: 1, minHeight: 250, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              {isZeroMatching || timelineData.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 30 }}>
                  <AlertTriangle size={24} style={{ marginBottom: 8, opacity: 0.5 }} />
                  <div>No reliability data matching active filters</div>
                  {hasActiveFilters && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={resetFilters} style={{ marginTop: 10 }}>
                      Reset Filters
                    </button>
                  )}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={230}>
                  <AreaChart data={timelineData} margin={{ top: 12, right: 16, left: -10, bottom: 4 }}>
                    <defs>
                      <linearGradient id="successAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#2563EB" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#2563EB" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                    <XAxis
                      dataKey="shortDate"
                      tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                      axisLine={{ stroke: 'var(--border)' }}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, 100]}
                      ticks={[0, 25, 50, 75, 100]}
                      unit="%"
                      tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip content={<TimelineTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="rate"
                      name="Success Rate"
                      stroke="#2563EB"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#successAreaGrad)"
                      dot={{ r: 3, fill: '#2563EB' }}
                      activeDot={{ r: 6, fill: '#1D4ED8' }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </div>

        {/* 5. Second Row: Symmetrical Outcomes Breakdown & Latency Rankings */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))', gap: 16, marginBottom: 20 }}>
          {/* Card 3: Execution Outcomes Breakdown */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-header" style={{ padding: '16px 18px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <div>
                <span className="card-title" style={{ fontSize: 15 }}>Execution Outcomes Breakdown</span>
                <span className="card-subtitle">Terminal states across all executions</span>
              </div>
            </div>

            <div style={{ padding: '20px', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              {statusCounts.total === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20 }}>
                  No execution outcomes matching active filters
                </div>
              ) : (
                <div>
                  {/* Multi-segment distribution progress bar */}
                  <div style={{
                    height: 12,
                    width: '100%',
                    background: 'var(--border-subtle)',
                    borderRadius: 6,
                    overflow: 'hidden',
                    display: 'flex',
                    marginBottom: 14,
                  }}>
                    {statusCounts.rows.map((r) => {
                      const pct = statusCounts.total ? (r.value / statusCounts.total) * 100 : 0;
                      if (pct === 0) return null;
                      return (
                        <div
                          key={r.key}
                          style={{
                            height: '100%',
                            width: `${pct}%`,
                            background: r.color,
                            transition: 'width 0.6s ease',
                          }}
                          title={`${r.name}: ${r.value} (${pct.toFixed(1)}%)`}
                        />
                      );
                    })}
                  </div>

                  {/* 4-cell status badge matrix */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                    {statusCounts.rows.map((row) => {
                      const pct = statusCounts.total ? ((row.value / statusCounts.total) * 100).toFixed(1) : '0.0';
                      return (
                        <div
                          key={row.key}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '8px 12px',
                            borderRadius: 6,
                            background: row.value > 0 ? row.bg : 'var(--bg-card-subtle)',
                            border: `1px solid ${row.value > 0 ? row.border : 'var(--border)'}`,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ width: 8, height: 8, borderRadius: '50%', background: row.color }} />
                            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{row.name}</span>
                          </div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                            {row.value} <span style={{ fontSize: 10.5, fontWeight: 500, color: 'var(--text-muted)' }}>({pct}%)</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Card 4: Slowest Pipelines by Latency */}
          <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-header" style={{ padding: '16px 18px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <div>
                <span className="card-title" style={{ fontSize: 15 }}>Slowest Pipelines by Latency</span>
                <span className="card-subtitle">Runtime ranking across executed pipelines</span>
              </div>
            </div>

            <div style={{ padding: '16px 18px', flex: 1, overflowY: 'auto' }}>
              {topByDuration.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20 }}>
                  No pipeline latency data matching active filters
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {topByDuration.map((p) => (
                    <div
                      key={p.pipeline_id || p.rank}
                      style={{
                        padding: '10px 12px',
                        background: 'var(--bg-card-subtle)',
                        borderRadius: 8,
                        border: '1px solid var(--border)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{
                            width: 18,
                            height: 18,
                            borderRadius: '50%',
                            background: '#0284C7',
                            color: '#FFFFFF',
                            fontSize: 10,
                            fontWeight: 700,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}>
                            {p.rank}
                          </span>
                          <strong style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
                            {dash(p.pipeline_name)}
                          </strong>
                          {p.tool && (
                            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', background: 'var(--border-subtle)', padding: '1px 5px', borderRadius: 4 }}>
                              {p.tool}
                            </span>
                          )}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <strong style={{ fontSize: 13, color: '#0284C7' }}>
                            {p.seconds}s
                          </strong>
                          {p.status && (
                            <span className={`status-pill ${statusPillClass(p.status_key, p.status)}`} style={{ fontSize: 10, padding: '1px 6px' }}>
                              {p.status}
                            </span>
                          )}
                        </div>
                      </div>
                      <div style={{ height: 5, width: '100%', background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                        <div
                          style={{
                            height: '100%',
                            width: `${Math.max(10, p.pct)}%`,
                            background: 'linear-gradient(90deg, #0284C7 0%, #38BDF8 100%)',
                            borderRadius: 3,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 6. Pipeline Execution Telemetry Table */}
        <div className="card">
          <div className="card-header" style={{ padding: '16px 18px', borderBottom: '1px solid var(--border-subtle)' }}>
            <div>
              <span className="card-title" style={{ fontSize: 15 }}>Pipeline Execution Telemetry</span>
              <span className="card-subtitle">
                Showing {filteredItems.length} of {itemsList.length} monitored pipelines
              </span>
            </div>
          </div>

          {loading ? (
            <TableSkeleton rows={6} cols={6} showHeader={false} />
          ) : filteredItems.length === 0 ? (
            <div className="obs-empty-card" style={{ padding: 40, textAlign: 'center' }}>
              <p style={{ color: 'var(--text-muted)', margin: '0 0 12px 0' }}>
                No pipelines matched the selected filter criteria.
              </p>
              {hasActiveFilters && (
                <button type="button" className="btn btn-secondary btn-sm" onClick={resetFilters}>
                  Clear Filters
                </button>
              )}
            </div>
          ) : (
            <div className="table-wrapper">
              <table className="vithi-table">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>Tool</th>
                    <th>Status</th>
                    <th>Success Rate</th>
                    <th>Avg Duration</th>
                    <th>Freshness</th>
                    <th>Total Runs</th>
                    <th>Last Execution</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((p, idx) => {
                    const rate = Number(p.success_rate_pct);
                    const freshness = p.avg_freshness_display || (p.avg_freshness_hours != null ? `${p.avg_freshness_hours}h` : '—');
                    return (
                      <tr key={p.pipeline_id || idx}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <GitBranch size={15} color="#0284C7" />
                            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                              {dash(p.pipeline_name)}
                            </span>
                          </div>
                        </td>
                        <td>
                          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            {dash(p.tool)}
                          </span>
                        </td>
                        <td>
                          <span className={`status-pill ${statusPillClass(p.status_key, p.status)}`}>
                            {p.status || p.status_key || '—'}
                          </span>
                        </td>
                        <td>
                          <strong style={{
                            color: !Number.isFinite(rate) ? 'var(--text-muted)'
                              : rate >= 99 ? '#10B981' : rate >= 90 ? '#F59E0B' : '#EF4444',
                          }}>
                            {Number.isFinite(rate) ? `${rate}%` : '—'}
                          </strong>
                        </td>
                        <td style={{ fontWeight: 600 }}>
                          {p.duration || (p.avg_duration_seconds != null ? `${p.avg_duration_seconds}s` : '—')}
                        </td>
                        <td>
                          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            {freshness}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontWeight: 600 }}>{p.runs ?? '—'}</span>
                        </td>
                        <td>
                          <div style={{ fontSize: 12, color: 'var(--text-primary)' }}>
                            {p.last_run_age || '—'}
                          </div>
                          {p.last_run_at && (
                            <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                              {p.last_run_at}
                            </div>
                          )}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <Link
                            to={`/pipelines`}
                            className="btn btn-secondary btn-sm"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'none' }}
                          >
                            <span>Runs</span>
                            <ArrowUpRight size={13} />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
