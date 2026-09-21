import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Search, XCircle, CheckCircle, AlertTriangle, X,
  ChevronLeft, ChevronRight, Terminal, Database, Shield, GitBranch,
  Clock, Activity,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../components/SkeletonLoaders';
import {
  fetchLogs, fetchFilters, fetchRunDetail, fetchRcaContext,
} from '../api/client';
import {
  dash, kpiMapFrom, buildDateParams, handleDateChange,
} from './DataObservability/obsUtils';

/**
 * Logs — Datadog Log Explorer pattern:
 *  1. Dense KPI rail from GET /api/v1/logs
 *  2. Facet filters (search / pipeline / tool / status / level) → API query params
 *  3. Log stream table
 *  4. Side panel: GET /api/v1/runs/{id} + /rca-context
 */

function asList(value) {
  if (value == null) return [];
  if (Array.isArray(value)) return value;
  return [value];
}

function displayKpi(kpi, fallback) {
  if (kpi && kpi.available !== false && kpi.display != null && kpi.display !== '') {
    return kpi.display;
  }
  if (fallback != null && fallback !== '') return fallback;
  return '—';
}

function levelClass(level, status) {
  const s = String(status || '').toLowerCase();
  const lv = String(level || '').toLowerCase();
  if (s === 'failed' || s === 'error' || lv === 'error' || lv === 'critical') return 'is-err';
  if (lv === 'warn' || lv === 'warning' || s === 'running') return 'is-warn';
  if (s === 'success' || lv === 'info' || lv === 'ok') return 'is-ok';
  return '';
}

function statusPill(status) {
  const s = String(status || '').toLowerCase();
  if (['success', 'succeeded', 'ok'].includes(s)) return 'good';
  if (['failed', 'error', 'critical'].includes(s)) return 'critical';
  if (['running', 'pending', 'warn', 'warning'].includes(s)) return 'warning';
  return 'info';
}

function checkTone(status) {
  const s = String(status || '').toLowerCase();
  if (['pass', 'passed', 'ok', 'success'].includes(s)) return 'good';
  if (['warn', 'warning'].includes(s)) return 'warning';
  if (['fail', 'failed', 'error'].includes(s)) return 'critical';
  return 'info';
}

function unwrapRunBundle(res) {
  if (!res) return null;
  const meta = res.meta || {};
  return {
    run: meta.run || meta,
    assets: asList(meta.assets),
    columns: asList(meta.columns),
    queryHistory: asList(meta.query_history),
  };
}

function unwrapRca(res) {
  if (!res) return null;
  const meta = res.meta || res;
  return {
    run: meta.run || null,
    pipeline: meta.pipeline || null,
    failure: meta.failure || null,
    freshness: meta.freshness || null,
    relations: asList(meta.relations),
    assets: asList(meta.assets),
    columns: asList(meta.columns),
    dbtTests: asList(meta.dbt_tests),
    dqChecks: asList(meta.dq_checks),
    lineageEdges: asList(meta.lineage_edges),
    summary: meta.summary || {},
    compiledSql: meta.compiled_sql || null,
    openIncidents: asList(meta.open_incidents),
  };
}

function formatRawLog(run) {
  const raw = run?.raw_log;
  if (!raw) return null;
  if (typeof raw === 'object') return JSON.stringify(raw, null, 2);
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return String(raw);
  }
}

function dimFromObserved(check) {
  if (check?.dimension) return check.dimension;
  const raw = check?.observed_json;
  if (!raw) return '—';
  try {
    const o = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return o.dimension || o.freshness || '—';
  } catch {
    return '—';
  }
}

function testName(check) {
  if (check?.name || check?.test || check?.rule_name) return check.name || check.test || check.rule_name;
  const raw = check?.observed_json;
  if (!raw) return check?.check_id || check?.monitor_id || 'Check';
  try {
    const o = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return o.test_id || o.message || check.message || check.check_id || 'Check';
  } catch {
    return check.message || check.check_id || 'Check';
  }
}

const LEVELS = ['INFO', 'WARN', 'ERROR', 'DEBUG'];

