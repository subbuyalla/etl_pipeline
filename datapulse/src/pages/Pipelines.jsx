import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import {
  GitBranch, CheckCircle, Clock,
  ArrowUpRight, Search, Eye,
  ChevronLeft, ChevronRight, X, Terminal, AlertTriangle,
  RotateCcw, ArrowRight, Activity, Shield, Layers, Database,
  CheckSquare, ExternalLink,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { TableSkeleton } from '../components/SkeletonLoaders';
import SearchableSelect from '../components/SearchableSelect';
import {
  fetchPipelines, fetchPipelineCatalog, fetchLogs, fetchFilters, fetchPipelineBindings,
  fetchPipelineMonitors, fetchPipelineRuns, fetchRcaContext,
  getCachedData, setCachedData,
} from '../api/client';

const fmtDuration = (sec) => {
  if (sec == null || Number.isNaN(Number(sec))) return '—';
  const s = Math.round(Number(sec));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
};

const fmtDate = (str) => {
  if (!str) return '—';
  try {
    const clean = String(str).trim().replace(' ', 'T');
    const d = new Date(clean);
    if (Number.isNaN(d.getTime())) return String(str);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return String(str);
  }
};

function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(Number(bytes))) return '—';
  const b = Number(bytes);
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

function buildQueryParams({
  headerDatePreset,
  customDateRange,
  customTimeRange,
  pipelineFilter,
  pipelineIdFilter,
  statusFilter,
  toolFilter,
  page,
  pageSize,
}) {
  const params = {};
  // 1. preset | start_date | end_date | start_time | end_time
  if (headerDatePreset === 'custom' && customDateRange?.start && customDateRange?.end) {
    params.start_date = customDateRange.start;
    params.end_date = customDateRange.end;
    if (customTimeRange?.start) params.start_time = customTimeRange.start;
    if (customTimeRange?.end) params.end_time = customTimeRange.end;
  } else if (headerDatePreset && headerDatePreset !== 'custom') {
    params.preset = headerDatePreset;
  } else {
    params.preset = 'all';
  }

  // 2. pipeline_name | pipeline_id
  if (pipelineFilter && pipelineFilter !== 'All') {
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(pipelineFilter)) {
      params.pipeline_id = pipelineFilter;
    } else {
      params.pipeline_name = pipelineFilter;
    }
  }
  if (pipelineIdFilter) {
    params.pipeline_id = pipelineIdFilter;
  }

  // 3. status
  if (statusFilter && statusFilter !== 'All') {
    params.status = String(statusFilter).toLowerCase();
  }

  // 4. tool
  if (toolFilter && toolFilter !== 'All') {
    params.tool = String(toolFilter).toLowerCase();
  }

  // 5. page & page_size
  if (page) params.page = Number(page);
  if (pageSize) params.page_size = Number(pageSize);

  return params;
}

function statusPillClass(status) {
  const s = (status || '').toLowerCase();
  if (s === 'success' || s === 'good' || s === 'pass' || s === 'ok') return 'success';
  if (s === 'failed' || s === 'error' || s === 'critical' || s === 'fail') return 'failed';
  if (s === 'running' || s === 'degraded' || s === 'warn') return 'warning';
  return 'neutral';
}

function dash(val) {
  if (val == null || val === '') return '—';
  return String(val);
}

const PRESET_LABELS = {
  all: 'All Time',
  '15m': 'Last 15 Minutes',
  '24h': 'Last 24 Hours',
  '7d': 'Last 7 Days',
  '30d': 'Last 30 Days',
};

