import { useEffect, useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, AlertCircle, Search, CheckCircle, Shield, X, Clock,
  Activity, ChevronLeft, ChevronRight,
} from 'lucide-react';
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../components/SkeletonLoaders';
import { fetchIncidents, fetchIncidentDetail, fetchFilters } from '../api/client';
import { useCopilot } from '../context/CopilotContext';
import {
  dash, kpiMapFrom, buildDateParams, handleDateChange,
  formatSeriesTick, TOOLTIP_STYLE,
} from './DataObservability/obsUtils';

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function sevClass(sev) {
  const s = String(sev || '').toLowerCase();
  if (!s || s === '—') return 'info';
  if (s === 'critical') return 'critical';
  if (s === 'high' || s === 'medium') return 'warning';
  return 'info';
}

function statusClass(status) {
  const s = String(status || '').toLowerCase();
  if (['resolved', 'fixed', 'closed', 'success'].includes(s)) return 'success';
  if (['triage', 'acknowledged', 'investigating', 'in_progress', 'work in progress'].includes(s)) return 'warning';
  if (['open', 'failed', 'critical', 'error'].includes(s)) return 'critical';
  return 'warning';
}

function pickList(res) {
  if (!res) return [];
  if (Array.isArray(res.items) && res.items.length) return res.items;
  if (Array.isArray(res.incidents) && res.incidents.length) return res.incidents;
  if (Array.isArray(res.items)) return res.items;
  if (Array.isArray(res.incidents)) return res.incidents;
  if (Array.isArray(res)) return res;
  return [];
}

function sumSeries(arr) {
  if (!Array.isArray(arr)) return 0;
  return arr.reduce((a, b) => a + (Number(b) || 0), 0);
}

function incidentTitle(inc) {
  return inc?.title || inc?.pipeline_name || 'Pipeline run failure';
}

function incidentDesc(inc) {
  return inc?.description || inc?.error_message || inc?.summary || '';
}

function incidentStatus(inc) {
  return inc?.status || inc?.state || 'open';
}

function unwrapDetail(res, fallback) {
  if (!res || typeof res !== 'object') return fallback || null;
  const item = res.item || res.incident || (res.data && (res.data.item || res.data)) || res;
  // Ignore envelope-only payloads
  if (item === res && res.ok === true && !res.title && !res.pipeline_name && !res.id && !res.incident_id) {
    return { ...(fallback || {}), ...res, _envelopeOnly: true };
  }
  return { ...(fallback || {}), ...item };
}

function detailRows(detail) {
  if (!detail || detail._envelopeOnly) return [];
  const rows = [
    ['Title', detail.title || incidentTitle(detail)],
    ['Status', incidentStatus(detail)],
    ['Severity', detail.severity],
    ['Priority', detail.priority],
    ['Alert Group ID', detail.alert_group_id],
    ['Pipeline', detail.pipeline_name],
    ['Pipeline ID', detail.pipeline_id],
    ['Run ID', detail.run_id || detail.latest_run_id],
    ['Detected', detail.opened_at || detail.start_time || detail.detected_at],
    ['Resolved', detail.resolved_at || detail.end_time || detail.closed_at],
    ['Resolved By', detail.resolved_by],
    ['Root Cause', detail.root_cause],
    ['Resolution', detail.resolution],
    ['Age', detail.opened_age || detail.age],
    ['Tool', detail.tool || detail.etl_tool || detail.source_tool],
    ['Message', incidentDesc(detail)],
  ];
  return rows.filter(([, v]) => v != null && String(v).trim() !== '');
}

function KpiDelta({ kpi }) {
  if (kpi?.delta == null || kpi.delta === '') return null;
  const n = Number(kpi.delta);
  const up = n > 0;
  const color = up ? '#EF4444' : '#10B981';
  return (
    <div style={{ fontSize: 11, color, marginTop: 2, fontWeight: 600 }}>
      {up ? '+' : ''}{kpi.delta}
      {kpi.delta_label ? ` ${kpi.delta_label}` : ''}
    </div>
  );
}

