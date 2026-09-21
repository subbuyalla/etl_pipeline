import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  GitBranch, CheckCircle, Clock, AlertTriangle,
  ArrowUpRight, Search, RotateCcw, ChevronRight, Activity, Shield, Database,
  Layers
} from 'lucide-react';
import {
  BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import OverviewSkeleton from '../components/OverviewSkeleton';
import {
  fetchOverview,
  fetchOverviewHealth,
  fetchRecentIncidents,
  fetchLogs,
  fetchFilters,
  getCachedData,
  setCachedData,
} from '../api/client';
import { TOOLTIP_STYLE } from './DataObservability/obsUtils';

function buildQueryParams({ headerDatePreset, customDateRange, pipelineFilter, statusFilter }) {
  const params = {};
  if (headerDatePreset === 'custom' && customDateRange?.start && customDateRange?.end) {
    params.start_date = customDateRange.start;
    params.end_date = customDateRange.end;
  } else if (headerDatePreset && headerDatePreset !== 'custom') {
    params.preset = headerDatePreset;
  }
  if (pipelineFilter && pipelineFilter !== 'All') params.pipeline_name = pipelineFilter;
  // Run status: success | failed | running | error | cancelled
  if (statusFilter && statusFilter !== 'All') params.status = String(statusFilter).toLowerCase();
  return params;
}

function formatChartLabel(lbl) {
  if (!lbl) return '';
  const d = new Date(lbl);
  if (!Number.isNaN(d.getTime())) {
    return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' });
  }
  return String(lbl);
}

export default function Overview() {
  const navigate = useNavigate();
  const [overviewData, setOverviewData] = useState(() => getCachedData('overview_default'));
  const [healthData, setHealthData] = useState(() => {
    const c = getCachedData('overview_default');
    return c?.health ? { items: c.health, pillars: c.health } : null;
  });
  const [incidentsData, setIncidentsData] = useState(() => {
    const c = getCachedData('overview_default');
    return c?.incidents ? { items: c.incidents, incidents: c.incidents } : null;
  });
  const [runs, setRuns] = useState(() => getCachedData('overview_runs') || []);
  const [filterCatalog, setFilterCatalog] = useState(() => getCachedData('filter_catalog'));
  const [loading, setLoading] = useState(() => !getCachedData('overview_default'));
  const [error, setError] = useState(null);

  const [search, setSearch] = useState('');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);
  const requestIdRef = useRef(0);

  const loadData = useCallback(async () => {
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const params = buildQueryParams({
        headerDatePreset,
        customDateRange,
        pipelineFilter,
        statusFilter,
      });

      const dateParams = {};
      if (params.preset) dateParams.preset = params.preset;
      if (params.start_date) dateParams.start_date = params.start_date;
      if (params.end_date) dateParams.end_date = params.end_date;

      const [ovRes, logsRes, filtersRes] = await Promise.allSettled([
        fetchOverview(params),
        fetchLogs({ ...params, limit: 100 }),
        fetchFilters(),
      ]);

      if (reqId !== requestIdRef.current) return;

      if (ovRes.status === 'fulfilled' && ovRes.value && typeof ovRes.value === 'object' && !Array.isArray(ovRes.value)) {
        // Guard: SPA/HTML or proxy errors must not look like "empty dashboard"
        if (ovRes.value.ok === false || ovRes.value.error) {
          setError(ovRes.value.error || 'Overview API returned an error');
          setOverviewData(null);
        } else if (Array.isArray(ovRes.value.kpis) || Array.isArray(ovRes.value.items) || ovRes.value.generated_at) {
          setOverviewData(ovRes.value);
          setCachedData('overview_default', ovRes.value);
          if (ovRes.value.health) setHealthData({ items: ovRes.value.health, pillars: ovRes.value.health });
          if (ovRes.value.incidents) setIncidentsData({ items: ovRes.value.incidents, incidents: ovRes.value.incidents });
        } else {
          setError('Invalid overview response (is the API proxy / API_BACKEND_URL working?)');
          setOverviewData(null);
        }
      } else if (ovRes.status === 'rejected') {
        const msg = ovRes.reason?.response?.data?.error
          || ovRes.reason?.message
          || 'Failed to load overview';
        setError(msg);
        setOverviewData(null);
      }

      if (logsRes.status === 'fulfilled' && logsRes.value) {
        const lList = logsRes.value.items || logsRes.value.logs || (Array.isArray(logsRes.value) ? logsRes.value : []);
        setRuns(lList);
        setCachedData('overview_runs', lList);
      }
      if (filtersRes.status === 'fulfilled' && filtersRes.value) {
        setFilterCatalog(filtersRes.value);
        setCachedData('filter_catalog', filtersRes.value);
      }
    } catch (e) {
      if (reqId !== requestIdRef.current) return;
      console.error('Failed to load live overview data:', e);
      setError(e.message || 'Failed to load overview');
    } finally {
      if (reqId === requestIdRef.current) setLoading(false);
    }
  }, [headerDatePreset, customDateRange, pipelineFilter, statusFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const distinctPipelineNames = useMemo(() => {
    const fromApi = [
      ...(filterCatalog?.items || []),
      ...(filterCatalog?.pipelines || []),
    ].map(p => p.pipeline_name);
    const fromOverview = (overviewData?.items || overviewData?.pipelines || []).map(p => p.pipeline_name);
    return Array.from(new Set([...fromApi, ...fromOverview].filter(Boolean))).sort();
  }, [filterCatalog, overviewData]);

  const statusOptions = useMemo(() => filterCatalog?.statuses || [], [filterCatalog]);

  const datePresets = useMemo(() => {
    const fromApi = filterCatalog?.presets;
    if (Array.isArray(fromApi) && fromApi.length) {
      return fromApi.map(p => ({ id: p.id, label: p.label || p.id }));
    }
    return [];
  }, [filterCatalog]);

  const handleHeaderDateChange = (val) => {
    if (typeof val === 'string') {
      setHeaderDatePreset(val);
      setCustomDateRange(null);
    } else if (val && val.start && val.end) {
      setHeaderDatePreset('custom');
      setCustomDateRange(val);
    }
  };

  const kpiMap = useMemo(() => {
    const map = {};
    if (overviewData?.kpis && Array.isArray(overviewData.kpis)) {
      overviewData.kpis.forEach(k => { map[k.id] = k; });
    }
    return map;
  }, [overviewData]);

  const pipelinesList = useMemo(() => {
    return overviewData?.items || overviewData?.pipelines || [];
  }, [overviewData]);

  const filteredPipelines = useMemo(() => {
    let list = pipelinesList;
    // When run-status filter is on, hide rows the API marks N/A (no matching runs)
    if (statusFilter !== 'All') {
      const want = statusFilter.toLowerCase();
      list = list.filter(p => {
        const s = (p.status || '').toLowerCase();
        if (!s || s === 'n/a') return false;
        return s === want;
      });
    }
    if (!search.trim()) return list;
    const q = search.toLowerCase();
    return list.filter(p => {
      const hay = [
        p.pipeline_name, p.source_tool, p.target_tool, p.etl_tool, p.status, p.source, p.target,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [pipelinesList, search, statusFilter]);

  const incidentsList = useMemo(() => {
    const incs =
      incidentsData?.items ||
      incidentsData?.incidents ||
      overviewData?.incidents ||
      [];
    return incs.map(inc => ({
      title: inc.title ?? inc.pipeline_name ?? '—',
      desc: inc.description ?? inc.error_message ?? '—',
      pipeline_name: inc.pipeline_name || '—',
      severity: inc.severity ?? '—',
      time: inc.opened_age ?? (inc.opened_at || inc.start_time
        ? new Date(inc.opened_at || inc.start_time).toLocaleString()
        : '—')
    }));
  }, [incidentsData, overviewData]);

  const healthPillars = useMemo(() => {
    const fromHealth = healthData?.items || healthData?.pillars || healthData?.health;
    const raw = Array.isArray(fromHealth) && fromHealth.length
      ? fromHealth
      : (overviewData?.pillars?.length
        ? overviewData.pillars
        : (overviewData?.health?.length ? overviewData.health : []));
    return raw.filter(p => p && p.available !== false && (p.status || '').toUpperCase() !== 'N/A');
  }, [healthData, overviewData]);

  const runsChart = useMemo(() => {
    const charts = overviewData?.charts;
    if (charts?.labels?.length && charts?.runs_over_time) {
      const labels = charts.labels;
      const successArr = charts.runs_over_time.success || [];
      const failedArr = charts.runs_over_time.failed || [];
      return labels.map((lbl, idx) => ({
        time: formatChartLabel(lbl),
        Success: Number(successArr[idx]) || 0,
        Failed: Number(failedArr[idx]) || 0,
      }));
    }
    const dateMap = {};
    runs.forEach(r => {
      const raw = (r.timestamp || r.start_time || '').substring(0, 10);
      if (!raw) return;
      const fmt = formatChartLabel(raw);
      if (!dateMap[fmt]) dateMap[fmt] = { time: fmt, Success: 0, Failed: 0, dateRaw: raw };
      if ((r.status || '').toLowerCase() === 'success') dateMap[fmt].Success += 1;
      else dateMap[fmt].Failed += 1;
    });
    return Object.values(dateMap).sort((a, b) => (a.dateRaw || '').localeCompare(b.dateRaw || ''));
  }, [overviewData, runs]);

  const successChart = useMemo(() => {
    const charts = overviewData?.charts;
    if (charts?.labels?.length && charts?.success_rate_over_time) {
      return charts.labels.map((lbl, idx) => ({
        time: formatChartLabel(lbl),
        rate: charts.success_rate_over_time[idx] != null
          ? Math.round(Number(charts.success_rate_over_time[idx]))
          : 0,
      }));
    }
    return runsChart.map(item => {
      const total = item.Success + item.Failed;
      return { time: item.time, rate: total > 0 ? Math.round((item.Success / total) * 100) : 0 };
    });
  }, [overviewData, runsChart]);

  const incidentsChart = useMemo(() => {
    const charts = overviewData?.charts;
    const series = charts?.incidents_over_time;
    if (charts?.labels?.length && series) {
      const openInc = series.open || series.failed_runs || [];
      return charts.labels.map((lbl, idx) => ({
        time: formatChartLabel(lbl),
        count: Number(openInc[idx]) || 0,
      }));
    }
    return runsChart.map(item => ({ time: item.time, count: item.Failed }));
  }, [overviewData, runsChart]);

  const clearFilters = () => {
    setSearch('');
    setPipelineFilter('All');
    setStatusFilter('All');
    setHeaderDatePreset('all');
    setCustomDateRange(null);
  };

  const hasActiveFilters =
    Boolean(search.trim()) ||
    pipelineFilter !== 'All' ||
    statusFilter !== 'All' ||
    headerDatePreset !== 'all';

  const formatApiTime = (raw) => {
    if (!raw) return null;
    const s = String(raw);
    // API "all" often starts at Unix epoch — show friendly label instead
    if (s.startsWith('1970-01-01')) return null;
    return s;
  };

  const rangeLabel = useMemo(() => {
    if (headerDatePreset === 'custom' && customDateRange?.start && customDateRange?.end) {
      return `${customDateRange.start} → ${customDateRange.end} (custom)`;
    }
    const presetMeta = datePresets.find(p => p.id === headerDatePreset);
    const presetName = presetMeta?.label || headerDatePreset || 'all';
    const from = formatApiTime(overviewData?.range?.from);
    const to = formatApiTime(overviewData?.range?.to) || overviewData?.range?.to;
    if (!from && (headerDatePreset === 'all' || overviewData?.range?.preset === 'all')) {
      return `All recorded history (${presetName})`;
    }
    if (from && to) return `${from} → ${to} (${presetName})`;
    return presetName;
  }, [overviewData, headerDatePreset, customDateRange, datePresets]);

  const activeIncidentsKpi = kpiMap.active_incidents || kpiMap.open_incidents;
  const failedRunsKpi = kpiMap.failed_runs;

  const statusFilterLabel = statusOptions.find(s => s.id === statusFilter)?.label || statusFilter;

  return (
    <div className="fade-in">
      <PageHeader
        title="Overview"
        subtitle="Real-time data observability, pipeline health, and SLAs powered by live backend."
        onRefresh={loadData}
        onDateChange={handleHeaderDateChange}
        datePreset={headerDatePreset}
        customStart={customDateRange?.start || ''}
        customEnd={customDateRange?.end || ''}
        latestTimestamp={overviewData?.generated_at}
        presets={datePresets}
      />

      <div className="page-body">
        <div className="filters-bar">
          <div className="search-box">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search pipeline name, source, ETL, target…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="filter-select">
            <label>Pipeline</label>
            <select
              className="select-control"
              value={pipelineFilter}
              onChange={e => setPipelineFilter(e.target.value)}
            >
              <option value="All">All Pipelines</option>
              {distinctPipelineNames.map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>

          <div className="filter-select">
            <label>Run status</label>
            <select
              className="select-control"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              title="Filters KPIs/charts by run outcome (success, failed, …)"
            >
              <option value="All">All run statuses</option>
              {statusOptions.map(s => (
                <option key={s.id} value={s.id}>
                  {s.label || s.id}
                </option>
              ))}
            </select>
          </div>

          {hasActiveFilters && (
            <button className="clear-filters-btn" onClick={clearFilters} title="Reset all filters">
              <RotateCcw size={12} style={{ display: 'inline', marginRight: 4 }} />
              Reset Filters
            </button>
          )}
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, flexWrap: 'wrap'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span>
              Time range: <strong style={{ color: 'var(--text-secondary)' }}>{rangeLabel || '—'}</strong>
              <span style={{ marginLeft: 6, color: 'var(--text-muted)' }}>(change in header date picker)</span>
            </span>
            {pipelineFilter !== 'All' && (
              <span className="tag">Pipeline: {pipelineFilter}</span>
            )}
            {statusFilter !== 'All' && (
              <span className="tag">Run status: {statusFilterLabel}</span>
            )}
            {search.trim() && (
              <span className="tag">Search: {search.trim()}</span>
            )}
            {overviewData?.generated_at && (
              <span>· Updated {new Date(overviewData.generated_at).toLocaleString()}</span>
            )}
          </div>
          {loading && overviewData && (
            <span style={{ color: '#059669', fontWeight: 600 }}>Refreshing…</span>
          )}
        </div>

        {statusFilter !== 'All' && Number(kpiMap.total_runs?.value) === 0 && (
          <div style={{
            padding: '10px 12px', marginBottom: 12, borderRadius: 8, fontSize: 12.5,
            background: '#FFFBEB', border: '1px solid #FDE68A', color: '#92400E'
          }}>
            No runs with status <strong>{statusFilterLabel}</strong> in this time range.
            Your last run may be <strong>Success</strong> — try that status, or set date to <strong>All Time</strong>.
          </div>
        )}

        {error && (
          <div style={{
            padding: '12px 14px', marginBottom: 14, borderRadius: 8,
            background: '#FEF2F2', border: '1px solid #FECACA', color: '#B91C1C', fontSize: 13
          }}>
            <strong>Cannot load Overview data.</strong> {error}
            <div style={{ marginTop: 8, fontSize: 12, color: '#991B1B' }}>
              Backend itself is fine when reached directly. Check:
              <ul style={{ margin: '6px 0 0 18px' }}>
                <li>Local: <code>API_BACKEND_URL</code> in <code>.env</code>, then restart <code>npm run dev</code></li>
                <li>Vercel: Project → Settings → Environment Variables → <code>API_BACKEND_URL</code>, then Redeploy</li>
                <li>Browser DevTools → Network → <code>/api/v1/overview</code> (should be JSON, not HTML/404)</li>
              </ul>
            </div>
          </div>
        )}

        {!loading && !error && !overviewData && (
          <div style={{
            padding: '12px 14px', marginBottom: 14, borderRadius: 8,
            background: '#FFFBEB', border: '1px solid #FDE68A', color: '#92400E', fontSize: 13
          }}>
            No overview payload loaded. Click Refresh, or verify the API proxy.
          </div>
        )}

        {loading && !overviewData ? (
          <OverviewSkeleton />
        ) : (
          <div style={{ opacity: loading ? 0.72 : 1, transition: 'opacity 0.15s ease' }}>
            <div className="kpi-grid-5">
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EEF2FF', color: '#6366F1' }}>
                    <GitBranch size={16} />
                  </div>
                  <span className="kpi-label">{kpiMap.total_pipelines?.title || '—'}</span>
                </div>
                <div className="kpi-value">
                  {kpiMap.total_pipelines?.display ?? (kpiMap.total_pipelines?.value ?? '—')}
                </div>
                <div className="kpi-delta up">
                  <ArrowUpRight size={12} />
                  <span>{kpiMap.total_pipelines?.delta_label || '—'}</span>
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}>
                    <CheckCircle size={16} />
                  </div>
                  <span className="kpi-label">{kpiMap.success_rate?.title || '—'}</span>
                </div>
                <div className="kpi-value" style={{ color: '#10B981' }}>
                  {kpiMap.success_rate?.available === false
                    ? '—'
                    : (kpiMap.success_rate?.display ?? '—')}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {failedRunsKpi?.display != null
                    ? `${failedRunsKpi.display} failed in window`
                    : (kpiMap.total_runs?.display != null
                      ? `${kpiMap.total_runs.display} runs in window`
                      : (kpiMap.success_rate?.delta_label || '—'))}
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}>
                    <Activity size={16} />
                  </div>
                  <span className="kpi-label">{kpiMap.total_runs?.title || '—'}</span>
                </div>
                <div className="kpi-value">
                  {kpiMap.total_runs?.display ?? '—'}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {kpiMap.total_runs?.delta_label || 'Selected time window'}
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                    <AlertTriangle size={16} />
                  </div>
                  <span className="kpi-label">{activeIncidentsKpi?.title || '—'}</span>
                </div>
                <div className="kpi-value" style={{ color: (activeIncidentsKpi?.value || 0) > 0 ? '#EF4444' : '#10B981' }}>
                  {activeIncidentsKpi?.display ?? '—'}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {activeIncidentsKpi?.delta_label || '—'}
                </div>
              </div>

              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#F8FAFC', color: '#64748B' }}>
                    <Clock size={16} />
                  </div>
                  <span className="kpi-label">{kpiMap.avg_duration?.title || '—'}</span>
                </div>
                <div className="kpi-value">
                  {kpiMap.avg_duration?.available === false
                    ? '—'
                    : (kpiMap.avg_duration?.display || '—')}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {kpiMap.avg_duration?.delta_label || '—'}
                </div>
              </div>
            </div>

            {healthPillars.length > 0 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Data Observability Health Pillars</span>
                    <span className="card-subtitle">
                      Live reliability from /api/v1/overview/health for the selected filters.
                    </span>
                  </div>
                  <button className="export-btn" onClick={() => navigate('/observability')}>
                    Deep Dive <ChevronRight size={13} />
                  </button>
                </div>

                <div className="grid-4" style={{ gap: 14 }}>
                  {healthPillars.map(pillar => {
                    const score = pillar.score != null ? Math.round(Number(pillar.score)) : null;
                    const tone = pillar.status === 'Critical' ? '#EF4444'
                      : pillar.status === 'Warning' || pillar.status === 'Degraded' ? '#F59E0B'
                      : pillar.status === 'N/A' ? '#94A3B8'
                      : '#10B981';
                    const iconMap = {
                      freshness: <Clock size={18} style={{ color: tone }} />,
                      volume: <Database size={18} style={{ color: tone }} />,
                      data_quality: <Shield size={18} style={{ color: tone }} />,
                      schema: <Layers size={18} style={{ color: tone }} />,
                      uniqueness: <CheckCircle size={18} style={{ color: tone }} />,
                      consistency: <Activity size={18} style={{ color: tone }} />,
                    };

                    return (
                      <div
                        key={pillar.id || pillar.name}
                        className="health-pillar-card"
                        onClick={() => {
                          if (pillar.id === 'freshness') navigate('/observability/freshness');
                          else if (pillar.id === 'volume') navigate('/observability/volume');
                          else if (pillar.id === 'data_quality') navigate('/observability/data-quality');
                          else if (pillar.id === 'schema') navigate('/observability/schema');
                          else if (pillar.id === 'lineage') navigate('/observability/lineage');
                          else navigate('/observability');
                        }}
                        style={{
                          background: 'var(--bg-card-subtle)',
                          border: '1px solid var(--border)',
                          borderRadius: 8,
                          padding: '14px 16px',
                          cursor: 'pointer',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {iconMap[pillar.id] || <Activity size={18} style={{ color: tone }} />}
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{pillar.name}</span>
                          </div>
                          <span className={`status-pill ${pillar.status === 'Good' ? 'good' : pillar.status === 'Critical' ? 'critical' : 'warning'}`}>
                            {pillar.status || '—'}
                          </span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8 }}>
                          <span style={{ fontSize: 24, fontWeight: 700, color: tone }}>
                            {pillar.display || (score != null ? `${score}%` : '—')}
                          </span>
                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>score</span>
                        </div>
                        <div style={{ width: '100%', height: 5, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                          <div style={{
                            width: `${score != null ? Math.min(100, Math.max(0, score)) : 0}%`,
                            height: '100%', background: tone, borderRadius: 4
                          }} />
                        </div>
                        {pillar.details && (
                          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 8 }}>
                            {pillar.id === 'freshness' && `${pillar.details.fresh ?? 0} fresh / ${pillar.details.delayed ?? 0} delayed / ${pillar.details.stale ?? 0} stale`}
                            {pillar.id === 'data_quality' && `${pillar.details.passed ?? 0} pass / ${pillar.details.warn ?? 0} warn / ${pillar.details.failed ?? 0} fail`}
                            {pillar.id === 'schema' && `${pillar.details.changes ?? 0} changes / ${pillar.details.breaking ?? 0} breaking`}
                            {pillar.id === 'volume' && `${pillar.details.healthy ?? 0} healthy / ${pillar.details.total ?? 0} datasets`}
                            {pillar.id === 'uniqueness' && `${pillar.details.checks_run ?? 0} uniqueness checks`}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="grid-3 mt-4" style={{ gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Runs Over Time</span>
                    <span className="card-subtitle">Execution distribution by status</span>
                  </div>
                </div>
                <div style={{ height: 180, width: '100%' }}>
                  {runsChart.length === 0 ? (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                      No run series in this filter window
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={runsChart} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                        <Tooltip {...TOOLTIP_STYLE} />
                        <Bar dataKey="Success" fill="#10B981" radius={[4, 4, 0, 0]} stackId="a" />
                        <Bar dataKey="Failed" fill="#EF4444" radius={[4, 4, 0, 0]} stackId="a" />
                      </BarChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Success Rate Trend</span>
                    <span className="card-subtitle">Reliability percentage (%)</span>
                  </div>
                </div>
                <div style={{ height: 180, width: '100%' }}>
                  {successChart.length === 0 ? (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                      No success-rate series in this window
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      {successChart.length < 2 ? (
                        <BarChart data={successChart} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <Tooltip {...TOOLTIP_STYLE} />
                          <Bar dataKey="rate" name="Success %" fill="#10B981" radius={[4, 4, 0, 0]} maxBarSize={48} />
                        </BarChart>
                      ) : (
                        <AreaChart data={successChart} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                          <defs>
                            <linearGradient id="successGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#10B981" stopOpacity={0.4} />
                              <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <Tooltip {...TOOLTIP_STYLE} />
                          <Area type="monotone" dataKey="rate" name="Success %" stroke="#10B981" strokeWidth={2} fillOpacity={1} fill="url(#successGrad)" dot={{ r: 3, fill: '#10B981' }} activeDot={{ r: 5 }} />
                        </AreaChart>
                      )}
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Incident Activity</span>
                    <span className="card-subtitle">Anomalies & failures</span>
                  </div>
                </div>
                <div style={{ height: 180, width: '100%' }}>
                  {incidentsChart.length === 0 ? (
                    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                      No incident series in this window
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      {incidentsChart.length < 2 ? (
                        <BarChart data={incidentsChart} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                          <Tooltip {...TOOLTIP_STYLE} />
                          <Bar dataKey="count" name="Incidents" fill="#EF4444" radius={[4, 4, 0, 0]} maxBarSize={48} minPointSize={4} />
                        </BarChart>
                      ) : (
                        <AreaChart data={incidentsChart} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                          <defs>
                            <linearGradient id="incidentGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#EF4444" stopOpacity={0.4} />
                              <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                          <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                          <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                          <Tooltip {...TOOLTIP_STYLE} />
                          <Area type="monotone" dataKey="count" name="Incidents" stroke="#EF4444" strokeWidth={2} fillOpacity={1} fill="url(#incidentGrad)" dot={{ r: 3, fill: '#EF4444' }} activeDot={{ r: 5 }} />
                        </AreaChart>
                      )}
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Pipeline Monitoring</span>
                  <span className="card-subtitle">{filteredPipelines.length} pipeline(s) for current filters</span>
                </div>
                <button className="export-btn" onClick={() => navigate('/pipelines')}>
                  View All Pipelines <ChevronRight size={13} />
                </button>
              </div>

              <div className="table-wrapper">
                <table className="vithi-table">
                  <thead>
                    <tr>
                      <th>Pipeline</th>
                      <th>Source → ETL → Target</th>
                      <th>Status</th>
                      <th>Total Runs</th>
                      <th>Success Rate</th>
                      <th>Avg Duration</th>
                      <th>Last Run</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPipelines.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text-muted)' }}>
                          No pipelines in this filter window.
                          {headerDatePreset !== 'all' && (
                            <div style={{ marginTop: 8 }}>
                              Tip: last known run may be older — try <strong>All Time</strong> in the date picker.
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : (
                      filteredPipelines.map((pipe) => {
                        const statusLower = (pipe.status || '').toLowerCase();
                        const isPassing = statusLower === 'success' || statusLower === 'good' || statusLower === 'healthy';
                        const isDegraded = statusLower === 'degraded' || statusLower === 'warning' || statusLower === 'n/a';
                        const statusClass = isPassing ? 'good' : isDegraded ? 'warning' : 'critical';
                        const ratePct = pipe.success_rate_pct != null
                          ? pipe.success_rate_pct
                          : (pipe.total_runs > 0 && pipe.success_runs != null
                            ? (pipe.success_runs / pipe.total_runs) * 100
                            : null);

                        return (
                          <tr key={pipe.pipeline_id || pipe.pipeline_name} className="interactive-row" onClick={() => navigate('/pipelines')}>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <GitBranch size={15} style={{ color: 'var(--accent)' }} />
                                <div>
                                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{pipe.pipeline_name}</div>
                                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                    ID: {pipe.pipeline_id ? `${pipe.pipeline_id.substring(0, 8)}…` : '—'}
                                  </div>
                                </div>
                              </div>
                            </td>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                                <span className="tag">{pipe.source_tool || '—'}</span>
                                <span style={{ color: 'var(--text-muted)' }}>→</span>
                                <span className="tag accent">{pipe.etl_tool || '—'}</span>
                                <span style={{ color: 'var(--text-muted)' }}>→</span>
                                <span className="tag">{pipe.target_tool || '—'}</span>
                              </div>
                            </td>
                            <td>
                              <span className={`status-pill ${statusClass}`}>{pipe.status || '—'}</span>
                            </td>
                            <td style={{ fontWeight: 600 }}>{pipe.total_runs ?? pipe.runs ?? 0}</td>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                {ratePct != null && (
                                  <div style={{ width: 48, height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                                    <div style={{
                                      width: `${Math.min(100, Math.max(0, ratePct))}%`,
                                      height: '100%',
                                      background: isPassing ? '#10B981' : '#F59E0B'
                                    }} />
                                  </div>
                                )}
                                <span style={{ fontSize: 12, fontWeight: 500 }}>
                                  {pipe.success_rate_pct != null ? `${pipe.success_rate_pct}%` : (pipe.success_rate || '—')}
                                </span>
                              </div>
                            </td>
                            <td style={{ color: 'var(--text-secondary)' }}>
                              {pipe.avg_duration ?? (pipe.avg_duration_seconds != null ? `${pipe.avg_duration_seconds}s` : '—')}
                            </td>
                            <td style={{ color: 'var(--text-secondary)' }}>
                              {pipe.last_run_age || pipe.last_run_at || pipe.last_run || '—'}
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              <button
                                className="export-btn"
                                style={{ padding: '4px 8px', fontSize: 11 }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigate('/pipelines');
                                }}
                              >
                                View Runs
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Recent Open Incidents</span>
                  <span className="card-subtitle">Active alerts and pipeline failures requiring attention</span>
                </div>
                <button className="export-btn" onClick={() => navigate('/incidents')}>
                  View All Incidents <ChevronRight size={13} />
                </button>
              </div>

              {incidentsList.length === 0 ? (
                <div style={{ padding: '28px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  No open incidents for this filter window.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 4px 8px' }}>
                  {incidentsList.map((inc, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '12px 14px',
                        background: 'var(--bg-card-subtle)',
                        borderRadius: 8,
                        borderLeft: `4px solid ${inc.severity === 'Critical' ? '#EF4444' : '#F59E0B'}`
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <AlertTriangle size={18} style={{ color: inc.severity === 'Critical' ? '#EF4444' : '#F59E0B' }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>{inc.title}</div>
                          <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>{inc.desc}</div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span className="tag">{inc.pipeline_name}</span>
                        <span className={`status-pill ${inc.severity === 'Critical' ? 'critical' : 'warning'}`}>
                          {inc.severity}
                        </span>
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{inc.time}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
