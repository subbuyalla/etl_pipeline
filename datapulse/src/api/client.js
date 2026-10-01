import axios from 'axios';

export const getBaseUrl = () => {
  if (typeof window !== 'undefined') {
    const custom = localStorage.getItem('API_BASE_URL');
    if (custom) {
      // If user is browsing on HTTPS and entered an insecure HTTP remote URL,
      // route via relative proxy to prevent browser mixed content blocking
      if (window.location.protocol === 'https:' && custom.startsWith('http://') && !custom.includes('localhost')) {
        return '';
      }
      return custom;
    }
  }
  // Always use relative paths; Vite (local) / Vercel (prod) proxy via API_BACKEND_URL
  return '';
};

const api = axios.create({
  baseURL: getBaseUrl(),
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  config.baseURL = getBaseUrl();
  const tenant = (typeof window !== 'undefined' && localStorage.getItem('TENANT_ID')) || 'demo';
  config.headers = config.headers || {};
  config.headers['X-Tenant-Id'] = tenant;
  return config;
});

// In-memory client cache for instant route switches (serves cache until user clicks Refresh)
const clientCache = new Map();

export const getCachedData = (key) => {
  const hit = clientCache.get(key);
  if (!hit) return null;
  // Keep cache valid until user explicitly clicks Refresh (or 10 min fallback)
  if (Date.now() - hit.time < 600000) {
    return hit.data;
  }
  return null;
};

export const setCachedData = (key, data) => {
  if (data) {
    clientCache.set(key, { time: Date.now(), data });
  }
};

export const clearClientCache = () => {
  clientCache.clear();
};

// Helper for resilient GET requests with universal client-side caching
const safeGet = async (path, fallbackPath, params = {}, options = {}) => {
  const queryParts = Object.entries(params || {})
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .sort()
    .join('&');
  const cacheKey = `${path}?${queryParts}`;

  if (!options?.skipCache) {
    const cached = getCachedData(cacheKey);
    if (cached) {
      return cached;
    }
  }

  try {
    const res = await api.get(path, { params });
    setCachedData(cacheKey, res.data);
    return res.data;
  } catch (err) {
    if (err.response && err.response.status === 404 && fallbackPath) {
      const resFallback = await api.get(fallbackPath, { params });
      setCachedData(cacheKey, resFallback.data);
      return resFallback.data;
    }
    // If running on HTTPS directly and axios failed because of base URL, retry with relative path
    if (typeof window !== 'undefined' && window.location.protocol === 'https:' && api.defaults.baseURL !== '') {
      try {
        const resRel = await axios.get(path, { params });
        setCachedData(cacheKey, resRel.data);
        return resRel.data;
      } catch (e2) {
        // pass through
      }
    }
    throw err;
  }
};

// ── Health & System ──────────────────────────────────────────────────────────
export const fetchSystemHealth = () =>
  safeGet('/api/v1/health', '/health');

export const fetchFilters = (params = {}) =>
  safeGet('/api/v1/filters', null, params).catch(() => ({
    ok: false,
    items: [],
    pipelines: [],
  }));

// ── Overview ────────────────────────────────────────────────────────────────
export const fetchOverview = (params = {}) =>
  safeGet('/api/v1/overview', '/v1/dashboard/overview', params);

export const fetchOverviewKPIs = (params = {}) =>
  safeGet('/api/v1/overview/kpis', '/api/overview/kpis', params);

export const fetchOverviewCharts = (params = {}) =>
  safeGet('/api/v1/overview/charts', '/api/overview/charts', params);

export const fetchOverviewHealth = (params = {}) =>
  safeGet('/api/v1/overview/health', '/api/overview/health', params);

export const fetchRecentIncidents = (params = {}) =>
  safeGet('/api/v1/overview/recent-incidents', '/api/overview/recent-incidents', params);

export const fetchPipelineMonitoring = (params = {}) =>
  safeGet('/api/v1/overview/pipelines', '/api/overview/pipeline-monitoring', params);

// ── Pipelines ────────────────────────────────────────────────────────────────
export const fetchPipelines = (params = {}) =>
  safeGet('/api/v1/pipelines', '/api/pipelines', params);

export const fetchPipelineCatalog = (params = {}) =>
  safeGet('/api/v1/pipelines/catalog', null, params);

export const fetchPipelineDetail = (pid) =>
  safeGet(`/api/v1/pipelines/${pid}`, `/api/pipelines/${pid}`);

export const fetchPipelineRuns = (pid, params = {}) =>
  safeGet(`/api/v1/pipelines/${pid}/runs`, `/api/pipelines/${pid}/runs`, params);

export const fetchPipelineBindings = (pid) =>
  safeGet(`/api/v1/pipelines/${pid}/bindings`, null);

export const fetchPipelineMonitors = (pid) =>
  safeGet(`/api/v1/pipelines/${pid}/monitors`, `/v1/monitors?pipeline_id=${pid}`);

// ── Data Observability ───────────────────────────────────────────────────────
export const fetchAssets = (params = {}) =>
  safeGet('/api/v1/observability/assets', '/api/v1/assets', params);

export const fetchFreshness = (params = {}) =>
  safeGet('/api/v1/observability/freshness', '/api/observability/freshness', params);