export default function Logs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const deepRunId = searchParams.get('run_id') || '';

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [data, setData] = useState(null);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [toolOptions, setToolOptions] = useState([]);
  const [statusOptions, setStatusOptions] = useState([]);

  const [search, setSearch] = useState('');
  const [searchApplied, setSearchApplied] = useState('');
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [toolFilter, setToolFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [levelFilter, setLevelFilter] = useState('All');
  const [page, setPage] = useState(1);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const [selected, setSelected] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [runBundle, setRunBundle] = useState(null);
  const [rca, setRca] = useState(null);
  const [panelTab, setPanelTab] = useState('overview');
  const panelBodyRef = useRef(null);

  useEffect(() => {
    let alive = true;
    fetchFilters()
      .then((res) => {
        if (!alive || !res) return;
        const pipes = asList(res.pipelines || res.items);
        const seen = new Set();
        setPipelineOptions(pipes.filter((p) => {
          if (!p?.pipeline_id || seen.has(p.pipeline_id)) return false;
          seen.add(p.pipeline_id);
          return true;
        }));
        setToolOptions(asList(res.tools));
        setStatusOptions(asList(res.statuses));
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Debounce search → API `search` param
  useEffect(() => {
    const t = setTimeout(() => {
      setSearchApplied(search.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [search]);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const params = {
        ...buildDateParams(headerDatePreset, customDateRange),
        page,
        page_size: 20,
      };
      if (pipelineFilter !== 'All') {
        const pipe = pipelineOptions.find((p) => p.pipeline_id === pipelineFilter);
        if (pipe?.pipeline_name) params.pipeline_name = pipe.pipeline_name;
        params.pipeline_id = pipelineFilter;
      }
      if (toolFilter !== 'All') params.tool = toolFilter;
      if (statusFilter !== 'All') params.status = statusFilter;
      if (levelFilter !== 'All') params.level = levelFilter;
      if (searchApplied) params.search = searchApplied;

      setData(await fetchLogs(params) || null);
    } catch (e) {
      console.error(e);
      setLoadError(e?.message || 'Failed to load logs');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [
    headerDatePreset, customDateRange, page, pipelineFilter, toolFilter,
    statusFilter, levelFilter, searchApplied, pipelineOptions,
  ]);

  useEffect(() => { loadLogs(); }, [loadLogs]);

  const logs = useMemo(() => asList(data?.items), [data]);
  const kpiMap = useMemo(() => kpiMapFrom(data?.kpis), [data]);
  const pagination = data?.pagination || { page: 1, page_size: 20, total: 0 };
  const totalPages = Math.max(1, Math.ceil((pagination.total || 0) / (pagination.page_size || 20)));
  const showPager = (pagination.total || 0) > (pagination.page_size || 20);

  // Deep-link: select matching log when list loads
  useEffect(() => {
    if (!deepRunId || !logs.length) return;
    const match = logs.find((l) => String(l.run_id) === String(deepRunId));
    if (match) setSelected(match);
  }, [deepRunId, logs]);

  useEffect(() => {
    if (panelBodyRef.current) panelBodyRef.current.scrollTop = 0;
  }, [panelTab]);

  const openDetail = useCallback(async (log) => {
    setSelected(log);
    setPanelTab('overview');
    setRunBundle(null);
    setRca(null);
    if (!log?.run_id) return;

    setDetailLoading(true);
    const [runRes, rcaRes] = await Promise.allSettled([
      fetchRunDetail(log.run_id),
      fetchRcaContext(log.run_id),
    ]);
    setRunBundle(runRes.status === 'fulfilled' ? unwrapRunBundle(runRes.value) : null);
    setRca(rcaRes.status === 'fulfilled' ? unwrapRca(rcaRes.value) : null);
    setDetailLoading(false);
  }, []);

  const closePanel = () => {
    setSelected(null);
    setRunBundle(null);
    setRca(null);
    if (deepRunId) {
      const next = new URLSearchParams(searchParams);
      next.delete('run_id');
      setSearchParams(next, { replace: true });
    }
  };

  const filtersActive =
    Boolean(search.trim()) ||
    pipelineFilter !== 'All' ||
    toolFilter !== 'All' ||
    statusFilter !== 'All' ||
    levelFilter !== 'All';

  const clearFilters = () => {
    setSearch('');
    setSearchApplied('');
    setPipelineFilter('All');
    setToolFilter('All');
    setStatusFilter('All');
    setLevelFilter('All');
    setPage(1);
  };

  const rail = [
    {
      label: 'Total',
      value: displayKpi(kpiMap.total_logs, String(pagination.total ?? logs.length)),
      tone: '',
    },
    {
      label: 'Failed',
      value: displayKpi(kpiMap.failed_logs),
      tone: Number(kpiMap.failed_logs?.value) > 0 ? 'is-bad' : 'is-ok',
      Icon: XCircle,
    },
    {
      label: 'Success',
      value: displayKpi(kpiMap.success_logs),
      tone: 'is-ok',
      Icon: CheckCircle,
    },
    {
      label: 'Avg duration',
      value: displayKpi(kpiMap.avg_duration),
      tone: '',
      Icon: Clock,
    },
  ];

  const run = rca?.run || runBundle?.run || null;
  const assets = (rca?.assets?.length ? rca.assets : runBundle?.assets) || [];
  const dqChecks = rca?.dqChecks || [];
  const dbtTests = rca?.dbtTests || [];
  const relations = rca?.relations?.length
    ? rca.relations
    : asList(run?.relations);
  const rawLogText = formatRawLog(run);
  const failedLogs = Number(kpiMap.failed_logs?.value) || 0;

  if (loading && !data) {
    return (
      <div className="fade-in">
        <PageHeader title="Logs" subtitle="Execution log explorer." onRefresh={loadLogs} />
        <div className="page-body">
          <DashboardPageSkeleton kpiCount={4} chartCount={0} tableRows={8} tableCols={5} />
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <PageHeader
        title="Logs"
        subtitle="Execution stream — search, facet, and inspect run context."
        onRefresh={loadLogs}
        datePreset={headerDatePreset}
        onDateChange={(v) => {
          handleDateChange(setHeaderDatePreset, setCustomDateRange, v);
          setPage(1);
        }}
        latestTimestamp={data?.generated_at}
      />

      <div className="page-body">
        {loadError ? (
          <div className="obs-alert is-bad">
            <AlertTriangle size={18} />
            <div><strong>Could not load logs.</strong> {loadError}</div>
          </div>
        ) : failedLogs > 0 ? (
          <div className="obs-alert is-bad">
            <XCircle size={18} />
            <div>
              <strong>{failedLogs} failed log{failedLogs === 1 ? '' : 's'}.</strong>
              {' '}Open a row to inspect RCA context.
            </div>
          </div>
        ) : (
          <div className="obs-alert is-ok">
            <CheckCircle size={18} />
            <div>
              <strong>Stream healthy.</strong>
              {' '}{displayKpi(kpiMap.total_logs)} log{Number(kpiMap.total_logs?.value) === 1 ? '' : 's'} in range.
            </div>
          </div>
        )}

        <div className="log-rail">
          {rail.map((m) => (
            <div key={m.label} className={`log-rail-item ${m.tone}`}>
              <span>{m.label}</span>
              <strong>{m.value}</strong>
            </div>
          ))}
        </div>

        <div className="filters-bar">
          <div className="search-box" style={{ flex: 1, maxWidth: 360 }}>
            <Search size={14} />
            <input
              placeholder="Search message, pipeline, run id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="filter-select">
            <label>Pipeline</label>
            <select className="select-control" value={pipelineFilter} onChange={(e) => { setPipelineFilter(e.target.value); setPage(1); }}>
              <option value="All">All</option>
              {pipelineOptions.map((p) => (
                <option key={p.pipeline_id} value={p.pipeline_id}>{p.pipeline_name || p.pipeline_id}</option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Tool</label>
            <select className="select-control" value={toolFilter} onChange={(e) => { setToolFilter(e.target.value); setPage(1); }}>
              <option value="All">All</option>
              {toolOptions.map((t) => (
                <option key={t.id || t} value={t.id || t}>{t.label || t.id || t}</option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Status</label>
            <select className="select-control" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
              <option value="All">All</option>
              {statusOptions.map((s) => (
                <option key={s.id || s} value={s.id || s}>{s.label || s.id || s}</option>
              ))}
            </select>
          </div>
          <div className="filter-select">
            <label>Level</label>
            <select className="select-control" value={levelFilter} onChange={(e) => { setLevelFilter(e.target.value); setPage(1); }}>
              <option value="All">All</option>
              {LEVELS.map((lv) => (
                <option key={lv} value={lv}>{lv}</option>
              ))}
            </select>
          </div>
          {filtersActive && (
            <button type="button" className="met-clear-btn" onClick={clearFilters}>Clear filters</button>
          )}
        </div>

        <div className={`log-workspace ${selected ? 'has-inspector' : ''}`}>
          <div className="card log-stream-card">
            <div className="card-header">
              <div>
                <span className="card-title">Log stream</span>
                <span className="card-subtitle">
                  {logs.length} shown · {pagination.total ?? logs.length} total
                  {loading ? ' · refreshing…' : ''}
                  {' '}· click a row for run detail
                </span>
              </div>
              {showPager && (
                <div className="met-pager">
                  <button type="button" className="met-pager-btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                    <ChevronLeft size={14} />
                  </button>
                  <span>{page}/{totalPages}</span>
                  <button type="button" className="met-pager-btn" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                    <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </div>

            {logs.length === 0 ? (
              <div className="obs-simple-empty" style={{ padding: 40 }}>
                No logs in this window.
                <div style={{ marginTop: 6, fontSize: 12 }}>Try <strong>All Time</strong> or clear facets.</div>
                {filtersActive && (
                  <button type="button" className="export-btn" style={{ marginTop: 12 }} onClick={clearFilters}>Clear filters</button>
                )}
              </div>
            ) : (
              <div className="table-wrapper log-stream-wrap">
                <table className="vithi-table log-stream-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Level</th>
                      <th>Pipeline</th>
                      <th>Message</th>
                      <th>Status</th>
                      <th>Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((l, idx) => {
                      const active = selected && String(selected.run_id) === String(l.run_id);
                      return (
                        <tr
                          key={l.run_id || idx}
                          className={active ? 'is-selected' : ''}
                          onClick={() => openDetail(l)}
                        >
                          <td className="log-time">{l.timestamp || '—'}</td>
                          <td>
                            <span className={`log-level ${levelClass(l.level, l.status)}`}>
                              {l.level || '—'}
                            </span>
                          </td>
                          <td>
                            <div style={{ fontWeight: 600 }}>{dash(l.pipeline_name)}</div>
                            <div className="log-meta">{dash(l.tool)} · #{l.run_id || '—'}</div>
                          </td>
                          <td className="log-msg" title={l.message || l.error_message || ''}>
                            {l.message || l.error_message || '—'}
                          </td>
                          <td>
                            <span className={`status-pill ${statusPill(l.status)}`}>
                              {l.status || '—'}
                            </span>
                          </td>
                          <td className="log-dur">
                            {l.duration || (l.duration_seconds != null ? `${l.duration_seconds}s` : '—')}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {selected && (
            <aside className="log-inspector">
              <div className="log-inspector-head">
                <div>
                  <div className="log-inspector-title">{selected.pipeline_name || 'Run detail'}</div>
                  <div className="log-inspector-sub">#{selected.run_id || '—'}</div>
                </div>
                <button type="button" className="met-pager-btn" onClick={closePanel} aria-label="Close">
                  <X size={14} />
                </button>
              </div>

              <div className="log-inspector-pills">
                <span className={`status-pill ${statusPill(selected.status || run?.status)}`}>
                  {selected.status || run?.status || '—'}
                </span>
                <span className="log-chip">{selected.tool || run?.tool_name || '—'}</span>
                <span className="log-chip">{selected.duration || run?.duration_display || '—'}</span>
              </div>

              <div className="log-tabs">
                {[
                  { id: 'overview', label: 'Overview' },
                  { id: 'raw', label: 'Raw log' },
                  { id: 'dq', label: `DQ (${dqChecks.length})` },
                  { id: 'tests', label: `Tests (${dbtTests.length})` },
                  { id: 'assets', label: `Assets (${assets.length})` },
                ].map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`log-tab ${panelTab === t.id ? 'is-active' : ''}`}
                    onClick={() => setPanelTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div className="log-inspector-body" ref={panelBodyRef}>
                {detailLoading && !run && !rca ? (
                  <div className="obs-simple-empty" style={{ padding: 24 }}>Loading run context…</div>
                ) : panelTab === 'overview' ? (
                  <div className="log-overview">
                    <div className="log-kv">
                      <span>Message</span>
                      <strong>{selected.message || '—'}</strong>
                    </div>
                    <div className="log-kv">
                      <span>Start</span>
                      <strong>{run?.start_time || selected.timestamp || '—'}</strong>
                    </div>
                    <div className="log-kv">
                      <span>End</span>
                      <strong>{run?.end_time || '—'}</strong>
                    </div>
                    <div className="log-kv">
                      <span>Rows read / written</span>
                      <strong>{run?.rows_read ?? '—'} / {run?.rows_written ?? '—'}</strong>
                    </div>
                    <div className="log-kv">
                      <span>Triggered by</span>
                      <strong>{run?.triggered_by || '—'}</strong>
                    </div>
                    <div className="log-kv">
                      <span>Mode</span>
                      <strong>{run?.execution_mode || '—'}</strong>
                    </div>
                    {rca?.freshness && (
                      <div className="log-kv">
                        <span>Freshness</span>
                        <strong className={String(rca.freshness.status_key).toLowerCase() === 'stale' ? 'is-bad-text' : ''}>
                          {rca.freshness.status} · {rca.freshness.current_lag_display || '—'}
                        </strong>
                      </div>
                    )}
                    {rca?.summary && (
                      <div className="log-summary-grid">
                        <div><Activity size={12} /><span>DQ checks</span><strong>{rca.summary.dq_check_count ?? '—'}</strong></div>
                        <div><Shield size={12} /><span>dbt tests</span><strong>{rca.summary.dbt_test_count ?? '—'}</strong></div>
                        <div><Database size={12} /><span>Assets</span><strong>{rca.summary.asset_count ?? assets.length}</strong></div>
                        <div><GitBranch size={12} /><span>Lineage</span><strong>{rca.summary.lineage_edge_count ?? '—'}</strong></div>
                      </div>
                    )}
                    {relations.length > 0 && (
                      <div className="log-block">
                        <div className="log-block-title">Relations</div>
                        {relations.map((r) => (
                          <code key={r}>{r}</code>
                        ))}
                      </div>
                    )}
                    {(rca?.failure?.error_message || rca?.failure?.failed_message) && (
                      <div className="log-block is-err">
                        <div className="log-block-title">Failure</div>
                        <pre>{rca.failure.error_message || rca.failure.failed_message}</pre>
                      </div>
                    )}
                    <div className="log-inspector-actions">
                      <Link className="met-related-link" to="/pipelines">View pipelines</Link>
                      <Link className="met-related-link" to="/incidents">View incidents</Link>
                    </div>
                  </div>
                ) : panelTab === 'raw' ? (
                  <div className="log-console">
                    <div className="log-console-head">
                      <Terminal size={13} />
                      <span>raw_log</span>
                    </div>
                    <pre>{rawLogText || selected.message || 'No raw log on this run.'}</pre>
                  </div>
                ) : panelTab === 'dq' ? (
                  dqChecks.length === 0 ? (
                    <div className="obs-simple-empty" style={{ padding: 24 }}>No DQ checks for this run.</div>
                  ) : (
                    <div className="log-check-list">
                      {dqChecks.map((c, i) => (
                        <div key={c.check_id || i} className="log-check-row">
                          <span className={`status-pill ${checkTone(c.status)}`}>{c.status || '—'}</span>
                          <div>
                            <strong>{c.message || testName(c)}</strong>
                            <em>{dimFromObserved(c)} · {c.severity || '—'}</em>
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : panelTab === 'tests' ? (
                  dbtTests.length === 0 ? (
                    <div className="obs-simple-empty" style={{ padding: 24 }}>No dbt tests for this run.</div>
                  ) : (
                    <div className="log-check-list">
                      {dbtTests.map((c, i) => (
                        <div key={c.check_id || i} className="log-check-row">
                          <span className={`status-pill ${checkTone(c.status)}`}>{c.status || '—'}</span>
                          <div>
                            <strong title={testName(c)}>{testName(c)}</strong>
                            <em>{dimFromObserved(c)} · {c.message || '—'}</em>
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                ) : (
                  assets.length === 0 ? (
                    <div className="obs-simple-empty" style={{ padding: 24 }}>No assets for this run.</div>
                  ) : (
                    <div className="log-asset-list">
                      {assets.map((a) => (
                        <div key={a.id || a.dataset_id} className="log-asset-card">
                          <div className="log-asset-role">{a.asset_role || 'ASSET'}</div>
                          <strong>{a.object_name || a.dataset_id || '—'}</strong>
                          <span>{[a.database_name, a.schema_name].filter(Boolean).join('.') || a.system_name || '—'}</span>
                          <div className="log-asset-stats">
                            <em>Rows {a.row_count ?? '—'}</em>
                            <em>Cols {a.column_count ?? '—'}</em>
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                )}
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
