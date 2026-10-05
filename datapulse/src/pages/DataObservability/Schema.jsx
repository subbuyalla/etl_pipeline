import { useEffect, useState, useMemo, useCallback } from 'react';
import { CheckCircle, AlertTriangle, Layers, Search, Layout, Info } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../../components/PageHeader';
import LoadingSpinner from '../../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../../components/SkeletonLoaders';
import { fetchSchema, fetchPipelines } from '../../api/client';
import {
  dash, kpiMapFrom, buildDateParams, handleDateChange, TOOLTIP_STYLE,
} from './obsUtils';

export default function Schema() {
  const [schemaData, setSchemaData] = useState(null);
  const [pipelineOptions, setPipelineOptions] = useState([]);
  const [pipelineFilter, setPipelineFilter] = useState('All');
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
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
      if (pipelineFilter && pipelineFilter !== 'All') {
        params.pipeline_name = pipelineFilter;
      }
      setSchemaData(await fetchSchema(params));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange, pipelineFilter]);

  useEffect(() => { loadData(); }, [loadData]);

  const availablePipelines = useMemo(() => {
    const names = new Set();
    pipelineOptions.forEach(p => {
      const n = p.pipeline_name || p.name;
      if (n) names.add(n);
    });
    return Array.from(names).sort();
  }, [pipelineOptions]);

  const kpi = useMemo(() => kpiMapFrom(schemaData?.kpis), [schemaData]);
  const changes = Number(kpi.schema_changes?.value ?? schemaData?.summary?.changes ?? 0);
  const breaking = Number(kpi.breaking_changes?.value ?? schemaData?.summary?.breaking ?? 0);
  const events = schemaData?.items || [];
  const meta = schemaData?.meta;

  const filtersDirty = Boolean(search || (pipelineFilter && pipelineFilter !== 'All'));
  const filtered = useMemo(() => events.filter((ev) => {
    if (!search) return true;
    const hay = [ev.table_name, ev.column_name, ev.change_type, ev.impact].join(' ').toLowerCase();
    return hay.includes(search.toLowerCase());
  }), [events, search]);

  const filteredChanges = filtered.length;
  const filteredBreaking = filtered.filter(ev => String(ev.impact || '').toLowerCase() === 'breaking').length;

  const displayChanges = filtersDirty ? filteredChanges : changes;
  const displayBreaking = filtersDirty ? filteredBreaking : breaking;

  const impactChart = useMemo(() => {
    if (filtersDirty) {
      return [
        { name: 'non breaking', count: Math.max(0, displayChanges - displayBreaking) },
        { name: 'breaking', count: displayBreaking },
      ];
    }
    const rows = schemaData?.charts?.by_impact;
    if (Array.isArray(rows) && rows.length) {
      return rows.map(r => ({
        name: String(r.impact || 'other').replace(/_/g, ' '),
        count: r.count ?? 0,
      }));
    }
    return [
      { name: 'non breaking', count: Math.max(0, changes - breaking) },
      { name: 'breaking', count: breaking },
    ];
  }, [filtersDirty, displayChanges, displayBreaking, schemaData, changes, breaking]);

  return (
    <div className="fade-in">
      <PageHeader
        title="Schema"
        subtitle="Did any columns get added, removed, or change type?"
        onRefresh={loadData}
        onDateChange={(v) => handleDateChange(setHeaderDatePreset, setCustomDateRange, v)}
      />

      <div className="page-body">
        {loading ? <DashboardPageSkeleton kpiCount={3} chartCount={0} tableRows={6} tableCols={5} /> : (
          <>
            {displayBreaking > 0 ? (
              <div className="obs-alert is-bad">
                <AlertTriangle size={18} />
                <div>
                  <strong>{displayBreaking} breaking change{displayBreaking === 1 ? '' : 's'}.</strong>
                  {' '}These can break dashboards or downstream jobs.
                </div>
              </div>
            ) : displayChanges > 0 ? (
              <div className="obs-alert is-warn">
                <Layout size={18} />
                <div>
                  <strong>{displayChanges} schema change{displayChanges === 1 ? '' : 's'} found.</strong>
                  {' '}Review the history list below.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div>
                  <strong>No schema changes.</strong>
                  {' '}Compatibility {dash(kpi.compatibility?.display)} across {dash(kpi.schemas_monitored?.display)} monitored schemas.
                </div>
              </div>
            )}

            <div className="obs-insight">
              <Info size={15} />
              <div>
                <strong>How schema drift is detected</strong>
                <span>
                  {meta?.formula
                    ? 'Compares TARGET columns between the latest two successful runs. Column add = non-breaking; drop or type change = breaking.'
                    : 'Compares schema between successful pipeline runs.'}
                  {meta?.available === false ? ' Schema monitoring is marked unavailable by the API.' : ''}
                </span>
              </div>
            </div>

            <div className="filters-bar">
              <div className="search-box">
                <Search size={14} />
                <input
                  placeholder="Search table or column…"
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
                  {availablePipelines.map(name => (
                    <option key={name} value={name}>{name}</option>
                  ))}
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
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>

            <div className="kpi-grid-4">
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#ECFDF5', color: '#10B981' }}><CheckCircle size={18} /></div>
                  <span className="kpi-label">Compatibility</span>
                </div>
                <div className="kpi-value" style={{ color: '#10B981' }}>{dash(kpi.compatibility?.display)}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#EFF6FF', color: '#3B82F6' }}><Layers size={18} /></div>
                  <span className="kpi-label">Schemas monitored</span>
                </div>
                <div className="kpi-value">{dash(kpi.schemas_monitored?.display)}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#F59E0B' }}><Layout size={18} /></div>
                  <span className="kpi-label">Changes found</span>
                </div>
                <div className="kpi-value">{dash(displayChanges)}</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-card-header">
                  <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}><AlertTriangle size={18} /></div>
                  <span className="kpi-label">Breaking changes</span>
                </div>
                <div className="kpi-value" style={{ color: displayBreaking ? '#EF4444' : '#10B981' }}>
                  {dash(displayBreaking)}
                </div>
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Impact breakdown</span>
                  <span className="card-subtitle">Breaking vs non-breaking from schema charts</span>
                </div>
              </div>
              <div style={{ height: 180 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={impactChart} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Bar dataKey="count" fill="#6366F1" radius={[4, 4, 0, 0]} name="Events" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Change history</span>
                  <span className="card-subtitle">Column / type changes for this time range</span>
                </div>
              </div>

              {filtered.length === 0 ? (
                <div className="obs-simple-empty" style={{ padding: '40px 16px' }}>
                  <CheckCircle size={28} style={{ color: '#10B981', marginBottom: 10 }} />
                  <div style={{ fontWeight: 650, color: 'var(--text-primary)', marginBottom: 4 }}>
                    {events.length === 0 ? 'Zero schema drift detected' : 'No matches'}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', maxWidth: 460, margin: '0 auto' }}>
                    {events.length === 0
                      ? `All ${dash(kpi.schemas_monitored?.display)} monitored schemas are in ${dash(kpi.compatibility?.display)} compatibility. When a column is added, removed, or mutates type between successful pipeline runs, it will be automatically recorded here.`
                      : 'Try a different search query.'}
                  </div>
                </div>
              ) : (
                <div className="table-wrapper">
                  <table className="vithi-table">
                    <thead>
                      <tr>
                        <th>Table</th>
                        <th>What changed</th>
                        <th>Column</th>
                        <th>Impact</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((ev, i) => (
                        <tr key={ev.id || i}>
                          <td style={{ fontWeight: 600 }}>{dash(ev.table_name)}</td>
                          <td><span className="tag">{dash(ev.change_type)}</span></td>
                          <td>{dash(ev.column_name)}</td>
                          <td>
                            <span className={`status-pill ${String(ev.impact).toLowerCase() === 'breaking' ? 'critical' : 'warning'}`}>
                              {dash(ev.impact)}
                            </span>
                          </td>
                          <td>{dash(ev.detected_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
