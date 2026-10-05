import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  Shield, CheckCircle, AlertTriangle, XCircle, Search, Play, ChevronLeft, ChevronRight, Info,
} from 'lucide-react';
import {
  LineChart, Line, PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../../components/PageHeader';
import LoadingSpinner from '../../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../../components/SkeletonLoaders';
import { fetchDataQuality, evaluateDqRules, fetchDqRules, fetchPipelines } from '../../api/client';
import {
  dash, kpiMapFrom, buildDateParams, handleDateChange, TOOLTIP_STYLE,
} from './obsUtils';

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatSource(item) {
  const raw = String(item?.source || '').toLowerCase();
  if (raw.includes('dbt')) return 'dbt test';
  if (raw.includes('monitor')) {
    const kind = item?.monitor_type ? String(item.monitor_type).replace(/_/g, ' ') : null;
    return kind ? `Monitor · ${kind}` : 'Monitor';
  }
  if (raw.includes('platform') || raw.includes('sql')) return 'Platform SQL';
  if (!raw) return '—';
  return item.source;
}

function formatCheckName(item) {
  const id = item?.test_id || item?.check_id || '';
  const src = String(item?.source || '').toLowerCase();
  if (src.includes('monitor') || /^[0-9a-f-]{20,}$/i.test(String(id))) {
    if (item?.monitor_type) {
      const t = String(item.monitor_type).replace(/_/g, ' ');
      return t.charAt(0).toUpperCase() + t.slice(1) + ' monitor';
    }
  }
  let name = String(id || 'Data check');
  if (name.includes('.')) name = name.split('.').slice(-2).join('.');
  // Soft-wrap long dbt ids (accepted_values_stg_…) without changing the text
  return name.replace(/_/g, '_\u200B');
}

function plainStatus(item) {
  const st = String(item?.status || '').toLowerCase();
  if (st.includes('fail')) return { label: 'Failed', tone: 'crit', meaning: 'Broken — fix this' };
  if (st.includes('warn')) return { label: 'Warning', tone: 'warn', meaning: 'Not broken yet — please review' };
  return { label: 'OK', tone: 'good', meaning: 'Looking good' };
}

function plainMessage(item) {
  const msg = String(item?.message || '').toLowerCase();
  if (msg.includes('no target timestamp') || msg.includes('freshness pending')) {
    return 'We could not see when the target data was last updated.';
  }
  if (msg.includes('volume baseline pending') || msg.includes('need 2')) {
    return 'Volume alerts need at least 2 successful runs before they can compare.';
  }
  if (msg.includes('no dbt test failures')) {
    return 'dbt tests on the latest run all passed.';
  }
  if (msg === 'ok' || msg === '') return 'No problems found for this check.';
  return item.message || 'No details from the API.';
}

function categoryLabel(dim) {
  const d = String(dim || '').toLowerCase();
  if (d === 'timeliness') return 'On-time data';
  if (d === 'completeness') return 'Completeness';
  if (d === 'validity') return 'Validity';
  if (d === 'uniqueness') return 'Uniqueness';
  if (!d) return 'General';
  return d.charAt(0).toUpperCase() + d.slice(1);
}

function formatObservedMetrics(item) {
  const parts = [];
  if (item?.column_name) {
    parts.push(`Col: ${item.column_name}`);
  }
  if (item?.null_rate != null) {
    const n = item.null_count != null ? ` (${item.null_count} nulls)` : '';
    parts.push(`Nulls: ${item.null_rate}%${n}`);
  } else if (item?.null_count != null) {
    parts.push(`Nulls: ${item.null_count}`);
  }
  if (item?.unique_rate != null) {
    const d = item.distinct_count != null ? ` (${item.distinct_count} distinct)` : '';
    parts.push(`Uniqueness: ${item.unique_rate}%${d}`);
  } else if (item?.distinct_count != null) {
    parts.push(`Distinct: ${item.distinct_count}`);
  }
  if (item?.blank_count != null && item.blank_count > 0) {
    parts.push(`Blanks: ${item.blank_count}`);
  }
  if (item?.total_rows != null) {
    parts.push(`Rows: ${Number(item.total_rows).toLocaleString()}`);
  }
  return parts;
}

export default function DataQuality() {
  const [data, setData] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [charts, setCharts] = useState(null);
  const [summary, setSummary] = useState(null);
  const [scoreSeries, setScoreSeries] = useState([]);
  const [dqRules, setDqRules] = useState([]);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [dimensionFilter, setDimensionFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [sourceFilter, setSourceFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [perPage] = useState(10);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  useEffect(() => {
    let alive = true;
    fetchPipelines({ preset: 'all' })
      .then((res) => {
        if (!alive || !res) return;
        setPipelineOptions(res.items || res.pipelines || []);
      })
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

  const handleEvaluateRules = async () => {
    setEvaluating(true);
    try {
      await evaluateDqRules();
      await loadData();
    } finally {
      setEvaluating(false);
    }
  };

  const kpiMap = useMemo(() => kpiMapFrom(kpis), [kpis]);

  const distinctDimensions = useMemo(
    () => Array.from(new Set(data.map(d => d.dimension).filter(Boolean))),
    [data],
  );

  const distinctPipelines = useMemo(() => {
    const set = new Set();
    pipelineOptions.forEach(p => {
      const n = p.pipeline_name || p.name;
      if (n) set.add(n);
    });
    data.forEach(d => { if (d.pipeline_name) set.add(d.pipeline_name); });
    return Array.from(set).sort();
  }, [pipelineOptions, data]);

  const filtered = useMemo(() => {
    const rank = (st) => {
      const s = String(st || '').toLowerCase();
      if (s.includes('fail')) return 0;
      if (s.includes('warn')) return 1;
      return 2;
    };
    return data.filter((d) => {
      const st = String(d.status || '').toLowerCase();
      const src = String(d.source || '').toLowerCase();
      const hay = [d.pipeline_name, d.test_id, d.check_id, d.column_name, d.message, d.dimension, d.monitor_type]
        .join(' ').toLowerCase();
      const matchSearch = !search || hay.includes(search.toLowerCase());
      const matchPipeline = pipelineFilter === 'All' || d.pipeline_name === pipelineFilter;
      const matchDim = dimensionFilter === 'All' || String(d.dimension || '').toLowerCase() === dimensionFilter.toLowerCase();
      const matchStatus = statusFilter === 'All'
        || (statusFilter === 'Passed' && st.includes('pass'))
        || (statusFilter === 'Warning' && st.includes('warn'))
        || (statusFilter === 'Failed' && st.includes('fail'));
      const matchSource = sourceFilter === 'All'
        || (sourceFilter === 'dbt' && src.includes('dbt'))
        || (sourceFilter === 'monitor' && src.includes('monitor'))
        || (sourceFilter === 'platform' && (src.includes('platform') || src.includes('sql')));
      return matchSearch && matchPipeline && matchDim && matchStatus && matchSource;
    }).sort((a, b) => rank(a.status) - rank(b.status));
  }, [data, search, pipelineFilter, dimensionFilter, statusFilter, sourceFilter]);

  const filtersDirty = Boolean(search || pipelineFilter !== 'All' || dimensionFilter !== 'All' || statusFilter !== 'All' || sourceFilter !== 'All');

  const filteredTotal = filtered.length;
  const filteredPassed = filtered.filter(d => String(d.status || '').toLowerCase().includes('pass')).length;
  const filteredFailed = filtered.filter(d => String(d.status || '').toLowerCase().includes('fail')).length;
  const filteredWarn = filtered.filter(d => String(d.status || '').toLowerCase().includes('warn')).length;

  const totalChecks = filtersDirty ? filteredTotal : (kpiMap.checks_run?.value ?? summary?.checks_run ?? data.length);
  const passedChecks = filtersDirty ? filteredPassed : (kpiMap.passed?.value ?? summary?.passed ?? 0);
  const failedChecks = filtersDirty ? filteredFailed : (kpiMap.failed?.value ?? summary?.failed ?? 0);
  const warnChecks = filtersDirty ? filteredWarn : (kpiMap.warning?.value ?? summary?.warn ?? 0);

  const qualityScoreDisplay = filtersDirty
    ? (totalChecks > 0 ? `${Math.round((passedChecks / totalChecks) * 100)}%` : '—')
    : (dash(kpiMap.quality_status?.display) || (totalChecks > 0 ? `${Math.round((passedChecks / totalChecks) * 100)}%` : '—'));

  const donutData = useMemo(() => {
    const p = filtersDirty ? passedChecks : (charts?.checks_by_status?.passed ?? passedChecks);
    const w = filtersDirty ? warnChecks : (charts?.checks_by_status?.warning ?? warnChecks);
    const f = filtersDirty ? failedChecks : (charts?.checks_by_status?.failed ?? failedChecks);
    const tot = p + w + f || 1;
    return [
      { name: 'Passed', value: p, color: '#10B981', pct: `${Math.round((p / tot) * 100)}%` },
      { name: 'Warning', value: w, color: '#F59E0B', pct: `${Math.round((w / tot) * 100)}%` },
      { name: 'Failed', value: f, color: '#EF4444', pct: `${Math.round((f / tot) * 100)}%` },
    ];
  }, [filtersDirty, passedChecks, warnChecks, failedChecks, charts]);

  const dimensionData = useMemo(() => {
    if (filtersDirty) {
      const byDim = {};
      filtered.forEach(d => {
        const dim = (d.dimension || 'General').toLowerCase();
        if (!byDim[dim]) byDim[dim] = { passed: 0, warn: 0, failed: 0 };
        const st = String(d.status || '').toLowerCase();
        if (st.includes('fail')) byDim[dim].failed += 1;
        else if (st.includes('warn')) byDim[dim].warn += 1;
        else byDim[dim].passed += 1;
      });
      return Object.entries(byDim).map(([dim, val]) => ({
        dimension: dim.charAt(0).toUpperCase() + dim.slice(1),
        passed: val.passed,
        warn: val.warn,
        failed: val.failed,
      }));
    }
    const byDim = charts?.by_dimension || summary?.by_dimension;
    if (!byDim) return [];
    return Object.entries(byDim).map(([dim, val]) => ({
      dimension: dim.charAt(0).toUpperCase() + dim.slice(1),
      passed: val.passed ?? 0,
      warn: val.warn ?? 0,
      failed: val.failed ?? 0,
    }));
  }, [filtersDirty, filtered, charts, summary]);

  const scoreTrend = useMemo(() => (
    (scoreSeries || [])
      .map(p => ({
        date: p.date || p.timestamp || '',
        score: Number(p.quality_score ?? p.score ?? 0),
      }))
      .filter(p => p.date)
      .sort((a, b) => String(a.date).localeCompare(String(a.date)))
  ), [scoreSeries]);

  const paginated = filtered.slice((page - 1) * perPage, page * perPage);
  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));

  return (
    <div className="fade-in">
      <PageHeader
        title="Data Quality"
        subtitle="Are dbt tests and monitor checks passing?"
        onRefresh={loadData}
        onDateChange={(v) => { handleDateChange(setHeaderDatePreset, setCustomDateRange, v); setPage(1); }}
      />

      <div className="page-body">
        {loading ? <DashboardPageSkeleton kpiCount={4} chartCount={2} tableRows={6} tableCols={8} /> : (
          <>
            {(failedChecks > 0 || warnChecks > 0) ? (
              <div className={`obs-alert ${failedChecks > 0 ? 'is-bad' : 'is-warn'}`}>
                <AlertTriangle size={18} />
                <div>
                  <strong>
                    {failedChecks > 0
                      ? `${failedChecks} failed check${failedChecks === 1 ? '' : 's'}`
                      : `${warnChecks} warning${warnChecks === 1 ? '' : 's'}`}.
                  </strong>
                  {' '}See Check results below for details.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div>
                  <strong>All checks passing.</strong> Score {dash(kpiMap.quality_status?.display)}.
                </div>
              </div>
            )}

            <div className="obs-insight">
              <Info size={15} />
              <div>
                <strong>Where checks come from</strong>
                <span>
                  {dash(summary?.dbt_checks)} dbt tests · {dash(summary?.monitor_checks)} monitors
                  · Score mode: {dash(summary?.score_mode)}
                </span>
              </div>
            </div>

            <div className="filters-bar">
              <div className="search-box">
                <Search size={14} />
                <input
                  placeholder="Search check, column, message…"
                  value={search}
                  onChange={e => { setSearch(e.target.value); setPage(1); }}
                />
              </div>
              <div className="filter-select">
                <label>Pipeline</label>
                <select className="select-control" value={pipelineFilter} onChange={e => { setPipelineFilter(e.target.value); setPage(1); }}>
                  <option value="All">All</option>
                  {distinctPipelines.map(name => <option key={name} value={name}>{name}</option>)}
                </select>
              </div>
              <div className="filter-select">
                <label>Dimension</label>
                <select className="select-control" value={dimensionFilter} onChange={e => { setDimensionFilter(e.target.value); setPage(1); }}>
                  <option value="All">All</option>
                  {distinctDimensions.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className="filter-select">
                <label>Status</label>
                <select className="select-control" value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}>
                  <option value="All">All</option>
                  <option value="Passed">Passed</option>
                  <option value="Warning">Warning</option>
                  <option value="Failed">Failed</option>
                </select>
              </div>
              <div className="filter-select">
                <label>Source</label>
                <select className="select-control" value={sourceFilter} onChange={e => { setSourceFilter(e.target.value); setPage(1); }}>
                  <option value="All">All sources</option>
                  <option value="dbt">dbt tests</option>
                  <option value="monitor">Monitors</option>
                  <option value="platform">Platform SQL</option>
                </select>
              </div>
              {filtersDirty && (
                <button
                  type="button"
                  className="export-btn"
                  style={{ marginLeft: 'auto' }}
                  onClick={() => {
                    setSearch('');
                    setPipelineFilter('All');
                    setDimensionFilter('All');
                    setStatusFilter('All');
                    setSourceFilter('All');
                    setPage(1);
                  }}
                >
                  Clear filters
                </button>
              )}
              <button type="button" className="export-btn" style={{ marginLeft: filtersDirty ? 0 : 'auto' }} onClick={handleEvaluateRules} disabled={evaluating}>
                <Play size={13} className={evaluating ? 'spin' : ''} />
                {evaluating ? 'Running…' : 'Run DQ checks'}
              </button>
            </div>

            <div className="kpi-grid-4 mt-4">
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}><Shield size={18} /></div>
                  <span className="kpi-label">Quality score</span>
                </div>
                <div className="kpi-value" style={{ color: '#10B981' }}>{qualityScoreDisplay}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {filtersDirty ? `${passedChecks} of ${totalChecks} passing (filtered)` : `${passedChecks} of ${totalChecks} passing`}
                </div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}><CheckCircle size={18} /></div>
                  <span className="kpi-label">Checks run</span>
                </div>
                <div className="kpi-value">{dash(totalChecks)}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}><AlertTriangle size={18} /></div>
                  <span className="kpi-label">Warnings</span>
                </div>
                <div className="kpi-value" style={{ color: warnChecks ? '#F59E0B' : '#10B981' }}>{dash(warnChecks)}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}><XCircle size={18} /></div>
                  <span className="kpi-label">Failed</span>
                </div>
                <div className="kpi-value" style={{ color: failedChecks ? '#EF4444' : '#10B981' }}>{dash(failedChecks)}</div>
              </div>
            </div>

            <div className="grid-2 mt-4" style={{ gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Status mix</span>
                    <span className="card-subtitle">Passed / warning / failed</span>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-around', height: 180 }}>
                  <div style={{ width: 130, height: 130 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={donutData} dataKey="value" cx="50%" cy="50%" innerRadius={40} outerRadius={60} paddingAngle={3}>
                          {donutData.map((e, i) => <Cell key={i} fill={e.color} />)}
                        </Pie>
                        <Tooltip {...TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
                    {donutData.map(d => (
                      <div key={d.name} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span style={{ width: 8, height: 8, borderRadius: 2, background: d.color }} />
                        <span style={{ color: 'var(--text-secondary)' }}>{d.name}</span>
                        <strong>{d.value} ({d.pct})</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">By dimension</span>
                    <span className="card-subtitle">Uniqueness, completeness, validity, timeliness</span>
                  </div>
                </div>
                <div style={{ height: 180 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dimensionData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="dimension" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip {...TOOLTIP_STYLE} />
                      <Bar dataKey="passed" stackId="a" fill="#10B981" name="Passed" />
                      <Bar dataKey="warn" stackId="a" fill="#F59E0B" name="Warning" />
                      <Bar dataKey="failed" stackId="a" fill="#EF4444" name="Failed" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {scoreTrend.length > 0 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Quality score over time</span>
                    <span className="card-subtitle">
                      {scoreTrend.length < 2
                        ? 'Only one score point from the API so far — more history will draw a fuller trend line'
                        : `Line trend across ${scoreTrend.length} points from quality series`}
                    </span>
                  </div>
                </div>
                <div style={{ height: 240 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={scoreTrend} margin={{ top: 16, right: 24, left: 0, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} padding={{ left: 24, right: 24 }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} width={40} tickFormatter={(v) => `${v}%`} />
                      <Tooltip {...TOOLTIP_STYLE} formatter={(value) => [`${value}%`, 'Quality score']} />
                      <Line
                        type="monotone"
                        dataKey="score"
                        stroke="#10B981"
                        strokeWidth={3}
                        dot={{ r: 5, fill: '#10B981', stroke: '#fff', strokeWidth: 2 }}
                        activeDot={{ r: 7 }}
                        connectNulls
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {dqRules.length > 0 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Configured DQ rules</span>
                    <span className="card-subtitle">From /v1/dq-rules</span>
                  </div>
                </div>
                <div className="table-wrapper">
                  <table className="vithi-table">
                    <thead>
                      <tr>
                        <th>Rule</th>
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
                          <td style={{ fontSize: 12 }}>{dash(rule.dataset_id)}</td>
                          <td>{dash(rule.column_name)}</td>
                          <td>{dash(rule.dimension)}</td>
                          <td>{dash(rule.severity)}</td>
                          <td>
                            <span className={`status-pill ${rule.is_enabled ? 'good' : 'warning'}`}>
                              {rule.is_enabled ? 'Yes' : 'No'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Check results — proper table */}
            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Check results</span>
                  <span className="card-subtitle">
                    dbt tests, monitors, and platform SQL
                    {sourceFilter !== 'All' ? ` · filtered to ${sourceFilter}` : ''}
                  </span>
                </div>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  {filtered.length === 0 ? 0 : (page - 1) * perPage + 1}–{Math.min(page * perPage, filtered.length)} of {filtered.length}
                </span>
              </div>

              <div className="table-wrapper">
                <table className="vithi-table dq-results-table">
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Pipeline</th>
                      <th>Category</th>
                      <th>Status</th>
                      <th>Observed Metrics</th>
                      <th>Message</th>
                      <th>Source</th>
                      <th>Checked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.length === 0 ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                          No checks match filters.
                        </td>
                      </tr>
                    ) : paginated.map((item, idx) => {
                      const st = plainStatus(item);
                      const pill = st.tone === 'good' ? 'good' : st.tone === 'warn' ? 'warning' : 'critical';
                      const fullId = item.test_id || item.check_id || '';
                      const metrics = formatObservedMetrics(item);
                      return (
                        <tr key={item.check_id || item.test_id || idx}>
                          <td className="dq-check-cell" title={fullId}>
                            <span className="dq-check-name">{formatCheckName(item)}</span>
                          </td>
                          <td className="dq-pipe-cell" style={{ fontWeight: 600 }}>{dash(item.pipeline_name)}</td>
                          <td><span className="tag">{categoryLabel(item.dimension)}</span></td>
                          <td>
                            <span className={`status-pill ${pill}`}>{st.label}</span>
                          </td>
                          <td className="dq-metrics-cell">
                            {metrics.length === 0 ? (
                              <span style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>—</span>
                            ) : (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxWidth: 220 }}>
                                {metrics.map((m, i) => (
                                  <span
                                    key={i}
                                    className="tag"
                                    style={{
                                      fontSize: 11,
                                      padding: '1px 6px',
                                      backgroundColor: m.startsWith('Nulls:') && !m.includes('0%') && !m.includes(': 0')
                                        ? 'rgba(239, 68, 68, 0.12)'
                                        : 'var(--bg-tertiary, #1f2937)',
                                      color: m.startsWith('Nulls:') && !m.includes('0%') && !m.includes(': 0')
                                        ? '#f87171'
                                        : 'inherit',
                                    }}
                                  >
                                    {m}
                                  </span>
                                ))}
                              </div>
                            )}
                          </td>
                          <td className="dq-message-cell">
                            <div className="dq-message-plain">{plainMessage(item)}</div>
                            {item.message && plainMessage(item) !== item.message && (
                              <div className="dq-message-raw" title={item.message}>{item.message}</div>
                            )}
                          </td>
                          <td className="dq-source-cell">
                            <span className="tag">{formatSource(item)}</span>
                          </td>
                          <td style={{ fontSize: 11.5, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                            {fmtTime(item.checked_at)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 14 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Page {page} of {totalPages}</span>
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
          </>
        )}
      </div>
    </div>
  );
}
