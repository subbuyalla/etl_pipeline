import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Database, Activity, Search, GitBranch, TrendingUp, Info, AlertTriangle, CheckCircle,
  Clock, Share2,
} from 'lucide-react';
import {
  AreaChart, Area, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../../components/PageHeader';
import LoadingSpinner from '../../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../../components/SkeletonLoaders';
import {
  fetchVolume, fetchMonitors, fetchPipelines, fetchPipelineRuns,
} from '../../api/client';
import {
  dash, kpiMapFrom, statusTone, buildDateParams, handleDateChange,
  TOOLTIP_STYLE, formatBytes,
} from './obsUtils';

const PIPELINE_COLORS = ['#10B981', '#3B82F6', '#F59E0B', '#8B5CF6', '#06B6D4', '#EF4444'];
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function dayKey(ts) {
  if (!ts) return null;
  const m = String(ts).match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : null;
}

function parseDay(key) {
  const [y, mo, d] = key.split('-').map(Number);
  return new Date(y, mo - 1, d);
}

function formatAxisDay(key) {
  if (!key) return '';
  const dt = parseDay(key);
  return `${MONTHS_SHORT[dt.getMonth()]} ${String(dt.getDate()).padStart(2, '0')}`;
}

function formatTooltipDay(key) {
  if (!key) return '';
  const dt = parseDay(key);
  return `${MONTHS_SHORT[dt.getMonth()]} ${String(dt.getDate()).padStart(2, '0')}, ${dt.getFullYear()}`;
}

/** Build a continuous daily trend (API often returns 1 point for preset=all). */
function buildVolumeTrend(series, range) {
  const byDay = new Map();
  (series || []).forEach((p) => {
    const key = dayKey(p.timestamp || p.time);
    if (!key) return;
    const bytes = Number(p.bytes ?? 0);
    byDay.set(key, {
      records: Number(p.records ?? 0),
      bytes,
      size_kb: Math.round((bytes / 1024) * 1000) / 1000,
      volume_gb: Number(p.volume_gb ?? 0),
    });
  });

  let endKey = dayKey(range?.to) || dayKey(new Date().toISOString());
  let startKey = dayKey(range?.from);

  // "all"/epoch ranges → last 30 days so the chart matches a real trend window
  if (!startKey || startKey.startsWith('1970')) {
    const end = parseDay(endKey);
    const start = new Date(end);
    start.setDate(start.getDate() - 29);
    startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
  }

  // Sparse series (1–2 points): still draw a 30-day baseline ending at range.to
  if (byDay.size > 0 && byDay.size < 5) {
    const end = parseDay(endKey);
    const start = new Date(end);
    start.setDate(start.getDate() - 29);
    startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
  }

  const out = [];
  const cursor = parseDay(startKey);
  const end = parseDay(endKey);
  // Safety: cap padded series length
  let guard = 0;
  while (cursor <= end && guard < 400) {
    const key = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, '0')}-${String(cursor.getDate()).padStart(2, '0')}`;
    const hit = byDay.get(key);
    out.push({
      time: key,
      label: formatAxisDay(key),
      records: hit?.records ?? 0,
      bytes: hit?.bytes ?? 0,
      size_kb: hit?.size_kb ?? 0,
      volume_gb: hit?.volume_gb ?? 0,
    });
    cursor.setDate(cursor.getDate() + 1);
    guard += 1;
  }
  return out;
}

function TrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
  return (
    <div className="vol-trend-tooltip">
      <div className="vol-trend-tooltip-title">{formatTooltipDay(row.time)}</div>
      <div className="vol-trend-tooltip-row">
        <span className="vol-trend-dot" style={{ background: '#1D4ED8' }} />
        <span>Records</span>
        <strong>{row.records ?? 0}</strong>
      </div>
      <div className="vol-trend-tooltip-row">
        <span className="vol-trend-dot" style={{ background: '#10B981' }} />
        <span>Size (KB)</span>
        <strong>{formatBytes(row.bytes) || '0 B'}</strong>
      </div>
      <div className="vol-trend-tooltip-row">
        <span className="vol-trend-dot" style={{ background: '#93C5FD' }} />
        <span>Volume (GB)</span>
        <strong>{Number(row.volume_gb || 0)} GB</strong>
      </div>
    </div>
  );
}

function formatStamp(ts) {
  if (!ts) return null;
  const s = String(ts);
  // "2026-09-02 08:09:34" → "Sep 02, 08:09"
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return s;
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `${months[Number(m[2]) - 1]} ${m[3]}, ${m[4]}:${m[5]}`;
}

function shortRunId(id) {
  if (id == null || id === '') return '—';
  const s = String(id);
  if (s.length <= 10) return s;
  return `${s.slice(0, 8)}…`;
}

function runStatusPill(status) {
  const s = String(status || '').toLowerCase();
  if (['success', 'succeeded', 'passed', 'ok', 'healthy'].includes(s)) return 'good';
  if (['warning', 'warn', 'degraded'].includes(s)) return 'warning';
  if (['failed', 'fail', 'error', 'critical'].includes(s)) return 'critical';
  return 'neutral';
}

function prettyStatus(status) {
  if (!status) return '—';
  const s = String(status);
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

function aggregateShares(rows) {
  const total = rows.reduce((acc, r) => acc + Number(r.bytes || 0), 0);
  return rows
    .map((r, i) => {
      const bytes = Number(r.bytes || 0);
      const share = total > 0 ? Math.round((bytes / total) * 1000) / 10 : 0;
      return {
        name: r.name,
        bytes,
        records: Number(r.records || 0),
        share,
        color: PIPELINE_COLORS[i % PIPELINE_COLORS.length],
        bytes_display: formatBytes(bytes) || '0 B',
      };
    })
    .filter(r => r.bytes > 0 || r.records > 0)
    .sort((a, b) => b.bytes - a.bytes);
}

export default function Volume() {
  const navigate = useNavigate();
  const [data, setData] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);
  const [byPipeline, setByPipeline] = useState([]);
  const [volumeMonitors, setVolumeMonitors] = useState([]);
  const [pipelineMeta, setPipelineMeta] = useState([]);
  const [recentRuns, setRecentRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [activityFilter, setActivityFilter] = useState('All');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [toolFilter, setToolFilter] = useState('All');
  const [breakTab, setBreakTab] = useState('pipeline');
  const [headerDatePreset, setHeaderDatePreset] = useState('30d');
  const [customDateRange, setCustomDateRange] = useState(null);
  const [apiRange, setApiRange] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params = buildDateParams(headerDatePreset, customDateRange);
      if (pipelineFilter && pipelineFilter !== 'All') {
        params.pipeline_name = pipelineFilter;
      }
      if (toolFilter && toolFilter !== 'All') {
        params.tool = toolFilter.toLowerCase();
      }
      const [volRes, monRes, pipeRes] = await Promise.allSettled([
        fetchVolume(params),
        fetchMonitors(),
        fetchPipelines({ preset: 'all' }),
      ]);

      let volItems = [];
      if (volRes.status === 'fulfilled') {
        const res = volRes.value;
        volItems = res?.items || [];
        setData(volItems);
        setKpis(res?.kpis || []);
        setSummary(res?.summary || null);
        setSeries(res?.series?.volume_over_time || []);
        setByPipeline(res?.charts?.by_pipeline || []);
        setApiRange(res?.range || null);
      }
      if (monRes.status === 'fulfilled') {
        const list = monRes.value?.items || [];
        setVolumeMonitors(list.filter(m => String(m.monitor_type || '').toLowerCase().includes('volume')));
      }
      if (pipeRes.status === 'fulfilled') {
        setPipelineMeta(pipeRes.value?.items || []);
      }

      const ids = [...new Set(volItems.map(i => i.pipeline_id).filter(Boolean))];
      if (ids.length === 0) {
        setRecentRuns([]);
      } else {
        const runLists = await Promise.all(
          ids.map(id => fetchPipelineRuns(id, params).catch(() => ({ items: [] }))),
        );
        const merged = runLists.flatMap(r => r?.items || []);
        merged.sort((a, b) => String(b.start_time || '').localeCompare(String(a.start_time || '')));
        setRecentRuns(merged.slice(0, 20));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange, pipelineFilter, toolFilter]);

  useEffect(() => { loadData(); }, [loadData]);

  const kpi = useMemo(() => kpiMapFrom(kpis), [kpis]);
  const totalRows = Number(summary?.total_rows ?? kpi.records_received?.value ?? 0);
  const totalBytes = Number(summary?.total_bytes ?? kpi.data_received?.value ?? 0);
  const prevRows = summary?.prev_rows;

  const metaById = useMemo(() => {
    const map = {};
    pipelineMeta.forEach((p) => {
      if (p.pipeline_id) map[p.pipeline_id] = p;
    });
    return map;
  }, [pipelineMeta]);

  const toolOptions = useMemo(() => {
    const set = new Set();
    pipelineMeta.forEach(p => {
      [p.source_tool, p.etl_tool, p.target_tool].forEach(t => {
        if (t && String(t).trim()) set.add(String(t).trim());
      });
    });
    const list = Array.from(set).sort();
    return list.length ? list : ['Informatica', 'Snowflake', 'dbt', 'MySQL', 'PostgreSQL'];
  }, [pipelineMeta]);

  const pipelineNames = useMemo(() => {
    const names = new Set();
    pipelineMeta.forEach(p => {
      const n = p.pipeline_name || p.name;
      if (n) names.add(n);
    });
    data.forEach(d => { if (d.pipeline_name) names.add(d.pipeline_name); });
    byPipeline.forEach(p => { if (p.pipeline_name) names.add(p.pipeline_name); });
    return [...names].sort();
  }, [pipelineMeta, data, byPipeline]);

  const filtered = useMemo(() => data.filter((d) => {
    const st = String(d.status_key || d.status || '').toLowerCase();
    const records = Number(d.records ?? 0);
    const hay = [d.pipeline_name, d.pipeline_id].join(' ').toLowerCase();
    const statusOk = statusFilter === 'All'
      || (statusFilter === 'healthy' && (st === 'healthy' || st === 'good' || st === 'ok'))
      || (statusFilter === 'warning' && (st === 'warning' || st === 'warn' || st === 'degraded'))
      || (statusFilter === 'critical' && (st === 'critical' || st === 'unhealthy' || st === 'error'));
    const activityOk = activityFilter === 'All'
      || (activityFilter === 'active' && records > 0)
      || (activityFilter === 'empty' && records === 0);
    const pipelineOk = pipelineFilter === 'All' || d.pipeline_name === pipelineFilter;
    const meta = metaById[d.pipeline_id];
    const toolHay = [meta?.source_tool, meta?.etl_tool, meta?.target_tool, d.source_tool, d.etl_tool, d.target_tool].filter(Boolean).join(' ').toLowerCase();
    const toolOk = toolFilter === 'All' || toolHay.includes(toolFilter.toLowerCase());
    return (!search || hay.includes(search.toLowerCase())) && statusOk && activityOk && pipelineOk && toolOk;
  }), [data, search, statusFilter, activityFilter, pipelineFilter, toolFilter, metaById]);

  const filtersDirty = Boolean(search || statusFilter !== 'All' || activityFilter !== 'All' || pipelineFilter !== 'All' || toolFilter !== 'All');

  const filteredTotalRows = useMemo(() => filtered.reduce((acc, d) => acc + Number(d.records || 0), 0), [filtered]);
  const filteredTotalBytes = useMemo(() => filtered.reduce((acc, d) => acc + Number(d.bytes || 0), 0), [filtered]);
  const filteredRunsCount = useMemo(() => filtered.reduce((acc, d) => acc + Number(d.runs || 0), 0), [filtered]);
  const filteredActiveCount = useMemo(() => filtered.filter(d => Number(d.records || 0) > 0).length, [filtered]);

  const displayedBytes = filtersDirty
    ? (formatBytes(filteredTotalBytes) || '0 B')
    : (kpi.data_received?.display || formatBytes(totalBytes) || '—');

  const displayedRows = filtersDirty
    ? filteredTotalRows.toLocaleString()
    : (kpi.records_received?.display ?? (summary?.total_rows != null ? Number(summary.total_rows).toLocaleString() : '—'));

  const displayedActive = filtersDirty
    ? `${filteredActiveCount} / ${filtered.length}`
    : (kpi.pipelines_active?.display || `${filteredActiveCount} / ${filtered.length}`);

  const displayedRuns = filtersDirty
    ? filteredRunsCount.toLocaleString()
    : (kpi.runs?.display || filteredRunsCount.toLocaleString());

  const trend = useMemo(() => {
    if (filtersDirty && filtered.length === 0) return [];
    return buildVolumeTrend(series, apiRange);
  }, [series, apiRange, filtersDirty, filtered]);
  const hasTrendSignal = trend.some(p => Number(p.records) > 0 || Number(p.bytes) > 0);

  const donutData = useMemo(() => {
    const source = (filtersDirty ? filtered : (byPipeline.length ? byPipeline : data))
      .filter(d => Number(d.records) > 0 || Number(d.bytes) > 0);
    const sumBytes = source.reduce((acc, r) => acc + Number(r.bytes || 0), 0);
    return source.map((p, i) => {
      const bytes = Number(p.bytes ?? 0);
      const share = sumBytes > 0 ? Math.round((bytes / sumBytes) * 1000) / 10 : (p.share_pct ?? 0);
      return {
        name: p.pipeline_name || p.name || '—',
        value: bytes || Number(p.records ?? 0),
        records: Number(p.records ?? 0),
        bytes,
        share,
        color: PIPELINE_COLORS[i % PIPELINE_COLORS.length],
        bytes_display: formatBytes(bytes) || (p.bytes_display ?? '—'),
      };
    }).filter(d => d.value > 0);
  }, [filtersDirty, filtered, byPipeline, data]);

  const breakByPipeline = useMemo(() => {
    const source = filtersDirty ? filtered : (byPipeline.length ? byPipeline : data);
    return aggregateShares(source.map(p => ({
      name: p.pipeline_name || '—',
      bytes: p.bytes,
      records: p.records,
    })));
  }, [filtersDirty, filtered, byPipeline, data]);

  const breakBySource = useMemo(() => {
    const buckets = {};
    const source = filtersDirty ? filtered : data;
    source.forEach((d) => {
      const meta = metaById[d.pipeline_id];
      const name = meta?.source_tool || meta?.source?.tool || 'Unknown source';
      if (!buckets[name]) buckets[name] = { name, bytes: 0, records: 0 };
      buckets[name].bytes += Number(d.bytes || 0);
      buckets[name].records += Number(d.records || 0);
    });
    return aggregateShares(Object.values(buckets));
  }, [filtersDirty, filtered, data, metaById]);

  const breakByDataset = useMemo(() => {
    const buckets = {};
    const allowedPipelineIds = new Set(filtered.map(d => d.pipeline_id));
    recentRuns
      .filter(run => !filtersDirty || allowedPipelineIds.has(run.pipeline_id))
      .forEach((run) => {
        (run.assets || [])
          .filter(a => String(a.asset_role || '').toUpperCase() === 'TARGET')
          .forEach((a) => {
            const name = a.object_name || a.dataset_id || 'Unknown dataset';
            if (!buckets[name]) buckets[name] = { name, bytes: 0, records: 0 };
            buckets[name].bytes += Number(a.size_bytes || 0);
            buckets[name].records += Number(a.row_count || 0);
          });
      });
    return aggregateShares(Object.values(buckets));
  }, [recentRuns, filtersDirty, filtered]);

  const breakdownRows = breakTab === 'source'
    ? breakBySource
    : breakTab === 'dataset'
      ? breakByDataset
      : breakByPipeline;

  const filteredRuns = useMemo(() => recentRuns.filter((r) => {
    if (pipelineFilter !== 'All' && r.pipeline_name !== pipelineFilter) return false;
    if (search) {
      const hay = [r.pipeline_name, r.id, r.status].join(' ').toLowerCase();
      if (!hay.includes(search.toLowerCase())) return false;
    }
    return true;
  }), [recentRuns, pipelineFilter, search]);

  const unhealthy = (filtersDirty ? filtered : data).filter(d => {
    const tone = statusTone(d.status_key || d.status);
    return tone === 'warn' || tone === 'crit';
  }).length;
  const critPct = volumeMonitors.find(m => m.config?.crit_pct != null)?.config?.crit_pct;
  const emptyWindow = filtersDirty ? filtered.length === 0 : (totalRows === 0 && data.length === 0);

  const bytesLabel = displayedBytes;
  const rowsLabel = displayedRows;

  const activeDisplay = String(displayedActive || '');
  const activeParts = activeDisplay.match(/(\d+)\s*\/\s*(\d+)/);
  const activeHint = filtersDirty
    ? `${filteredActiveCount} active with volume (${filtered.length} total)`
    : (activeParts
      ? `${activeParts[1]} with volume, ${Math.max(0, Number(activeParts[2]) - Number(activeParts[1]))} inactive`
      : 'with volume in this range');

  const targetFromRun = (run) => {
    const assets = run.assets || [];
    const target = assets.find(a => String(a.asset_role || '').toUpperCase() === 'TARGET');
    return {
      records: run.rows_written ?? run.rows_added ?? target?.row_count ?? null,
      bytes: target?.size_bytes ?? null,
    };
  };

  return (
    <div className="fade-in">
      <PageHeader
        title="Volume"
        subtitle="Track how much data each pipeline produced — rows and size over time."
        onRefresh={loadData}
        datePreset={headerDatePreset}
        onDateChange={(v) => handleDateChange(setHeaderDatePreset, setCustomDateRange, v)}
      />

      <div className="page-body">
        {loading ? <DashboardPageSkeleton kpiCount={4} chartCount={2} tableRows={6} tableCols={6} /> : (
          <>
            {emptyWindow ? (
              <div className="obs-alert is-warn">
                <AlertTriangle size={18} />
                <div>
                  <strong>No volume in this time range.</strong>
                  {' '}Try <em>All Time</em> or <em>Last 30 Days</em>
                  {prevRows != null && Number(prevRows) > 0
                    ? ` — previous window had ${prevRows} rows.`
                    : '.'}
                </div>
              </div>
            ) : unhealthy > 0 ? (
              <div className="obs-alert is-warn">
                <TrendingUp size={18} />
                <div>
                  <strong>{unhealthy} pipeline{unhealthy === 1 ? '' : 's'} need review.</strong>
                  {' '}Volume status is not healthy for those rows below.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div>
                  <strong>Volume looks normal.</strong>
                  {' '}{dash(rowsLabel)} records · {dash(bytesLabel)} received.
                </div>
              </div>
            )}

            <div className="obs-insight">
              <Info size={15} />
              <div>
                <strong>How volume is measured</strong>
                <span>
                  Totals for the selected range: {dash(rowsLabel)} rows · {dash(bytesLabel)}.
                  {critPct != null ? ` Drop monitor alerts if rows fall by ≥${critPct}%.` : ''}
                  {prevRows != null ? ` Previous window: ${prevRows} rows.` : ''}
                </span>
              </div>
            </div>

            <div className="filters-bar">
              <div className="search-box">
                <Search size={14} />
                <input
                  placeholder="Search pipeline…"
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
                  <option value="All">All pipelines</option>
                  {pipelineNames.map(name => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </div>
              <div className="filter-select">
                <label>Connection / Tool</label>
                <select
                  className="select-control"
                  value={toolFilter}
                  onChange={e => setToolFilter(e.target.value)}
                  title="Filter volume by connection or tool (Informatica, Snowflake, dbt, etc.)"
                >
                  <option value="All">All Connections</option>
                  {toolOptions.map(name => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </div>
              <div className="filter-select">
                <label>Status</label>
                <select
                  className="select-control"
                  value={statusFilter}
                  onChange={e => setStatusFilter(e.target.value)}
                >
                  <option value="All">All</option>
                  <option value="healthy">Healthy</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div className="filter-select">
                <label>Activity</label>
                <select
                  className="select-control"
                  value={activityFilter}
                  onChange={e => setActivityFilter(e.target.value)}
                >
                  <option value="All">All</option>
                  <option value="active">Has rows</option>
                  <option value="empty">No rows</option>
                </select>
              </div>
              {filtersDirty && (
                <button
                  type="button"
                  className="export-btn"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => {
                    setSearch('');
                    setStatusFilter('All');
                    setActivityFilter('All');
                    setPipelineFilter('All');
                    setToolFilter('All');
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>

            <div className="kpi-grid-4 mt-4">
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EEF2FF', color: '#6366F1' }}><Database size={18} /></div>
                  <span className="kpi-label">Data received</span>
                </div>
                <div className="kpi-value">{dash(displayedBytes)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{filtersDirty ? 'in filtered scope' : 'vs previous period'}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}><Activity size={18} /></div>
                  <span className="kpi-label">Records received</span>
                </div>
                <div className="kpi-value" style={{ color: (filtersDirty ? filteredTotalRows : totalRows) > 0 ? '#10B981' : undefined }}>
                  {dash(displayedRows)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{filtersDirty ? 'in filtered scope' : 'vs previous period'}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}><GitBranch size={18} /></div>
                  <span className="kpi-label">Pipelines active</span>
                </div>
                <div className="kpi-value">{dash(displayedActive)}</div>
                <div style={{
                  fontSize: 11,
                  marginTop: 2,
                  color: kpi.pipelines_active?.tone === 'warn' ? '#D97706' : 'var(--text-muted)',
                }}>
                  {activeHint}
                </div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}><TrendingUp size={18} /></div>
                  <span className="kpi-label">Runs</span>
                </div>
                <div className="kpi-value">{dash(displayedRuns)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{filtersDirty ? 'in filtered scope' : 'in selected range'}</div>
              </div>
            </div>

            <div className="grid-2 mt-4" style={{ gap: 16 }}>
              <div className="card">
                <div className="card-header vol-trend-header">
                  <div>
                    <span className="card-title">Data volume trend</span>
                    <span className="card-subtitle">Daily records, size, and volume in this range</span>
                  </div>
                  <div className="vol-trend-legend">
                    <span><i style={{ background: '#1D4ED8' }} /> Records</span>
                    <span><i style={{ background: '#10B981' }} /> Size (KB)</span>
                    <span><i style={{ background: '#93C5FD' }} /> Volume (GB)</span>
                  </div>
                </div>
                {trend.length === 0 || !hasTrendSignal ? (
                  <div className="obs-simple-empty">
                    {trend.length === 0
                      ? 'No history points for this range.'
                      : 'No volume in this window — try Last 30 Days or All Time.'}
                  </div>
                ) : (
                  <div style={{ height: 260, padding: '4px 8px 8px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={trend} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="volRecGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="#3B82F6" stopOpacity={0.02} />
                          </linearGradient>
                          <linearGradient id="volSizeGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#10B981" stopOpacity={0.28} />
                            <stop offset="100%" stopColor="#10B981" stopOpacity={0.02} />
                          </linearGradient>
                          <linearGradient id="volGbGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#93C5FD" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="#93C5FD" stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                        <XAxis
                          dataKey="label"
                          tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                          axisLine={false}
                          tickLine={false}
                          interval="preserveStartEnd"
                          minTickGap={36}
                        />
                        <YAxis
                          tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                          axisLine={false}
                          tickLine={false}
                          width={36}
                        />
                        <Tooltip content={<TrendTooltip />} cursor={{ stroke: '#CBD5E1', strokeDasharray: '4 4' }} />
                        <Area
                          type="monotone"
                          dataKey="volume_gb"
                          name="Volume (GB)"
                          stroke="#93C5FD"
                          fill="url(#volGbGrad)"
                          strokeWidth={2}
                          dot={false}
                          activeDot={{ r: 4, strokeWidth: 0, fill: '#93C5FD' }}
                        />
                        <Area
                          type="monotone"
                          dataKey="size_kb"
                          name="Size (KB)"
                          stroke="#10B981"
                          fill="url(#volSizeGrad)"
                          strokeWidth={2}
                          dot={false}
                          activeDot={{ r: 4, strokeWidth: 0, fill: '#10B981' }}
                        />
                        <Area
                          type="monotone"
                          dataKey="records"
                          name="Records"
                          stroke="#1D4ED8"
                          fill="url(#volRecGrad)"
                          strokeWidth={2.5}
                          dot={false}
                          activeDot={{ r: 5, strokeWidth: 0, fill: '#1D4ED8' }}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Volume by pipeline</span>
                    <span className="card-subtitle">Share of total size in this range</span>
                  </div>
                </div>
                {donutData.length === 0 ? (
                  <div className="obs-simple-empty">No pipeline share data for this range.</div>
                ) : (
                  <div className="vol-donut-wrap">
                    <div className="vol-donut-chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={donutData}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            innerRadius={52}
                            outerRadius={74}
                            paddingAngle={donutData.length > 1 ? 2 : 0}
                          >
                            {donutData.map((e) => (
                              <Cell key={e.name} fill={e.color} />
                            ))}
                          </Pie>
                          <Tooltip
                            {...TOOLTIP_STYLE}
                            formatter={(_, __, props) => {
                              const p = props?.payload;
                              if (!p) return ['—', ''];
                              const share = p.share != null ? `${p.share}%` : '';
                              return [
                                `${p.bytes_display || formatBytes(p.bytes) || p.value}${share ? ` · ${share}` : ''} · ${p.records} rows`,
                                p.name,
                              ];
                            }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="vol-donut-center">
                        <strong>{dash(bytesLabel)}</strong>
                        <span>Total size</span>
                      </div>
                    </div>
                    <div className="vol-donut-legend">
                      {donutData.map(d => (
                        <div key={d.name} className="vol-donut-legend-row">
                          <span className="vol-donut-swatch" style={{ background: d.color }} />
                          <div className="vol-donut-legend-text">
                            <strong>{d.name}</strong>
                            <span>
                              {d.bytes_display}
                              {d.share != null ? ` · ${d.share}%` : ''}
                              {` · ${d.records} rows`}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Pipeline volume + Volume breakdown (mockup layout) */}
            <div className="grid-2 mt-4" style={{ gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Database size={16} style={{ color: '#3B82F6' }} />
                    <div>
                      <span className="card-title">Pipeline volume</span>
                      <span className="card-subtitle">Per-pipeline totals for this range</span>
                    </div>
                  </div>
                </div>
                <div className="table-wrapper">
                  <table className="vithi-table">
                    <thead>
                      <tr>
                        <th>Pipeline</th>
                        <th>Records</th>
                        <th>Size</th>
                        <th>Runs</th>
                        <th>Last updated</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.length === 0 ? (
                        <tr>
                          <td colSpan={6} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                            {data.length === 0
                              ? 'No volume data for this range. Try All Time or Last 30 Days.'
                              : 'No pipelines match these filters.'}
                          </td>
                        </tr>
                      ) : filtered.map(item => {
                        const tone = statusTone(item.status_key || item.status);
                        const pill = tone === 'good' ? 'good' : tone === 'warn' ? 'warning' : tone === 'crit' ? 'critical' : 'neutral';
                        return (
                          <tr key={item.pipeline_id || item.pipeline_name}>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Database size={14} style={{ color: '#64748B' }} />
                                <strong>{dash(item.pipeline_name)}</strong>
                              </div>
                            </td>
                            <td style={{ fontWeight: 700, color: '#3B82F6' }}>
                              {dash(item.records_display ?? item.records)}
                            </td>
                            <td>{dash(item.bytes_display ?? formatBytes(item.bytes))}</td>
                            <td>{dash(item.runs)}</td>
                            <td>
                              <div style={{ fontSize: 12.5, color: 'var(--text-primary)' }}>
                                {formatStamp(item.last_updated_at) || '—'}
                              </div>
                              {item.last_updated_age && (
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  {item.last_updated_age}
                                </div>
                              )}
                            </td>
                            <td>
                              <span className={`status-pill ${pill}`}>
                                {dash(item.status)}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="vol-table-footer">
                  Showing {filtered.length} of {data.length} pipeline{data.length === 1 ? '' : 's'}
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Share2 size={16} style={{ color: '#3B82F6' }} />
                    <div>
                      <span className="card-title">Volume breakdown</span>
                      <span className="card-subtitle">Share of size in this range</span>
                    </div>
                  </div>
                </div>

                <div className="vol-break-tabs">
                  {[
                    { id: 'pipeline', label: 'By Pipeline' },
                    { id: 'source', label: 'By Source' },
                    { id: 'dataset', label: 'By Dataset' },
                  ].map(tab => (
                    <button
                      key={tab.id}
                      type="button"
                      className={`vol-break-tab ${breakTab === tab.id ? 'active' : ''}`}
                      onClick={() => setBreakTab(tab.id)}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                {breakdownRows.length === 0 ? (
                  <div className="obs-simple-empty">
                    {breakTab === 'dataset'
                      ? 'No target dataset sizes in recent runs for this range.'
                      : 'No breakdown data for this range.'}
                  </div>
                ) : (
                  <div className="vol-break-body">
                    <div className="vol-break-bar" title="Share of total size">
                      {breakdownRows.map(seg => (
                        <div
                          key={seg.name}
                          className="vol-break-seg"
                          style={{
                            width: `${Math.max(seg.share, seg.share > 0 ? 2 : 0)}%`,
                            background: seg.color,
                          }}
                          title={`${seg.name}: ${seg.bytes_display} (${seg.share}%)`}
                        />
                      ))}
                    </div>
                    <div className="vol-break-legend">
                      {breakdownRows.map(seg => (
                        <div key={seg.name} className="vol-break-legend-row">
                          <span className="vol-donut-swatch" style={{ background: seg.color }} />
                          <strong>{seg.name}</strong>
                          <span className="vol-break-meta">{seg.bytes_display}</span>
                          <span className="vol-break-pct">{seg.share}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Recent runs */}
            <div className="card mt-4">
              <div className="card-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Clock size={16} style={{ color: '#3B82F6' }} />
                  <div>
                    <span className="card-title">Recent runs</span>
                    <span className="card-subtitle">Executions that produced volume in this range</span>
                  </div>
                </div>
              </div>
              <div className="table-wrapper">
                <table className="vithi-table">
                  <thead>
                    <tr>
                      <th>Pipeline</th>
                      <th>Run ID</th>
                      <th>Status</th>
                      <th>Records</th>
                      <th>Size</th>
                      <th>Started at</th>
                      <th>Duration</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRuns.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                          No runs found for this range.
                        </td>
                      </tr>
                    ) : filteredRuns.map((run) => {
                      const vol = targetFromRun(run);
                      return (
                        <tr key={run.id || `${run.pipeline_id}-${run.start_time}`}>
                          <td><strong>{dash(run.pipeline_name)}</strong></td>
                          <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, color: '#3B82F6' }}>
                            {shortRunId(run.id)}
                          </td>
                          <td>
                            <span className={`status-pill ${runStatusPill(run.status)}`}>
                              {prettyStatus(run.status)}
                            </span>
                          </td>
                          <td style={{ fontWeight: 650 }}>{dash(vol.records)}</td>
                          <td>{dash(formatBytes(vol.bytes))}</td>
                          <td>{formatStamp(run.start_time) || '—'}</td>
                          <td>{dash(run.duration_display ?? (run.duration != null ? `${run.duration}s` : null))}</td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              type="button"
                              className="vol-link-btn"
                              onClick={() => navigate('/pipelines')}
                            >
                              View details →
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
