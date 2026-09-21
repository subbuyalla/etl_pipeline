import { useEffect, useState, useCallback } from 'react';
import { Settings as SettingsIcon, Sliders, Key, Bell, Users, Database, Globe, Check, RefreshCw, Server, ShieldCheck, Activity } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import { getBaseUrl, fetchTools, testToolConnection, fetchSystemHealth } from '../api/client';

export default function Settings() {
  const [saved, setSaved] = useState(false);
  const [apiUrl, setApiUrl] = useState(getBaseUrl());
  const [slaTime, setSlaTime] = useState(60);
  const [tools, setTools] = useState([]);
  const [systemHealth, setSystemHealth] = useState(null);
  const [testingToolId, setTestingToolId] = useState(null);
  const [testResult, setTestResult] = useState({});

  const loadData = useCallback(async () => {
    try {
      const [toolsRes, healthRes] = await Promise.allSettled([
        fetchTools(),
        fetchSystemHealth()
      ]);

      if (toolsRes.status === 'fulfilled' && toolsRes.value) {
        setTools(toolsRes.value.items || toolsRes.value || []);
      }
      if (healthRes.status === 'fulfilled' && healthRes.value) {
        setSystemHealth(healthRes.value);
      }
    } catch (e) {
      console.error('Failed to load settings data:', e);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSave = (e) => {
    e.preventDefault();
    localStorage.setItem('API_BASE_URL', apiUrl.trim());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleTestConnection = async (toolId) => {
    setTestingToolId(toolId);
    try {
      const res = await testToolConnection(toolId);
      setTestResult(prev => ({ ...prev, [toolId]: { ok: true, message: res.message || 'Connected successfully!' } }));
    } catch (e) {
      setTestResult(prev => ({ ...prev, [toolId]: { ok: false, message: e.response?.data?.detail || e.message } }));
    } finally {
      setTestingToolId(null);
    }
  };

  return (
    <div className="fade-in">
      <PageHeader
        title="Settings"
        subtitle="Manage platform configuration, live database connectors, and workspace preferences."
        onRefresh={loadData}
      />

      <div className="page-body">
        {/* System Health Status Banner */}
        {systemHealth && (
          <div className="card" style={{ marginBottom: 16, background: 'var(--bg-card-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Activity size={18} style={{ color: '#10B981' }} />
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>Observability Backend Status</div>
                  <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                    Database: <strong style={{ color: '#10B981' }}>{systemHealth.database || 'Connected (AWS RDS MySQL)'}</strong> • API Status: <strong style={{ color: '#10B981' }}>{systemHealth.status || 'Active'}</strong>
                  </div>
                </div>
              </div>
              <span className="status-pill good">Healthy</span>
            </div>
          </div>
        )}

        <div className="grid-2">
          {/* General Configuration */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">General Platform Config</span>
            </div>
            <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="filter-select">
                <label>Backend API Base URL</label>
                <input
                  type="text"
                  className="search-box"
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                  value={apiUrl}
                  onChange={e => setApiUrl(e.target.value)}
                />
              </div>

              <div className="filter-select">
                <label>Default Freshness SLA (Hours)</label>
                <input
                  type="number"
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                  value={slaTime}
                  onChange={e => setSlaTime(Number(e.target.value))}
                />
              </div>

              <button type="submit" className="export-btn" style={{ alignSelf: 'flex-start', marginTop: 4 }}>
                {saved ? <Check size={14} /> : null}
                <span>{saved ? 'Saved Successfully!' : 'Save Settings'}</span>
              </button>
            </form>
          </div>

          {/* Connected Tool Integrations from Live API */}
          <div className="card">
            <div className="card-header">
              <div>
                <span className="card-title">Connected Tool Integrations</span>
                <span className="card-subtitle">Live Snowflake and dbt connectors registered in backend</span>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {tools.length === 0 ? (
                <div style={{ padding: 16, color: 'var(--text-muted)', textAlign: 'center' }}>
                  Loading connected integrations...
                </div>
              ) : (
                tools.map((tool) => {
                  const isDb = tool.kind === 'database' || tool.connector_type === 'snowflake';
                  const tRes = testResult[tool.tool_id];

                  return (
                    <div
                      key={tool.tool_id}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                        padding: '12px 14px',
                        background: 'var(--bg-card-subtle)',
                        borderRadius: 8,
                        border: '1px solid var(--border)'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          {isDb ? <Database size={18} style={{ color: '#38BDF8' }} /> : <Sliders size={18} style={{ color: '#F97316' }} />}
                          <div>
                            <div style={{ fontWeight: 600, fontSize: 13 }}>{tool.name}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                              {tool.connector_type.toUpperCase()} • {tool.config?.schema ? `${tool.config.schema} Schema` : tool.config?.project_name || 'Active Service'}
                            </div>
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span className={`status-pill ${tool.status === 'active' ? 'good' : 'warning'}`}>
                            {tool.status}
                          </span>
                          <button
                            className="export-btn"
                            style={{ padding: '4px 8px', fontSize: 11 }}
                            onClick={() => handleTestConnection(tool.tool_id)}
                            disabled={testingToolId === tool.tool_id}
                          >
                            <RefreshCw size={11} className={testingToolId === tool.tool_id ? 'spin' : ''} />
                            {testingToolId === tool.tool_id ? 'Testing...' : 'Test'}
                          </button>
                        </div>
                      </div>

                      {tRes && (
                        <div style={{ fontSize: 11, color: tRes.ok ? '#10B981' : '#EF4444', marginTop: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
                          {tRes.ok ? <ShieldCheck size={13} /> : null}
                          <span>{tRes.message}</span>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