export default function Incidents() {
  const { openCopilot } = useCopilot();
  const [incidents, setIncidents] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [series, setSeries] = useState(null);
  const [charts, setCharts] = useState(null);
  const [summary, setSummary] = useState(null);
  const [meta, setMeta] = useState(null);
  const [pagination, setPagination] = useState({ page: 1, page_size: 20, total: 0 });
  const [generatedAt, setGeneratedAt] = useState(null);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [incidentStatuses, setIncidentStatuses] = useState([
    { id: 'open', label: 'Open' },
    { id: 'resolved', label: 'Resolved' },
  ]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [search, setSearch] = useState('');
  const [sevFilter, setSevFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [toolFilter, setToolFilter] = useState('All');
  const [toolOptions, setToolOptions] = useState([]);
  const [page, setPage] = useState(1);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);

  useEffect(() => {
    let alive = true;
    fetchFilters()
      .then((res) => {
        if (!alive || !res) return;
        const pipes = res.pipelines || res.items || [];
        const seen = new Set();
        setPipelineOptions(pipes.filter((p) => {
          if (!p?.pipeline_id || seen.has(p.pipeline_id)) return false;
          seen.add(p.pipeline_id);
          return true;
        }));
        if (Array.isArray(res.incident_statuses) && res.incident_statuses.length) {
          setIncidentStatuses(res.incident_statuses);
        }
        if (Array.isArray(res.tools) && res.tools.length) {
          setToolOptions(res.tools);
        }
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const params = {
        ...buildDateParams(headerDatePreset, customDateRange),
        page,
        page_size: 20,
      };
      if (statusFilter !== 'All') params.status = statusFilter.toLowerCase();
      if (pipelineFilter !== 'All') params.pipeline_id = pipelineFilter;
      if (toolFilter !== 'All') params.tool = toolFilter.toLowerCase();

      const res = await fetchIncidents(params);
      setIncidents(pickList(res));
      setKpis(res?.kpis || []);
      setSeries(res?.series || null);
      setCharts(res?.charts || null);
      setSummary(res?.summary || null);
      setMeta(res?.meta || null);
      setPagination(res?.pagination || { page: 1, page_size: 20, total: 0 });
      setGeneratedAt(res?.generated_at || null);
    } catch (e) {
      console.error('Failed to load incidents:', e);
      setLoadError(e?.message || 'Failed to load incidents');
      setIncidents([]);
      setKpis([]);
      setSeries(null);
      setCharts(null);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange, statusFilter, pipelineFilter, toolFilter, page]);

  useEffect(() => { loadData(); }, [loadData]);

  const openDetail = async (inc) => {
    setSelected(inc);
    setDetail(unwrapDetail(null, inc));
    setDetailError(null);
    const id = inc?.id || inc?.incident_id;
    if (!id) {
      setDetailError('This row has no incident id — showing list fields only.');
      return;
    }
    setDetailLoading(true);
    try {
      const res = await fetchIncidentDetail(id);
      if (!res || res.ok === false) {
        setDetail(unwrapDetail(null, inc));
        setDetailError('Detail endpoint returned no incident payload — showing list fields only.');
      } else {
        setDetail(unwrapDetail(res, inc));
        setDetailError(null);
      }
    } catch (e) {
      console.error('Incident detail failed:', e);
      setDetail(unwrapDetail(null, inc));
      setDetailError('Could not load `/incidents/:id` — showing list fields only.');
    } finally {
      setDetailLoading(false);
    }
  };

  const kpiMap = useMemo(() => kpiMapFrom(kpis), [kpis]);
  const openCount = Number(kpiMap.open?.value ?? summary?.open ?? 0);
  const triageCount = Number(kpiMap.triage?.value ?? summary?.triage ?? 0);
  const criticalCount = Number(kpiMap.critical?.value ?? summary?.critical ?? 0);
  const resolvedCount = Number(kpiMap.resolved?.value ?? summary?.resolved ?? 0);

  const seriesTotals = useMemo(() => {
    const s = series?.incidents_over_time || {};
    return {
      failedRuns: sumSeries(s.failed_runs),
      successRuns: sumSeries(s.success_runs),
    };
  }, [series]);

  const incidentTrend = useMemo(() => {
    const s = series?.incidents_over_time;
    const labels = s?.labels || [];
    if (!labels.length) return [];
    return labels.map((lbl, i) => ({
      time: formatSeriesTick(lbl),
      Open: Number(s.open?.[i]) || 0,
      Resolved: Number(s.resolved?.[i]) || 0,
    }));
  }, [series]);

  const runTrend = useMemo(() => {
    const s = series?.incidents_over_time;
    const labels = s?.labels || [];
    if (!labels.length) return [];
    return labels.map((lbl, i) => ({
      time: formatSeriesTick(lbl),
      Failed: Number(s.failed_runs?.[i]) || 0,
      Success: Number(s.success_runs?.[i]) || 0,
    }));
  }, [series]);

  const severityData = useMemo(() => {
    const rows = charts?.by_severity || [];
    return rows.map((r) => ({
      name: String(r.severity || '').replace(/^\w/, (c) => c.toUpperCase()),
      count: Number(r.count) || 0,
    }));
  }, [charts]);

  const severityHasSignal = severityData.some((r) => r.count > 0);
  const incidentTrendHasSignal = incidentTrend.some((r) => r.Open > 0 || r.Resolved > 0);
  const runTrendHasSignal = runTrend.some((r) => r.Failed > 0 || r.Success > 0);

  const severitiesInFeed = useMemo(() => {
    const set = new Set();
    incidents.forEach((inc) => {
      const s = String(inc.severity || '').trim();
      if (s) set.add(s);
    });
    return Array.from(set).sort();
  }, [incidents]);

  // Severity is client-only (not an OpenAPI list filter). Search is client-only.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return incidents.filter((inc) => {
      const sev = String(inc.severity || '').toLowerCase();
      const matchSev = sevFilter === 'All' || sev === sevFilter.toLowerCase();
      if (!matchSev) return false;
      if (toolFilter !== 'All') {
        const toolHay = [inc.tool, inc.tool_name, inc.source_tool, inc.pipeline_name].filter(Boolean).join(' ').toLowerCase();
        if (!toolHay.includes(toolFilter.toLowerCase())) return false;
      }
      if (!q) return true;
      const hay = [
        incidentTitle(inc),
        incidentDesc(inc),
        inc.pipeline_name,
        inc.pipeline_id,
        incidentStatus(inc),
        inc.run_id,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [incidents, search, sevFilter, toolFilter]);

  const clientFiltersActive = Boolean(search.trim()) || sevFilter !== 'All';
  const apiFiltersActive =
    statusFilter !== 'All' ||
    pipelineFilter !== 'All' ||
    toolFilter !== 'All' ||
    headerDatePreset !== 'all';
  const filtersActive = clientFiltersActive || apiFiltersActive;

  const clearFilters = () => {
    setSearch('');
    setSevFilter('All');
    setStatusFilter('All');
    setPipelineFilter('All');
    setToolFilter('All');
    setPage(1);
    setHeaderDatePreset('all');
    setCustomDateRange(null);
  };

  const pageSize = pagination.page_size || 20;
  const total = pagination.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const showPager = total > pageSize;
  const inspectorRows = detailRows(detail || selected);

  const formula =
    meta?.formula ||
    'Open incident = pipeline whose latest run failed (deduped by pipeline_id). Resolved = failure in range then later success. Run series are run-status counts, not incident timelines.';

  if (loading && !kpis.length && !incidents.length && !series) {
    return (
      <div className="fade-in">
        <PageHeader title="Incidents" subtitle="Pipeline failure incidents from live run status." onRefresh={loadData} />
        <div className="page-body">
          <DashboardPageSkeleton kpiCount={4} chartCount={1} tableRows={6} tableCols={6} />
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <PageHeader
        title="Incidents"
        subtitle="Track open and resolved pipeline failures from live run status."
        onRefresh={loadData}
        datePreset={headerDatePreset}
        onDateChange={(v) => {
          handleDateChange(setHeaderDatePreset, setCustomDateRange, v);
          setPage(1);
        }}
        latestTimestamp={generatedAt}
      />

      <div className="page-body">
        {loadError && (
          <div className="obs-alert is-bad">
            <AlertTriangle size={18} />
            <div><strong>Could not load incidents.</strong> {loadError}</div>
          </div>
        )}

        {!loadError && (openCount > 0 || criticalCount > 0 ? (
          <div className={`obs-alert ${criticalCount > 0 ? 'is-bad' : 'is-warn'}`} style={{ display: 'flex', alignItems: 'center' }}>
            <AlertTriangle size={18} />
            <div>
              <strong>
                {openCount} open incident{openCount === 1 ? '' : 's'}
                {criticalCount > 0 ? ` · ${criticalCount} critical` : ''}
                {triageCount > 0 ? ` · ${triageCount} in triage` : ''}.
              </strong>
              {' '}Review failed pipeline runs in the feed below.
            </div>
            <button
              type="button"
              className="export-btn"
              style={{ marginLeft: 'auto', background: 'rgba(99, 102, 241, 0.1)', color: '#6366f1', border: '1px solid rgba(99, 102, 241, 0.3)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6 }}
              onClick={() => openCopilot('What is the root cause of our current open incidents?')}
            >
              ✨ Ask Copilot to Triage
            </button>
          </div>
        ) : (
          <div className="obs-alert is-ok">
            <CheckCircle size={18} />
            <div>
              <strong>No open incidents.</strong>
              {' '}Latest pipeline runs are not in a failed state
              {resolvedCount > 0 ? ` · ${resolvedCount} resolved in this range` : ''}.
            </div>
          </div>
        ))}

        <div className="filters-bar">
          <div className="search-box">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search loaded page (client)…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="filter-select">
            <label>Status (API)</label>
            <select
              className="select-control"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            >
              <option value="All">All</option>
              {incidentStatuses.map((s) => (
                <option key={s.id} value={s.id}>{s.label || s.id}</option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Severity (list)</label>
            <select
              className="select-control"
              value={sevFilter}
              onChange={(e) => setSevFilter(e.target.value)}
              disabled={incidents.length === 0 && sevFilter === 'All'}
            >
              <option value="All">All</option>
              {(severitiesInFeed.length
                ? severitiesInFeed
                : ['Critical', 'High', 'Medium', 'Low']
              ).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Connection / Tool</label>
            <select
              className="select-control"
              value={toolFilter}
              onChange={(e) => { setToolFilter(e.target.value); setPage(1); }}
              title="Filter incidents by connection or tool (Informatica, Snowflake, dbt, etc.)"
            >
              <option value="All">All Connections</option>
              {toolOptions.map((t) => (
                <option key={t.id || t.name} value={t.id || t.name}>
                  {t.label || t.name || t.id}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Pipeline (API)</label>
            <select
              className="select-control"
              value={pipelineFilter}
              onChange={(e) => { setPipelineFilter(e.target.value); setPage(1); }}
            >
              <option value="All">All pipelines</option>
              {pipelineOptions.map((p) => (
                <option key={p.pipeline_id} value={p.pipeline_id}>
                  {p.pipeline_name || p.pipeline_id}
                  {p.tool ? ` · ${p.tool}` : ''}
                </option>
              ))}
            </select>
          </div>
          {filtersActive && (
            <button type="button" className="export-btn" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>

        <div className="kpi-grid-4 mt-4">
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                <AlertTriangle size={18} />
              </div>
              <span className="kpi-label">{kpiMap.open?.title || 'Open'}</span>
            </div>
            <div className="kpi-value" style={{ color: openCount > 0 ? '#EF4444' : '#10B981', marginTop: 4 }}>
              {kpiMap.open?.display ?? openCount}
            </div>
            <KpiDelta kpi={kpiMap.open} />
            {!kpiMap.open?.delta && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                Latest run failed · per pipeline
              </div>
            )}
          </div>

          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}>
                <AlertCircle size={18} />
              </div>
              <span className="kpi-label">{kpiMap.triage?.title || 'In Triage'}</span>
            </div>
            <div className="kpi-value" style={{ color: triageCount > 0 ? '#F59E0B' : 'var(--text-muted)', marginTop: 4 }}>
              {kpiMap.triage?.display ?? triageCount}
            </div>
            <KpiDelta kpi={kpiMap.triage} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {triageCount === 0 ? 'API field — unused until triage states exist' : 'Under investigation'}
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                <Shield size={18} />
              </div>
              <span className="kpi-label">{kpiMap.critical?.title || 'Critical'}</span>
            </div>
            <div className="kpi-value" style={{ color: criticalCount > 0 ? '#EF4444' : '#10B981', marginTop: 4 }}>
              {kpiMap.critical?.display ?? criticalCount}
            </div>
            <KpiDelta kpi={kpiMap.critical} />
            {!kpiMap.critical?.delta && (
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                Highest severity open
              </div>
            )}
          </div>

          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}>
                <CheckCircle size={18} />
              </div>
              <span className="kpi-label">{kpiMap.resolved?.title || 'Resolved'}</span>
            </div>
            <div className="kpi-value" style={{ color: '#10B981', marginTop: 4 }}>
              {kpiMap.resolved?.display ?? resolvedCount}
            </div>
            <KpiDelta kpi={kpiMap.resolved} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              Fail then later success
            </div>
          </div>
        </div>

        {/* Split charts: incidents ≠ runs (API meta) */}
        <div className="grid-2 mt-4" style={{ gap: 16 }}>
          <div className="card">
            <div className="card-header">
              <div>
                <span className="card-title">Incidents over time</span>
                <span className="card-subtitle">Open vs resolved only — from series.incidents_over_time</span>
              </div>
            </div>
            <div style={{ height: 200, width: '100%', padding: '0 8px 8px' }}>
              {!incidentTrend.length ? (
                <div className="obs-simple-empty" style={{ height: '100%' }}>No incident series for this range</div>
              ) : !incidentTrendHasSignal ? (
                <div className="obs-simple-empty" style={{ height: '100%' }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>All zeros in this window</div>
                  <div style={{ fontSize: 12 }}>No open/resolved points in the incident series.</div>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={incidentTrend} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                    <defs>
                      <linearGradient id="incOpenGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#EF4444" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="incResGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="Open" stroke="#EF4444" fill="url(#incOpenGrad)" strokeWidth={2} />
                    <Area type="monotone" dataKey="Resolved" stroke="#10B981" fill="url(#incResGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div>
                <span className="card-title">
                  {severityHasSignal ? 'By severity' : 'Pipeline runs over time'}
                </span>
                <span className="card-subtitle">
                  {severityHasSignal
                    ? 'charts.by_severity'
                    : 'failed_runs / success_runs — run counts, not incidents'}
                </span>
              </div>
            </div>
            <div style={{ height: 200, width: '100%', padding: '0 8px 8px' }}>
              {severityHasSignal ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={severityData} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Bar dataKey="count" name="Incidents" fill="#6366F1" radius={[4, 4, 0, 0]} maxBarSize={48} />
                  </BarChart>
                </ResponsiveContainer>
              ) : !runTrend.length || !runTrendHasSignal ? (
                <div className="obs-simple-empty" style={{ height: '100%' }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>No severity or run signal</div>
                  <div style={{ fontSize: 12 }}>
                    Severity chart hidden while all counts are 0.
                    {seriesTotals.successRuns === 0 && seriesTotals.failedRuns === 0
                      ? ' Run series is also empty.'
                      : ''}
                  </div>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={runTrend} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="Success" stackId="runs" fill="#10B981" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Failed" stackId="runs" fill="#EF4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </div>

        {severityHasSignal && runTrendHasSignal && (
          <div className="card mt-4">
            <div className="card-header">
              <div>
                <span className="card-title">Pipeline runs over time</span>
                <span className="card-subtitle">Separate from incidents — failed_runs / success_runs</span>
              </div>
            </div>
            <div style={{ height: 180, width: '100%', padding: '0 8px 8px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={runTrend} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="Success" stackId="runs" fill="#10B981" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Failed" stackId="runs" fill="#EF4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        <div className={`inc-workspace mt-4 ${selected ? 'has-inspector' : ''}`}>
          <div className="card" style={{ margin: 0 }}>
            <div className="card-header">
              <div>
                <span className="card-title">Incident feed</span>
                <span className="card-subtitle">
                  {total} from API
                  {clientFiltersActive ? ` · ${filtered.length} after list filters` : ''}
                  {loading ? ' · refreshing…' : ''}
                </span>
              </div>
              {showPager && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    type="button"
                    className="export-btn"
                    disabled={page <= 1 || loading}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{page} / {totalPages}</span>
                  <button
                    type="button"
                    className="export-btn"
                    disabled={page >= totalPages || loading}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </div>

            {filtered.length === 0 ? (
              <div className="obs-simple-empty" style={{ padding: '40px 16px' }}>
                <Activity size={28} style={{ marginBottom: 8, opacity: 0.5 }} />
                <div style={{ fontWeight: 600, marginBottom: 4 }}>
                  {clientFiltersActive
                    ? 'No rows on this page match search/severity'
                    : apiFiltersActive
                      ? 'No incidents for these API filters'
                      : 'No incidents returned'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 480, margin: '0 auto' }}>
                  {formula}
                </div>
                {filtersActive && (
                  <button type="button" className="export-btn" style={{ marginTop: 12 }} onClick={clearFilters}>
                    Clear filters
                  </button>
                )}
              </div>
            ) : (
              <div className="table-wrapper">
                <table className="vithi-table">
                  <thead>
                    <tr>
                      <th>Incident</th>
                      <th>Pipeline</th>
                      <th>Severity</th>
                      <th>Status</th>
                      <th>Detected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((inc, i) => {
                      const id = inc.id || inc.incident_id || `row-${i}`;
                      const sev = inc.severity;
                      const st = incidentStatus(inc);
                      const active = selected && (selected.id || selected.incident_id) === (inc.id || inc.incident_id);
                      return (
                        <tr
                          key={id}
                          className={active ? 'is-selected' : ''}
                          style={{ cursor: 'pointer' }}
                          onClick={() => openDetail(inc)}
                        >
                          <td>
                            <div style={{ fontWeight: 600 }}>{incidentTitle(inc)}</div>
                            {incidentDesc(inc) ? (
                              <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
                                {incidentDesc(inc)}
                              </div>
                            ) : null}
                          </td>
                          <td><span className="tag">{dash(inc.pipeline_name)}</span></td>
                          <td>
                            {sev ? (
                              <span className={`status-pill ${sevClass(sev)}`}>{sev}</span>
                            ) : (
                              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>
                            )}
                          </td>
                          <td>
                            <span className={`status-pill ${statusClass(st)}`}>{st}</span>
                          </td>
                          <td style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>
                            {inc.opened_age || fmtTime(inc.opened_at || inc.start_time || inc.detected_at)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="lin-inspector-foot" style={{ borderTop: '1px solid var(--border)', padding: '10px 14px', display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <Clock size={12} style={{ marginTop: 2, flexShrink: 0 }} />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{formula}</span>
            </div>
          </div>

          {selected && (
            <aside className="lin-inspector card" style={{ margin: 0 }}>
              <div className="card-header" style={{ alignItems: 'flex-start' }}>
                <div>
                  <span className="card-title">Investigation</span>
                  <span className="card-subtitle">List row + detail API when available</span>
                </div>
                <button
                  type="button"
                  className="export-btn"
                  onClick={() => { setSelected(null); setDetail(null); setDetailError(null); }}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="lin-inspector-body">
                {detailLoading ? (
                  <div className="obs-simple-empty">Loading detail…</div>
                ) : (
                  <>
                    <div className="lin-inspector-pill">
                      <span className={`status-pill ${statusClass(incidentStatus(selected))}`}>
                        {incidentStatus(selected)}
                      </span>
                      {selected.severity && (
                        <span className={`status-pill ${sevClass(selected.severity)}`}>
                          {selected.severity}
                        </span>
                      )}
                    </div>
                    {detailError && (
                      <div style={{ fontSize: 11.5, color: '#B45309', background: '#FFFBEB', padding: '8px 10px', borderRadius: 8 }}>
                        {detailError}
                      </div>
                    )}
                    <div className="lin-inspector-block">
                      {inspectorRows.length === 0 ? (
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No detail fields on this row.</div>
                      ) : inspectorRows.map(([label, value]) => (
                        <div key={label}>
                          <span>{label}</span>
                          <strong className={label.includes('ID') ? 'mono' : undefined}>
                            {label === 'Detected' || label === 'Resolved' ? fmtTime(value) : String(value)}
                          </strong>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
                      <button
                        type="button"
                        className="export-btn"
                        style={{
                          background: 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)',
                          color: '#ffffff',
                          border: 'none',
                          fontWeight: 600,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6
                        }}
                        onClick={() => openCopilot(`Diagnose root cause for incident '${incidentTitle(selected)}'`, {
                          active_pipeline_id: selected.pipeline_id,
                          active_run_id: selected.run_id || detail?.run_id,
                          active_tool: selected.tool || detail?.tool,
                        })}
                      >
                        ✨ Copilot Diagnosis
                      </button>
                      <Link className="export-btn" to="/pipelines">Pipelines</Link>
                      <Link className="export-btn" to="/logs">Logs</Link>
                      {(selected.run_id || detail?.run_id) && (
                        <Link
                          className="export-btn"
                          to={`/logs?run_id=${encodeURIComponent(selected.run_id || detail.run_id)}`}
                        >
                          Run logs
                        </Link>
                      )}
                    </div>
                  </>
                )}
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
