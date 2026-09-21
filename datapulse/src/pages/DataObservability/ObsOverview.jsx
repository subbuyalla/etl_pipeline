import { useEffect, useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Clock, BarChart2, Shield, Layers, ChevronRight, AlertTriangle, CheckCircle, Network,
} from 'lucide-react';
import {
  BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import PageHeader from '../../components/PageHeader';
import LoadingSpinner from '../../components/LoadingSpinner';
import { ObservabilityDashboardSkeleton } from '../../components/SkeletonLoaders';
import {
  fetchOverviewHealth,
  fetchFreshness,
  fetchVolume,
  fetchDataQuality,
  fetchSchema,
} from '../../api/client';
import {
  dash, kpiMapFrom, statusTone, buildDateParams, handleDateChange, TOOLTIP_STYLE,
} from './obsUtils';

const PILLARS = [
  { id: 'freshness', name: 'Freshness', path: '/observability/freshness', Icon: Clock, help: 'Is data arriving on time?' },
  { id: 'volume', name: 'Volume', path: '/observability/volume', Icon: BarChart2, help: 'Are row counts normal?' },
  { id: 'data_quality', name: 'Data Quality', path: '/observability/data-quality', Icon: Shield, help: 'Are tests and checks passing?' },
  { id: 'schema', name: 'Schema', path: '/observability/schema', Icon: Layers, help: 'Did columns or types change?' },
  { id: 'lineage', name: 'Lineage', path: '/observability/lineage', Icon: Network, help: 'Visual DAG & dependencies' },
];

export default function ObsOverview() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState([]);
  const [freshness, setFreshness] = useState(null);
  const [volume, setVolume] = useState(null);
  const [quality, setQuality] = useState(null);
  const [schema, setSchema] = useState(null);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const params = buildDateParams(headerDatePreset, customDateRange);
      const [h, f, v, q, s] = await Promise.allSettled([
        fetchOverviewHealth(params),
        fetchFreshness(params),
        fetchVolume(params),
        fetchDataQuality(params),
        fetchSchema(params),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value?.pillars || h.value?.health || h.value?.items || []);
      if (f.status === 'fulfilled') setFreshness(f.value);
      if (v.status === 'fulfilled') setVolume(v.value);
      if (q.status === 'fulfilled') setQuality(q.value);
      if (s.status === 'fulfilled') setSchema(s.value);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange]);

  useEffect(() => { loadData(); }, [loadData]);

  const byId = useMemo(() => {
    const map = {};
    health.forEach(p => {
      if (!p?.id) return;
      map[p.id] = p;
      if (p.id === 'data_quality') map['quality'] = p;
      if (p.id === 'quality') map['data_quality'] = p;
    });
    return map;
  }, [health]);

  const fKpi = useMemo(() => kpiMapFrom(freshness?.kpis), [freshness]);
  const vKpi = useMemo(() => kpiMapFrom(volume?.kpis), [volume]);
  const qKpi = useMemo(() => kpiMapFrom(quality?.kpis), [quality]);
  const sKpi = useMemo(() => kpiMapFrom(schema?.kpis), [schema]);

  const problems = PILLARS
    .map(p => ({ ...p, pillar: byId[p.id] }))
    .filter(p => p.pillar && statusTone(p.pillar.status) === 'crit');

  const volumeTrend = useMemo(() => (
    (volume?.series?.volume_over_time || []).map(p => ({
      time: p.timestamp || p.time || '',
      records: p.records ?? 0,
    }))
  ), [volume]);

  const dimensionList = useMemo(() => {
    const byDim = quality?.charts?.by_dimension || quality?.summary?.by_dimension;
    if (!byDim) return [];
    return Object.entries(byDim).map(([k, v]) => ({
      name: k.charAt(0).toUpperCase() + k.slice(1),
      passed: v.passed ?? 0,
      warn: v.warn ?? 0,
      failed: v.failed ?? 0,
    }));
  }, [quality]);

  const staleRows = (freshness?.items || []).filter(i => statusTone(i.status_key || i.status) === 'crit');

  return (
    <div className="fade-in">
      <PageHeader
        title="Data Observability"
        subtitle="Check if your data is on time, complete, correct, and structurally stable."
        onRefresh={loadData}
        onDateChange={(v) => handleDateChange(setHeaderDatePreset, setCustomDateRange, v)}
      />

      <div className="page-body">
        {loading ? <ObservabilityDashboardSkeleton kpiCount={4} hasPillars={true} /> : (
          <>
            {problems.length > 0 ? (
              <div className="obs-alert is-bad">
                <AlertTriangle size={18} />
                <div>
                  <strong>Needs attention:</strong>{' '}
                  {problems.map(p => p.name).join(', ')}.
                  {' '}Open the pillar below to see which pipelines are affected.
                </div>
              </div>
            ) : (
              <div className="obs-alert is-ok">
                <CheckCircle size={18} />
                <div>
                  <strong>Looking good.</strong> No critical pillar issues in this time range.
                </div>
              </div>
            )}

            <div className="kpi-grid-5">
              {PILLARS.map(({ id, name, path, Icon, help }) => {
                const p = byId[id] || {};
                const tone = statusTone(p.status);
                let detail = '—';
                if (id === 'freshness') detail = `Avg lag ${dash(fKpi.avg_lag?.display)}`;
                if (id === 'volume') detail = `${dash(vKpi.records_received?.display)} records`;
                if (id === 'data_quality') detail = `${dash(qKpi.passed?.display)}/${dash(qKpi.checks_run?.display)} checks pass`;
                if (id === 'schema') detail = `${dash(sKpi.compatibility?.display)} compatible`;
                if (id === 'lineage') detail = 'Visual DAG & relations';

                return (
                  <button
                    key={id}
                    type="button"
                    className="kpi-card interactive-card obs-pillar-btn"
                    onClick={() => navigate(path)}
                  >
                    <div className="kpi-card-header">
                      <div className="kpi-icon" style={{ background: '#F1F5F9', color: '#475569' }}>
                        <Icon size={18} />
                      </div>
                      <span className="kpi-label">{name}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                      <div className="kpi-value">{dash(p.display)}</div>
                      <span className={`status-pill ${tone === 'good' ? 'good' : tone === 'warn' ? 'warning' : tone === 'crit' ? 'critical' : 'info'}`}>
                        {dash(p.status)}
                      </span>
                    </div>
                    <div className="kpi-delta" style={{ marginTop: 4 }}>
                      <span>{help}</span>
                    </div>
                    <div className="obs-pillar-detail">
                      {detail} <ChevronRight size={13} />
                    </div>
                  </button>
                );
              })}
            </div>

            {staleRows.length > 0 && (
              <div className="card mt-4">
                <div className="card-header">
                  <div>
                    <span className="card-title">Late data (Freshness)</span>
                    <span className="card-subtitle">Pipelines that missed their update SLA</span>
                  </div>
                  <button type="button" className="export-btn" onClick={() => navigate('/observability/freshness')}>
                    Open Freshness <ChevronRight size={13} />
                  </button>
                </div>
                <div className="table-wrapper">
                  <table className="vithi-table">
                    <thead>
                      <tr>
                        <th>Pipeline</th>
                        <th>Status</th>
                        <th>How late</th>
                        <th>Allowed SLA</th>
                        <th>Last update</th>
                      </tr>
                    </thead>
                    <tbody>
                      {staleRows.map(row => (
                        <tr key={row.pipeline_id || row.pipeline_name}>
                          <td style={{ fontWeight: 600 }}>{dash(row.pipeline_name)}</td>
                          <td><span className="status-pill critical">{dash(row.status)}</span></td>
                          <td style={{ fontWeight: 700, color: '#DC2626' }}>{dash(row.current_lag_display)}</td>
                          <td>{row.sla_hours != null ? `${row.sla_hours}h` : '—'}</td>
                          <td>{dash(row.last_updated_age || row.last_updated_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="grid-2 mt-4" style={{ gap: 16 }}>
              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Records over time</span>
                    <span className="card-subtitle">Volume from the API</span>
                  </div>
                  <button type="button" className="export-btn" onClick={() => navigate('/observability/volume')}>
                    Open Volume <ChevronRight size={13} />
                  </button>
                </div>
                {volumeTrend.length === 0 ? (
                  <div className="obs-simple-empty">No volume history for this range.</div>
                ) : (
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={volumeTrend} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                        <Tooltip {...TOOLTIP_STYLE} />
                        <Area type="monotone" dataKey="records" stroke="#3B82F6" fill="#DBEAFE" strokeWidth={2} name="Records" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              <div className="card">
                <div className="card-header">
                  <div>
                    <span className="card-title">Quality by dimension</span>
                    <span className="card-subtitle">Passed / warning / failed checks</span>
                  </div>
                  <button type="button" className="export-btn" onClick={() => navigate('/observability/data-quality')}>
                    Open Quality <ChevronRight size={13} />
                  </button>
                </div>
                {dimensionList.length === 0 ? (
                  <div className="obs-simple-empty">No quality breakdown yet.</div>
                ) : (
                  <div style={{ height: 200 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dimensionList} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                        <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                        <Tooltip {...TOOLTIP_STYLE} />
                        <Bar dataKey="passed" stackId="a" fill="#10B981" name="Passed" />
                        <Bar dataKey="warn" stackId="a" fill="#F59E0B" name="Warning" />
                        <Bar dataKey="failed" stackId="a" fill="#EF4444" name="Failed" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>

            <div className="card mt-4">
              <div className="card-header">
                <div>
                  <span className="card-title">Schema status</span>
                  <span className="card-subtitle">
                    Compatibility {dash(sKpi.compatibility?.display)} · Monitored {dash(sKpi.schemas_monitored?.display)} · Changes {dash(sKpi.schema_changes?.display)}
                  </span>
                </div>
                <button type="button" className="export-btn" onClick={() => navigate('/observability/schema')}>
                  Open Schema <ChevronRight size={13} />
                </button>
              </div>
              <div className="obs-simple-empty" style={{ paddingTop: 20, paddingBottom: 24 }}>
                {Number(sKpi.schema_changes?.value || 0) === 0
                  ? 'No column or type changes in this time range.'
                  : `${sKpi.schema_changes.display} schema change(s) found — open Schema for details.`}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
