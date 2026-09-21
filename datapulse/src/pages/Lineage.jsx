import { useEffect, useState, useMemo, useCallback, useRef, useLayoutEffect } from 'react';
import {
  Search, Database, GitBranch, Table, X, Clock, AlertTriangle, CheckCircle,
  ZoomIn, ZoomOut, Maximize2, Users, MoreVertical, ArrowRight,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../components/SkeletonLoaders';
import {
  fetchLineage, fetchLineageDetail, fetchRunDetail, fetchPipelines,
} from '../api/client';
import {
  dash, kpiMapFrom, statusTone, buildDateParams, handleDateChange, formatBytes,
} from './DataObservability/obsUtils';

function parseRelations(raw) {
  if (!raw) return [];
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function shortDataset(name) {
  if (!name) return '—';
  const parts = String(name).split('.');
  return parts.length >= 2 ? parts.slice(-2).join('.') : String(name);
}

function healthToneClass(tone) {
  if (tone === 'good') return 'is-ok';
  if (tone === 'warn') return 'is-warn';
  if (tone === 'crit') return 'is-bad';
  return 'is-warn';
}

function statusPill(status) {
  const tone = statusTone(status);
  return tone === 'good' ? 'good' : tone === 'warn' ? 'warning' : tone === 'crit' ? 'critical' : 'neutral';
}

/** Local coords — correct for CSS transform:scale on ancestors (zoom) */
/** Port center in root layout space (immune to ancestor CSS scale when matrix is read). */
function localPort(el, root) {
  const er = el.getBoundingClientRect();
  const rr = root.getBoundingClientRect();
  // Screen delta is already scaled; divide by the zoom ancestor's matrix (not width ratio —
  // ratio drifts when the zoom frame size and content size disagree after Table↔Column).
  let sx = 1;
  let sy = 1;
  let node = root.parentElement;
  while (node) {
    const tr = getComputedStyle(node).transform;
    if (tr && tr !== 'none') {
      const m = new DOMMatrixReadOnly(tr);
      sx = Math.abs(m.a) > 0.01 ? m.a : 1;
      sy = Math.abs(m.d) > 0.01 ? m.d : 1;
      break;
    }
    node = node.parentElement;
  }
  return {
    x: (er.left + er.width / 2 - rr.left) / sx,
    y: (er.top + er.height / 2 - rr.top) / sy,
  };
}

function sCurve(x1, y1, x2, y2) {
  const dx = Math.max(36, Math.abs(x2 - x1) * 0.5);
  return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

/**
 * Reference-style lineage from LIVE API only:
 * - Source/Target columns from run meta.columns
 * - Transform stages from last_run.relations_json (not invented step timings)
 * - Wires fan into/out of transform edge ports (name-matched columns)
 */
function ColumnLineageGraph({
  sourceName, sourceSystem, sourceRows,
  targetName, targetSystem, targetRows,
  pipelineName, etlLabel, runMeta,
  sourceCols, targetCols, relations,
  selectedColumn, selectedNode,
  onSelectColumn, onSelectNode,
  onSize,
}) {
  const rootRef = useRef(null);
  const [wires, setWires] = useState([]);
  const [box, setBox] = useState({ w: 960, h: 400 });

  const pairs = useMemo(() => sourceCols
    .map((sc) => {
      const name = String(sc.column_name || '').toUpperCase();
      const tgt = targetCols.find(tc => String(tc.column_name || '').toUpperCase() === name);
      if (!tgt) return null;
      return { name, src: sc, tgt };
    })
    .filter(Boolean), [sourceCols, targetCols]);

  const measure = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;
    const lanes = root.querySelector('.lin-col-lanes');
    const w = Math.ceil(Math.max(lanes?.offsetWidth || 0, lanes?.scrollWidth || 0, root.scrollWidth, 900));
    const h = Math.ceil(Math.max(lanes?.offsetHeight || 0, lanes?.scrollHeight || 0, root.scrollHeight, 300));

    const next = pairs.map((p) => {
      const srcEl = root.querySelector(`[data-port="src:${p.name}"]`);
      const midIn = root.querySelector(`[data-port="mid-in:${p.name}"]`);
      const midOut = root.querySelector(`[data-port="mid-out:${p.name}"]`);
      const tgtEl = root.querySelector(`[data-port="tgt:${p.name}"]`);
      if (!srcEl || !tgtEl || !midIn || !midOut) return null;
      const hot = selectedColumn && String(selectedColumn).toUpperCase() === p.name;
      return {
        name: p.name,
        s: localPort(srcEl, root),
        mi: localPort(midIn, root),
        mo: localPort(midOut, root),
        t: localPort(tgtEl, root),
        hot,
      };
    }).filter(Boolean);

    setWires(next);
    setBox({ w, h });
    onSize?.({ w, h });
  }, [pairs, selectedColumn, onSize]);

  useLayoutEffect(() => {
    let alive = true;
    const run = () => { if (alive) measure(); };
    // Remeasure across paints after remount (Table→Column). Do NOT remasure on zoom —
    // CSS scale on the parent keeps SVG + ports aligned; remasuring under scale drifts
    // endpoints (especially Transform→Target).
    run();
    const raf1 = requestAnimationFrame(() => {
      run();
      requestAnimationFrame(run);
    });
    const t1 = setTimeout(run, 50);
    const t2 = setTimeout(run, 200);
    const root = rootRef.current;
    const lanes = root?.querySelector('.lin-col-lanes');
    const ro = (typeof ResizeObserver !== 'undefined' && lanes) ? new ResizeObserver(run) : null;
    if (ro && lanes) ro.observe(lanes);
    window.addEventListener('resize', run);
    return () => {
      alive = false;
      cancelAnimationFrame(raf1);
      clearTimeout(t1);
      clearTimeout(t2);
      ro?.disconnect();
      window.removeEventListener('resize', run);
    };
  }, [measure, sourceCols, targetCols, relations]);

  return (
    <div ref={rootRef} className="lin-col-graph">
      <svg className="lin-wires" width={box.w} height={box.h} viewBox={`0 0 ${box.w} ${box.h}`} aria-hidden>
        {wires.map((w) => {
          const dim = selectedColumn && !w.hot;
          const leftStroke = w.hot ? '#059669' : '#3B82F6';
          const rightStroke = w.hot ? '#059669' : '#14B8A6';
          const width = w.hot ? 2.4 : 1.4;
          const opacity = dim ? 0.1 : w.hot ? 1 : 0.7;
          return (
            <g key={w.name} opacity={opacity}>
              <path d={sCurve(w.s.x, w.s.y, w.mi.x, w.mi.y)} fill="none" stroke={leftStroke} strokeWidth={width} strokeLinecap="round" />
              <path d={sCurve(w.mo.x, w.mo.y, w.t.x, w.t.y)} fill="none" stroke={rightStroke} strokeWidth={width} strokeLinecap="round" />
              <circle cx={w.s.x} cy={w.s.y} r={w.hot ? 4 : 3} fill={leftStroke} />
              <circle cx={w.mi.x} cy={w.mi.y} r={2.6} fill={leftStroke} />
              <circle cx={w.mo.x} cy={w.mo.y} r={2.6} fill={rightStroke} />
              <circle cx={w.t.x} cy={w.t.y} r={w.hot ? 4 : 3} fill={rightStroke} />
            </g>
          );
        })}
      </svg>

      <div className="lin-col-lanes">
        <div
          className={`lin-wire-card is-source ${selectedNode === 'source' ? 'is-active' : ''}`}
          onClick={() => onSelectNode('source')}
        >
          <div className="lin-wire-head">
            <span className="lin-pill">Source</span>
            <strong>{dash(sourceName)}</strong>
            <div className="lin-wire-sub">{dash(sourceSystem)} · {dash(sourceRows)} rows</div>
          </div>
          <div className="lin-wire-cols">
            {sourceCols.length === 0 ? (
              <div className="lin-card-empty">No source columns from latest run</div>
            ) : sourceCols.map((c) => {
              const hot = selectedColumn && String(c.column_name).toUpperCase() === String(selectedColumn).toUpperCase();
              return (
                <button
                  type="button"
                  key={c.id || c.column_name}
                  className={`lin-wire-col ${hot ? 'is-hot' : ''}`}
                  onClick={(e) => { e.stopPropagation(); onSelectColumn(c, 'source'); }}
                >
                  <code>{c.column_name}</code>
                  <span>{c.data_type || ''}</span>
                  <i className="lin-port is-right" data-port={`src:${String(c.column_name).toUpperCase()}`} />
                </button>
              );
            })}
          </div>
        </div>

        <div
          className={`lin-wire-card is-etl ${selectedNode === 'etl' ? 'is-active' : ''}`}
          data-etl-card
          onClick={() => onSelectNode('etl')}
        >
          <div className="lin-wire-head">
            <span className="lin-pill">Transform</span>
            <strong>{dash(pipelineName)}</strong>
            <div className="lin-wire-sub">
              {dash(etlLabel)}
              {runMeta?.duration != null ? ` · ${runMeta.duration}s` : ''}
              {runMeta?.status ? ` · ${runMeta.status}` : ''}
            </div>
          </div>
          <div className="lin-wire-cols lin-etl-body">
            {relations.length === 0 ? (
              <div className="lin-card-empty">No models on latest run (relations_json)</div>
            ) : relations.map((name) => (
              <div key={name} className="lin-wire-stage">
                <span className="lin-stage-dot" />
                <code title={name}>{shortDataset(name)}</code>
              </div>
            ))}
            {runMeta?.duration != null && (
              <div className="lin-etl-runmeta">Run duration {runMeta.duration}s{runMeta?.status ? ` · ${runMeta.status}` : ''}</div>
            )}
            {/* Edge ports for column fan-in / fan-out (API has no column-edge map) */}
            <div className="lin-etl-rails" aria-hidden>
              {pairs.map((p, idx) => {
                const top = pairs.length <= 1 ? 50 : ((idx + 0.5) / pairs.length) * 100;
                return (
                  <span key={p.name} className="lin-etl-rail-row" style={{ top: `${top}%` }}>
                    <i className="lin-port is-left" data-port={`mid-in:${p.name}`} />
                    <i className="lin-port is-right" data-port={`mid-out:${p.name}`} />
                  </span>
                );
              })}
            </div>
          </div>
        </div>

        <div
          className={`lin-wire-card is-target ${selectedNode === 'target' ? 'is-active' : ''}`}
          onClick={() => onSelectNode('target')}
        >
          <div className="lin-wire-head">
            <span className="lin-pill">Target</span>
            <strong>{dash(targetName)}</strong>
            <div className="lin-wire-sub">{dash(targetSystem)} · {dash(targetRows)} rows</div>
          </div>
          <div className="lin-wire-cols">
            {targetCols.length === 0 ? (
              <div className="lin-card-empty">No target columns from latest run</div>
            ) : targetCols.map((c) => {
              const hot = selectedColumn && String(c.column_name).toUpperCase() === String(selectedColumn).toUpperCase();
              return (
                <button
                  type="button"
                  key={c.id || c.column_name}
                  className={`lin-wire-col ${hot ? 'is-hot' : ''}`}
                  onClick={(e) => { e.stopPropagation(); onSelectColumn(c, 'target'); }}
                >
                  <i className="lin-port is-left" data-port={`tgt:${String(c.column_name).toUpperCase()}`} />
                  <code>{c.column_name}</code>
                  <span>{c.data_type || ''}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Lineage() {
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [items, setItems] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [summary, setSummary] = useState(null);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState(null);
  const [columns, setColumns] = useState([]);
  const [level, setLevel] = useState('column');
  const [search, setSearch] = useState('');
  const [colSearch, setColSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [etlFilter, setEtlFilter] = useState('All');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedNode, setSelectedNode] = useState('target');
  const [selectedColumn, setSelectedColumn] = useState(null);
  const [zoomLevel, setZoomLevel] = useState(100);
  const [graphSize, setGraphSize] = useState({ w: 960, h: 400 });
  const [colGraphKey, setColGraphKey] = useState(0);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const onGraphSize = useCallback((size) => {
    if (!size?.w || !size?.h) return;
    setGraphSize((prev) => (prev.w === size.w && prev.h === size.h ? prev : size));
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const params = buildDateParams(headerDatePreset, customDateRange);
      // Lineage list = Health (Healthy/Degraded). Pipelines list = Last run (Success/Failed).
      const [res, pipeRes] = await Promise.all([
        fetchLineage(params),
        fetchPipelines(params).catch(() => null),
      ]);
      const runById = new Map();
      (pipeRes?.items || []).forEach((p) => {
        if (!p?.pipeline_id) return;
        runById.set(p.pipeline_id, {
          last_run_status: p.status || null,
          last_run_activity: p.activity || null,
        });
      });
      const list = (res?.items || []).map((row) => {
        const run = runById.get(row.pipeline_id);
        if (!run) return row;
        return {
          ...row,
          last_run_status: run.last_run_status,
          last_run_activity: run.last_run_activity,
        };
      });
      setItems(list);
      setKpis(res?.kpis || []);
      setSummary(res?.summary || null);
      setSelectedId((prev) => {
        if (prev && list.some(i => i.pipeline_id === prev)) return prev;
        const preferred = list.find(i => i.last_run_at) || list[0];
        return preferred?.pipeline_id || '';
      });
    } catch (e) {
      console.error(e);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange]);

  useEffect(() => { loadList(); }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setColumns([]);
      return undefined;
    }
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      setSelectedColumn(null);
      try {
        const params = buildDateParams(headerDatePreset, customDateRange);
        const det = await fetchLineageDetail(selectedId, params);
        if (cancelled) return;
        setDetail(det);

        const runId = det?.meta?.last_run?.id || det?.meta?.freshness?.run_id;
        if (runId) {
          const run = await fetchRunDetail(runId).catch(() => null);
          if (cancelled) return;
          setColumns(run?.meta?.columns || []);
        } else {
          setColumns([]);
        }
      } catch (e) {
        console.error(e);
        if (!cancelled) {
          setDetail(null);
          setColumns([]);
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId, headerDatePreset, customDateRange]);

  const kpi = useMemo(() => kpiMapFrom(kpis), [kpis]);
  const meta = detail?.meta || {};
  const lineageItem = meta.lineage_item || items.find(i => i.pipeline_id === selectedId) || null;
  const pipe = meta.pipeline || null;
  const assets = meta.assets || [];
  const sourceAsset = assets.find(a => String(a.asset_role).toUpperCase() === 'SOURCE') || null;
  const targetAsset = assets.find(a => String(a.asset_role).toUpperCase() === 'TARGET') || null;
  const lastRun = meta.last_run || null;
  const freshness = meta.freshness || null;
  const dataQuality = meta.data_quality || null;
  const schemaHealth = meta.schema || null;

  const relations = useMemo(() => parseRelations(lastRun?.relations_json), [lastRun]);
  const sourceCols = useMemo(
    () => columns
      .filter(c => String(c.asset_role).toUpperCase() === 'SOURCE')
      .sort((a, b) => (a.ordinal_position || 0) - (b.ordinal_position || 0)),
    [columns],
  );
  const targetCols = useMemo(
    () => columns
      .filter(c => String(c.asset_role).toUpperCase() === 'TARGET')
      .sort((a, b) => (a.ordinal_position || 0) - (b.ordinal_position || 0)),
    [columns],
  );

  const filterCols = (list) => {
    if (!colSearch) return list;
    const q = colSearch.toLowerCase();
    return list.filter(c => String(c.column_name || '').toLowerCase().includes(q)
      || String(c.data_type || '').toLowerCase().includes(q));
  };

  const filteredSourceCols = useMemo(() => filterCols(sourceCols), [sourceCols, colSearch]);
  const filteredTargetCols = useMemo(() => filterCols(targetCols), [targetCols, colSearch]);

  const matchedColumns = useMemo(() => {
    const src = new Set(sourceCols.map(c => String(c.column_name || '').toUpperCase()));
    return targetCols
      .map(c => String(c.column_name || '').toUpperCase())
      .filter(name => src.has(name));
  }, [sourceCols, targetCols]);

  const filteredItems = useMemo(() => items.filter((row) => {
    const st = String(row.status_key || row.status || '').toLowerCase();
    const etl = String(row.etl || '').toLowerCase();
    const hay = [row.pipeline_name, row.source, row.target, row.etl, row.pipeline_id].join(' ').toLowerCase();
    const statusOk = statusFilter === 'All' || st === statusFilter.toLowerCase();
    const etlOk = etlFilter === 'All' || etl === etlFilter.toLowerCase();
    return (!search || hay.includes(search.toLowerCase())) && statusOk && etlOk;
  }), [items, search, statusFilter, etlFilter]);

  const etlOptions = useMemo(() => {
    const set = new Set();
    items.forEach((row) => {
      const e = String(row.etl || '').trim();
      if (e) set.add(e);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [items]);

  // Keep selected pipeline inside current filter set when possible
  useEffect(() => {
    if (!filteredItems.length) return;
    if (filteredItems.some(i => i.pipeline_id === selectedId)) return;
    const preferred = filteredItems.find(i => i.last_run_at) || filteredItems[0];
    if (preferred?.pipeline_id) setSelectedId(preferred.pipeline_id);
  }, [filteredItems, selectedId]);

  const viewStats = useMemo(() => {
    let healthy = 0;
    let degradedN = 0;
    let failedN = 0;
    const sources = new Set();
    filteredItems.forEach((row) => {
      const st = String(row.status_key || row.status || '').toLowerCase();
      if (st === 'healthy' || st === 'good' || st === 'success') healthy += 1;
      else if (st === 'failed' || st === 'critical' || st === 'error') failedN += 1;
      else degradedN += 1;
      if (row.source) sources.add(String(row.source));
      if (row.target) sources.add(String(row.target));
    });
    const total = filteredItems.length;
    const pct = (n) => (total ? `${n} (${((n / total) * 100).toFixed(n && n !== total ? 1 : 0)}%)` : '0 (0%)');
    return {
      total,
      healthy,
      degraded: degradedN,
      failed: failedN,
      sources: sources.size,
      healthyDisplay: pct(healthy),
      degradedDisplay: pct(degradedN),
      filtersActive: Boolean(search || statusFilter !== 'All' || etlFilter !== 'All'),
    };
  }, [filteredItems, search, statusFilter, etlFilter]);

  // KPIs: API values when unfiltered; filtered set when filters are on
  const degraded = viewStats.filtersActive
    ? viewStats.degraded
    : Number(kpi.degraded?.value ?? summary?.degraded ?? viewStats.degraded);
  const failed = viewStats.filtersActive
    ? viewStats.failed
    : Number(kpi.failed?.value ?? summary?.failed ?? viewStats.failed);
  const kpiPipelines = viewStats.filtersActive
    ? viewStats.total
    : dash(kpi.total_pipelines?.display ?? summary?.total ?? viewStats.total);
  const kpiHealthy = viewStats.filtersActive
    ? viewStats.healthyDisplay
    : dash(kpi.healthy?.display ?? viewStats.healthyDisplay);
  const kpiDegraded = viewStats.filtersActive
    ? viewStats.degradedDisplay
    : dash(kpi.degraded?.display ?? viewStats.degradedDisplay);
  const kpiSources = viewStats.filtersActive
    ? viewStats.sources
    : dash(kpi.data_sources?.display ?? summary?.sources ?? viewStats.sources);
  const freshnessTone = statusTone(freshness?.status_key || freshness?.status || lineageItem?.freshness);

  const pipelineName = lineageItem?.pipeline_name || pipe?.pipeline_name || '—';
  const etlLabel = pipe?.etl_tool || lineageItem?.etl || 'ETL';
  const sourceName = sourceAsset?.object_name || lineageItem?.source || '—';
  const targetName = targetAsset?.object_name || lineageItem?.target || '—';
  const sourceSystem = sourceAsset?.system_name || pipe?.source_tool || '—';
  const targetSystem = targetAsset?.system_name || pipe?.target_tool || '—';

  const pathSteps = useMemo(() => {
    const steps = [];
    if (sourceAsset?.dataset_id || sourceName !== '—') {
      steps.push({
        role: 'Source',
        name: sourceAsset?.dataset_id || sourceName,
        tone: 'source',
      });
    }
    relations.forEach((rel) => {
      steps.push({ role: 'Model', name: rel, tone: 'etl' });
    });
    if (targetAsset?.dataset_id || targetName !== '—') {
      const tgt = targetAsset?.dataset_id || targetName;
      if (!steps.some(s => String(s.name).toLowerCase() === String(tgt).toLowerCase())) {
        steps.push({ role: 'Target', name: tgt, tone: 'target' });
      }
    }
    return steps;
  }, [sourceAsset, targetAsset, sourceName, targetName, relations]);

  const selectColumn = (col, node) => {
    setSelectedColumn(col?.column_name || null);
    setSelectedNode(node);
    setDrawerOpen(true);
  };

  const inspectorTitle = selectedNode === 'source'
    ? (sourceAsset?.dataset_id || sourceName)
    : selectedNode === 'etl'
      ? `${etlLabel} · ${pipelineName}`
      : (targetAsset?.dataset_id || targetName);

  const inspectorAsset = selectedNode === 'source' ? sourceAsset
    : selectedNode === 'target' ? targetAsset : null;

  const selectedColMeta = useMemo(() => {
    if (!selectedColumn) return null;
    const upper = String(selectedColumn).toUpperCase();
    return columns.find(c => String(c.column_name || '').toUpperCase() === upper) || null;
  }, [columns, selectedColumn]);

  return (
    <div className="fade-in">
      <PageHeader
        title="Lineage"
        subtitle="Track how your pipelines move data from source tables through transforms to targets."
        onRefresh={loadList}
        datePreset={headerDatePreset}
        onDateChange={(v) => handleDateChange(setHeaderDatePreset, setCustomDateRange, v)}
      />

      <div className="page-body">
        {loading ? <DashboardPageSkeleton kpiCount={4} chartCount={0} tableRows={6} tableCols={6} /> : (
          <>
            {failed > 0 ? (
              <div className="obs-alert is-bad">
                <AlertTriangle size={18} />
                <div><strong>{failed} failed pipeline{failed === 1 ? '' : 's'}.</strong> Check runs and target freshness below.</div>
              </div>
            ) : degraded > 0 ? (
              <div className="obs-alert is-warn">
                <AlertTriangle size={18} />
                <div>
                  <strong>{degraded} degraded pipeline{degraded === 1 ? '' : 's'}.</strong>
                  {' '}Health is soft (often stale freshness) — Last run can still be Success.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div><strong>Lineage healthy.</strong> Listed pipelines report good health.</div>
              </div>
            )}

            <div className="filters-bar">
              <div className="search-box">
                <Search size={14} />
                <input
                  placeholder="Search pipeline, source, target…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
              </div>
              <div className="filter-select">
                <label>View pipeline</label>
                <select className="select-control" value={selectedId} onChange={e => setSelectedId(e.target.value)}>
                  {filteredItems.length === 0 && <option value="">No matching pipelines</option>}
                  {filteredItems.map(p => (
                    <option key={p.pipeline_id} value={p.pipeline_id}>
                      {p.pipeline_name}{p.last_run_at ? '' : ' (no runs)'}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-select">
                <label>ETL</label>
                <select className="select-control" value={etlFilter} onChange={e => setEtlFilter(e.target.value)}>
                  <option value="All">All tools</option>
                  {etlOptions.map(e => (
                    <option key={e} value={e}>{e}</option>
                  ))}
                </select>
              </div>
              <div className="filter-select">
                <label>Health</label>
                <select className="select-control" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                  <option value="All">All</option>
                  <option value="healthy">Healthy</option>
                  <option value="degraded">Degraded</option>
                  <option value="failed">Failed</option>
                </select>
              </div>
              <button
                type="button"
                className="export-btn"
                onClick={() => { setSearch(''); setStatusFilter('All'); setEtlFilter('All'); setColSearch(''); }}
              >
                Clear filters
              </button>
            </div>

            <div className="kpi-grid-4 mt-4">
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}><GitBranch size={18} /></div>
                  <span className="kpi-label">Pipelines{viewStats.filtersActive ? ' (filtered)' : ''}</span>
                </div>
                <div className="kpi-value">{kpiPipelines}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                  {viewStats.filtersActive ? `${viewStats.total} of ${items.length} match filters` : 'From lineage API'}
                </div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}><CheckCircle size={18} /></div>
                  <span className="kpi-label">Healthy</span>
                </div>
                <div className="kpi-value" style={{ color: '#10B981' }}>{kpiHealthy}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}><AlertTriangle size={18} /></div>
                  <span className="kpi-label">Degraded</span>
                </div>
                <div className="kpi-value" style={{ color: degraded ? '#D97706' : undefined }}>{kpiDegraded}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EEF2FF', color: '#6366F1' }}><Database size={18} /></div>
                  <span className="kpi-label">Data sources</span>
                </div>
                <div className="kpi-value">{kpiSources}</div>
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Pipelines in lineage</span>
                  <span className="card-subtitle">Select a row to open its source → transform → target graph</span>
                </div>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{filteredItems.length} of {items.length}</span>
              </div>
              <div className="table-wrapper">
                <table className="vithi-table">
                  <thead>
                    <tr>
                      <th>Pipeline</th>
                      <th>Source</th>
                      <th>ETL</th>
                      <th>Target</th>
                      <th>Freshness</th>
                      <th>Target rows</th>
                      <th>Edges</th>
                      <th>Health</th>
                      <th>Last run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredItems.length === 0 ? (
                      <tr>
                        <td colSpan={9} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                          No lineage pipelines match filters.
                        </td>
                      </tr>
                    ) : filteredItems.map(row => (
                      <tr
                        key={row.pipeline_id}
                        className={row.pipeline_id === selectedId ? 'lin-row-active' : ''}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setSelectedId(row.pipeline_id)}
                      >
                        <td><strong>{dash(row.pipeline_name)}</strong></td>
                        <td>{dash(row.source)}</td>
                        <td><span className="tag">{dash(row.etl)}</span></td>
                        <td>{dash(row.target)}</td>
                        <td>
                          <span className={`status-pill ${statusPill(row.freshness)}`}>
                            {dash(row.freshness)}
                            {row.freshness_lag_hours != null ? ` · ${Math.round(row.freshness_lag_hours)}h` : ''}
                          </span>
                        </td>
                        <td>{dash(row.target_rows)}</td>
                        <td>{dash(row.manifest_edges)}</td>
                        <td><span className={`status-pill ${statusPill(row.status_key || row.status)}`}>{dash(row.status)}</span></td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                            {row.last_run_status ? (
                              <span className={`status-pill ${statusPill(row.last_run_status)}`}>
                                {dash(row.last_run_status)}
                              </span>
                            ) : null}
                            <span>{dash(row.last_run_at)}</span>
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{dash(row.last_run_age)}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className={`lin-workspace mt-4 ${drawerOpen ? 'has-inspector' : ''}`}>
              <div className="card lin-canvas-card">
                <div className="card-header lin-canvas-header">
                  <div>
                    <span className="card-title">{level === 'table' ? 'Table lineage' : 'Column lineage'}</span>
                    <span className="card-subtitle">
                      {pipelineName} · {dash(etlLabel)}
                      {matchedColumns.length > 0 ? ` · ${matchedColumns.length} shared column names` : ''}
                    </span>
                  </div>
                  <div className="lin-toolbar-actions">
                    {level === 'column' && (
                      <div className="search-box lin-filters-col">
                        <Search size={13} />
                        <input
                          placeholder="Filter columns…"
                          value={colSearch}
                          onChange={e => setColSearch(e.target.value)}
                        />
                      </div>
                    )}
                    <div className="lin-level-toggle" role="group" aria-label="Lineage level">
                      <button
                        type="button"
                        className={level === 'table' ? 'active' : ''}
                        onClick={() => { setLevel('table'); setZoomLevel(100); }}
                      >
                        Table
                      </button>
                      <button
                        type="button"
                        className={level === 'column' ? 'active' : ''}
                        onClick={() => {
                          setLevel('column');
                          setZoomLevel(100);
                          setGraphSize({ w: 960, h: 400 });
                          setColGraphKey((k) => k + 1);
                        }}
                      >
                        Column
                      </button>
                    </div>
                    <button type="button" className="export-btn" title="Zoom in" onClick={() => setZoomLevel(z => Math.min(140, z + 10))}><ZoomIn size={12} /></button>
                    <button type="button" className="export-btn" title="Zoom out" onClick={() => setZoomLevel(z => Math.max(70, z - 10))}><ZoomOut size={12} /></button>
                    <button type="button" className="export-btn" title="Reset zoom" onClick={() => setZoomLevel(100)}><Maximize2 size={12} /></button>
                    <span className="lin-zoom-label">{zoomLevel}%</span>
                    <div className="lin-legend">
                      <span><i className="is-source" /> Source</span>
                      <span><i className="is-etl" /> Transform</span>
                      <span><i className="is-target" /> Target</span>
                    </div>
                    <button type="button" className="export-btn" onClick={() => setDrawerOpen(o => !o)}>
                      {drawerOpen ? 'Hide details' : 'Show details'}
                    </button>
                  </div>
                </div>

                {detailLoading ? (
                  <div className="obs-simple-empty">Loading lineage for this pipeline…</div>
                ) : filteredItems.length === 0 ? (
                  <div className="obs-simple-empty">No pipelines match the current filters.</div>
                ) : !selectedId ? (
                  <div className="obs-simple-empty">Select a pipeline in the table above.</div>
                ) : level === 'column' ? (
                  <div className="lin-canvas">
                    <div
                      className="lin-zoom-frame"
                      style={{
                        width: Math.max(graphSize.w * (zoomLevel / 100), 120),
                        height: Math.max(graphSize.h * (zoomLevel / 100), 120),
                      }}
                    >
                      <div
                        className="lin-zoom-inner"
                        style={{
                          width: graphSize.w,
                          transform: `scale(${zoomLevel / 100})`,
                          transformOrigin: 'top left',
                        }}
                      >
                        <ColumnLineageGraph
                          key={`col-${selectedId}-${colGraphKey}`}
                          sourceName={sourceName}
                          sourceSystem={sourceSystem}
                          sourceRows={sourceAsset?.row_count}
                          targetName={targetName}
                          targetSystem={targetSystem}
                          targetRows={targetAsset?.row_count ?? lineageItem?.target_rows}
                          pipelineName={pipelineName}
                          etlLabel={etlLabel}
                          runMeta={{
                            duration: lastRun?.duration ?? lineageItem?.duration,
                            status: lastRun?.status,
                          }}
                          sourceCols={filteredSourceCols}
                          targetCols={filteredTargetCols}
                          relations={relations}
                          selectedColumn={selectedColumn}
                          selectedNode={selectedNode}
                          onSelectColumn={selectColumn}
                          onSelectNode={(n) => { setSelectedNode(n); setDrawerOpen(true); }}
                          onSize={onGraphSize}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="lin-canvas">
                    <div className="lin-flow" style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top left' }}>
                      <button
                        type="button"
                        className={`lin-card is-source ${selectedNode === 'source' ? 'is-active' : ''}`}
                        onClick={() => { setSelectedNode('source'); setDrawerOpen(true); }}
                      >
                        <div className="lin-card-head">
                          <div className="lin-card-head-top">
                            <span className="lin-pill">Source table</span>
                            <MoreVertical size={14} className="lin-card-menu" />
                          </div>
                          <div className="lin-card-title">{dash(sourceName)}</div>
                          <div className="lin-card-platform"><span className="lin-snow">❄</span> {dash(sourceSystem)}</div>
                          <div className="lin-card-stats">
                            <span><Users size={12} /> {dash(sourceAsset?.row_count)} rows</span>
                            <span>{dash(sourceAsset?.column_count ?? sourceCols.length)} columns</span>
                          </div>
                          <div className="lin-card-dataset">{dash(sourceAsset?.dataset_id)}</div>
                        </div>
                        <div className="lin-card-body">
                          <div className="lin-card-empty">
                            Schema {dash(sourceAsset?.schema_name || pipe?.source_schema)} · switch to Column level for wired columns
                          </div>
                        </div>
                      </button>

                      <div className="lin-hop"><ArrowRight size={20} /></div>

                      <button
                        type="button"
                        className={`lin-card is-etl ${selectedNode === 'etl' ? 'is-active' : ''}`}
                        onClick={() => { setSelectedNode('etl'); setDrawerOpen(true); }}
                      >
                        <div className="lin-card-head">
                          <div className="lin-card-head-top">
                            <span className="lin-pill">Transformation</span>
                            <MoreVertical size={14} className="lin-card-menu" />
                          </div>
                          <div className="lin-card-title lin-card-title-row">
                            <span className="lin-etl-icon">▣</span>
                            {dash(pipelineName)}
                          </div>
                          <div className="lin-card-live-row">
                            <span className="lin-live-pill"><span className="lin-live-dot" /> {dash(etlLabel)}</span>
                            <span className="lin-card-duration">
                              <Clock size={12} />
                              {lastRun?.duration != null ? `${lastRun.duration}s` : dash(lineageItem?.duration)}
                              {lastRun?.status ? ` · ${lastRun.status}` : ''}
                            </span>
                          </div>
                        </div>
                        <div className="lin-card-body">
                          {relations.length === 0 ? (
                            <div className="lin-card-empty">No dbt relations on the latest run.</div>
                          ) : relations.map(name => (
                            <div key={name} className="lin-card-col lin-stage-row">
                              <span className="lin-stage-dot" />
                              <code title={name}>{shortDataset(name)}</code>
                            </div>
                          ))}
                        </div>
                      </button>

                      <div className="lin-hop"><ArrowRight size={20} /></div>

                      <button
                        type="button"
                        className={`lin-card is-target ${selectedNode === 'target' ? 'is-active' : ''}`}
                        onClick={() => { setSelectedNode('target'); setDrawerOpen(true); }}
                      >
                        <div className="lin-card-head">
                          <div className="lin-card-head-top">
                            <span className="lin-pill">Target table</span>
                            <MoreVertical size={14} className="lin-card-menu" />
                          </div>
                          <div className="lin-card-title">{dash(targetName)}</div>
                          <div className="lin-card-platform"><span className="lin-snow">❄</span> {dash(targetSystem)}</div>
                          <div className="lin-card-stats">
                            <span><Users size={12} /> {dash(targetAsset?.row_count ?? lineageItem?.target_rows)} rows</span>
                            <span>{dash(targetAsset?.column_count ?? targetCols.length)} columns</span>
                          </div>
                          <div className="lin-card-dataset">{dash(targetAsset?.dataset_id)}</div>
                        </div>
                        <div className="lin-card-body">
                          <div className="lin-card-empty">
                            Schema {dash(targetAsset?.schema_name || pipe?.target_schema)} · freshness {dash(freshness?.status || lineageItem?.freshness)}
                          </div>
                        </div>
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {drawerOpen && (
                <div className="card lin-inspector">
                  <div className="card-header">
                    <div>
                      <span className="card-title">Observability health</span>
                      <span className="card-subtitle">From lineage detail + latest run APIs</span>
                    </div>
                    <button type="button" className="icon-btn" onClick={() => setDrawerOpen(false)}><X size={14} /></button>
                  </div>
                  <div className="lin-inspector-body">
                    <div className="lin-inspector-pill">
                      <Table size={14} />
                      <strong title={inspectorTitle}>{inspectorTitle}</strong>
                    </div>

                    {selectedColMeta && (
                      <div className="lin-inspector-block">
                        <div><span>Column</span><strong>{selectedColMeta.column_name}</strong></div>
                        <div><span>Type</span><strong>{dash(selectedColMeta.data_type)}</strong></div>
                        <div><span>Role</span><strong>{dash(selectedColMeta.asset_role)}</strong></div>
                        <div><span>Dataset</span><strong className="mono">{dash(selectedColMeta.dataset_id)}</strong></div>
                        <div>
                          <span>Shared name</span>
                          <strong>{matchedColumns.includes(String(selectedColMeta.column_name).toUpperCase()) ? 'Yes — also on peer table' : 'Only on this side'}</strong>
                        </div>
                      </div>
                    )}

                    {inspectorAsset && (
                      <div className="lin-inspector-block">
                        <div><span>System</span><strong>{dash(inspectorAsset.system_name)}</strong></div>
                        <div><span>Dataset</span><strong className="mono">{dash(inspectorAsset.dataset_id)}</strong></div>
                        <div><span>Rows</span><strong>{dash(inspectorAsset.row_count)}</strong></div>
                        <div><span>Size</span><strong>{dash(formatBytes(inspectorAsset.size_bytes))}</strong></div>
                        <div><span>Updated</span><strong>{dash(inspectorAsset.last_updated_at)}</strong></div>
                      </div>
                    )}

                    {selectedNode === 'etl' && (
                      <div className="lin-inspector-block">
                        <div><span>Tool</span><strong>{dash(etlLabel)}</strong></div>
                        <div><span>Run</span><strong className="mono">{dash(lastRun?.id)}</strong></div>
                        <div><span>Status</span><strong>{dash(lastRun?.status)}</strong></div>
                        <div><span>Duration</span><strong>{lastRun?.duration != null ? `${lastRun.duration}s` : '—'}</strong></div>
                        <div><span>Rows in → out</span><strong>{dash(lastRun?.rows_read)} → {dash(lastRun?.rows_written)}</strong></div>
                        <div><span>Edges</span><strong>{dash(lineageItem?.manifest_edges)}</strong></div>
                      </div>
                    )}

                    <div className="lin-health-grid">
                      <div className={`lin-health ${healthToneClass(freshnessTone)}`}>
                        <span>Freshness</span>
                        <strong>
                          {dash(freshness?.status || lineageItem?.freshness)}
                          {freshness?.current_lag_display ? ` · ${freshness.current_lag_display}` : ''}
                        </strong>
                      </div>
                      <div className="lin-health is-ok">
                        <span>Volume</span>
                        <strong>{dash(targetAsset?.row_count ?? lineageItem?.target_rows)} target rows</strong>
                      </div>
                      <div className={`lin-health ${Number(dataQuality?.failed_tests) > 0 ? 'is-bad' : 'is-ok'}`}>
                        <span>Data quality</span>
                        <strong>
                          {dash(dataQuality?.display || lineageItem?.data_quality_display)}
                          {dataQuality?.failed_tests != null ? ` · ${dataQuality.failed_tests} failed` : ''}
                        </strong>
                      </div>
                      <div className={`lin-health ${statusTone(schemaHealth?.status) === 'crit' ? 'is-bad' : 'is-ok'}`}>
                        <span>Schema</span>
                        <strong>
                          {dash(schemaHealth?.display)}
                          {schemaHealth?.breaking_changes != null ? ` · ${schemaHealth.breaking_changes} breaking` : ''}
                        </strong>
                      </div>
                    </div>

                    {(() => {
                      const schemaPct = Number.parseFloat(String(schemaHealth?.display || '').replace('%', ''));
                      return Number.isFinite(schemaPct) ? (
                        <div className="lin-bars">
                          <div>
                            <div className="lin-bar-label"><span>Schema stability</span><strong>{schemaPct}%</strong></div>
                            <div className="lin-bar-track"><div style={{ width: `${Math.min(100, schemaPct)}%` }} /></div>
                          </div>
                        </div>
                      ) : null;
                    })()}

                    <div className="lin-impact-box">
                      <strong>{matchedColumns.length} shared column names</strong>
                      <span>Click a column to highlight Source → Transform → Target. Links use matching names from the latest run schema.</span>
                      <button
                        type="button"
                        className="export-btn"
                        style={{ background: '#10B981', color: '#fff', border: 'none', width: '100%', justifyContent: 'center' }}
                        onClick={() => { setLevel('column'); setDrawerOpen(true); }}
                      >
                        View {targetCols.length || sourceCols.length || 0} columns →
                      </button>
                    </div>

                    {pathSteps.length > 0 && (
                      <div className="lin-path">
                        <span className="lin-section-label">Lineage path</span>
                        {pathSteps.map((step, idx) => (
                          <div key={`${step.name}-${idx}`} className={`lin-path-step is-${step.tone}`}>
                            <span>{step.role}</span>
                            <code>{step.name}</code>
                          </div>
                        ))}
                      </div>
                    )}

                    {lastRun && (
                      <div className="lin-inspector-foot">
                        <Clock size={13} />
                        <span>
                          Last run{' '}
                          <span className={`status-pill ${statusPill(lastRun.status || lineageItem?.last_run_status)}`}>
                            {dash(lastRun.status || lineageItem?.last_run_status)}
                          </span>
                          {' '}
                          {dash(lastRun.end_time || lastRun.start_time)} · {dash(lineageItem?.last_run_age)}
                        </span>
                      </div>
                    )}
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
