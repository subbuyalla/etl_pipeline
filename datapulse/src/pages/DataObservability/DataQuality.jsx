import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  Shield, CheckCircle, AlertTriangle, XCircle, Search, Play,
  ChevronLeft, ChevronRight, RotateCcw, Database, Info,
} from 'lucide-react';
import {
  LineChart, Line, PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../../components/PageHeader';
import { DashboardPageSkeleton } from '../../components/SkeletonLoaders';
import { fetchDataQuality, evaluateDqRules, fetchDqRules, fetchPipelines } from '../../api/client';
import { dash, kpiMapFrom, buildDateParams, handleDateChange, TOOLTIP_STYLE } from './obsUtils';

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** Map raw source string to a friendly badge label + colour */
function sourceInfo(item) {
  const src = String(item?.source || item?.check_type || '').toLowerCase();
  if (src.includes('informatica') || src.includes('infa'))
    return { label: 'Informatica', color: '#F97316', bg: 'rgba(249,115,22,0.12)' };
  if (src.includes('dbt'))
    return { label: 'dbt test', color: '#6366F1', bg: 'rgba(99,102,241,0.12)' };
  if (src.includes('monitor'))
    return { label: 'Monitor', color: '#3B82F6', bg: 'rgba(59,130,246,0.12)' };
  if (src.includes('platform') || src.includes('sql'))
    return { label: 'Platform SQL', color: '#8B5CF6', bg: 'rgba(139,92,246,0.12)' };
  if (src) return { label: src, color: '#64748B', bg: 'rgba(100,116,139,0.1)' };
  return { label: '—', color: '#64748B', bg: 'transparent' };
}

/** Human-readable check name */
function readableCheckName(item) {
  // Prefer check_name (Informatica) over test_id (dbt)
  const raw = String(item?.check_name || item?.test_id || item?.check_id || 'Data check');
  // Strip long node prefixes like "model.project.table.not_null_col"
  const parts = raw.split('.');
  const short = parts.length >= 3 ? parts.slice(-2).join('.') : raw;
  return short.replace(/_/g, ' ');
}

/** Status badge props */
function statusInfo(item) {
  const st = String(item?.status || '').toLowerCase();
  if (st.includes('fail') || st === 'error')
    return { label: 'Failed', pill: 'critical', icon: XCircle, color: '#EF4444' };
  if (st.includes('warn'))
    return { label: 'Warning', pill: 'warning', icon: AlertTriangle, color: '#F59E0B' };
  return { label: 'Passed', pill: 'good', icon: CheckCircle, color: '#10B981' };
}

/** Friendly dimension label */
function dimLabel(dim) {
  const d = String(dim || '').toLowerCase();
  const map = {
    timeliness: 'On-time', completeness: 'Completeness',
    validity: 'Validity', uniqueness: 'Uniqueness',
    accuracy: 'Accuracy', consistency: 'Consistency',
  };
  return map[d] || (d ? d.charAt(0).toUpperCase() + d.slice(1) : 'General');
}

/** Readable what-went-wrong message */
function readableMessage(item) {
  const src = String(item?.source || item?.check_type || '').toLowerCase();
  const msg = String(item?.message || '').trim();
  const st = String(item?.status || '').toLowerCase();

  // Informatica-specific
  if (src.includes('infa') || src.includes('informatica')) {
    if (item?.failure_count > 0)
      return `${item.failure_count.toLocaleString()} row(s) rejected out of ${(item.total_rows || 0).toLocaleString()} processed.`;
    if (st.includes('pass'))
      return `All ${(item.total_rows || 0).toLocaleString()} rows processed successfully.`;
  }

  if (!msg || msg.toLowerCase() === 'ok') return 'No issues found.';
  if (msg.toLowerCase().includes('no target timestamp')) return 'Could not read when target data was last updated.';
  if (msg.toLowerCase().includes('volume baseline')) return 'Not enough runs yet to detect volume anomalies (needs ≥ 2).';
  if (msg.toLowerCase().includes('no dbt test failures')) return 'All dbt tests passed on this run.';
  return msg;
}

// ── component ─────────────────────────────────────────────────────────────────

export default function DataQuality() {
  const [data, setData]                   = useState([]);
  const [kpis, setKpis]                   = useState([]);
  const [charts, setCharts]               = useState(null);
  const [summary, setSummary]             = useState(null);
  const [scoreSeries, setScoreSeries]     = useState([]);
  const [dqRules, setDqRules]             = useState([]);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [loading, setLoading]             = useState(true);
  const [evaluating, setEvaluating]       = useState(false);

  const [pipelineFilter, setPipelineFilter]   = useState('All');
  const [dimensionFilter, setDimensionFilter] = useState('All');
  const [statusFilter, setStatusFilter]       = useState('All');
  const [sourceFilter, setSourceFilter]       = useState('All');
  const [search, setSearch]                   = useState('');
  const [page, setPage]                       = useState(1);
  const PER_PAGE                              = 12;

  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange]   = useState(null);

  // Load pipeline names for filter dropdown
  useEffect(() => {
    let alive = true;
    fetchPipelines({ preset: 'all' })
      .then(res => { if (alive && res) setPipelineOptions(res.items || res.pipelines || []); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params = buildDateParams(headerDatePreset, customDateRange);
      if (pipelineFilter !== 'All') params.pipeline_name = pipelineFilter;
      if (dimensionFilter !== 'All') params.dimension = dimensionFilter.toLowerCase();

      const [qRes, rulesRes] = await Promise.allSettled([
        fetchDataQuality(params),
        fetchDqRules(),
      ]);

      if (qRes.status === 'fulfilled' && qRes.value) {
        const res = qRes.value;
        setData(res.items || res.checks || []);
        setKpis(res.kpis || []);
        setCharts(res.charts || null);
        setSummary(res.summary || null);
        setScoreSeries(res.series?.quality_score_over_time || []);
      }
      if (rulesRes.status === 'fulfilled') {
        setDqRules(rulesRes.value?.items || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange, pipelineFilter, dimensionFilter]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleRunChecks = async () => {
    setEvaluating(true);
    try { await evaluateDqRules(); await loadData(); }
    finally { setEvaluating(false); }
  };

  const kpiMap = useMemo(() => kpiMapFrom(kpis), [kpis]);

  const distinctDimensions = useMemo(
    () => Array.from(new Set(data.map(d => d.dimension).filter(Boolean))).sort(),
    [data],
  );
  const distinctPipelines = useMemo(() => {
    const s = new Set();
    pipelineOptions.forEach(p => { const n = p.pipeline_name || p.name; if (n) s.add(n); });
    data.forEach(d => { if (d.pipeline_name) s.add(d.pipeline_name); });
    return Array.from(s).sort();
  }, [pipelineOptions, data]);

  // Distinct sources for the filter
  const distinctSources = useMemo(() => {
    const s = new Set();
    data.forEach(d => {
      const src = String(d.source || d.check_type || '').toLowerCase();
      if (src.includes('infa') || src.includes('informatica')) s.add('informatica');
      else if (src.includes('dbt')) s.add('dbt');
      else if (src.includes('monitor')) s.add('monitor');
      else if (src.includes('platform') || src.includes('sql')) s.add('platform');
    });
    return Array.from(s);
  }, [data]);

  const filtered = useMemo(() => {
    const rankOf = st => {
      const s = String(st || '').toLowerCase();
      if (s.includes('fail') || s === 'error') return 0;
      if (s.includes('warn')) return 1;
      return 2;
    };
    return data.filter(d => {
      const st  = String(d.status || '').toLowerCase();
      const src = String(d.source || d.check_type || '').toLowerCase();
      const hay = [d.pipeline_name, d.check_name, d.test_id, d.check_id, d.column_name,
                   d.message, d.dimension, d.dataset_id].join(' ').toLowerCase();
      const matchSearch   = !search || hay.includes(search.toLowerCase());
      const matchPipeline = pipelineFilter === 'All' || d.pipeline_name === pipelineFilter;
      const matchDim      = dimensionFilter === 'All' || String(d.dimension || '').toLowerCase() === dimensionFilter.toLowerCase();
      const matchStatus   = statusFilter === 'All'
        || (statusFilter === 'Passed' && (st.includes('pass') || st === 'ok'))
        || (statusFilter === 'Warning' && st.includes('warn'))
        || (statusFilter === 'Failed'  && (st.includes('fail') || st === 'error'));
      const matchSource   = sourceFilter === 'All'
        || (sourceFilter === 'informatica' && (src.includes('infa') || src.includes('informatica')))
        || (sourceFilter === 'dbt'         && src.includes('dbt'))
        || (sourceFilter === 'monitor'     && src.includes('monitor'))
        || (sourceFilter === 'platform'    && (src.includes('platform') || src.includes('sql')));
      return matchSearch && matchPipeline && matchDim && matchStatus && matchSource;
    }).sort((a, b) => rankOf(a.status) - rankOf(b.status));
  }, [data, search, pipelineFilter, dimensionFilter, statusFilter, sourceFilter]);

  const filtersDirty = Boolean(search || pipelineFilter !== 'All' || dimensionFilter !== 'All'
    || statusFilter !== 'All' || sourceFilter !== 'All');

  const totalChecks  = filtersDirty ? filtered.length : (kpiMap.checks_run?.value ?? summary?.checks_run ?? data.length);
  const passedChecks = filtersDirty
    ? filtered.filter(d => { const s = String(d.status||'').toLowerCase(); return s.includes('pass')||s==='ok'; }).length
    : (kpiMap.passed?.value ?? summary?.passed ?? 0);
  const failedChecks = filtersDirty
    ? filtered.filter(d => { const s = String(d.status||'').toLowerCase(); return s.includes('fail')||s==='error'; }).length
    : (kpiMap.failed?.value ?? summary?.failed ?? 0);
  const warnChecks   = filtersDirty
    ? filtered.filter(d => String(d.status||'').toLowerCase().includes('warn')).length
    : (kpiMap.warning?.value ?? summary?.warn ?? 0);

  const scoreNum = totalChecks > 0 ? Math.round((passedChecks / totalChecks) * 100) : null;
  const scoreColor = scoreNum === null ? '#64748B' : scoreNum >= 90 ? '#10B981' : scoreNum >= 70 ? '#F59E0B' : '#EF4444';

  const donutData = useMemo(() => {
    const p = filtersDirty ? passedChecks : (charts?.checks_by_status?.passed ?? passedChecks);
    const w = filtersDirty ? warnChecks   : (charts?.checks_by_status?.warning ?? warnChecks);
    const f = filtersDirty ? failedChecks : (charts?.checks_by_status?.failed  ?? failedChecks);
    const tot = p + w + f || 1;
    return [
      { name: 'Passed',  value: p, color: '#10B981', pct: `${Math.round((p/tot)*100)}%` },
      { name: 'Warning', value: w, color: '#F59E0B', pct: `${Math.round((w/tot)*100)}%` },
      { name: 'Failed',  value: f, color: '#EF4444', pct: `${Math.round((f/tot)*100)}%` },
    ];
  }, [filtersDirty, passedChecks, warnChecks, failedChecks, charts]);

  const dimensionData = useMemo(() => {
    if (filtersDirty) {
      const byDim = {};
      filtered.forEach(d => {
        const dim = (d.dimension || 'general').toLowerCase();
        if (!byDim[dim]) byDim[dim] = { passed: 0, warn: 0, failed: 0 };
        const st = String(d.status||'').toLowerCase();
        if (st.includes('fail')||st==='error') byDim[dim].failed++;
        else if (st.includes('warn')) byDim[dim].warn++;
        else byDim[dim].passed++;
      });
      return Object.entries(byDim).map(([dim, v]) => ({
        dimension: dimLabel(dim), passed: v.passed, warn: v.warn, failed: v.failed,
      }));
    }
    const byDim = charts?.by_dimension || summary?.by_dimension;
    if (!byDim) return [];
    return Object.entries(byDim).map(([dim, v]) => ({
      dimension: dimLabel(dim),
      passed: v.passed ?? 0,
      warn: v.warn ?? 0,
      failed: v.failed ?? 0,
    }));
  }, [filtersDirty, filtered, charts, summary]);

  const scoreTrend = useMemo(() => (scoreSeries || [])
    .map(p => ({ date: p.date || p.timestamp || '', score: Number(p.quality_score ?? p.score ?? 0) }))
    .filter(p => p.date)
    .sort((a, b) => String(a.date).localeCompare(String(b.date))),
  [scoreSeries]);

  const paginated  = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));

  const clearFilters = () => {
    setSearch(''); setPipelineFilter('All'); setDimensionFilter('All');
    setStatusFilter('All'); setSourceFilter('All'); setPage(1);
  };

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div className="fade-in">
      <PageHeader
        title="Data Quality"
        subtitle="Are your pipeline checks passing? Covers dbt tests, Informatica row checks, and monitors."
        onRefresh={loadData}
        onDateChange={v => { handleDateChange(setHeaderDatePreset, setCustomDateRange, v); setPage(1); }}
      />

      <div className="page-body">
        {loading ? <DashboardPageSkeleton kpiCount={4} chartCount={2} tableRows={8} tableCols={7} /> : (
          <>
            {/* ── Hero alert banner ───────────────────────────────── */}
            {failedChecks > 0 ? (
              <div className="obs-alert is-bad">
                <XCircle size={18} />
                <div>
                  <strong>{failedChecks} check{failedChecks !== 1 ? 's' : ''} failed</strong>
                  {' '}— scroll to the table below and filter by <em>Failed</em> to see which pipelines and datasets are affected.
                </div>
              </div>
            ) : warnChecks > 0 ? (
              <div className="obs-alert is-warn">
                <AlertTriangle size={18} />
                <div>
                  <strong>{warnChecks} warning{warnChecks !== 1 ? 's' : ''}</strong>
                  {' '}— not broken yet, but worth reviewing.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div>
                  <strong>All checks passing.</strong>{' '}
                  {scoreNum !== null && `Quality score: ${scoreNum}%.`}
                </div>
              </div>
            )}

            {/* ── What is this page? info strip ──────────────────── */}
            <div className="obs-insight" style={{ marginBottom: 12 }}>
              <Info size={15} />
              <div>
                <strong>What you see here</strong>
                <span>
                  Every data check result from your connected tools in the selected time window.
                  Sources: <strong>dbt tests</strong> (schema, not-null, uniqueness checks),
                  {' '}<strong>Informatica</strong> (row-level rejection counts per transformation),
                  {' '}<strong>monitors</strong> (freshness, volume, null-rate thresholds).
                  {summary?.dbt_checks != null && ` — ${summary.dbt_checks} dbt · `}
                  {summary?.monitor_checks != null && `${summary.monitor_checks} monitors`}
                </span>
              </div>
            </div>

            {/* ── KPI cards ──────────────────────────────────────── */}
            <div className="kpi-grid-4">
              {/* Score */}
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}>
                    <Shield size={18} />
                  </div>
                  <span className="kpi-label">Overall quality score</span>
                </div>
                <div className="kpi-value" style={{ color: scoreColor }}>
                  {scoreNum !== null ? `${scoreNum}%` : '—'}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {passedChecks} of {totalChecks} checks passed
                  {filtersDirty && ' (filtered view)'}
                </div>
              </div>

              {/* Total checks */}
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}>
                    <Database size={18} />
                  </div>
                  <span className="kpi-label">Total checks run</span>
                </div>
                <div className="kpi-value">{dash(totalChecks)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  across all pipelines &amp; tools
                </div>
              </div>

              {/* Warnings */}
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}>
                    <AlertTriangle size={18} />
                  </div>
                  <span className="kpi-label">Warnings</span>
                </div>
                <div className="kpi-value" style={{ color: warnChecks ? '#F59E0B' : '#10B981' }}>
                  {dash(warnChecks)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  not broken, but review needed
                </div>
              </div>

              {/* Failures */}
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                    <XCircle size={18} />
                  </div>
                  <span className="kpi-label">Failed checks</span>
                </div>
                <div className="kpi-value" style={{ color: failedChecks ? '#EF4444' : '#10B981' }}>
                  {dash(failedChecks)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {failedChecks ? 'action required' : 'none — looking good'}
                </div>
              </div>
            </div>

            {/* ── Charts row ─────────────────────────────────────── */}
            <div className="grid-2 mt-4" style={{ gap: 16 }}>

              {/* Donut */}
              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Check results breakdown</span>
                    <span className="card-subtitle">How many passed, warned, or failed</span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around', height: 180 }}>
                  <div style={{ width: 140, height: 140 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={donutData} dataKey="value" cx="50%" cy="50%"
                          innerRadius={42} outerRadius={62} paddingAngle={3}>
                          {donutData.map((e, i) => <Cell key={i} fill={e.color} />)}
                        </Pie>
                        <Tooltip {...TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
                    {donutData.map(d => (
                      <div key={d.name} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                        <span style={{ width: 10, height: 10, borderRadius: 3, background: d.color, flexShrink: 0 }} />
                        <span style={{ color: 'var(--text-secondary)', minWidth: 58 }}>{d.name}</span>
                        <strong style={{ color: 'var(--text-primary)' }}>{d.value}</strong>
                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>({d.pct})</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* By dimension */}
              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Checks by data quality dimension</span>
                    <span className="card-subtitle">
                      Completeness = nulls/blanks · Uniqueness = duplicates · Validity = format/range · On-time = freshness
                    </span>
                  </div>
                </div>
                {dimensionData.length === 0 ? (
                  <div className="obs-simple-empty">No dimension data for this range.</div>
                ) : (
                  <div style={{ height: 180 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dimensionData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="dimension" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                        <Tooltip {...TOOLTIP_STYLE} />
                        <Bar dataKey="passed" stackId="a" fill="#10B981" name="Passed" />
                        <Bar dataKey="warn"   stackId="a" fill="#F59E0B" name="Warning" />
                        <Bar dataKey="failed" stackId="a" fill="#EF4444" name="Failed" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>

            {/* ── Score trend ────────────────────────────────────── */}
            {scoreTrend.length > 1 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Quality score over time</span>
                    <span className="card-subtitle">% of checks passing day-by-day</span>
                  </div>
                </div>
                <div style={{ height: 200 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={scoreTrend} margin={{ top: 16, right: 24, left: 0, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} width={40} tickFormatter={v => `${v}%`} />
                      <Tooltip {...TOOLTIP_STYLE} formatter={v => [`${v}%`, 'Quality score']} />
                      <Line type="monotone" dataKey="score" stroke="#10B981" strokeWidth={2.5}
                        dot={{ r: 4, fill: '#10B981', stroke: '#fff', strokeWidth: 2 }}
                        activeDot={{ r: 6 }} connectNulls isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* ── Filters + table ────────────────────────────────── */}
            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">All check results</span>
                  <span className="card-subtitle">
                    Failed checks appear first · {filtered.length} result{filtered.length !== 1 ? 's' : ''}
                    {filtersDirty && ' (filtered)'}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {filtersDirty && (
                    <button type="button" className="export-btn" onClick={clearFilters}>
                      <RotateCcw size={13} /> Clear filters
                    </button>
                  )}
                  <button type="button" className="export-btn" onClick={handleRunChecks} disabled={evaluating}>
                    <Play size={13} className={evaluating ? 'spin' : ''} />
                    {evaluating ? 'Running checks…' : 'Run DQ checks'}
                  </button>
                </div>
              </div>

              {/* Filter bar */}
              <div className="filters-bar" style={{ paddingTop: 0, paddingBottom: 12 }}>
                <div className="search-box">
                  <Search size={14} />
                  <input
                    placeholder="Search by check name, pipeline, column…"
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1); }}
                  />
                </div>
                <div className="filter-select">
                  <label>Pipeline</label>
                  <select className="select-control" value={pipelineFilter}
                    onChange={e => { setPipelineFilter(e.target.value); setPage(1); }}>
                    <option value="All">All pipelines</option>
                    {distinctPipelines.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </div>
                <div className="filter-select">
                  <label>Result</label>
                  <select className="select-control" value={statusFilter}
                    onChange={e => { setStatusFilter(e.target.value); setPage(1); }}>
                    <option value="All">All results</option>
                    <option value="Passed">✅ Passed only</option>
                    <option value="Warning">⚠️ Warnings only</option>
                    <option value="Failed">❌ Failed only</option>
                  </select>
                </div>
                <div className="filter-select">
                  <label>Dimension</label>
                  <select className="select-control" value={dimensionFilter}
                    onChange={e => { setDimensionFilter(e.target.value); setPage(1); }}>
                    <option value="All">All dimensions</option>
                    {distinctDimensions.map(d => <option key={d} value={d}>{dimLabel(d)}</option>)}
                  </select>
                </div>
                {distinctSources.length > 1 && (
                  <div className="filter-select">
                    <label>Source</label>
                    <select className="select-control" value={sourceFilter}
                      onChange={e => { setSourceFilter(e.target.value); setPage(1); }}>
                      <option value="All">All sources</option>
                      {distinctSources.includes('dbt')         && <option value="dbt">dbt tests</option>}
                      {distinctSources.includes('informatica') && <option value="informatica">Informatica</option>}
                      {distinctSources.includes('monitor')     && <option value="monitor">Monitors</option>}
                      {distinctSources.includes('platform')    && <option value="platform">Platform SQL</option>}
                    </select>
                  </div>
                )}
              </div>

              <div className="table-wrapper">
                <table className="vithi-table">
                  <thead>
                    <tr>
                      <th>Check name</th>
                      <th>Pipeline</th>
                      <th>Dataset / Table</th>
                      <th>Result</th>
                      <th>What went wrong</th>
                      <th>Dimension</th>
                      <th>Source</th>
                      <th>When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', padding: 32, color: 'var(--text-muted)' }}>
                          {filtersDirty
                            ? 'No checks match your current filters. Try clearing them.'
                            : 'No check results yet. Run a pipeline sync or click "Run DQ checks".'}
                        </td>
                      </tr>
                    ) : paginated.map((item, idx) => {
                      const st  = statusInfo(item);
                      const src = sourceInfo(item);
                      const dataset = String(item.dataset_id || item.column_name || '').trim() || '—';
                      return (
                        <tr key={item.check_id || item.test_id || idx}>

                          {/* Check name */}
                          <td style={{ fontWeight: 600, maxWidth: 220 }}>
                            <span title={item.test_id || item.check_id || ''}>
                              {readableCheckName(item)}
                            </span>
                          </td>

                          {/* Pipeline */}
                          <td style={{ fontWeight: 500 }}>{dash(item.pipeline_name)}</td>

                          {/* Dataset */}
                          <td style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--text-secondary)' }}>
                            {dataset}
                          </td>

                          {/* Result */}
                          <td>
                            <span className={`status-pill ${st.pill}`}>
                              {st.label}
                            </span>
                          </td>

                          {/* What went wrong */}
                          <td style={{ maxWidth: 260, fontSize: 12.5, color: 'var(--text-secondary)' }}>
                            {readableMessage(item)}
                          </td>

                          {/* Dimension */}
                          <td>
                            <span className="tag" style={{ fontSize: 11 }}>
                              {dimLabel(item.dimension)}
                            </span>
                          </td>

                          {/* Source badge */}
                          <td>
                            <span style={{
                              fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                              color: src.color, background: src.bg,
                            }}>
                              {src.label}
                            </span>
                          </td>

                          {/* Timestamp */}
                          <td style={{ fontSize: 11.5, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                            {fmtTime(item.checked_at)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    Page {page} of {totalPages} · {filtered.length} results
                  </span>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button type="button" className="export-btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                      <ChevronLeft size={14} /> Prev
                    </button>
                    <button type="button" className="export-btn" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                      Next <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* ── DQ Rules (config) ─────────────────────────────── */}
            {dqRules.length > 0 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Configured DQ rules</span>
                    <span className="card-subtitle">Rules that get evaluated when you click "Run DQ checks"</span>
                  </div>
                </div>
                <div className="table-wrapper">
                  <table className="vithi-table">
                    <thead>
                      <tr>
                        <th>Rule name</th>
                        <th>Type</th>
                        <th>Dataset</th>
                        <th>Column</th>
                        <th>Dimension</th>
                        <th>Severity</th>
                        <th>Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dqRules.map(rule => (
                        <tr key={rule.rule_id}>
                          <td style={{ fontWeight: 600 }}>{dash(rule.rule_name)}</td>
                          <td><span className="tag">{dash(rule.rule_type)}</span></td>
                          <td style={{ fontSize: 12, fontFamily: 'monospace' }}>{dash(rule.dataset_id)}</td>
                          <td>{dash(rule.column_name)}</td>
                          <td>{dimLabel(rule.dimension)}</td>
                          <td>{dash(rule.severity)}</td>
                          <td>
                            <span className={`status-pill ${rule.is_enabled ? 'good' : 'warning'}`}>
                              {rule.is_enabled ? 'Active' : 'Disabled'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