export default function Pipelines() {
  const [runs, setRuns] = useState(() => getCachedData('pipelines_runs') || []);
  const [pipelinesList, setPipelinesList] = useState(() => getCachedData('pipelines_list') || []);
  const [pipelinePayload, setPipelinePayload] = useState(() => getCachedData('pipelines_payload'));
  const [filterCatalog, setFilterCatalog] = useState(() => getCachedData('filter_catalog'));
  const [loading, setLoading] = useState(() => !getCachedData('pipelines_list'));
  const [error, setError] = useState(null);

  const [selectedPipelineName, setSelectedPipelineName] = useState(null);
  const [activePipelineTab, setActivePipelineTab] = useState('runs'); // 'runs' | 'bindings'
  const [bindings, setBindings] = useState([]);
  const [monitors, setMonitors] = useState([]);
  const [pipelineRuns, setPipelineRuns] = useState([]);
  const [detailsLoading, setDetailsLoading] = useState(false);

  // Run Details & RCA state
  const [selectedRun, setSelectedRun] = useState(null);
  const [rcaContext, setRcaContext] = useState(null);
  const [rcaLoading, setRcaLoading] = useState(false);
  const [activeRcaTab, setActiveRcaTab] = useState('tests'); // 'tests' | 'dq_checks' | 'assets'

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [toolFilter, setToolFilter] = useState('All');
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);
  const [page, setPage] = useState(1);
  const [perPage] = useState(10);
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
        toolFilter,
      });

      const [pRes, catRes, lRes, fRes] = await Promise.allSettled([
        fetchPipelines(params),
        fetchPipelineCatalog(),
        fetchLogs({ ...params, limit: 100 }),
        fetchFilters(),
      ]);

      if (reqId !== requestIdRef.current) return;

      const catItems = catRes.status === 'fulfilled' && catRes.value ? (catRes.value.items || catRes.value.pipelines || []) : [];
      const pipeItems = pRes.status === 'fulfilled' && pRes.value ? (pRes.value.items || pRes.value.pipelines || []) : [];

      if (pRes.status === 'fulfilled' && pRes.value && typeof pRes.value === 'object') {
        if (pRes.value.ok === false || pRes.value.error) {
          setError(pRes.value.error || 'Pipelines API returned an error');
          setPipelinePayload(null);
        } else if (Array.isArray(pRes.value.kpis) || Array.isArray(pRes.value.items) || pRes.value.generated_at) {
          setPipelinePayload(pRes.value);
        }
      }

      // Catalog map for static metadata (like sla_hours)
      const catalogMap = new Map();
      (Array.isArray(catItems) ? catItems : []).forEach(c => {
        const key = c.pipeline_id || c.pipeline_name;
        if (key) catalogMap.set(key, c);
      });

      // Enrich active pipeItems from GET /api/v1/pipelines
      const enrichedList = (Array.isArray(pipeItems) ? pipeItems : []).map(p => {
        const key = p.pipeline_id || p.pipeline_name;
        const cat = catalogMap.get(key) || {};
        return { ...cat, ...p };
      });

      const hasFilterActive = pipelineFilter !== 'All' || statusFilter !== 'All' || toolFilter !== 'All' || (headerDatePreset && headerDatePreset !== 'all');
      const finalPipes = (!hasFilterActive && enrichedList.length === 0 && catItems.length > 0) ? catItems : enrichedList;
      setPipelinesList(finalPipes);
      setCachedData('pipelines_list', finalPipes);
      if (pRes.value) setCachedData('pipelines_payload', pRes.value);

      if (lRes.status === 'fulfilled' && lRes.value) {
        const logs = lRes.value.items || lRes.value.logs || (Array.isArray(lRes.value) ? lRes.value : []);
        setRuns(Array.isArray(logs) ? logs : []);
        setCachedData('pipelines_runs', Array.isArray(logs) ? logs : []);
      } else {
        setRuns([]);
      }

      if (fRes.status === 'fulfilled' && fRes.value) {
        setFilterCatalog(fRes.value);
        setCachedData('filter_catalog', fRes.value);
      }
    } catch (e) {
      if (reqId !== requestIdRef.current) return;
      console.error('Failed to load pipelines & runs:', e);
      setError(e.message || 'Failed to load pipelines');
    } finally {
      if (reqId === requestIdRef.current) setLoading(false);
    }
  }, [headerDatePreset, customDateRange, pipelineFilter, statusFilter, toolFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // KPI Map
  const kpiMap = useMemo(() => {
    const map = {};
    if (Array.isArray(pipelinePayload?.kpis)) {
      pipelinePayload.kpis.forEach(k => { if (k?.id) map[k.id] = k; });
    }
    return map;
  }, [pipelinePayload]);

  const pipelineOptions = useMemo(() => {
    const fromCat = filterCatalog?.pipelines || filterCatalog?.items || [];
    const names = new Set(fromCat.map(p => p.pipeline_name).filter(Boolean));
    pipelinesList.forEach(p => { if (p.pipeline_name) names.add(p.pipeline_name); });
    return Array.from(names);
  }, [filterCatalog, pipelinesList]);

  const toolOptions = useMemo(() => {
    const fromCat = filterCatalog?.tools || [];
    if (fromCat.length > 0) return fromCat;
    return [{ id: 'dbt', label: 'dbt' }, { id: 'snowflake', label: 'snowflake' }];
  }, [filterCatalog]);

  const statusOptions = useMemo(() => {
    const fromCat = filterCatalog?.statuses || [];
    if (fromCat.length > 0) return fromCat;
    return [
      { id: 'success', label: 'Success' },
      { id: 'failed', label: 'Failed' },
      { id: 'running', label: 'Running' },
      { id: 'error', label: 'Error' },
      { id: 'cancelled', label: 'Cancelled' },
      { id: 'inactive', label: 'Inactive' },
    ];
  }, [filterCatalog]);

  // Filtered pipelines list
  const filteredPipelines = useMemo(() => {
    return pipelinesList.filter(p => {
      if (pipelineFilter !== 'All' && p.pipeline_name !== pipelineFilter) {
        return false;
      }
      if (toolFilter !== 'All') {
        const t = (p.tool || p.etl_tool || p.source_tool || p.target_tool || '').toLowerCase();
        if (!t.includes(toolFilter.toLowerCase())) return false;
      }
      if (statusFilter !== 'All') {
        const s = (p.status || p.last_run_status || '').toLowerCase();
        if (s !== statusFilter.toLowerCase()) return false;
      }
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      const hay = [
        p.pipeline_name, p.pipeline_id, p.tool, p.source_tool, p.etl_tool, p.target_tool, p.status, p.activity,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [pipelinesList, pipelineFilter, toolFilter, statusFilter, search]);

  // Default to first pipeline in filteredPipelines
  useEffect(() => {
    if (!filteredPipelines.length) {
      setSelectedPipelineName(null);
      return;
    }
    const names = filteredPipelines.map(p => p.pipeline_name).filter(Boolean);
    if (!selectedPipelineName || !names.includes(selectedPipelineName)) {
      setSelectedPipelineName(names[0]);
      setPage(1);
    }
  }, [filteredPipelines, selectedPipelineName]);

  const selectedPipeline = useMemo(
    () => filteredPipelines.find(p => p.pipeline_name === selectedPipelineName) || null,
    [filteredPipelines, selectedPipelineName]
  );

  // Load Bindings, Monitors, and Runs when selected pipeline changes
  useEffect(() => {
    if (!selectedPipeline?.pipeline_id) {
      setBindings([]);
      setMonitors([]);
      setPipelineRuns([]);
      return;
    }
    let active = true;
    setDetailsLoading(true);

    const runParams = { preset: headerDatePreset || 'all' };
    if (statusFilter !== 'All') runParams.status = String(statusFilter).toLowerCase();
    if (toolFilter !== 'All') runParams.tool = String(toolFilter).toLowerCase();

    Promise.allSettled([
      fetchPipelineBindings(selectedPipeline.pipeline_id),
      fetchPipelineMonitors(selectedPipeline.pipeline_id),
      fetchPipelineRuns(selectedPipeline.pipeline_id, runParams),
    ]).then(([bRes, mRes, rRes]) => {
      if (!active) return;
      if (bRes.status === 'fulfilled' && bRes.value?.items) {
        setBindings(bRes.value.items);
      } else {
        setBindings([]);
      }
      if (mRes.status === 'fulfilled' && (mRes.value?.items || mRes.value?.monitors)) {
        setMonitors(mRes.value.items || mRes.value.monitors || []);
      } else {
        setMonitors([]);
      }
      if (rRes.status === 'fulfilled' && rRes.value?.items) {
        setPipelineRuns(rRes.value.items);
      } else {
        setPipelineRuns([]);
      }
      setDetailsLoading(false);
    });

    return () => { active = false; };
  }, [selectedPipeline?.pipeline_id, headerDatePreset, statusFilter, toolFilter]);

  // Load RCA Context when a run is clicked
  useEffect(() => {
    if (!selectedRun) {
      setRcaContext(null);
      return;
    }
    const runId = selectedRun.run_id || selectedRun.id;
    if (!runId) return;

    let active = true;
    setRcaLoading(true);
    fetchRcaContext(runId)
      .then((res) => {
        if (!active) return;
        const rca = res?.meta || res;
        setRcaContext(rca);
      })
      .catch((err) => {
        console.error('Failed to load RCA context:', err);
        setRcaContext(null);
      })
      .finally(() => {
        if (active) setRcaLoading(false);
      });

    return () => { active = false; };
  }, [selectedRun]);

  const freshnessMonitor = useMemo(() => {
    return monitors.find(m => m.monitor_kind === 'freshness' || m.monitor_type === 'freshness');
  }, [monitors]);

  // Filtered runs for selected pipeline
  const focusedRuns = useMemo(() => {
    let list = pipelineRuns.length > 0 ? pipelineRuns : runs;
    if (selectedPipelineName) {
      list = list.filter(r => !r.pipeline_name || r.pipeline_name === selectedPipelineName);
    }
    if (statusFilter !== 'All') {
      const sf = statusFilter.toLowerCase();
      list = list.filter(r => (r.status || '').toLowerCase() === sf);
    }
    if (toolFilter !== 'All') {
      const tf = toolFilter.toLowerCase();
      list = list.filter(r => (r.tool || r.tool_name || '').toLowerCase() === tf);
    }
    if (!search.trim()) return list;
    const q = search.toLowerCase();
    return list.filter(r => {
      const hay = [
        r.pipeline_name, r.run_id, r.id, r.tool, r.tool_name,
        r.error_message, r.message, r.status,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [pipelineRuns, runs, selectedPipelineName, statusFilter, toolFilter, search]);

  const totalPages = Math.max(1, Math.ceil(focusedRuns.length / perPage));
  const paginated = useMemo(() => {
    const start = (page - 1) * perPage;
    return focusedRuns.slice(start, start + perPage);
  }, [focusedRuns, page, perPage]);

  const hasActiveFilters = Boolean(search.trim()) || statusFilter !== 'All' || pipelineFilter !== 'All' || toolFilter !== 'All' || headerDatePreset !== 'all';
  const clearFilters = () => {
    setSearch('');
    setStatusFilter('All');
    setPipelineFilter('All');
    setToolFilter('All');
    setHeaderDatePreset('all');
    setCustomDateRange(null);
  };

  const selectedPresetLabel = PRESET_LABELS[headerDatePreset] || headerDatePreset;

  return (
    <div className="fade-in">
      <PageHeader
        title="Pipelines"
        subtitle="Platform execution topology, declared bindings, attached monitors, and run history."
        onRefresh={loadData}
        datePreset={headerDatePreset}
        onDateChange={(v) => {
          if (typeof v === 'string') {
            setHeaderDatePreset(v);
            setCustomDateRange(null);
          } else if (v && v.start && v.end) {
            setHeaderDatePreset('custom');
            setCustomDateRange(v);
          }
          setPage(1);
        }}
      />

      <div className="page-body">
        {error && (
          <div className="obs-alert is-bad" style={{ marginBottom: 16 }}>
            <AlertTriangle size={18} />
            <div><strong>Failed to load pipelines:</strong> {error}</div>
          </div>
        )}

        {/* ── TOP FILTERS & SEARCH BAR (API-Synchronized) ─────────────── */}
        <div className="filters-bar" style={{ marginBottom: 16 }}>
          <div className="search-box" style={{ minWidth: 260, flex: 1, maxWidth: 360 }}>
            <Search size={14} />
            <input
              placeholder="Search pipelines, connectors, or runs…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <div className="filter-select" style={{ minWidth: 200, maxWidth: 280 }}>
            <label>Pipeline</label>
            <SearchableSelect
              options={[
                { value: 'All', label: 'All Pipelines' },
                ...pipelineOptions.map(name => ({ value: name, label: name }))
              ]}
              value={pipelineFilter}
              onChange={val => {
                const nextVal = val || 'All';
                setPipelineFilter(nextVal);
                if (nextVal !== 'All') setSelectedPipelineName(nextVal);
                setPage(1);
              }}
              placeholder="All Pipelines"
              searchPlaceholder="Search pipelines…"
            />
          </div>

          <div className="filter-select" style={{ minWidth: 170, maxWidth: 240 }}>
            <label>Tool / Connector</label>
            <SearchableSelect
              options={[
                { value: 'All', label: 'All Tools' },
                ...toolOptions.map(t => ({ value: t.id, label: t.label || t.id }))
              ]}
              value={toolFilter}
              onChange={val => {
                setToolFilter(val || 'All');
                setPage(1);
              }}
              placeholder="All Tools"
              searchPlaceholder="Search tools…"
            />
          </div>

          <div className="filter-select">
            <label>Status</label>
            <select
              className="select-control"
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            >
              <option value="All">All Statuses</option>
              {statusOptions.map(s => (
                <option key={s.id} value={s.id}>{s.label || s.id}</option>
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

        {/* ── TOP KPI SUMMARY CARDS (Synchronized with Filters) ──────── */}
        <div className="kpi-grid-5" style={{ marginBottom: 20 }}>
          {/* Card 1: Total Pipelines */}
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#EEF2FF', color: '#6366F1' }}>
                <GitBranch size={16} />
              </div>
              <span className="kpi-label">{kpiMap.total_pipelines?.title || 'Total Pipelines'}</span>
            </div>
            <div className="kpi-value">
              {filteredPipelines.length}
            </div>
            <div className="kpi-delta up">
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                {hasActiveFilters ? 'Matching active filters' : 'Registered in workspace'}
              </span>
            </div>
          </div>

          {/* Card 2: Total Runs */}
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}>
                <Activity size={16} />
              </div>
              <span className="kpi-label">{kpiMap.total_runs?.title || 'Runs Executed'}</span>
            </div>
            <div className="kpi-value">
              {filteredPipelines.length === 0 ? 0 : (kpiMap.total_runs?.value ?? focusedRuns.length)}
            </div>
            <div className="kpi-delta up">
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>In {selectedPresetLabel}</span>
            </div>
          </div>

          {/* Card 3: Success Rate */}
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}>
                <CheckCircle size={16} />
              </div>
              <span className="kpi-label">{kpiMap.success_rate?.title || 'Successful Runs'}</span>
            </div>
            <div className="kpi-value" style={{ color: kpiMap.success_rate?.available && filteredPipelines.length > 0 ? '#10B981' : 'var(--text-muted)' }}>
              {filteredPipelines.length === 0
                ? 'N/A'
                : kpiMap.success_rate?.available
                  ? (kpiMap.success_rate.display || `${kpiMap.success_rate.value}%`)
                  : 'N/A'}
            </div>
            <div className="kpi-delta up">
              {filteredPipelines.length > 0 && kpiMap.success_rate?.available ? (
                <>
                  <ArrowUpRight size={12} color="#10B981" />
                  <span style={{ color: '#10B981', fontWeight: 600 }}>Healthy execution</span>
                </>
              ) : (
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>No runs in scope</span>
              )}
            </div>
          </div>

          {/* Card 4: Avg Duration */}
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}>
                <Clock size={16} />
              </div>
              <span className="kpi-label">{kpiMap.avg_duration?.title || 'Avg Pipeline Duration'}</span>
            </div>
            <div className="kpi-value" style={{ color: kpiMap.avg_duration?.available && filteredPipelines.length > 0 ? 'var(--text-primary)' : 'var(--text-muted)' }}>
              {filteredPipelines.length === 0
                ? '—'
                : kpiMap.avg_duration?.available
                  ? (kpiMap.avg_duration.display || fmtDuration(kpiMap.avg_duration.value))
                  : '—'}
            </div>
            <div className="kpi-delta">
              <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                {filteredPipelines.length > 0 && kpiMap.avg_duration?.available ? 'Standard execution window' : 'No execution duration'}
              </span>
            </div>
          </div>

          {/* Card 5: Active Incidents */}
          <div className="kpi-card">
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                <AlertTriangle size={16} />
              </div>
              <span className="kpi-label">{kpiMap.active_incidents?.title || 'Active Incidents'}</span>
            </div>
            <div className="kpi-value" style={{ color: Number(kpiMap.active_incidents?.value || 0) > 0 ? '#EF4444' : '#10B981' }}>
              {filteredPipelines.length === 0 ? 0 : (kpiMap.active_incidents?.display ?? (kpiMap.active_incidents?.value ?? '0'))}
            </div>
            <div className="kpi-delta up">
              <span style={{ color: '#10B981', fontWeight: 600 }}>0 blocking failures</span>
            </div>
          </div>
        </div>

        {/* Informative Time Window Banner when 0 runs in selected preset */}
        {headerDatePreset !== 'all' && focusedRuns.length === 0 && (
          <div style={{
            padding: '10px 14px', marginBottom: 16, borderRadius: 8, fontSize: 12.5,
            background: 'var(--info-dim)', border: '1px solid var(--info-border)', color: 'var(--info-text)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Clock size={15} color="#2563EB" />
              <span>
                Time window <strong>"{selectedPresetLabel}"</strong> returned 0 runs. Most recent execution was on <strong>Sep 02, 2026 (14d ago)</strong>.
              </span>
            </div>
            <button
              type="button"
              className="export-btn"
              style={{ fontSize: 11.5, padding: '3px 10px', background: '#2563EB', color: '#FFFFFF', border: 'none' }}
              onClick={() => setHeaderDatePreset('all')}
            >
              Switch to All Time
            </button>
          </div>
        )}

        {/* ── Pipeline Catalog Registry Table ─────────────────────────── */}
        {loading && pipelinesList.length === 0 ? (
          <TableSkeleton rows={6} cols={6} />
        ) : (
          <div className="card" style={{ marginBottom: 20, overflow: 'hidden' }}>
            <div className="card-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <span className="card-title">Pipeline Registry</span>
                <span className="card-subtitle">Active data pipelines registered in the workspace</span>
              </div>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Showing {filteredPipelines.length} of {pipelinesList.length} pipelines
              </span>
            </div>

            {/* Clean Enterprise Table with clean responsive scrolling */}
            <div style={{ width: '100%', overflowX: 'auto' }}>
              <table className="vithi-table" style={{ width: '100%', minWidth: 960, tableLayout: 'fixed' }}>
                <thead>
                  <tr>
                    <th style={{ width: '22%' }}>Pipeline Name</th>
                    <th style={{ width: '23%' }}>Execution Flow</th>
                    <th style={{ width: '7%' }}>Tool</th>
                    <th style={{ width: '9%' }}>Status</th>
                    <th style={{ width: '8%' }}>Activity</th>
                    <th style={{ width: '9%' }}>Avg Duration</th>
                    <th style={{ width: '6%', textAlign: 'center' }}>Runs</th>
                    <th style={{ width: '8%' }}>Success Rate</th>
                    <th style={{ width: '8%' }}>Last Execution</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPipelines.length === 0 ? (
                    <tr>
                      <td colSpan={9} style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                        <div style={{ marginBottom: 8 }}>No pipelines match your search or filter criteria.</div>
                        {hasActiveFilters && (
                          <button
                            type="button"
                            className="export-btn"
                            style={{ margin: '0 auto', fontSize: 12 }}
                            onClick={clearFilters}
                          >
                            Clear All Filters
                          </button>
                        )}
                      </td>
                    </tr>
                  ) : (
                    filteredPipelines.map((p) => {
                      const isSelected = p.pipeline_name === selectedPipelineName;
                      return (
                        <tr
                          key={p.pipeline_id}
                          onClick={() => { setSelectedPipelineName(p.pipeline_name); setPage(1); }}
                          style={{
                            cursor: 'pointer',
                            background: isSelected ? 'rgba(16, 185, 129, 0.05)' : undefined,
                          }}
                        >
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <div style={{
                                width: 28, height: 28, borderRadius: 6,
                                background: isSelected ? '#10B981' : 'var(--bg-card-subtle)',
                                color: isSelected ? '#FFFFFF' : '#10B981',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                flexShrink: 0,
                              }}>
                                <GitBranch size={15} />
                              </div>
                              <div style={{ minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <strong style={{ fontSize: 13, color: isSelected ? 'var(--brand)' : 'var(--text-primary)' }}>
                                    {p.pipeline_name}
                                  </strong>
                                  {isSelected && (
                                    <span className="pipeline-selected-badge">
                                      SELECTED
                                    </span>
                                  )}
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                                  {p.pipeline_id ? p.pipeline_id.slice(0, 8) + '…' : ''}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11.5 }}>
                              {p.source_tool ? <span className="flow-tool-tag source">{p.source_tool}</span> : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                              <ArrowRight size={10} style={{ color: 'var(--text-muted)' }} />
                              {p.etl_tool ? <span className="flow-tool-tag etl">{p.etl_tool}</span> : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                              <ArrowRight size={10} style={{ color: 'var(--text-muted)' }} />
                              {p.target_tool ? <span className="flow-tool-tag target">{p.target_tool}</span> : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                            </div>
                          </td>
                          <td>
                            <span className="tool-badge">{p.tool || p.etl_tool || 'dbt'}</span>
                          </td>
                          <td>
                            <span className={`status-pill ${statusPillClass(p.status || p.last_run_status)}`}>
                              {dash(p.status || p.last_run_status)}
                            </span>
                          </td>
                          <td>
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
                              color: p.activity === 'Active' || p.is_active ? '#10B981' : 'var(--text-muted)',
                              fontWeight: 600,
                            }}>
                              <span style={{
                                width: 6, height: 6, borderRadius: '50%',
                                background: p.activity === 'Active' || p.is_active ? '#10B981' : 'var(--text-muted)',
                              }} />
                              {p.activity || (p.is_active ? 'Active' : 'Inactive')}
                            </span>
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            {p.avg_duration || (p.avg_duration_seconds ? `${p.avg_duration_seconds}s` : '—')}
                          </td>
                          <td style={{ fontWeight: 600, textAlign: 'center' }}>
                            {p.runs ?? p.total_runs ?? 0}
                          </td>
                          <td>
                            {p.success_rate_pct != null ? (
                              <span style={{
                                fontWeight: 700, fontSize: 12,
                                color: Number(p.success_rate_pct) >= 90 ? '#10B981' : '#F59E0B',
                              }}>
                                {p.success_rate_pct}%
                              </span>
                            ) : (
                              <span style={{ fontWeight: 600, color: '#10B981' }}>{p.success_rate || '100%'}</span>
                            )}
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            <div style={{ fontWeight: 500 }}>
                              {fmtDate(p.last_run_at || p.global_last_run)}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                              {p.last_run_age || (p.global_last_run ? '14d ago' : '—')}
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── FOCUSED PIPELINE INSPECTOR WORKSPACE ────────────────────── */}
        {selectedPipeline && (
          <div className="card" style={{ overflow: 'hidden' }}>
            {/* Inspector Header */}
            <div className="card-header" style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              flexWrap: 'wrap', gap: 14, borderBottom: '1px solid var(--border)', padding: '16px 20px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{
                  width: 38, height: 38, borderRadius: 8,
                  background: 'var(--brand-dim)', color: 'var(--brand)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  border: '1px solid var(--brand-border)', flexShrink: 0,
                }}>
                  <GitBranch size={20} />
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span className="card-title" style={{ fontSize: 17 }}>{selectedPipeline.pipeline_name}</span>
                    <span className={`status-pill ${statusPillClass(selectedPipeline.status || selectedPipeline.last_run_status)}`}>
                      {dash(selectedPipeline.status || selectedPipeline.last_run_status)}
                    </span>
                    {selectedPipeline.sla_hours != null && (
                      <span className="pipeline-sla-pill neutral"
                        title={`Configured Pipeline SLA Target: ${selectedPipeline.sla_hours}h allowed execution interval (from catalog definition)`}>
                        <Clock size={12} color="#10B981" />
                        <span>SLA Target: {selectedPipeline.sla_hours}h</span>
                      </span>
                    )}
                    {freshnessMonitor && (
                      <span className="pipeline-sla-pill"
                        title="Freshness Guardrail SLA from active monitor">
                        <Clock size={12} color="#10B981" />
                        <span>Freshness SLA: {freshnessMonitor.config?.sla_hours || 24}h</span>
                      </span>
                    )}
                    <span className="pipeline-sla-pill">
                      <Shield size={12} color="#10B981" />
                      <span>{monitors.length > 0 ? `${monitors.length} Guardrails Active` : 'Guardrails Active'}</span>
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 12, color: 'var(--text-muted)' }}>
                    <span>Pipeline ID: <code style={{ fontSize: 11 }}>{selectedPipeline.pipeline_id}</code></span>
                    <span>•</span>
                    <span>Flow: <strong>{selectedPipeline.source_tool || 'snowflake'}</strong> ➔ <strong>{selectedPipeline.etl_tool || 'dbt'}</strong> ➔ <strong>{selectedPipeline.target_tool || 'snowflake'}</strong></span>
                  </div>
                </div>
              </div>
            </div>

            {/* Pipeline Tabs Bar (Strictly Operational: Runs & Topology) */}
            <div className="pipe-tab-bar" style={{ padding: '0 20px', background: 'var(--bg-card)' }}>
              <button
                type="button"
                className={`pipe-tab-btn ${activePipelineTab === 'runs' ? 'active' : ''}`}
                onClick={() => setActivePipelineTab('runs')}
              >
                <Activity size={14} />
                <span>Execution Runs</span>
                <span className="pipe-tab-badge">{focusedRuns.length}</span>
              </button>

              <button
                type="button"
                className={`pipe-tab-btn ${activePipelineTab === 'bindings' ? 'active' : ''}`}
                onClick={() => setActivePipelineTab('bindings')}
              >
                <Layers size={14} />
                <span>Pipeline Architecture & Topology</span>
                <span className="pipe-tab-badge">{bindings.length}</span>
              </button>
            </div>

            <div style={{ padding: '16px 20px' }}>
              {/* ── TAB 1: RUNS LIST ─────────────────────────────────── */}
              {activePipelineTab === 'runs' && (
                <>
                  <div style={{ width: '100%', overflowX: 'hidden' }}>
                    <table className="vithi-table" style={{ width: '100%', tableLayout: 'fixed' }}>
                      <thead>
                        <tr>
                          <th style={{ width: '18%' }}>Run ID</th>
                          <th style={{ width: '11%' }}>Status</th>
                          <th style={{ width: '22%' }}>Timestamp</th>
                          <th style={{ width: '11%' }}>Duration</th>
                          <th style={{ width: '10%' }}>Tool</th>
                          <th style={{ width: '16%' }}>Message / Diagnostic</th>
                          <th style={{ width: '12%', textAlign: 'right' }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {paginated.length === 0 ? (
                          <tr>
                            <td colSpan={7} style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                              No execution runs recorded for <strong>{selectedPipeline.pipeline_name}</strong> in {selectedPresetLabel}.
                            </td>
                          </tr>
                        ) : (
                          paginated.map((r, idx) => {
                            const isFailed = (r.status || '').toLowerCase() === 'failed';
                            const runTime = r.timestamp || r.start_time || r.created_at;
                            return (
                              <tr
                                key={r.run_id || r.id || idx}
                                style={{ cursor: 'pointer' }}
                                onClick={() => setSelectedRun(r)}
                              >
                                <td>
                                  <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#10B981', fontSize: 13 }}>
                                    #{r.run_id || r.id}
                                  </span>
                                </td>
                                <td>
                                  <span className={`status-pill ${statusPillClass(r.status)}`}>
                                    {dash(r.status)}
                                  </span>
                                </td>
                                <td>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)' }}>
                                    <Clock size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                                    <span>{fmtDate(runTime)}</span>
                                  </div>
                                </td>
                                <td style={{ fontWeight: 600 }}>
                                  {r.duration_display || (r.duration != null ? `${r.duration}s` : fmtDuration(r.duration_seconds))}
                                </td>
                                <td><span className="tool-badge">{r.tool || r.tool_name || 'dbt'}</span></td>
                                <td>
                                  <span style={{
                                    color: isFailed ? '#EF4444' : 'var(--text-secondary)',
                                    fontSize: 12,
                                    display: 'block',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                  }}>
                                    {r.error_message || r.message || 'Execution completed successfully'}
                                  </span>
                                </td>
                                <td style={{ textAlign: 'right' }}>
                                  <button
                                    type="button"
                                    className="export-btn"
                                    style={{
                                      padding: '5px 12px', fontSize: 12,
                                      display: 'inline-flex', alignItems: 'center', gap: 5,
                                      background: isFailed ? '#DC2626' : '#047857',
                                      color: '#FFFFFF', border: 'none',
                                      fontWeight: 600,
                                    }}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelectedRun(r);
                                    }}
                                  >
                                    {isFailed ? (
                                      <>
                                        <AlertTriangle size={12} />
                                        <span>Diagnose RCA</span>
                                      </>
                                    ) : (
                                      <>
                                        <Eye size={12} />
                                        <span>View Details</span>
                                      </>
                                    )}
                                  </button>
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>

                  {totalPages > 1 && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 }}>
                      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Page {page} of {totalPages}</span>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="export-btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                          <ChevronLeft size={14} /> Previous
                        </button>
                        <button className="export-btn" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                          Next <ChevronRight size={14} />
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* ── TAB 2: PIPELINE ARCHITECTURE & TOPOLOGY ────────── */}
              {activePipelineTab === 'bindings' && (
                <div>
                  {detailsLoading ? (
                    <LoadingSpinner />
                  ) : (
                    <div>
                      {/* Section 1: Visual Execution Flow Track */}
                      <div style={{
                        background: 'var(--bg-card-subtle)',
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        padding: '14px 20px',
                        marginBottom: 24,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 14,
                        flexWrap: 'wrap',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span className="flow-tool-tag source" style={{ fontWeight: 700, fontSize: 10 }}>
                            SOURCE
                          </span>
                          <div>
                            <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                              Snowflake ({selectedPipeline.source_tool || 'snowflake'})
                            </strong>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>RAW_DATA.RAW_INVENTORY</div>
                          </div>
                        </div>

                        <ArrowRight size={18} color="#10B981" />

                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span className="flow-tool-tag etl" style={{ fontWeight: 700, fontSize: 10 }}>
                            TRANSFORM
                          </span>
                          <div>
                            <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                              dbt Cloud ({selectedPipeline.etl_tool || 'dbt'})
                            </strong>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{selectedPipeline.pipeline_name}-etl</div>
                          </div>
                        </div>

                        <ArrowRight size={18} color="#10B981" />

                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span className="flow-tool-tag target" style={{ fontWeight: 700, fontSize: 10 }}>
                            TARGET
                          </span>
                          <div>
                            <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                              Snowflake ({selectedPipeline.target_tool || 'snowflake'})
                            </strong>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>FINAL_DATA.DIM_INVENTORY</div>
                          </div>
                        </div>
                      </div>

                      {/* Section 2: Clean Connector Bindings Table (NO BOXES) */}
                      <div style={{ marginBottom: 28 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
                          Connected Infrastructure Instances ({bindings.length})
                        </div>
                        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                          <table className="vithi-table" style={{ width: '100%', tableLayout: 'fixed' }}>
                            <thead>
                              <tr>
                                <th style={{ width: '16%' }}>Role</th>
                                <th style={{ width: '22%' }}>Instance Name</th>
                                <th style={{ width: '14%' }}>Tool / Connector</th>
                                <th style={{ width: '34%' }}>Declared Schema & Tables</th>
                                <th style={{ width: '14%' }}>Kind</th>
                              </tr>
                            </thead>
                            <tbody>
                              {bindings.length === 0 ? (
                                <tr>
                                  <td colSpan={5} style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                                    No connector bindings recorded for this pipeline.
                                  </td>
                                </tr>
                              ) : (
                                bindings.map((b) => {
                                  const role = String(b.role || '').toLowerCase();
                                  let parsedAsset = null;
                                  try {
                                    parsedAsset = typeof b.asset_selector_json === 'string'
                                      ? JSON.parse(b.asset_selector_json)
                                      : b.asset_selector_json;
                                  } catch {
                                    parsedAsset = null;
                                  }

                                  return (
                                    <tr key={b.binding_id}>
                                      <td>
                                        <span className={`binding-role-tag ${role}`}>
                                          {b.role}
                                        </span>
                                      </td>
                                      <td>
                                        <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                                          {b.instance_name || b.instance_id}
                                        </strong>
                                      </td>
                                      <td>
                                        <span className="tool-badge">{b.connector_type}</span>
                                      </td>
                                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                                        {parsedAsset?.schema && (
                                          <span>Schema: <strong>{parsedAsset.schema}</strong> </span>
                                        )}
                                        {parsedAsset?.tables?.length > 0 && (
                                          <span style={{ color: 'var(--text-secondary)' }}>
                                            [Tables: {parsedAsset.tables.join(', ')}]
                                          </span>
                                        )}
                                        {!parsedAsset?.schema && !parsedAsset?.tables?.length && (
                                          <span style={{ color: 'var(--text-muted)' }}>Models / Transformation Scope</span>
                                        )}
                                      </td>
                                      <td style={{ fontSize: 12, color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                                        {b.kind || 'Connector'}
                                      </td>
                                    </tr>
                                  );
                                })
                              )}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      {/* Section 3: Clean Health Guardrails Table (NO BOXES) */}
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Shield size={14} color="#10B981" />
                            <span>Active Health Guardrails & SLAs ({monitors.length})</span>
                          </div>
                          <a
                            href="/observability/data-quality"
                            style={{ fontSize: 12, color: '#10B981', fontWeight: 600, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
                          >
                            <span>Manage rules in Data Observability</span>
                            <ExternalLink size={12} />
                          </a>
                        </div>

                        <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                          <table className="vithi-table" style={{ width: '100%', tableLayout: 'fixed' }}>
                            <thead>
                              <tr>
                                <th style={{ width: '24%' }}>Guardrail / Monitor</th>
                                <th style={{ width: '16%' }}>Type</th>
                                <th style={{ width: '18%' }}>Dimension</th>
                                <th style={{ width: '26%' }}>Configured SLA / Target</th>
                                <th style={{ width: '16%', textAlign: 'right' }}>Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {monitors.length === 0 ? (
                                <tr>
                                  <td colSpan={5} style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                                    No active monitors or guardrails configured.
                                  </td>
                                </tr>
                              ) : (
                                monitors.map((m) => {
                                  let thresholdDesc = 'Standard assertion';
                                  if (m.config?.sla_hours) thresholdDesc = `${m.config.sla_hours} hours SLA`;
                                  if (m.config?.crit_pct) thresholdDesc = `Critical drop threshold: ${m.config.crit_pct}%`;
                                  if (m.monitor_kind === 'dbt_test_failure') thresholdDesc = 'Zero dbt test failures';
                                  if (m.monitor_kind === 'pipeline_failure') thresholdDesc = 'Zero execution failures';

                                  return (
                                    <tr key={m.monitor_id}>
                                      <td>
                                        <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>
                                          {m.name || m.monitor_kind}
                                        </strong>
                                      </td>
                                      <td>
                                        <span className="tag" style={{ textTransform: 'uppercase', fontSize: 10 }}>
                                          {m.monitor_type || m.monitor_kind}
                                        </span>
                                      </td>
                                      <td style={{ fontSize: 12, color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                                        {m.dimension || 'Operational'}
                                      </td>
                                      <td style={{ fontSize: 12, color: 'var(--text-primary)' }}>
                                        {thresholdDesc}
                                      </td>
                                      <td style={{ textAlign: 'right' }}>
                                        <span style={{
                                          display: 'inline-flex', alignItems: 'center', gap: 4,
                                          fontSize: 11, fontWeight: 700,
                                          color: m.is_enabled ? 'var(--brand-text)' : 'var(--text-muted)',
                                          background: m.is_enabled ? 'var(--brand-dim)' : 'var(--bg-card-subtle)',
                                          border: m.is_enabled ? '1px solid var(--brand-border)' : '1px solid var(--border)',
                                          padding: '2px 8px', borderRadius: 6,
                                        }}>
                                          {m.is_enabled ? '● Active' : 'Disabled'}
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                })
                              )}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════════════ */}
        {/* RUN DETAILS & RCA MODAL                                            */}
        {/* ═══════════════════════════════════════════════════════════════════ */}
        {selectedRun && (
          <div className="modal-backdrop" onClick={() => setSelectedRun(null)}>
            <div className="modal-content rca-modal-container" onClick={e => e.stopPropagation()}>
              {/* Modal Header */}
              {(() => {
                const isFailedRun = (selectedRun.status || '').toLowerCase() === 'failed';
                return (
                  <div className="modal-header">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      {isFailedRun ? (
                        <AlertTriangle size={18} style={{ color: '#EF4444' }} />
                      ) : (
                        <CheckCircle size={18} style={{ color: '#10B981' }} />
                      )}
                      <div>
                        <span style={{ fontWeight: 700, fontSize: 15 }}>
                          {isFailedRun ? 'Root Cause Analysis (RCA) Workbench' : 'Run Diagnostics & Validations'}
                        </span>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
                          Run #{selectedRun.run_id || selectedRun.id} · {selectedRun.pipeline_name}
                        </span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className={`status-pill ${statusPillClass(selectedRun.status)}`}>
                        {dash(selectedRun.status)}
                      </span>
                      <button type="button" className="icon-btn" onClick={() => setSelectedRun(null)}>
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                );
              })()}

              {/* Modal Body */}
              <div className="modal-body" style={{ overflowY: 'auto', padding: 20 }}>
                {rcaLoading ? (
                  <LoadingSpinner />
                ) : (
                  <>
                    {/* Top RCA Metric Counters */}
                    <div className="rca-grid-summary">
                      <div className="rca-summary-box">
                        <div className="lbl">dbt Tests</div>
                        <div className="val" style={{ color: '#10B981' }}>
                          {rcaContext?.summary?.dbt_test_count ?? 0}
                        </div>
                      </div>

                      <div className="rca-summary-box">
                        <div className="lbl">Failed Tests</div>
                        <div className="val" style={{ color: (rcaContext?.summary?.failed_test_count || 0) > 0 ? '#EF4444' : '#10B981' }}>
                          {rcaContext?.summary?.failed_test_count ?? 0}
                        </div>
                      </div>

                      <div className="rca-summary-box">
                        <div className="lbl">DQ Checks</div>
                        <div className="val">
                          {rcaContext?.summary?.dq_check_count ?? 0}
                        </div>
                      </div>

                      <div className="rca-summary-box">
                        <div className="lbl">Duration</div>
                        <div className="val" style={{ fontSize: 15 }}>
                          {selectedRun.duration_display || (selectedRun.duration != null ? `${selectedRun.duration}s` : fmtDuration(selectedRun.duration_seconds))}
                        </div>
                      </div>

                      <div className="rca-summary-box">
                        <div className="lbl">Execution Mode</div>
                        <div className="val" style={{ fontSize: 13, textTransform: 'capitalize' }}>
                          {selectedRun.execution_mode || 'Orchestrated'}
                        </div>
                      </div>
                    </div>

                    {/* Failure Diagnostic Banner (if failed) */}
                    {(selectedRun.error_message || selectedRun.failure_stage) && (
                      <div style={{
                        padding: 12,
                        background: 'rgba(239, 68, 68, 0.08)',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                        borderRadius: 6,
                        marginBottom: 16,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#EF4444', fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
                          <AlertTriangle size={15} />
                          <span>Failure Diagnosis: {selectedRun.failure_stage || 'Execution Failure'}</span>
                        </div>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                          {selectedRun.error_message || selectedRun.message}
                        </div>
                      </div>
                    )}

                    {/* RCA Sub-Tabs */}
                    <div className="pipe-tab-bar" style={{ marginBottom: 12 }}>
                      <button
                        type="button"
                        className={`pipe-tab-btn ${activeRcaTab === 'tests' ? 'active' : ''}`}
                        onClick={() => setActiveRcaTab('tests')}
                      >
                        <CheckSquare size={14} />
                        <span>dbt Tests ({rcaContext?.dbt_tests?.length || 0})</span>
                      </button>

                      <button
                        type="button"
                        className={`pipe-tab-btn ${activeRcaTab === 'dq_checks' ? 'active' : ''}`}
                        onClick={() => setActiveRcaTab('dq_checks')}
                      >
                        <Shield size={14} />
                        <span>DQ Checks ({rcaContext?.dq_checks?.length || 0})</span>
                      </button>

                      <button
                        type="button"
                        className={`pipe-tab-btn ${activeRcaTab === 'assets' ? 'active' : ''}`}
                        onClick={() => setActiveRcaTab('assets')}
                      >
                        <Database size={14} />
                        <span>Asset Impact</span>
                      </button>
                    </div>

                    {/* Tab: dbt Tests */}
                    {activeRcaTab === 'tests' && (
                      <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', maxHeight: 300, overflowY: 'auto' }}>
                        <table className="vithi-table" style={{ width: '100%', tableLayout: 'fixed' }}>
                          <thead>
                            <tr>
                              <th style={{ width: '18%' }}>Status</th>
                              <th style={{ width: '48%' }}>Test Name</th>
                              <th style={{ width: '18%' }}>Dimension</th>
                              <th style={{ width: '16%' }}>Duration</th>
                            </tr>
                          </thead>
                          <tbody>
                            {!rcaContext?.dbt_tests?.length ? (
                              <tr>
                                <td colSpan={4} style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>
                                  No dbt test results captured for this run.
                                </td>
                              </tr>
                            ) : (
                              rcaContext.dbt_tests.map((t, idx) => {
                                let testId = t.test_id || '';
                                try {
                                  if (t.observed_json) {
                                    const parsed = JSON.parse(t.observed_json);
                                    if (parsed.test_id) testId = parsed.test_id;
                                  }
                                } catch {}
                                const cleanName = testId.replace(/^test\.[^.]+\./, '');

                                return (
                                  <tr key={t.check_id || idx}>
                                    <td>
                                      <span className={`status-pill ${statusPillClass(t.status)}`}>
                                        {t.status || 'PASS'}
                                      </span>
                                    </td>
                                    <td>
                                      <strong style={{ fontSize: 12, color: 'var(--text-primary)', wordBreak: 'break-all' }}>
                                        {cleanName || testId}
                                      </strong>
                                    </td>
                                    <td>
                                      <span className="tag">{t.dimension || 'validity'}</span>
                                    </td>
                                    <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                      {t.execution_time != null ? `${Number(t.execution_time).toFixed(2)}s` : '—'}
                                    </td>
                                  </tr>
                                );
                              })
                            )}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Tab: DQ Checks */}
                    {activeRcaTab === 'dq_checks' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {!rcaContext?.dq_checks?.length ? (
                          <div className="obs-simple-empty" style={{ padding: 24 }}>
                            No DQ assertions attached to this run.
                          </div>
                        ) : (
                          rcaContext.dq_checks.map((chk, idx) => (
                            <div key={chk.check_id || idx} style={{
                              background: 'var(--bg-card-subtle)',
                              border: '1px solid var(--border)',
                              borderRadius: 6,
                              padding: 12,
                            }}>
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                                <span className={`status-pill ${statusPillClass(chk.status)}`}>
                                  {chk.status || 'PASS'}
                                </span>
                                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  Checked {dash(chk.checked_at)}
                                </span>
                              </div>
                              <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>
                                {chk.message || 'Assertion evaluated'}
                              </div>
                              {chk.observed_json && (
                                <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)', marginTop: 4 }}>
                                  {chk.observed_json}
                                </div>
                              )}
                            </div>
                          ))
                        )}
                      </div>
                    )}

                    {/* Tab: Asset Impact */}
                    {activeRcaTab === 'assets' && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        {!(rcaContext?.assets || selectedRun.assets)?.length ? (
                          <div className="obs-simple-empty" style={{ padding: 24 }}>
                            No dataset asset telemetry recorded for this run.
                          </div>
                        ) : (
                          (rcaContext?.assets || selectedRun.assets).map((asset, idx) => (
                            <div key={idx} style={{
                              background: 'var(--bg-card-subtle)',
                              border: '1px solid var(--border)',
                              borderRadius: 6,
                              padding: 14,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                            }}>
                              <div>
                                <span className={`binding-role-tag ${String(asset.asset_role || '').toLowerCase()}`}>
                                  {asset.asset_role}
                                </span>
                                <div style={{ fontWeight: 600, fontSize: 14, marginTop: 6, color: 'var(--text-primary)' }}>
                                  {asset.dataset_id || asset.object_name}
                                </div>
                              </div>

                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                                  {asset.row_count != null ? `${asset.row_count.toLocaleString()} rows` : '—'}
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  {formatBytes(asset.size_bytes)}
                                </div>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
