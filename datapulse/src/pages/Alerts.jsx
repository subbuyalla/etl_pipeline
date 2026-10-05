import { useEffect, useState, useMemo, useCallback } from 'react';
import { Bell, Plus, CheckCircle, AlertTriangle, Shield, Trash2, Tag, X, Search, RotateCcw, Database } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { DashboardPageSkeleton } from '../components/SkeletonLoaders';
import { fetchAlerts, fetchPipelines } from '../api/client';

export default function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [liveKpis, setLiveKpis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newAlertName, setNewAlertName] = useState('');
  const [newAlertChannel, setNewAlertChannel] = useState('#data-alerts (Slack)');
  const [newAlertCondition, setNewAlertCondition] = useState('');

  // Filters
  const [search, setSearch] = useState('');
  const [toolFilter, setToolFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [toolOptions, setToolOptions] = useState(['Informatica', 'Snowflake', 'dbt', 'MySQL', 'PostgreSQL']);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAlerts();
      if (res && res.kpis) setLiveKpis(res.kpis);
      setAlerts(Array.isArray(res?.items) ? res.items : []);
    } catch (e) {
      console.error('Failed to load alerts:', e);
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const toggleAlert = (id) => {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, active: !a.active } : a));
  };

  const [alertError, setAlertError] = useState('');

  const handleAddAlert = (e) => {
    e.preventDefault();
    const trimmed = newAlertName.trim();
    if (!trimmed || !newAlertCondition.trim()) return;
    if (alerts.some(a => String(a.name || '').toLowerCase() === trimmed.toLowerCase())) {
      setAlertError(`An alert rule named “${trimmed}” already exists. Alert rule names must be unique.`);
      return;
    }
    const newA = {
      id: Date.now(),
      name: trimmed,
      channel: newAlertChannel,
      condition: newAlertCondition.trim(),
      active: true
    };
    setAlerts(prev => [newA, ...prev]);
    setNewAlertName('');
    setNewAlertCondition('');
    setAlertError('');
    setShowAddModal(false);
  };

  const activeCount = alerts.filter(a => a.active ?? a.is_enabled ?? a.status === 'active').length;
  const kpiMap = useMemo(() => {
    const map = {};
    (liveKpis || []).forEach(k => { if (k?.id) map[k.id] = k; });
    return map;
  }, [liveKpis]);
  const channels = useMemo(() => {
    const set = new Set(alerts.map(a => a.channel || a.notification_channel).filter(Boolean));
    return set.size;
  }, [alerts]);

  const filteredAlerts = useMemo(() => {
    return alerts.filter(a => {
      if (statusFilter !== 'All') {
        const st = String(a.status || 'open').toLowerCase();
        if (st !== statusFilter.toLowerCase()) return false;
      }
      if (toolFilter !== 'All') {
        const hay = [a.tool, a.tool_name, a.source_tool, a.name, a.pipeline_name, a.condition].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(toolFilter.toLowerCase())) return false;
      }
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const hay = [a.name, a.alert_name, a.channel, a.condition, a.pipeline_name, a.severity, a.status].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [alerts, statusFilter, toolFilter, search]);

  const filtersActive = Boolean(search.trim()) || statusFilter !== 'All' || toolFilter !== 'All';

  const clearFilters = () => {
    setSearch('');
    setStatusFilter('All');
    setToolFilter('All');
  };

  if (loading && alerts.length === 0) {
    return (
      <div className="fade-in">
        <PageHeader title="Alerts" subtitle="Configure and manage pipeline health alerts." onRefresh={loadData} />
        <div className="page-body">
          <DashboardPageSkeleton kpiCount={4} chartCount={0} tableRows={6} tableCols={5} />
        </div>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <PageHeader
        title="Alerts"
        subtitle="Configure and manage pipeline health alerts, incident paging, and notification channels."
        onRefresh={loadData}
      />

      <div className="page-body">
        <div className="kpi-grid-4">
          <div className="kpi-card">
            <div className="kpi-label">Open Alerts</div>
            <div className="kpi-value" style={{ color: '#EF4444', marginTop: 4 }}>
              {kpiMap.open_alerts?.display ?? kpiMap.open?.display ?? alerts.filter(a => (a.status || 'open') === 'open').length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Pending triage</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Critical Severity</div>
            <div className="kpi-value" style={{ color: '#DC2626', marginTop: 4 }}>
              {kpiMap.critical_alerts?.display ?? kpiMap.critical?.display ?? alerts.filter(a => String(a.severity || '').toLowerCase() === 'critical').length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Requires immediate action</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Acknowledged</div>
            <div className="kpi-value" style={{ color: '#F59E0B', marginTop: 4 }}>
              {kpiMap.acked_alerts?.display ?? kpiMap.acked?.display ?? alerts.filter(a => a.status === 'acked').length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Under investigation</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">Resolved (24h)</div>
            <div className="kpi-value" style={{ color: '#10B981', marginTop: 4 }}>
              {kpiMap.resolved_alerts?.display ?? kpiMap.resolved?.display ?? alerts.filter(a => a.status === 'resolved').length}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Mitigated</div>
          </div>
        </div>

        <div className="card mt-4">
          <div className="card-header">
            <div>
              <span className="card-title">Live Observability Alerts</span>
              <span className="card-subtitle">Triggered anomalies, threshold breaches, and grouped alerts</span>
            </div>
            <button className="export-btn" onClick={() => setShowAddModal(true)} style={{ padding: '6px 12px', fontSize: 12 }}>
              <Plus size={13} /> Add Alert Rule
            </button>
          </div>

          <div className="filters-bar" style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)' }}>
            <div className="search-box">
              <Search size={14} />
              <input
                placeholder="Search alerts, channels, conditions…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <div className="filter-select">
              <label>Connection / Tool</label>
              <select
                className="select-control"
                value={toolFilter}
                onChange={e => setToolFilter(e.target.value)}
                title="Filter alerts by connection or tool (Informatica, Snowflake, dbt, etc.)"
              >
                <option value="All">All Connections</option>
                {toolOptions.map(t => (
                  <option key={t} value={t}>{t}</option>
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
                <option value="All">All Statuses</option>
                <option value="open">Open</option>
                <option value="acked">Acknowledged</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
            {filtersActive && (
              <button type="button" className="export-btn" style={{ marginLeft: 'auto' }} onClick={clearFilters}>
                <RotateCcw size={12} style={{ display: 'inline', marginRight: 4 }} />
                Clear filters
              </button>
            )}
          </div>

          <div className="table-wrapper">
            <table className="vithi-table">
              <thead>
                <tr>
                  <th>Alert Name</th>
                  <th>Severity</th>
                  <th>Pipeline / Target</th>
                  <th>Group ID</th>
                  <th>Triggered</th>
                  <th>Status</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredAlerts.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', padding: 28, color: 'var(--text-muted)' }}>
                      {filtersActive ? 'No alerts match the selected filters.' : 'No active alerts in the selected window.'}
                    </td>
                  </tr>
                ) : filteredAlerts.map(a => {
                  const s = String(a.status || 'open').toLowerCase();
                  const sev = String(a.severity || 'info').toLowerCase();
                  const sevTone = sev === 'critical' ? 'critical' : (sev === 'high' || sev === 'medium') ? 'warning' : 'info';
                  return (
                    <tr key={a.id || a.alert_id || a.name}>
                      <td style={{ fontWeight: 600 }}>{a.alert_name || a.name || '—'}</td>
                      <td>
                        <span className={`status-pill ${sevTone}`}>
                          {(a.severity || 'Info').toUpperCase()}
                        </span>
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {a.pipeline_name || a.pipeline_id || a.dataset_id || '—'}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)' }}>
                        {a.alert_group_id ? a.alert_group_id.slice(0, 8) + '…' : '—'}
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {a.triggered_at ? new Date(a.triggered_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                      </td>
                      <td>
                        <span className={`status-pill ${s === 'resolved' ? 'good' : s === 'acked' ? 'warning' : 'critical'}`}>
                          {s.toUpperCase()}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="export-btn"
                          style={{ padding: '3px 8px', fontSize: 11 }}
                          onClick={() => toggleAlert(a.id || a.alert_id)}
                        >
                          {s === 'resolved' ? 'Reopen' : 'Acknowledge'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Add Alert Modal */}
        {showAddModal && (
          <div className="modal-backdrop" onClick={() => setShowAddModal(false)}>
            <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
              <div className="modal-header">
                <span style={{ fontWeight: 600, fontSize: 15 }}>Create Alert Rule</span>
                <button className="icon-btn" onClick={() => setShowAddModal(false)}><X size={16} /></button>
              </div>
              <form onSubmit={handleAddAlert} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {alertError && (
                  <div style={{ padding: '8px 12px', borderRadius: 6, background: 'var(--danger-dim)', color: 'var(--danger-text)', border: '1px solid var(--danger-border)', fontSize: 12 }}>
                    ⚠️ {alertError}
                  </div>
                )}
                <div className="filter-select">
                  <label>Alert Rule Name</label>
                  <input
                    type="text"
                    placeholder="e.g., Critical Freshness SLA Breach"
                    value={newAlertName}
                    onChange={e => setNewAlertName(e.target.value)}
                    required
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                  />
                </div>

                <div className="filter-select">
                  <label>Trigger Condition</label>
                  <input
                    type="text"
                    placeholder="e.g., Freshness lag > 2 hours or DQ failure > 0"
                    value={newAlertCondition}
                    onChange={e => setNewAlertCondition(e.target.value)}
                    required
                    style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                  />
                </div>

                <div className="filter-select">
                  <label>Notification Channel</label>
                  <select
                    value={newAlertChannel}
                    onChange={e => setNewAlertChannel(e.target.value)}
                    className="select-control"
                    style={{ width: '100%' }}
                  >
                    <option value="#data-alerts (Slack)">#data-alerts (Slack)</option>
                    <option value="#data-governance (Slack)">#data-governance (Slack)</option>
                    <option value="PagerDuty">PagerDuty (On-Call High Priority)</option>
                    <option value="email: datateam@vithi.dev">Email Digest</option>
                  </select>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
                  <button type="button" className="export-btn" onClick={() => setShowAddModal(false)}>Cancel</button>
                  <button type="submit" className="export-btn" style={{ background: 'var(--accent)', color: '#FFFFFF', border: 'none' }}>Create Alert</button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