export const fetchVolume = (params = {}) =>
  safeGet('/api/v1/observability/volume', '/api/observability/volume', params);

export const fetchSchema = (params = {}) =>
  safeGet('/api/v1/observability/schema', '/api/observability/schema', params);

export const fetchDataQuality = (params = {}) =>
  safeGet('/api/v1/observability/quality', '/api/observability/data-quality', params);

export const fetchMetrics = (params = {}) =>
  safeGet('/api/v1/metrics', '/api/observability/metrics', params);

// ── Lineage ──────────────────────────────────────────────────────────────────
export const fetchLineage = (params = {}) =>
  safeGet('/api/v1/lineage', '/api/lineage', params);

export const fetchLineageDetail = (pid, params = {}) =>
  safeGet(`/api/v1/lineage/${pid}`, null, params);

// ── Incidents ────────────────────────────────────────────────────────────────
export const fetchIncidents = (params = {}) =>
  safeGet('/api/v1/incidents', '/api/incidents', params);

export const fetchIncidentDetail = (id) =>
  safeGet(`/api/v1/incidents/${id}`, null);

// ── Logs & RCA ───────────────────────────────────────────────────────────────
export const fetchLogs = (params = {}) =>
  safeGet('/api/v1/logs', '/api/logs', params);

export const fetchRunDetail = (runId) =>
  safeGet(`/api/v1/runs/${runId}`, `/api/runs/${runId}`);

export const fetchRcaContext = (runId) =>
  safeGet(`/api/v1/runs/${runId}/rca-context`, null);

// ── Alerts & Monitors ────────────────────────────────────────────────────────
export const fetchAlerts = (params = {}) =>
  safeGet('/api/v1/alerts', '/api/alerts', params).catch(() => ({ items: [] }));

export const fetchMonitors = (params = {}) =>
  safeGet('/v1/monitors', null, params).catch(() => ({ items: [] }));

export const fetchDqRules = (params = {}) =>
  safeGet('/v1/dq-rules', null, params).catch(() => ({ items: [] }));

// ── Tools & Connectors ───────────────────────────────────────────────────────
export const fetchTools = (params = {}) =>
  safeGet('/api/v1/tools', '/v1/tools', params);

export const fetchTool = (toolId) =>
  safeGet(`/v1/tools/${toolId}`, null);

export const fetchConnectorTypes = () =>
  safeGet('/api/v1/connectors/types', '/v1/tools/types');

export const testToolConnection = (toolId) =>
  api.post(`/v1/tools/${toolId}/test`).then(r => r.data);

export const validateToolCredentials = (payload) =>
  api.post('/v1/tools/test-credentials', payload).then(r => r.data);

export const createTool = (payload, skipValidation = false) =>
  api.post(`/v1/tools${skipValidation ? '?skip_validation=true' : ''}`, payload).then(r => { clearClientCache(); return r.data; });

export const updateToolSecret = (toolId, payload) =>
  api.put(`/v1/tools/${toolId}/secret`, payload).then(r => { clearClientCache(); return r.data; });

export const createPipelineFromTools = (payload) =>
  api.post('/v1/pipelines/from-tools', payload).then(r => { clearClientCache(); return r.data; });

export const fetchPipelineTemplates = () =>
  safeGet('/v1/pipelines/templates', null);

/** Sync-default pipeline with embedded source / etl / target tool configs */
export const fetchCurrentPipeline = () =>
  safeGet('/v1/pipelines/current', null);

// ── Operations & Triggers ────────────────────────────────────────────────────
export const triggerSync = (payload = {}) =>
  api.post('/v1/sync', payload).then(r => { clearClientCache(); return r.data; });

export const evaluateMonitors = () =>
  api.post('/api/v1/ops/evaluate-monitors').then(r => r.data);

export const evaluateDqRules = (pipelineId) =>
  api.post('/api/v1/ops/evaluate-dq-rules', null, { params: pipelineId ? { pipeline_id: pipelineId } : {} }).then(r => r.data);

// ── Observability Maturity Assessment & KPI Matrix ───────────────────────────
export const fetchAssessmentSummary = (params = {}) =>
  safeGet('/api/v1/assessment/summary', null, params);

export const fetchAssessmentScorecard = (params = {}) =>
  safeGet('/api/v1/assessment/scorecard', null, params);

export const fetchAssessmentRoi = (params = {}) =>
  safeGet('/api/v1/assessment/roi-model', null, params);

export const fetchAssessmentRoadmap = (params = {}) =>
  safeGet('/api/v1/assessment/roadmap', null, params);

// ── DataOps Practice Diagnostic & Reliability Assessment ────────────────────
export const fetchDataOpsSummary = (params = {}) =>
  safeGet('/api/v1/dataops/summary', null, params);

export const fetchDataOpsScorecard = (params = {}) =>
  safeGet('/api/v1/dataops/scorecard', null, params);

export const fetchDataOpsOutcomes = (params = {}) =>
  safeGet('/api/v1/dataops/outcomes', null, params);

export const fetchDataOpsRoadmap = (params = {}) =>
  safeGet('/api/v1/dataops/roadmap', null, params);

// ── Convenience Aliases ──────────────────────────────────────────────────────
export const fetchHealth = fetchOverviewHealth;

export default api;

