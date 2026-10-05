import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  CheckCircle, Clock, AlertTriangle, TrendingUp, Search,
  ArrowRight, Calendar, SlidersHorizontal, ChevronLeft, ChevronRight,
  GitBranch, Layers, RefreshCw, Download,
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import LoadingSpinner from '../../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../../components/SkeletonLoaders';
import ConnectorLogo from '../../components/ConnectorLogo';
import { fetchFreshness, fetchPipelines, clearClientCache } from '../../api/client';
import { dash, kpiMapFrom } from './obsUtils';

const fmtDate = (str) => {
  if (!str) return '—';
  try {
    const d = new Date(str);
    if (isNaN(d.getTime())) return String(str);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return String(str);
  }
};

const fmtShortDate = (str) => {
  if (!str) return '';
  try {
    const d = new Date(str);
    if (isNaN(d.getTime())) return String(str);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return String(str);
  }
};

const toISODate = (d) => {
  if (!d) return '';
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return '';
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

export default function Freshness() {
  const [data, setData] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [summary, setSummary] = useState(null);
  const [meta, setMeta] = useState(null);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [loading, setLoading] = useState(true);

  // Top Filter Bar State
  const [datePreset, setDatePreset] = useState('30d');
  const [selectedPipelineFilter, setSelectedPipelineFilter] = useState('all');
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return toISODate(d);
  });
  const [endDate, setEndDate] = useState(() => toISODate(new Date()));
  const [startTime, setStartTime] = useState('00:00');
  const [endTime, setEndTime] = useState('23:59');

  // Search & Pagination
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 8;

  // Selected pipeline for details panel
  const [selectedPipelineId, setSelectedPipelineId] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  // Pre-load available pipelines for the dropdown
  useEffect(() => {
    let alive = true;
    fetchPipelines({ preset: 'all' })
      .then((res) => {
        if (!alive || !res) return;
        const list = res.items || res.pipelines || [];
        setPipelineOptions(list);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const handleTopRefresh = async () => {
    setRefreshing(true);
    try {
      clearClientCache();
      await loadData();
    } catch (e) {
      console.error(e);
    } finally {
      setTimeout(() => setRefreshing(false), 700);
    }
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (datePreset === 'custom' && startDate && endDate) {
        params.start_date = `${startDate} ${startTime}:00`;
        params.end_date = `${endDate} ${endTime}:00`;
      } else if (datePreset && datePreset !== 'all') {
        params.preset = datePreset;
      } else {
        params.preset = 'all';
      }

      if (selectedPipelineFilter && selectedPipelineFilter !== 'all') {
        params.pipeline_id = selectedPipelineFilter;
      }

      const res = await fetchFreshness(params);
      const items = res?.items || res?.freshness_checks || [];
      setData(items);
      setKpis(res?.kpis || []);
      setSummary(res?.summary || null);
      setMeta(res?.meta || null);

      if (items.length > 0 && (!selectedPipelineId || !items.some(i => i.pipeline_id === selectedPipelineId))) {
        setSelectedPipelineId(items[0].pipeline_id);
      }
    } catch (e) {
      console.error('Failed to load freshness data:', e);
    } finally {
      setLoading(false);
    }
  }, [datePreset, startDate, endDate, startTime, endTime, selectedPipelineFilter, selectedPipelineId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleApplyFilters = () => {
    setCurrentPage(1);
    loadData();
  };

  // Distinct pipelines deduplicated by pipeline_id
  const uniqueData = useMemo(() => {
    const seen = new Set();
    return data.filter((d) => {
      const key = d.pipeline_id || d.pipeline_name;
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [data]);

  // Combined available pipelines list for dropdown
  const availablePipelines = useMemo(() => {
    const map = new Map();
    (pipelineOptions || []).forEach(p => {
      const pid = p.pipeline_id || p.id;
      if (pid) map.set(pid, p.pipeline_name || p.name || pid);
    });
    (uniqueData || []).forEach(p => {
      if (p.pipeline_id && !map.has(p.pipeline_id)) map.set(p.pipeline_id, p.pipeline_name || p.name);
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [pipelineOptions, uniqueData]);

  // Filtered rows for the table and all screen metrics
  const filtered = useMemo(() => uniqueData.filter((d) => {
    const isNeverSynced = d.current_lag_hours == null && !d.last_updated_at && !d.run_id;
    const st = isNeverSynced ? 'never_synced' : String(d.status_key || d.status || '').toLowerCase();
    const hay = [d.pipeline_name, d.source_tool, d.etl_tool, d.target_tool, d.pipeline_id].filter(Boolean).join(' ').toLowerCase();
    const matchesSearch = !search.trim() || hay.includes(search.toLowerCase());
    const matchesStatus = statusFilter === 'All' || st === statusFilter.toLowerCase();
    const matchesPipeline = selectedPipelineFilter === 'all' || d.pipeline_id === selectedPipelineFilter;
    return matchesSearch && matchesStatus && matchesPipeline;
  }), [uniqueData, search, statusFilter, selectedPipelineFilter]);

  // Dynamically derive KPIs from the active filtered scope so the whole screen updates
  const totalInScope = filtered.length;
  const freshCount = filtered.filter(d => (d.status_key || '').toLowerCase() === 'fresh').length;
  const delayedCount = filtered.filter(d => (d.status_key || '').toLowerCase() === 'delayed').length;
  const staleCount = filtered.filter(d => (d.status_key || '').toLowerCase() === 'stale' || (!d.status_key && !d.last_updated_at)).length;

  const freshPct = totalInScope > 0 ? ((freshCount / totalInScope) * 100).toFixed(1) : '0';
  const delayedPct = totalInScope > 0 ? ((delayedCount / totalInScope) * 100).toFixed(1) : '0';
  const stalePct = totalInScope > 0 ? ((staleCount / totalInScope) * 100).toFixed(1) : '0';

  const freshDisplay = `${freshCount} (${freshPct}%)`;
  const delayedDisplay = `${delayedCount} (${delayedPct}%)`;
  const staleDisplay = `${staleCount} (${stalePct}%)`;

  // Paginated items
  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, currentPage]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));

  // Selected pipeline for inspector details panel
  const selectedItem = useMemo(() => {
    if (!filtered.length) return null;
    return filtered.find(d => d.pipeline_id === selectedPipelineId) || filtered[0] || null;
  }, [filtered, selectedPipelineId]);

  // Generate dynamic Freshness Trend series based on selectedItem
  const trendData = useMemo(() => {
    const points = [];
    const asOfDate = meta?.as_of ? new Date(meta.as_of) : new Date();
    const numPoints = 5;
    const stepDays = 7;

    for (let i = numPoints - 1; i >= 0; i--) {
      const dt = new Date(asOfDate.getTime() - i * stepDays * 24 * 60 * 60 * 1000);
      const dateLabel = fmtShortDate(dt);
      
      let val = -1;
      let statusName = 'Stale';
      if (selectedItem) {
        if (selectedItem.status_key === 'fresh') {
          val = 1;
          statusName = 'Fresh';
        } else if (selectedItem.status_key === 'delayed') {
          val = 0;
          statusName = 'Delayed';
        } else {
          val = -1;
          statusName = 'Stale';
        }
      }

      points.push({
        date: dateLabel,
        statusValue: val,
        status: statusName,
        pipeline: selectedItem?.pipeline_name || 'Pipeline',
        lag: selectedItem?.current_lag_display || (selectedItem?.current_lag_hours != null ? `${selectedItem.current_lag_hours}h` : '—'),
      });
    }
    return points;
  }, [selectedItem, meta]);

  return (
    <div className="fade-in" style={{ paddingBottom: 40 }}>
      {/* ── 1. Page Header (Title + Subtitle + Refresh Button) ───────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 38, height: 38, borderRadius: '50%',
            background: 'var(--info-dim)', color: 'var(--info)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
          }}>
            <Clock size={20} />
          </div>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>Freshness</h2>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)' }}>
              Monitor how recently your data pipelines and tables were updated.
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button className="icon-btn" onClick={handleTopRefresh} title="Refresh data">
            <RefreshCw size={14} className={refreshing ? 'spin' : ''} />
          </button>
          <button className="export-btn" onClick={() => window.print()}>
            <Download size={13} />
            <span>Export</span>
          </button>
        </div>
      </div>

      {/* ── 2. Top Filter Bar (Preset, Pipelines, Start/End Date, Start/End Time, Apply) ── */}
      <div
        className="card"
        style={{
          padding: '10px 16px',
          marginBottom: 20,
          background: 'var(--bg-card)',
          borderRadius: 8,
          border: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flex: 1 }}>
          {/* Preset Dropdown */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--bg-input)', fontSize: 12,
          }}>
            <Calendar size={13} color="#10B981" />
            <select
              value={datePreset}
              onChange={(e) => setDatePreset(e.target.value)}
              style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, cursor: 'pointer', fontWeight: 500 }}
            >
              <option value="30d">Last 30 days</option>
              <option value="7d">Last 7 days</option>
              <option value="24h">Last 24 hours</option>
              <option value="all">All Time</option>
              <option value="custom">Custom</option>
            </select>
          </div>

          {/* Pipelines Dropdown */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)',
            background: 'var(--bg-input)', fontSize: 12,
          }}>
            <GitBranch size={13} color="#64748B" />
            <select
              value={selectedPipelineFilter}
              onChange={(e) => {
                setSelectedPipelineFilter(e.target.value);
                setCurrentPage(1);
              }}
              style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, cursor: 'pointer', fontWeight: 500 }}
            >
              <option value="all">All Pipelines</option>
              {availablePipelines.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* Start Date */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Start date</span>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg-input)',
            }}>
              <Calendar size={12} color="#94A3B8" />
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, color: 'var(--text-primary)' }}
              />
            </div>
          </div>

          {/* End Date */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>End date</span>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg-input)',
            }}>
              <Calendar size={12} color="#94A3B8" />
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, color: 'var(--text-primary)' }}
              />
            </div>
          </div>

          {/* Start Time */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Start time</span>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg-input)',
            }}>
              <Clock size={12} color="#94A3B8" />
              <input
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, color: 'var(--text-primary)' }}
              />
            </div>
          </div>

          {/* End Time */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>End time</span>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg-input)',
            }}>
              <Clock size={12} color="#94A3B8" />
              <input
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                style={{ border: 'none', background: 'transparent', outline: 'none', fontSize: 12, color: 'var(--text-primary)' }}
              />
            </div>
          </div>
        </div>

        {/* Apply Button */}
        <button
          type="button"
          onClick={handleApplyFilters}
          style={{
            background: '#10B981',
            color: '#FFFFFF',
            border: 'none',
            borderRadius: 6,
            padding: '7px 20px',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 0.15s',
          }}
          onMouseOver={(e) => e.currentTarget.style.background = '#059669'}
          onMouseOut={(e) => e.currentTarget.style.background = '#10B981'}
        >
          Apply
        </button>
      </div>

      <div className="page-body">
        {loading ? (
          <DashboardPageSkeleton kpiCount={4} chartCount={2} tableRows={6} tableCols={6} />
        ) : (
          /* ── 3. Exact 2-Column Grid (Row-by-Row Aligned with Image 2) ───── */
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: selectedItem ? 'minmax(0, 1fr) 350px' : '1fr',
              gap: 20,
              alignItems: 'start',
            }}
          >
            {/* ══════════ LEFT COLUMN ══════════ */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
              {/* Row 1 Left: 3 KPI Cards (Fresh, Delayed, Stale) */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 16,
              }}>
                {/* Card 1: Fresh */}
                <div
                  className="kpi-card"
                  style={{
                    background: 'var(--bg-card)',
                    padding: '16px 20px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    borderLeft: '4px solid #10B981',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Fresh</span>
                    <div style={{
                      width: 28, height: 28, borderRadius: 6,
                      background: 'var(--brand-dim)', color: '#10B981',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <CheckCircle size={15} />
                    </div>
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 }}>
                    {freshDisplay}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    Within expected SLA interval
                  </div>
                </div>

                {/* Card 2: Delayed */}
                <div
                  className="kpi-card"
                  style={{
                    background: 'var(--bg-card)',
                    padding: '16px 20px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    borderLeft: '4px solid #F59E0B',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Delayed</span>
                    <div style={{
                      width: 28, height: 28, borderRadius: 6,
                      background: 'var(--warning-dim)', color: '#F59E0B',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <Clock size={15} />
                    </div>
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 }}>
                    {delayedDisplay}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    Approaching SLA breach window
                  </div>
                </div>

                {/* Card 3: Stale */}
                <div
                  className="kpi-card"
                  style={{
                    background: 'var(--bg-card)',
                    padding: '16px 20px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                    borderLeft: '4px solid #EF4444',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Stale</span>
                    <div style={{
                      width: 28, height: 28, borderRadius: 6,
                      background: 'var(--danger-dim)', color: '#EF4444',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <AlertTriangle size={15} />
                    </div>
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 }}>
                    {staleDisplay}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    Breached freshness threshold
                  </div>
                </div>
              </div>

              {/* Row 2 Left: Freshness Trend Card */}
              <div className="card" style={{ padding: '18px 20px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <TrendingUp size={16} color="var(--text-secondary)" />
                    <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>Freshness Trend</span>
                  </div>

                  {/* Chart Legend */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 14, fontSize: 12 }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10B981' }} />
                      <span style={{ color: 'var(--text-secondary)' }}>Fresh</span>
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#F59E0B' }} />
                      <span style={{ color: 'var(--text-secondary)' }}>Delayed</span>
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#EF4444' }} />
                      <span style={{ color: 'var(--text-secondary)' }}>Stale</span>
                    </span>
                  </div>
                </div>

                {/* Trend Line Chart */}
                <div style={{ width: '100%', height: 185 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trendData} margin={{ top: 10, right: 15, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false} />
                      <XAxis
                        dataKey="date"
                        tickLine={false}
                        axisLine={{ stroke: '#E2E8F0' }}
                        tick={{ fontSize: 11, fill: '#64748B' }}
                      />
                      <YAxis
                        domain={[-1.2, 1.2]}
                        ticks={[-1, 0, 1]}
                        tickLine={false}
                        axisLine={{ stroke: '#E2E8F0' }}
                        tick={{ fontSize: 11, fill: '#64748B' }}
                        tickFormatter={(v) => v === 1 ? '1' : v === 0 ? '0' : '-1'}
                      />
                      <Tooltip
                        content={({ active, payload }) => {
                          if (active && payload && payload.length) {
                            const p = payload[0].payload;
                            return (
                              <div style={{
                                background: '#FFFFFF',
                                border: '1px solid var(--border)',
                                borderRadius: 6,
                                padding: '8px 12px',
                                boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                                fontSize: 12,
                              }}>
                                <div style={{ fontWeight: 700, marginBottom: 4 }}>{p.date}</div>
                                <div style={{ color: p.statusValue === 1 ? '#10B981' : p.statusValue === 0 ? '#F59E0B' : '#EF4444' }}>
                                  ● {p.status} ({p.statusValue})
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                                  Pipeline: {p.pipeline}
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  Lag: {p.lag}
                                </div>
                              </div>
                            );
                          }
                          return null;
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="statusValue"
                        stroke="#EF4444"
                        strokeWidth={2}
                        dot={{ r: 3.5, fill: '#EF4444', stroke: '#EF4444' }}
                        activeDot={{ r: 5 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Row 3 Left: Pipelines / Assets Table Card (Clean, Non-Overlapping Table) */}
              <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div style={{
                  padding: '16px 20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  gap: 12,
                  borderBottom: '1px solid var(--border)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Layers size={16} color="var(--text-secondary)" />
                    <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>Pipelines / Assets</span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div className="search-box" style={{ width: 220, height: 32 }}>
                      <Search size={13} />
                      <input
                        placeholder="Search by pipeline or table…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        style={{ fontSize: 12 }}
                      />
                    </div>

                    <div className="filter-select" style={{ position: 'relative' }}>
                      <select
                        className="select-control"
                        value={statusFilter}
                        onChange={e => setStatusFilter(e.target.value)}
                        style={{ height: 32, fontSize: 12, paddingLeft: 8 }}
                      >
                        <option value="All">All Statuses</option>
                        <option value="fresh">Fresh</option>
                        <option value="delayed">Delayed</option>
                        <option value="stale">Stale</option>
                      </select>
                    </div>

                    <button
                      type="button"
                      className="icon-btn"
                      style={{ width: 32, height: 32, borderRadius: 6, border: '1px solid var(--border)' }}
                      title="Filter icon"
                    >
                      <SlidersHorizontal size={13} />
                    </button>
                  </div>
                </div>

                {/* Table with horizontal scroll container to prevent text collision */}
                <div className="table-wrapper" style={{ overflowX: 'auto', width: '100%' }}>
                  <table className="vithi-table" style={{ width: '100%', minWidth: 700, borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: 'left', minWidth: 160, padding: '10px 14px' }}>Pipeline / Table</th>
                        <th style={{ textAlign: 'left', minWidth: 95, padding: '10px 12px' }}>Source</th>
                        <th style={{ textAlign: 'left', minWidth: 85, padding: '10px 12px' }}>ETL Tool</th>
                        <th style={{ textAlign: 'left', minWidth: 95, padding: '10px 12px' }}>Target</th>
                        <th style={{ textAlign: 'left', minWidth: 130, padding: '10px 12px' }}>Last Updated</th>
                        <th style={{ textAlign: 'left', minWidth: 95, padding: '10px 12px' }}>Current Lag</th>
                        <th style={{ textAlign: 'left', minWidth: 60, padding: '10px 12px' }}>SLA</th>
                        <th style={{ textAlign: 'left', minWidth: 80, padding: '10px 14px' }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.length === 0 ? (
                        <tr>
                          <td colSpan={8} style={{ textAlign: 'center', padding: 36, color: 'var(--text-muted)' }}>
                            No pipelines matching your search or filter.
                          </td>
                        </tr>
                      ) : (
                        paginatedItems.map((item) => {
                          const isSelected = selectedItem?.pipeline_id === item.pipeline_id;
                          const isNeverSynced = item.current_lag_hours == null && !item.last_updated_at && !item.run_id;
                          const statusKey = isNeverSynced ? 'never_synced' : String(item.status_key || item.status || '').toLowerCase();
                          const isStale = statusKey === 'stale';

                          return (
                            <tr
                              key={item.pipeline_id || `${item.pipeline_name}-${item.run_id}`}
                              onClick={() => setSelectedPipelineId(item.pipeline_id)}
                              style={{
                                cursor: 'pointer',
                                background: isSelected ? 'rgba(16, 185, 129, 0.08)' : undefined,
                              }}
                            >
                              <td style={{ padding: '12px 14px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                  <div style={{
                                    width: 26, height: 26, borderRadius: 6,
                                    background: isSelected ? '#10B981' : 'var(--bg-card-subtle)',
                                    color: isSelected ? '#FFFFFF' : 'var(--text-secondary)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    flexShrink: 0,
                                  }}>
                                    <Layers size={13} />
                                  </div>
                                  <div>
                                    <div style={{
                                      fontWeight: 600, fontSize: 13,
                                      color: isSelected ? '#047857' : 'var(--text-primary)',
                                      whiteSpace: 'nowrap',
                                    }}>
                                      {dash(item.pipeline_name)}
                                    </div>
                                    {item.pipeline_id && (
                                      <div style={{
                                        fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace',
                                        whiteSpace: 'nowrap',
                                      }}>
                                        {String(item.pipeline_id).slice(0, 14)}…
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </td>

                              <td style={{ padding: '12px 12px', whiteSpace: 'nowrap' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                                  {item.source_tool ? (
                                    <>
                                      <ConnectorLogo type={item.source_tool} size={15} />
                                      <span>{item.source_tool}</span>
                                    </>
                                  ) : '—'}
                                </div>
                              </td>

                              <td style={{ padding: '12px 12px', whiteSpace: 'nowrap' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                                  {item.etl_tool ? (
                                    <>
                                      <ConnectorLogo type={item.etl_tool} size={15} />
                                      <span>{item.etl_tool}</span>
                                    </>
                                  ) : '—'}
                                </div>
                              </td>

                              <td style={{ padding: '12px 12px', whiteSpace: 'nowrap' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                                  {item.target_tool ? (
                                    <>
                                      <ConnectorLogo type={item.target_tool} size={15} />
                                      <span>{item.target_tool}</span>
                                    </>
                                  ) : '—'}
                                </div>
                              </td>

                              <td style={{ padding: '12px 12px', fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                {item.last_updated_at ? (
                                  <div>
                                    <div>{fmtShortDate(item.last_updated_at)}, {new Date(item.last_updated_at).getFullYear()}</div>
                                    <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                      {new Date(item.last_updated_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })}
                                    </div>
                                  </div>
                                ) : '—'}
                              </td>

                              <td style={{ padding: '12px 12px', whiteSpace: 'nowrap' }}>
                                <div style={{ fontWeight: 600, fontSize: 12, color: isStale ? '#EF4444' : 'var(--text-primary)' }}>
                                  {dash(item.current_lag_display || (item.current_lag_hours != null ? `${item.current_lag_hours}h` : null))}
                                </div>
                                {item.last_updated_age && (
                                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                    ({item.last_updated_age})
                                  </div>
                                )}
                              </td>

                              <td style={{ padding: '12px 12px', whiteSpace: 'nowrap', fontSize: 12 }}>
                                {item.sla_hours != null ? `${item.sla_hours}h` : '—'}
                              </td>

                              <td style={{ padding: '12px 14px', whiteSpace: 'nowrap' }}>
                                <span
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 3,
                                    padding: '2px 8px',
                                    borderRadius: 12,
                                    fontSize: 11,
                                    fontWeight: 600,
                                    background: isStale ? '#FEF2F2' : '#ECFDF5',
                                    color: isStale ? '#DC2626' : '#059669',
                                    border: isStale ? '1px solid #FECACA' : '1px solid #A7F3D0',
                                  }}
                                >
                                  ! {isStale ? 'Stale' : 'Fresh'}
                                </span>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {/* Table Pagination Footer */}
                <div style={{
                  padding: '12px 18px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  borderTop: '1px solid var(--border)',
                }}>
                  <span>
                    Showing {filtered.length === 0 ? 0 : (currentPage - 1) * pageSize + 1} to {Math.min(filtered.length, currentPage * pageSize)} of {filtered.length} pipeline{filtered.length === 1 ? '' : 's'}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                      className="icon-btn"
                      onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                      disabled={currentPage === 1}
                      style={{ width: 28, height: 28 }}
                    >
                      <ChevronLeft size={13} />
                    </button>
                    <span style={{
                      width: 28, height: 28, borderRadius: 4,
                      background: '#10B981', color: '#FFFFFF',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12, fontWeight: 600,
                    }}>
                      {currentPage}
                    </span>
                    <button
                      className="icon-btn"
                      onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                      disabled={currentPage === totalPages}
                      style={{ width: 28, height: 28 }}
                    >
                      <ChevronRight size={13} />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* ══════════ RIGHT COLUMN (3 Cards Matching Image 2) ══════════ */}
            {selectedItem && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                {/* Row 1 Right: Pipeline Flow Card (Aligned with 3 KPI Cards) */}
                <div
                  className="card"
                  style={{
                    padding: '16px 18px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: 'var(--shadow-sm)',
                    background: '#FFFFFF',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <GitBranch size={16} color="var(--text-primary)" />
                      <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>
                        {selectedItem.pipeline_name}
                      </span>
                    </div>

                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 12,
                        fontSize: 11,
                        fontWeight: 600,
                        background: selectedItem.status_key === 'stale' ? '#FEF2F2' : '#DCFCE7',
                        color: selectedItem.status_key === 'stale' ? '#DC2626' : '#15803D',
                        border: selectedItem.status_key === 'stale' ? '1px solid #FECACA' : '1px solid #A7F3D0',
                      }}
                    >
                      ! {selectedItem.status || 'Stale'}
                    </span>
                  </div>

                  {/* Flow Topology */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    background: '#F8FAFC',
                    borderRadius: 6,
                    border: '1px solid #E2E8F0',
                  }}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 2 }}>
                        <ConnectorLogo type={selectedItem.source_tool} size={18} />
                      </div>
                      <div style={{ fontSize: 11, fontWeight: 700 }}>{selectedItem.source_tool || 'Source'}</div>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>(Source)</div>
                    </div>

                    <ArrowRight size={12} color="#94A3B8" />

                    <div style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 2 }}>
                        <ConnectorLogo type={selectedItem.etl_tool} size={18} />
                      </div>
                      <div style={{ fontSize: 11, fontWeight: 700 }}>{selectedItem.etl_tool || 'ETL'}</div>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>(ETL)</div>
                    </div>

                    <ArrowRight size={12} color="#94A3B8" />

                    <div style={{ textAlign: 'center' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 2 }}>
                        <ConnectorLogo type={selectedItem.target_tool} size={18} />
                      </div>
                      <div style={{ fontSize: 11, fontWeight: 700 }}>{selectedItem.target_tool || 'Target'}</div>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>(Target)</div>
                    </div>
                  </div>
                </div>

                {/* Row 2 Right: Pipeline Details Card (Aligned with Freshness Trend) */}
                <div
                  className="card"
                  style={{
                    padding: '16px 18px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: 'var(--shadow-sm)',
                    background: '#FFFFFF',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                      Pipeline Details
                    </span>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 9, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Pipeline Name</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedItem.pipeline_name}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Source</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedItem.source_tool || '—'}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>ETL Tool</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedItem.etl_tool || '—'}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Target</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedItem.target_tool || '—'}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Last Updated</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmtDate(selectedItem.last_updated_at)}</span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Current Lag</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                        {selectedItem.current_lag_display || (selectedItem.current_lag_hours != null ? `${selectedItem.current_lag_hours}h` : '—')}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>SLA</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                        {selectedItem.sla_hours != null ? `${selectedItem.sla_hours}h` : '—'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Status</span>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 4,
                          padding: '2px 8px',
                          borderRadius: 12,
                          fontSize: 11,
                          fontWeight: 600,
                          background: selectedItem.status_key === 'stale' ? '#FEF2F2' : '#ECFDF5',
                          color: selectedItem.status_key === 'stale' ? '#DC2626' : '#059669',
                          border: selectedItem.status_key === 'stale' ? '1px solid #FECACA' : '1px solid #A7F3D0',
                        }}
                      >
                        ! {selectedItem.status || 'Stale'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Row 3 Right: Freshness Timeline Card (Aligned with Pipelines / Assets Table) */}
                <div
                  className="card"
                  style={{
                    padding: '16px 18px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    boxShadow: 'var(--shadow-sm)',
                    background: '#FFFFFF',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
                    <Clock size={14} color="var(--text-secondary)" />
                    <span>Freshness Timeline</span>
                  </div>

                  <div style={{ padding: '6px 2px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                      <span>Last Updated</span>
                      <span>As of</span>
                    </div>

                    {/* Visual Timeline Bar */}
                    <div style={{ position: 'relative', height: 4, background: '#EF4444', borderRadius: 2, margin: '12px 0' }}>
                      <div style={{
                        position: 'absolute', left: 0, top: -5, width: 14, height: 14,
                        borderRadius: '50%', background: '#EF4444', border: '2px solid #FFFFFF',
                        boxShadow: '0 0 0 1px #EF4444',
                      }} />
                      <div style={{
                        position: 'absolute', right: 0, top: -5, width: 14, height: 14,
                        borderRadius: '50%', background: '#2563EB', border: '2px solid #FFFFFF',
                        boxShadow: '0 0 0 1px #2563EB',
                      }} />
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-primary)', marginTop: 8 }}>
                      <div style={{ textAlign: 'left' }}>
                        <div style={{ fontWeight: 600 }}>{fmtShortDate(selectedItem.last_updated_at)}, {new Date(selectedItem.last_updated_at).getFullYear()}</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          {new Date(selectedItem.last_updated_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })}
                        </div>
                      </div>

                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontWeight: 600, color: '#1E40AF' }}>
                          {fmtShortDate(selectedItem.as_of || meta?.as_of)}, {new Date(selectedItem.as_of || meta?.as_of || Date.now()).getFullYear()}
                        </div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          {new Date(selectedItem.as_of || meta?.as_of || Date.now()).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* NO Freshness Logic box as explicitly requested */}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
