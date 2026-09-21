import { useEffect, useState, useMemo, useCallback } from 'react';
import { Database, Search, Shield, Clock, Layers, Table, HardDrive, RefreshCw } from 'lucide-react';
import PageHeader from '../../components/PageHeader';
import LoadingSpinner from '../../components/LoadingSpinner';
import { fetchAssets } from '../../api/client';
import { formatBytes, statusTone } from './obsUtils';

export default function Assets() {
  const [assets, setAssets] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('All');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAssets();
      setAssets(Array.isArray(res?.items) ? res.items : []);
      setKpis(res?.kpis || []);
    } catch (e) {
      console.error('Failed to load assets catalog:', e);
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredAssets = useMemo(() => {
    return assets.filter(a => {
      if (typeFilter !== 'All' && (a.asset_type || '').toLowerCase() !== typeFilter.toLowerCase()) {
        return false;
      }
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      const hay = [
        a.dataset_id,
        a.pipeline_id,
        a.asset_type,
        a.freshness_status,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(q);
    });
  }, [assets, search, typeFilter]);

  const types = useMemo(() => {
    const set = new Set(assets.map(a => a.asset_type).filter(Boolean));
    return ['All', ...Array.from(set)];
  }, [assets]);

  const totalRows = useMemo(() => {
    return assets.reduce((sum, a) => sum + (Number(a.row_count) || 0), 0);
  }, [assets]);

  const totalBytes = useMemo(() => {
    return assets.reduce((sum, a) => sum + (Number(a.byte_size) || 0), 0);
  }, [assets]);

  const healthyCount = useMemo(() => {
    return assets.filter(a => (a.freshness_status || '').toLowerCase() === 'fresh' || Number(a.quality_score || 0) >= 90).length;
  }, [assets]);

  return (
    <div className="fade-in">
      <PageHeader
        title="Assets Catalog"
        subtitle="Canonical datasets, tables, and warehouses observed across your data estate."
        onRefresh={loadData}
      />

      <div className="page-body">
        <div className="kpi-grid-4">
          <div className="kpi-card">
            <div className="kpi-label">Monitored Assets</div>
            <div className="kpi-value" style={{ color: '#6366F1', marginTop: 4 }}>
              {assets.length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Canonical datasets</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Total Records</div>
            <div className="kpi-value" style={{ color: '#10B981', marginTop: 4 }}>
              {totalRows.toLocaleString()}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Aggregated row count</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Total Volume</div>
            <div className="kpi-value" style={{ color: '#3B82F6', marginTop: 4 }}>
              {formatBytes(totalBytes)}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Storage footprint</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Healthy Datasets</div>
            <div className="kpi-value" style={{ color: '#10B981', marginTop: 4 }}>
              {healthyCount} / {assets.length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Fresh & passing checks</div>
          </div>
        </div>

        <div className="card mt-4">
          <div className="card-header">
            <div>
              <span className="card-title">Dataset Health & Inventory</span>
              <span className="card-subtitle">Tables and views synchronized from warehouses and ETL pipelines</span>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <div className="search-box" style={{ width: 220 }}>
                <Search size={14} style={{ color: 'var(--text-muted)', marginLeft: 8 }} />
                <input
                  type="text"
                  placeholder="Search datasets…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  style={{ width: '100%', border: 'none', background: 'transparent', padding: '6px 10px', fontSize: 12 }}
                />
              </div>
              <select
                value={typeFilter}
                onChange={e => setTypeFilter(e.target.value)}
                className="select-control"
                style={{ fontSize: 12, padding: '4px 8px' }}
              >
                {types.map(t => (
                  <option key={t} value={t}>{t === 'All' ? 'All Types' : t.toUpperCase()}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="table-wrapper">
            <table className="vithi-table">
              <thead>
                <tr>
                  <th>Dataset / Table</th>
                  <th>Type</th>
                  <th>Pipeline</th>
                  <th>Row Count</th>
                  <th>Size</th>
                  <th>Freshness</th>
                  <th>Quality Score</th>
                  <th>Last Synced</th>
                </tr>
              </thead>
              <tbody>
                {loading && assets.length === 0 ? (
                  Array.from({ length: 6 }).map((_, r) => (
                    <tr key={r}>
                      {Array.from({ length: 8 }).map((_, c) => (
                        <td key={c} style={{ padding: '14px 12px' }}>
                          <div className="skeleton-box" style={{ height: 16, width: c === 0 ? 140 : c === 1 ? 80 : 60, opacity: 0.7 }} />
                        </td>
                      ))}
                    </tr>
                  ))
                ) : filteredAssets.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                      No canonical assets registered yet. Trigger a sync in Integrations to populate assets.
                    </td>
                  </tr>
                ) : filteredAssets.map(a => {
                  const fTone = statusTone(a.freshness_status);
                  const qScore = a.quality_score != null ? Number(a.quality_score) : null;
                  return (
                    <tr key={a.asset_id || a.dataset_id}>
                      <td style={{ fontWeight: 600, fontFamily: 'monospace' }}>
                        <Database size={13} style={{ display: 'inline', marginRight: 6, color: '#6366F1' }} />
                        {a.dataset_id}
                      </td>
                      <td>
                        <span className="status-pill neutral" style={{ fontSize: 10.5 }}>
                          {(a.asset_type || 'table').toUpperCase()}
                        </span>
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {a.pipeline_id || '—'}
                      </td>
                      <td style={{ fontWeight: 500 }}>
                        {a.row_count != null ? Number(a.row_count).toLocaleString() : '—'}
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                        {formatBytes(a.byte_size)}
                      </td>
                      <td>
                        <span className={`status-pill ${fTone === 'good' ? 'good' : fTone === 'crit' ? 'critical' : 'warning'}`}>
                          {a.freshness_status || 'Unknown'}
                        </span>
                      </td>
                      <td>
                        {qScore != null ? (
                          <span style={{ fontWeight: 600, color: qScore >= 90 ? '#10B981' : qScore >= 75 ? '#F59E0B' : '#EF4444' }}>
                            {qScore}%
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>N/A</span>
                        )}
                      </td>
                      <td style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                        {a.updated_at || a.last_synced_at ? new Date(a.updated_at || a.last_synced_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
