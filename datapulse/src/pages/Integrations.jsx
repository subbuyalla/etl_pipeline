import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Search, Eye, X, Plus, Copy, Check, ArrowRight, Star, Play,
  Database, Layers, SlidersHorizontal, ShieldCheck, CheckCircle2, AlertCircle, Loader2,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  fetchTools,
  fetchTool,
  fetchPipelines,
  fetchCurrentPipeline,
  fetchConnectorTypes,
  fetchPipelineBindings,
  updateToolSecret,
  createTool,
  validateToolCredentials,
  createPipelineFromTools,
  triggerSync,
} from '../api/client';
import ConnectorLogo from '../components/ConnectorLogo';
import SearchableSelect from '../components/SearchableSelect';
import { handleDateChange } from './DataObservability/obsUtils';

/**
 * Integrations
 * Tab 1 Connections — registered Source → Transform → Target
 * Tab 2 Compose & Sync — ONLY:
 *   POST /v1/pipelines/from-tools
 *   POST /v1/sync
 */

const TABS = [
  { id: 'connections', label: 'Connections' },
  { id: 'compose', label: 'Compose & Sync' },
  { id: 'directory', label: 'Directory' },
];

const EMPTY_COMPOSE = {
  pipeline_name: '',
  source_tool_id: '',
  etl_tool_id: '',
  target_tool_id: '',
  description: '',
};

const CONNECTOR_META = {
  snowflake: {
    label: 'Snowflake',
    color: '#29B5E8',
    category: 'warehouses',
    desc: 'Cloud data warehouse for analytics and BI.',
  },
  redshift: {
    label: 'Amazon Redshift',
    color: '#CC292B',
    category: 'warehouses',
    desc: 'Data warehouse for large-scale analytics.',
  },
  bigquery: {
    label: 'Google BigQuery',
    color: '#4285F4',
    category: 'warehouses',
    desc: 'Serverless data warehouse from Google Cloud.',
  },
  mysql: {
    label: 'MySQL',
    color: '#00758F',
    category: 'databases',
    desc: 'Popular open source database.',
  },
  postgres: {
    label: 'PostgreSQL',
    color: '#336791',
    category: 'databases',
    desc: 'Open source relational database.',
  },
  dbt: {
    label: 'dbt Cloud',
    color: '#FF694B',
    category: 'etl',
    desc: 'Data transformation & modeling.',
  },
  dbt_cloud: {
    label: 'dbt Cloud',
    color: '#FF694B',
    category: 'etl',
    desc: 'Data transformation & modeling.',
  },
  airbyte: {
    label: 'Airbyte',
    color: '#615EFF',
    category: 'etl',
    desc: 'Open-source data movement and replication.',
  },
  airflow: {
    label: 'Apache Airflow',
    color: '#017CEE',
    category: 'etl',
    desc: 'Workflow orchestration & scheduling.',
  },
  informatica: {
    label: 'Informatica (IICS / IDMC)',
    color: '#FF4D00',
    category: 'etl',
    desc: 'Cloud Data Integration (CDI), Taskflows & Data Quality.',
  },
};

const DIR_SECTIONS = [
  {
    id: 'warehouses',
    title: 'Data Warehouses & Lakes',
    subtitle: 'Connect your data warehouses, lakehouses and cloud storage.',
    icon: Layers,
    iconColor: '#2563EB',
    iconBg: '#EFF6FF',
  },
  {
    id: 'databases',
    title: 'Databases',
    subtitle: 'Connect to your operational and analytical databases.',
    icon: Database,
    iconColor: '#059669',
    iconBg: '#ECFDF5',
  },
  {
    id: 'etl',
    title: 'Transformations & ETL',
    subtitle: 'Orchestrate, transform and move your data across systems.',
    icon: SlidersHorizontal,
    iconColor: '#EA580C',
    iconBg: '#FFF7ED',
  },
];

function categoryForType(id, kind) {
  const meta = CONNECTOR_META[id];
  if (meta?.category) return meta.category;
  if (kind === 'etl' || kind === 'orchestrator') return 'etl';
  if (kind === 'database') return 'databases';
  return 'warehouses';
}

const FORM_SCHEMAS = {
  snowflake: [
    { key: 'account_id', label: 'Account Identifier', required: true },
    { key: 'warehouse_id', label: 'Warehouse', required: true },
    { key: 'database_id', label: 'Database', required: true },
    { key: 'schema', label: 'Schema', required: true },
    { key: 'tables', label: 'Tables (comma-separated)', required: false },
    { key: 'user_id', label: 'Username', required: true },
    { key: 'sf_role', label: 'Snowflake role', required: false },
    { key: 'secret', label: 'Password / Private Key', type: 'password', required: true },
  ],
  mysql: [
    { key: 'host', label: 'Host', required: true },
    { key: 'port', label: 'Port', required: true, placeholder: '3306' },
    { key: 'database_id', label: 'Database', required: true },
    { key: 'user_id', label: 'Username', required: true },
    { key: 'secret', label: 'Password', type: 'password', required: true },
  ],
  postgres: [
    { key: 'host', label: 'Host', required: true },
    { key: 'port', label: 'Port', required: true, placeholder: '5432' },
    { key: 'database_id', label: 'Database', required: true },
    { key: 'schema', label: 'Schema', required: true },
    { key: 'user_id', label: 'Username', required: true },
    { key: 'secret', label: 'Password', type: 'password', required: true },
  ],
  redshift: [
    { key: 'host', label: 'Cluster endpoint', required: true },
    { key: 'port', label: 'Port', required: true, placeholder: '5439' },
    { key: 'database_id', label: 'Database', required: true },
    { key: 'schema', label: 'Schema', required: true },
    { key: 'user_id', label: 'Username', required: true },
    { key: 'secret', label: 'Password', type: 'password', required: true },
  ],
  bigquery: [
    { key: 'project_id', label: 'GCP Project ID', required: true },
    { key: 'dataset_id', label: 'Dataset ID', required: true },
    { key: 'secret', label: 'Service Account JSON', type: 'textarea', required: true },
  ],
  dbt: [
    { key: 'account_id', label: 'dbt Cloud Account ID', required: true },
    { key: 'job_id', label: 'Job ID', required: true },
    { key: 'project_name', label: 'Project Name', required: true },
    { key: 'api_base', label: 'API Base URL', required: true, placeholder: 'https://cloud.getdbt.com/api/v2' },
    { key: 'secret', label: 'API Token', type: 'password', required: true },
  ],
  dbt_cloud: [
    { key: 'account_id', label: 'dbt Cloud Account ID', required: true },
    { key: 'job_id', label: 'Job ID', required: true },
    { key: 'project_name', label: 'Project Name', required: true },
    { key: 'api_base', label: 'API Base URL', required: true, placeholder: 'https://cloud.getdbt.com/api/v2' },
    { key: 'secret', label: 'API Token', type: 'password', required: true },
  ],
  airbyte: [
    { key: 'api_url', label: 'Airbyte API URL', required: true },
    { key: 'workspace_id', label: 'Workspace ID', required: true },
    { key: 'secret', label: 'API Token', type: 'password', required: true },
  ],
  airflow: [
    { key: 'webserver_url', label: 'Webserver URL', required: true },
    { key: 'dag_id', label: 'DAG ID', required: true },
    { key: 'user_id', label: 'Username', required: true },
    { key: 'secret', label: 'Password / Token', type: 'password', required: true },
  ],
  informatica: [
    { key: 'pod_url', label: 'POD Region / Base URL', required: true, placeholder: 'dm-us (or https://dm-us.informaticacloud.com)' },
    { key: 'username', label: 'Username / Service Email', required: true, placeholder: 'svc_datapulse@company.com' },
    { key: 'secret', label: 'Password', type: 'password', required: true },
    { key: 'org_id', label: 'Organization ID (Optional)', required: false, placeholder: 'Auto-discovered from login' },
    { key: 'task_type', label: 'Task Type Filter', required: false, placeholder: 'MTT (Mapping Tasks), TASKFLOW, or ALL' },
    { key: 'task_filter', label: 'Task Name Filter (Optional)', required: false, placeholder: 'e.g. mtt_orders or leave empty' },
  ],
};

const GENERIC_FIELDS = [
  { key: 'host', label: 'Host / Endpoint', required: true },
  { key: 'secret', label: 'Password / API Token', type: 'password', required: true },
];

const SECRET_KEYS = new Set(['secret', 'password', 'token', 'api_key', 'access_key_id']);
const ROLE_ORDER = ['SOURCE', 'ETL', 'TARGET'];

function fieldsForType(id) {
  return FORM_SCHEMAS[id] || GENERIC_FIELDS;
}

function isTransformConnector(typeOrId, kind) {
  const id = typeof typeOrId === 'object' ? typeOrId?.id : typeOrId;
  const k = typeof typeOrId === 'object' ? typeOrId?.kind : kind;
  if (k === 'etl' || k === 'orchestrator') return true;
  return categoryForType(String(id || '').toLowerCase(), k) === 'etl';
}

/** Warehouses/DBs → SOURCE|TARGET only. Transform tools → TRANSFORM only. */
function rolesForConnector(type) {
  if (isTransformConnector(type)) {
    return [{ value: 'ETL', label: 'TRANSFORM' }];
  }
  return [
    { value: 'SOURCE', label: 'SOURCE' },
    { value: 'TARGET', label: 'TARGET' },
  ];
}

function defaultRoleForConnector(type) {
  return isTransformConnector(type) ? 'ETL' : 'SOURCE';
}

function roleFromTool(tool) {
  const explicit = (tool?.config?.role || tool?.role || '').toUpperCase();
  if (explicit === 'SOURCE' || explicit === 'TARGET' || explicit === 'ETL' || explicit === 'TRANSFORM') {
    return explicit === 'TRANSFORM' ? 'ETL' : explicit;
  }
  if (tool?.kind === 'etl' || tool?.kind === 'orchestrator') return 'ETL';
  const name = String(tool?.name || '').toLowerCase();
  if (name.includes('-etl') || name.endsWith('etl') || name.includes('transform')) return 'ETL';
  if (name.includes('source')) return 'SOURCE';
  if (name.includes('target')) return 'TARGET';
  return tool?.kind === 'database' ? 'SOURCE' : '—';
}

function toolIdOf(tool) {
  return tool?.tool_id || tool?.instance_id || '';
}

function extractToolId(res) {
  if (!res) return '';
  return res.tool_id || res.instance_id || res.tool?.tool_id || res.item?.tool_id || '';
}

function extractPipelineId(res) {
  if (!res) return '';
  return res.pipeline_id || res.pipeline?.pipeline_id || res.item?.pipeline_id || '';
}

function extractSyncMessage(res, fallback) {
  if (!res) return fallback;
  if (typeof res.message === 'string') return res.message;
  if (typeof res.detail === 'string') return res.detail;
  if (typeof res.status === 'string') return res.status;
  return fallback;
}

function dash(v) {
  if (v == null || v === '') return '—';
  return String(v);
}

function labelForType(id) {
  return CONNECTOR_META[id]?.label || id || '—';
}

function roleLabel(role) {
  if (role === 'ETL') return 'TRANSFORM';
  return role || '—';
}

function roleClass(role) {
  if (role === 'SOURCE') return 'is-source';
  if (role === 'ETL' || role === 'TRANSFORM') return 'is-etl';
  if (role === 'TARGET') return 'is-target';
  return '';
}

function parseAsset(json) {
  if (!json) return null;
  try {
    return typeof json === 'string' ? JSON.parse(json) : json;
  } catch {
    return null;
  }
}

function assetLine(tool, binding) {
  const cfg = tool?.config || {};
  const asset = parseAsset(binding?.asset_selector_json) || {};
  const schema = asset.schema || cfg.schema;
  const tables = asset.tables || cfg.tables;
  const database = cfg.database_id || cfg.project_id;
  const tableStr = Array.isArray(tables) ? tables.join(', ') : tables;
  const type = String(tool?.connector_type || binding?.connector_type || '').toLowerCase();

  if (type === 'dbt' || type === 'dbt_cloud') {
    const project = cfg.project_name || '—';
    const job = cfg.job_id || '—';
    return `${project} · job ${job}`;
  }
  if (database || schema || tableStr) {
    return [database, schema, tableStr].filter(Boolean).join(' · ');
  }
  return labelForType(type);
}

/** Live tools API ignores preset — filter locally by created/updated timestamps. */
function dateWindow(preset, customRange) {
  const end = new Date();
  if (preset === 'custom' && customRange?.start && customRange?.end) {
    const start = new Date(`${customRange.start}T00:00:00`);
    const endDay = new Date(`${customRange.end}T23:59:59`);
    return { start, end: endDay };
  }
  if (preset === '15m') return { start: new Date(end.getTime() - 15 * 60 * 1000), end };
  if (preset === '24h') return { start: new Date(end.getTime() - 24 * 60 * 60 * 1000), end };
  if (preset === '7d') return { start: new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000), end };
  if (preset === '30d') return { start: new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000), end };
  return null; // all
}

function toolTimestamp(tool) {
  const raw = tool?.updated_at || tool?.created_at;
  if (!raw) return null;
  const d = new Date(String(raw).replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d;
}

function inDateWindow(tool, window) {
  if (!window) return true;
  const ts = toolTimestamp(tool);
  if (!ts) return true; // keep if API gave no timestamp
  return ts >= window.start && ts <= window.end;
}

export default function Integrations() {
  const [tab, setTab] = useState('connections');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);

  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const [tools, setTools] = useState([]);
  const [pipelines, setPipelines] = useState([]);
  const [bindingsByPipe, setBindingsByPipe] = useState({});
  const [currentPipeline, setCurrentPipeline] = useState(null);
  const [connectorTypes, setConnectorTypes] = useState([]);

  const [search, setSearch] = useState('');
  const [pipelineFilter, setPipelineFilter] = useState('all');
  const [roleFilter, setRoleFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dirSearch, setDirSearch] = useState('');
  const [dirCategory, setDirCategory] = useState('all');

  const [addOpen, setAddOpen] = useState(false);
  const [connectTypeId, setConnectTypeId] = useState('');
  const [connectLocked, setConnectLocked] = useState(false);
  const [connectionName, setConnectionName] = useState('');
  const [connectionRole, setConnectionRole] = useState('SOURCE');
  const [formValues, setFormValues] = useState({});
  const [savingTool, setSavingTool] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [registerResult, setRegisterResult] = useState(null);
  const [testingCreds, setTestingCreds] = useState(false);
  const [credTestResult, setCredTestResult] = useState(null);
  const [credTestError, setCredTestError] = useState(null);

  const [inspectTool, setInspectTool] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [secretDraft, setSecretDraft] = useState('');
  const [savingSecret, setSavingSecret] = useState(false);
  const [copiedId, setCopiedId] = useState('');

  const [composeForm, setComposeForm] = useState(EMPTY_COMPOSE);
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState(null);
  const [syncPipelineName, setSyncPipelineName] = useState('');
  const [syncRefreshDb, setSyncRefreshDb] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncResult, setLastSyncResult] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Tools list is not date-scoped by API — load full set, filter in UI
      const [toolsRes, pipesRes, typesRes, currentRes] = await Promise.allSettled([
        fetchTools(),
        fetchPipelines({}),
        fetchConnectorTypes(),
        fetchCurrentPipeline(),
      ]);

      let toolList = [];
      if (toolsRes.status === 'fulfilled' && toolsRes.value) {
        if (toolsRes.value.ok === false || toolsRes.value.error) {
          setError(toolsRes.value.error || 'Tools API returned an error');
        } else {
          toolList = toolsRes.value.items || toolsRes.value.tools || [];
          toolList = Array.isArray(toolList) ? toolList : [];
        }
      } else if (toolsRes.status === 'rejected') {
        setError(toolsRes.reason?.response?.data?.error || toolsRes.reason?.message || 'Failed to load tools');
      }
      setTools(toolList);

      let pipeList = [];
      if (pipesRes.status === 'fulfilled' && pipesRes.value) {
        pipeList = pipesRes.value.items || pipesRes.value.pipelines || [];
        pipeList = Array.isArray(pipeList) ? pipeList : [];
      }
      setPipelines(pipeList);

      if (typesRes.status === 'fulfilled' && typesRes.value) {
        const items = typesRes.value.items || typesRes.value.types || [];
        const raw = Array.isArray(items) ? items : [];
        const hasDbtCloud = raw.some((t) => String(t.id || '').toLowerCase() === 'dbt_cloud');
        setConnectorTypes(
          raw
            .map((t) => {
              const id = String(t.id || t.name || t.connector_type || '').toLowerCase();
              if (!id || (id === 'dbt' && hasDbtCloud)) return null;
              return { id, label: labelForType(id) || t.label, kind: t.kind || 'database' };
            })
            .filter(Boolean),
        );
      }

      if (currentRes.status === 'fulfilled' && currentRes.value) {
        setCurrentPipeline(currentRes.value);
      } else {
        setCurrentPipeline(null);
      }

      const map = {};
      await Promise.all(
        pipeList.map(async (p) => {
          if (!p?.pipeline_id) return;
          try {
            const res = await fetchPipelineBindings(p.pipeline_id);
            map[p.pipeline_id] = res?.items || res?.bindings || [];
          } catch {
            map[p.pipeline_id] = [];
          }
        }),
      );
      setBindingsByPipe(map);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const windowRange = useMemo(
    () => dateWindow(headerDatePreset, customDateRange),
    [headerDatePreset, customDateRange],
  );

  const toolsInRange = useMemo(
    () => tools.filter((t) => inDateWindow(t, windowRange)),
    [tools, windowRange],
  );

  const toolsById = useMemo(() => {
    const map = {};
    tools.forEach((t) => {
      const id = toolIdOf(t);
      if (id) map[id] = t;
    });
    return map;
  }, [tools]);

  const pipelineRows = useMemo(() => {
    const byId = new Map();
    pipelines.forEach((p) => {
      if (p?.pipeline_id && !byId.has(p.pipeline_id)) byId.set(p.pipeline_id, p);
    });
    return Array.from(byId.values());
  }, [pipelines]);

  const syncDefault = useMemo(() => {
    return pipelineRows.find((p) => p.is_sync_default)
      || (currentPipeline?.pipeline_id
        ? pipelineRows.find((p) => p.pipeline_id === currentPipeline.pipeline_id)
        : null)
      || currentPipeline;
  }, [pipelineRows, currentPipeline]);

  const sourceTools = useMemo(
    () => tools.filter((t) => {
      const role = roleFromTool(t);
      return role === 'SOURCE' || (t.kind === 'database' && role !== 'TARGET' && role !== 'ETL');
    }),
    [tools],
  );
  const etlTools = useMemo(
    () => tools.filter((t) => roleFromTool(t) === 'ETL' || t.kind === 'etl' || t.kind === 'orchestrator'),
    [tools],
  );
  const targetTools = useMemo(
    () => tools.filter((t) => {
      const role = roleFromTool(t);
      return role === 'TARGET' || (t.kind === 'database' && role !== 'SOURCE' && role !== 'ETL');
    }),
    [tools],
  );

  const isDuplicatePipelineName = useMemo(() => {
    const trimmed = composeForm.pipeline_name.trim().toLowerCase();
    if (!trimmed) return false;
    return pipelines.some((p) => String(p.pipeline_name || '').toLowerCase() === trimmed);
  }, [composeForm.pipeline_name, pipelines]);

  const isDuplicateConnectionName = useMemo(() => {
    const trimmed = connectionName.trim().toLowerCase();
    if (!trimmed) return false;
    return tools.some((t) => String(t.name || '').toLowerCase() === trimmed);
  }, [connectionName, tools]);

  const sourceOptions = useMemo(() => {
    const list = [];
    sourceTools.forEach((t) => {
      list.push({
        value: toolIdOf(t),
        label: t.name,
        sublabel: labelForType(t.connector_type),
        group: 'Source Databases & Warehouses',
        icon: <ConnectorLogo type={t.connector_type} size={15} />,
      });
    });
    tools.filter((t) => !sourceTools.includes(t) && roleFromTool(t) !== 'ETL').forEach((t) => {
      list.push({
        value: toolIdOf(t),
        label: t.name,
        sublabel: labelForType(t.connector_type),
        group: 'Other Available Connections',
        icon: <ConnectorLogo type={t.connector_type} size={15} />,
      });
    });
    return list;
  }, [sourceTools, tools]);

  const etlOptions = useMemo(() => {
    const list = [];
    const pool = etlTools.length > 0 ? etlTools : tools;
    pool.forEach((t) => {
      list.push({
        value: toolIdOf(t),
        label: t.name,
        sublabel: labelForType(t.connector_type),
        group: 'Transform / ETL Tools',
        icon: <ConnectorLogo type={t.connector_type} size={15} />,
      });
    });
    return list;
  }, [etlTools, tools]);

  const targetOptions = useMemo(() => {
    const list = [];
    targetTools.forEach((t) => {
      list.push({
        value: toolIdOf(t),
        label: t.name,
        sublabel: labelForType(t.connector_type),
        group: 'Target Databases & Warehouses',
        icon: <ConnectorLogo type={t.connector_type} size={15} />,
      });
    });
    tools.filter((t) => !targetTools.includes(t) && roleFromTool(t) !== 'ETL').forEach((t) => {
      list.push({
        value: toolIdOf(t),
        label: t.name,
        sublabel: labelForType(t.connector_type),
        group: 'Other Available Connections',
        icon: <ConnectorLogo type={t.connector_type} size={15} />,
      });
    });
    return list;
  }, [targetTools, tools]);

  const pipelineSyncOptions = useMemo(() => {
    return [
      { value: '', label: 'Default Pipeline (sync-default)', sublabel: 'Auto-detect active sync pipeline' },
      ...pipelines.map((p) => ({
        value: p.pipeline_name,
        label: p.pipeline_name,
        sublabel: p.is_sync_default ? '★ Sync Default' : (p.tool || p.etl_tool || 'pipeline'),
      })),
    ];
  }, [pipelines]);

  const connectionGroups = useMemo(() => {
    return pipelineRows
      .map((pipe) => {
        const bindings = bindingsByPipe[pipe.pipeline_id] || [];
        const nodes = ROLE_ORDER.map((role) => {
          const binding = bindings.find((b) => String(b.role || '').toUpperCase() === role)
            || bindings.find((b) => role === 'ETL' && String(b.role || '').toUpperCase() === 'TRANSFORM');
          let tool = binding ? toolsById[binding.instance_id] : null;
          if (!tool && binding?.instance_id) {
            tool = tools.find((t) => toolIdOf(t) === binding.instance_id) || null;
          }
          return {
            role,
            binding: binding || null,
            tool,
            toolId: toolIdOf(tool) || binding?.instance_id || '',
          };
        });
        const registeredCount = nodes.filter((n) => n.binding || n.tool).length;
        return { pipe, nodes, bindings, registeredCount };
      })
      // Connections: only registered pipelines (have Source / Transform / Target bindings)
      .filter((g) => g.registeredCount > 0);
  }, [pipelineRows, bindingsByPipe, toolsById, tools]);

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();

    return connectionGroups
      .map(({ pipe, nodes, bindings }) => {
        const datedNodes = nodes.map((node) => {
          const inRange = !node.tool || inDateWindow(node.tool, windowRange);
          return { ...node, inRange, hiddenByDate: Boolean(node.tool) && !inRange };
        });
        return { pipe, nodes: datedNodes, bindings };
      })
      .filter(({ pipe, nodes }) => {
        if (pipelineFilter !== 'all' && pipe.pipeline_id !== pipelineFilter) return false;

        // Date: keep pipeline if at least one connected tool is in range (or no tools yet)
        const connected = nodes.filter((n) => n.tool);
        if (windowRange && connected.length > 0 && connected.every((n) => n.hiddenByDate)) {
          return false;
        }

        if (statusFilter !== 'all') {
          const wantActive = statusFilter === 'active';
          const hasStatus = nodes.some((n) => {
            if (!n.tool || n.hiddenByDate) return false;
            const active = String(n.tool.status || '').toLowerCase() === 'active';
            return wantActive ? active : !active;
          });
          if (!hasStatus) return false;
        }

        if (roleFilter !== 'all') {
          const node = nodes.find((n) => n.role === roleFilter);
          if (!node?.tool || node.hiddenByDate) return false;
        }

        if (q) {
          const hay = [
            pipe.pipeline_name,
            pipe.pipeline_id,
            ...nodes.flatMap((n) => [
              n.tool?.name,
              n.binding?.instance_name,
              n.tool?.connector_type,
              n.binding?.connector_type,
              roleLabel(n.role),
            ]),
          ].join(' ').toLowerCase();
          if (!hay.includes(q)) return false;
        }

        return true;
      })
      .map(({ pipe, nodes, bindings }) => {
        // Role filter: keep full flow but mark non-matching as dimmed
        const viewNodes = nodes.map((n) => ({
          ...n,
          dimmed:
            n.hiddenByDate
            || (roleFilter !== 'all' && n.role !== roleFilter)
            || (statusFilter === 'active' && n.tool && String(n.tool.status || '').toLowerCase() !== 'active')
            || (statusFilter === 'inactive' && n.tool && String(n.tool.status || '').toLowerCase() === 'active'),
        }));
        return { pipe, nodes: viewNodes, bindings };
      });
  }, [connectionGroups, pipelineFilter, roleFilter, statusFilter, search, windowRange]);

  const visibleToolIds = useMemo(() => {
    const ids = new Set();
    filteredGroups.forEach(({ nodes }) => {
      nodes.forEach((n) => {
        if (n.toolId && !n.hiddenByDate && !n.dimmed) ids.add(n.toolId);
      });
    });
    return ids;
  }, [filteredGroups]);

  const filtersActive = Boolean(
    search.trim() || pipelineFilter !== 'all' || roleFilter !== 'all' || statusFilter !== 'all',
  );

  const kpiConnectionCount = filtersActive
    ? toolsInRange.filter((t) => visibleToolIds.has(toolIdOf(t))).length
    : toolsInRange.length;

  const activeCount = (filtersActive
    ? toolsInRange.filter((t) => visibleToolIds.has(toolIdOf(t)))
    : toolsInRange
  ).filter((t) => String(t.status || '').toLowerCase() === 'active').length;

  const selectedType = connectorTypes.find((t) => t.id === connectTypeId) || null;
  const roleOptions = rolesForConnector(selectedType);
  const dbWarehouseTypes = connectorTypes.filter((t) => !isTransformConnector(t));
  const transformTypes = connectorTypes.filter((t) => isTransformConnector(t));
  const typeFields = selectedType ? fieldsForType(selectedType.id) : [];

  const clearFilters = () => {
    setSearch('');
    setPipelineFilter('all');
    setRoleFilter('all');
    setStatusFilter('all');
  };

  const onHeaderDateChange = (v) => {
    handleDateChange(setHeaderDatePreset, setCustomDateRange, v);
  };

  const openAdd = (typeId) => {
    setAddOpen(true);
    setSaveError(null);
    setRegisterResult(null);
    setCredTestResult(null);
    setCredTestError(null);
    setConnectionName('');
    setFormValues({});
    const id = typeId || '';
    setConnectTypeId(id);
    setConnectLocked(Boolean(typeId));
    const next = connectorTypes.find((t) => t.id === id);
    setConnectionRole(defaultRoleForConnector(next || { id, kind: CONNECTOR_META[id]?.category === 'etl' ? 'etl' : 'database' }));
  };

  const closeAdd = () => {
    if (savingTool || testingCreds) return;
    setAddOpen(false);
    setRegisterResult(null);
    setSaveError(null);
    setCredTestResult(null);
    setCredTestError(null);
  };

  const applyConnectorChange = (id) => {
    setConnectTypeId(id);
    setFormValues({});
    setCredTestResult(null);
    setCredTestError(null);
    setSaveError(null);
    const next = connectorTypes.find((t) => t.id === id);
    setConnectionRole(defaultRoleForConnector(next));
  };

  const directoryEntries = useMemo(() => {
    const counts = {};
    tools.forEach((t) => {
      const type = String(t.connector_type || t.type || '').toLowerCase();
      if (!type) return;
      counts[type] = (counts[type] || 0) + 1;
    });

    return connectorTypes.map((t) => {
      const meta = CONNECTOR_META[t.id] || {};
      const connected = counts[t.id] || 0;
      return {
        id: t.id,
        label: meta.label || t.label || t.id,
        desc: meta.desc || `${meta.label || t.label || t.id} connector.`,
        color: meta.color || '#64748B',
        category: categoryForType(t.id, t.kind),
        kind: t.kind,
        connected,
      };
    });
  }, [connectorTypes, tools]);

  const filteredDirectory = useMemo(() => {
    const q = dirSearch.trim().toLowerCase();
    return directoryEntries.filter((e) => {
      if (dirCategory !== 'all' && e.category !== dirCategory) return false;
      if (!q) return true;
      return (
        e.label.toLowerCase().includes(q)
        || e.id.toLowerCase().includes(q)
        || e.desc.toLowerCase().includes(q)
        || e.kind?.toLowerCase().includes(q)
      );
    });
  }, [directoryEntries, dirSearch, dirCategory]);

  const directoryBySection = useMemo(() => {
    const map = { warehouses: [], databases: [], etl: [] };
    filteredDirectory.forEach((e) => {
      if (map[e.category]) map[e.category].push(e);
      else map.warehouses.push(e);
    });
    return map;
  }, [filteredDirectory]);

  const dirCounts = useMemo(() => {
    const all = directoryEntries.length;
    return {
      all,
      warehouses: directoryEntries.filter((e) => e.category === 'warehouses').length,
      databases: directoryEntries.filter((e) => e.category === 'databases').length,
      etl: directoryEntries.filter((e) => e.category === 'etl').length,
    };
  }, [directoryEntries]);

  const buildToolPayload = () => {
    if (!selectedType) return null;
    const fields = fieldsForType(selectedType.id);
    const config = { role: connectionRole };
    let secret = null;
    fields.forEach((field) => {
      const raw = formValues[field.key];
      if (raw == null || String(raw).trim() === '') return;
      if (SECRET_KEYS.has(field.key) || field.type === 'password') {
        secret = String(raw);
        return;
      }
      if (field.key === 'tables') {
        config.tables = String(raw).split(',').map((s) => s.trim()).filter(Boolean);
      } else {
        config[field.key] = String(raw).trim();
      }
    });
    return {
      name: connectionName.trim() || `${selectedType.id}-draft`,
      connector_type: selectedType.id,
      kind: selectedType.kind || undefined,
      secret: secret || undefined,
      config,
    };
  };

  const handleTestCredentials = async () => {
    if (!selectedType) return;
    const payload = buildToolPayload();
    if (!payload) return;

    setTestingCreds(true);
    setCredTestError(null);
    setCredTestResult(null);
    setSaveError(null);
    try {
      const res = await validateToolCredentials(payload);
      if (res?.ok) {
        setCredTestResult(res);
      } else {
        const msg = res?.message || 'Credential or permission test failed';
        setCredTestError(msg);
        setCredTestResult(res);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : (detail?.message || err?.response?.data?.message || err?.message || 'Connection test failed');
      setCredTestError(msg);
    } finally {
      setTestingCreds(false);
    }
  };

  const handleSaveTool = async (e) => {
    e.preventDefault();
    if (!selectedType) return;
    const trimmedName = connectionName.trim();
    if (!trimmedName) return;

    if (isDuplicateConnectionName) {
      setSaveError(`A connection named “${trimmedName}” already exists. Connection names must be unique.`);
      return;
    }

    setSavingTool(true);
    setSaveError(null);
    try {
      const payload = buildToolPayload();
      payload.name = trimmedName;

      // createTool validates credentials and permissions on backend
      const res = await createTool(payload);
      const tid = extractToolId(res);
      const cid = res?.connection_id || res?.item?.connection_id || res?.tool?.connection_id || '';
      setRegisterResult({
        raw: res,
        tool_id: tid,
        connection_id: cid,
        name: trimmedName,
        connector_type: selectedType.id,
        kind: selectedType.kind || res?.kind || '',
        role: connectionRole,
        status: res?.status || res?.item?.status || 'active',
        verified: true,
      });
      setActionMsg(tid
        ? `Registered “${trimmedName}” · credentials & permissions verified · tool_id ${String(tid).slice(0, 8)}…`
        : `Registered “${trimmedName}” · credentials & permissions verified.`);
      await loadData();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : (detail?.message || err?.response?.data?.message || err?.message || 'Failed to create connection');
      setSaveError(msg);
    } finally {
      setSavingTool(false);
    }
  };

  const openInspect = async (tool) => {
    if (!tool) return;
    const tid = toolIdOf(tool);
    setInspectTool(tool);
    setSecretDraft('');
    if (!tid) return;
    setInspectLoading(true);
    try {
      const res = await fetchTool(tid);
      const item = res?.item || res?.tool || (res?.tool_id || res?.name ? res : null);
      if (item) setInspectTool(item);
    } catch {
      /* keep */
    } finally {
      setInspectLoading(false);
    }
  };

  const handleCompose = async (e) => {
    e.preventDefault();
    setComposing(true);
    setComposeError(null);
    try {
      const name = composeForm.pipeline_name.trim();
      const source = composeForm.source_tool_id.trim();
      const etl = composeForm.etl_tool_id.trim();
      const target = composeForm.target_tool_id.trim();
      if (!name) throw new Error('Pipeline name is required');
      if (!etl) throw new Error('Transform / ETL connection is required');

      if (isDuplicatePipelineName) {
        throw new Error(`A pipeline named “${name}” already exists. Pipeline names must be unique.`);
      }

      // This tab only: POST /v1/pipelines/from-tools
      const payload = {
        pipeline_name: name,
        etl_tool_id: etl,
      };
      if (source) payload.source_tool_id = source;
      if (target) payload.target_tool_id = target;
      if (composeForm.description.trim()) payload.description = composeForm.description.trim();
      const res = await createPipelineFromTools(payload);
      setComposeForm(EMPTY_COMPOSE);
      setSyncPipelineName(name);
      setActionMsg(`Pipeline “${name}” composed successfully. Selected in Sync below.`);
      await loadData();
    } catch (err) {
      setComposeError(err?.response?.data?.detail || err?.response?.data?.error || err.message || 'Compose failed');
    } finally {
      setComposing(false);
    }
  };

  const handleSync = async (e) => {
    e?.preventDefault?.();
    setSyncing(true);
    setLastSyncResult(null);
    // POST /v1/sync — pipeline_name only (or empty body = sync-default)
    const body = {};
    const name = syncPipelineName.trim();
    if (name) body.pipeline_name = name;
    if (syncRefreshDb) body.refresh_db = true;
    const label = name || 'sync-default';
    try {
      const res = await triggerSync(body);
      const msg = extractSyncMessage(res, `Sync completed for ${label}.`);
      setLastSyncResult({ ok: true, message: msg });
      setActionMsg(msg);
    } catch (err) {
      const detail = err?.response?.data;
      const errMsg = detail?.detail || detail?.error || err.message || 'Sync failed';
      setLastSyncResult({ ok: false, message: typeof errMsg === 'string' ? errMsg : 'Sync failed' });
      setActionMsg(typeof errMsg === 'string' ? errMsg : 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  const handleRotateSecret = async (e) => {
    e.preventDefault();
    const tid = toolIdOf(inspectTool);
    if (!tid || !secretDraft.trim()) return;
    setSavingSecret(true);
    try {
      await updateToolSecret(tid, { secret: secretDraft.trim() });
      setSecretDraft('');
      setActionMsg(`Secret updated for “${inspectTool.name || tid}”.`);
      const res = await fetchTool(tid);
      const item = res?.item || res?.tool || (res?.tool_id || res?.name ? res : null);
      if (item) setInspectTool(item);
    } catch (err) {
      setActionMsg(err?.response?.data?.detail || err?.response?.data?.error || err.message || 'Secret update failed');
    } finally {
      setSavingSecret(false);
    }
  };

  const copyText = async (text) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(text);
      setTimeout(() => setCopiedId(''), 1500);
    } catch {
      setActionMsg(text);
    }
  };

  return (
    <div className="fade-in">
      <PageHeader
        title="Integrations"
        subtitle="Connections, pipelines, and connector directory — live API operations hub."
        onRefresh={loadData}
        datePreset={headerDatePreset}
        customStart={customDateRange?.start || ''}
        customEnd={customDateRange?.end || ''}
        onDateChange={onHeaderDateChange}
      />

      <div className="page-body">
        <div className="integration-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={`integration-tab${tab === t.id ? ' is-active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              <span className="integration-tab-dot" />
              {t.label}
              {t.id === 'connections' ? ` (${connectionGroups.length})` : ''}
              {t.id === 'directory' ? ` (${connectorTypes.length})` : ''}
            </button>
          ))}
        </div>

        {error && (
          <div className="int-banner is-error">
            <strong>Cannot load Integrations.</strong> {error}
          </div>
        )}
        {actionMsg && (
          <div className={`int-banner${/fail/i.test(actionMsg) ? ' is-error' : ' is-ok'}`}>
            {actionMsg}
            <button type="button" className="int-banner-dismiss" onClick={() => setActionMsg(null)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}

        {tab === 'connections' && (
          <>
            <div className="int-panel-head" style={{ marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0 }}>Connections</h3>
                <p style={{ margin: '4px 0 0', fontSize: 12.5, color: 'var(--text-muted)' }}>
                  Registered pipelines only — Source → Transform → Target
                </p>
              </div>
              <button type="button" className="int-register-btn" onClick={openAdd}>
                <Plus size={14} /> Add connection
              </button>
            </div>

            <div className="filters-bar integration-toolbar int-conn-filters">
              <div className="search-box integration-search">
                <Search size={14} />
                <input
                  type="text"
                  placeholder="Search by name, pipeline, connector…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div style={{ minWidth: 200, maxWidth: 260 }}>
                <SearchableSelect
                  options={[
                    { value: 'all', label: 'All registered pipelines' },
                    ...connectionGroups.map(({ pipe: p }) => ({
                      value: p.pipeline_id,
                      label: p.pipeline_name || 'unnamed',
                      sublabel: `${String(p.pipeline_id).slice(0, 8)}${(p.is_sync_default || p.pipeline_id === syncDefault?.pipeline_id) ? ' ★' : ''}`,
                    })),
                  ]}
                  value={pipelineFilter}
                  onChange={(val) => setPipelineFilter(val || 'all')}
                  placeholder="Filter pipeline…"
                  searchPlaceholder="Search pipelines…"
                />
              </div>
              <select
                className="select-control"
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                aria-label="Role"
              >
                <option value="all">All roles</option>
                <option value="SOURCE">Source</option>
                <option value="ETL">Transform</option>
                <option value="TARGET">Target</option>
              </select>
              <select
                className="select-control"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Status"
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <button type="button" className="export-btn" disabled={!filtersActive} onClick={clearFilters}>
                Clear
              </button>
            </div>
            <p className="int-filter-meta">
              Showing {filteredGroups.length} of {connectionGroups.length} registered pipelines
              {headerDatePreset !== 'all' ? ` · date: ${headerDatePreset === 'custom' ? 'custom range' : headerDatePreset}` : ''}
            </p>

            <div className="int-kpi-rail int-kpi-rail-4">
              <div className="int-kpi"><span>Connections</span><strong>{kpiConnectionCount}</strong></div>
              <div className="int-kpi"><span>Active</span><strong className="int-kpi-ok">{activeCount}</strong></div>
              <div className="int-kpi"><span>Pipelines</span><strong>{filteredGroups.length}</strong></div>
              <div className="int-kpi"><span>Catalog types</span><strong>{connectorTypes.length}</strong></div>
            </div>

            {loading && !tools.length && !pipelineRows.length ? (
              <LoadingSpinner />
            ) : filteredGroups.length === 0 ? (
              <div className="int-empty">
                <p>No registered pipelines to show.</p>
                {filtersActive && (
                  <button type="button" className="int-primary-btn" onClick={clearFilters}>Clear filters</button>
                )}
              </div>
            ) : (
              <div className="int-conn-groups">
                {filteredGroups.map(({ pipe, nodes }) => {
                  const isDefault = pipe.is_sync_default || pipe.pipeline_id === syncDefault?.pipeline_id;
                  return (
                    <section key={pipe.pipeline_id} className="int-conn-group">
                      <div className="int-conn-group-head">
                        <div>
                          <div className="int-conn-group-title">
                            <strong>{dash(pipe.pipeline_name)}</strong>
                            {isDefault && (
                              <span className="int-status-chip is-ok">
                                <Star size={10} /> Default sync
                              </span>
                            )}
                          </div>
                          <div className="int-conn-group-sub">Source → Transform → Target</div>
                        </div>
                        <button
                          type="button"
                          className="export-btn"
                          onClick={() => setPipelineFilter(pipe.pipeline_id)}
                        >
                          Open pipeline
                        </button>
                      </div>

                      <div className="integration-arch-flow">
                        {nodes.map((node, idx) => {
                          const tool = node.tool;
                          const tid = node.toolId;
                          const name = tool?.name || node.binding?.instance_name || 'Not connected';
                          const ctype = String(tool?.connector_type || node.binding?.connector_type || '').toLowerCase();
                          const status = tool?.status || (node.binding ? 'bound' : 'missing');
                          const ok = String(status).toLowerCase() === 'active';
                          return (
                            <div key={node.role} className="integration-arch-node">
                              {idx > 0 && <ArrowRight size={18} className="integration-arch-arrow" />}
                              <div className={`integration-arch-card ${roleClass(node.role)}${node.dimmed ? ' is-dimmed' : ''}`}>
                                <div className="int-arch-card-top">
                                  <div className="int-arch-logo">
                                    {ctype ? <ConnectorLogo type={ctype} size={22} /> : null}
                                  </div>
                                  <span className={`int-arch-role ${roleClass(node.role)}`}>
                                    {roleLabel(node.role)}
                                  </span>
                                </div>
                                <div className="integration-arch-name">{name}</div>
                                <div className="integration-arch-meta">{assetLine(tool, node.binding)}</div>
                                <div className="int-arch-card-foot">
                                  <span className={`int-status-chip${ok ? ' is-ok' : ' is-warn'}`}>
                                    <span className="integration-market-status-dot" />
                                    {dash(status)}
                                  </span>
                                  <button
                                    type="button"
                                    className="export-btn"
                                    disabled={!tool}
                                    onClick={() => openInspect(tool)}
                                  >
                                    <Eye size={12} /> Details
                                  </button>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  );
                })}
              </div>
            )}
          </>
        )}

        {tab === 'compose' && (
          <div className="int-panel int-pipe-stack int-compose-stack">
            <p className="int-filter-meta">
              Select registered connections by name to compose your pipeline. Pipeline names must be unique. Once composed, run a sync below.
            </p>

            <section className="int-card">
              <div className="int-card-head">
                <h3>Compose pipeline</h3>
                <p>Create a pipeline from registered Source, Transform, and Target connections.</p>
              </div>
              <form className="int-form" onSubmit={handleCompose}>
                {composeError && (
                  <div className="int-banner is-error">
                    {typeof composeError === 'string' ? composeError : JSON.stringify(composeError)}
                  </div>
                )}
                <label className="int-field">
                  Pipeline name *
                  <input
                    required
                    value={composeForm.pipeline_name}
                    placeholder="e.g. inventory_etl"
                    onChange={(e) => setComposeForm((f) => ({ ...f, pipeline_name: e.target.value }))}
                  />
                  {isDuplicatePipelineName && (
                    <span style={{ color: '#EF4444', fontSize: 11.5, marginTop: 4, fontWeight: 500 }}>
                      ⚠️ A pipeline named “{composeForm.pipeline_name.trim()}” already exists. Pipeline names must be unique.
                    </span>
                  )}
                </label>
                <div className="int-form-grid">
                  <div className="int-field">
                    <span>Source connection (Origin)</span>
                    <SearchableSelect
                      options={sourceOptions}
                      value={composeForm.source_tool_id}
                      onChange={(val) => setComposeForm((f) => ({ ...f, source_tool_id: val }))}
                      placeholder="Select Source Connection (Optional)…"
                      searchPlaceholder="Search database or warehouse…"
                      allowClear={true}
                    />
                  </div>

                  <div className="int-field">
                    <span>Transform / ETL connection *</span>
                    <SearchableSelect
                      options={etlOptions}
                      value={composeForm.etl_tool_id}
                      onChange={(val) => setComposeForm((f) => ({ ...f, etl_tool_id: val }))}
                      placeholder="Select Transform / ETL Tool *…"
                      searchPlaceholder="Search dbt or ETL tools…"
                      required={true}
                    />
                  </div>

                  <div className="int-field">
                    <span>Target connection (Destination)</span>
                    <SearchableSelect
                      options={targetOptions}
                      value={composeForm.target_tool_id}
                      onChange={(val) => setComposeForm((f) => ({ ...f, target_tool_id: val }))}
                      placeholder="Select Target Connection (Optional)…"
                      searchPlaceholder="Search destination warehouse…"
                      allowClear={true}
                    />
                  </div>
                </div>
                <label className="int-field">
                  Description
                  <input
                    value={composeForm.description}
                    placeholder="Optional business description"
                    onChange={(e) => setComposeForm((f) => ({ ...f, description: e.target.value }))}
                  />
                </label>
                <div className="int-form-actions">
                  <button
                    type="submit"
                    className="int-primary-btn"
                    disabled={composing || isDuplicatePipelineName || !composeForm.pipeline_name.trim() || !composeForm.etl_tool_id}
                  >
                    {composing ? 'Composing…' : 'Compose pipeline'}
                  </button>
                </div>
              </form>
            </section>

            <section className="int-card">
              <div className="int-card-head">
                <h3>Run sync</h3>
                <p>Select a pipeline by name to trigger an on-demand sync, or leave as default.</p>
              </div>
              <form className="int-form" onSubmit={handleSync}>
                <div className="int-field">
                  <span>Pipeline to sync</span>
                  <SearchableSelect
                    options={pipelineSyncOptions}
                    value={syncPipelineName}
                    onChange={(val) => setSyncPipelineName(val)}
                    placeholder="Select pipeline to sync…"
                    searchPlaceholder="Search pipelines by name…"
                    allowClear={true}
                  />
                </div>
                <label className="int-check">
                  <input
                    type="checkbox"
                    checked={syncRefreshDb}
                    onChange={(e) => setSyncRefreshDb(e.target.checked)}
                  />
                  Refresh database snapshots
                </label>
                <div className="int-form-actions">
                  <button type="submit" className="int-primary-btn" disabled={syncing}>
                    <Play size={14} />
                    {syncing ? 'Running…' : 'Run sync'}
                  </button>
                </div>
              </form>
              {(syncing || lastSyncResult) && (
                <p className={`int-sync-msg${lastSyncResult ? (lastSyncResult.ok ? ' is-ok' : ' is-fail') : ''}`}>
                  {syncing && !lastSyncResult ? 'Sync in progress…' : (lastSyncResult?.message || '')}
                </p>
              )}
            </section>
          </div>
        )}

        {tab === 'directory' && (
          <div className="integration-directory">
            <div className="integration-dir-toolbar">
              <div className="search-box integration-dir-search">
                <Search size={14} />
                <input
                  type="text"
                  placeholder="Search connectors by name, type…"
                  value={dirSearch}
                  onChange={(e) => setDirSearch(e.target.value)}
                />
              </div>
              <div className="integration-category-pills">
                {[
                  { id: 'all', label: `All (${dirCounts.all})` },
                  { id: 'warehouses', label: `Data Warehouses & Lakes (${dirCounts.warehouses})` },
                  { id: 'databases', label: `Databases (${dirCounts.databases})` },
                  { id: 'etl', label: `Transformations & ETL (${dirCounts.etl})` },
                ].map((pill) => (
                  <button
                    key={pill.id}
                    type="button"
                    className={`integration-pill${dirCategory === pill.id ? ' is-active' : ''}`}
                    onClick={() => setDirCategory(pill.id)}
                  >
                    {pill.label}
                  </button>
                ))}
              </div>
            </div>

            {loading ? (
              <LoadingSpinner label="Loading connector directory…" />
            ) : filteredDirectory.length === 0 ? (
              <div className="int-empty">
                <p>No connectors match your search{dirCategory !== 'all' ? ' in this category' : ''}.</p>
              </div>
            ) : (
              DIR_SECTIONS.filter((section) => (
                (dirCategory === 'all' || dirCategory === section.id)
                && directoryBySection[section.id]?.length > 0
              )).map((section) => {
                const items = directoryBySection[section.id] || [];
                const Icon = section.icon;
                return (
                  <section key={section.id} className="integration-directory-panel">
                    <div className="integration-section-header">
                      <div className="integration-section-title-row">
                        <div
                          className="integration-section-icon"
                          style={{ background: section.iconBg, color: section.iconColor }}
                        >
                          <Icon size={16} />
                        </div>
                        <div>
                          <h3 className="integration-section-title">{section.title}</h3>
                          <p className="integration-section-subtitle">{section.subtitle}</p>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="integration-section-link"
                        onClick={() => setDirCategory(section.id)}
                      >
                        {items.length} connector{items.length === 1 ? '' : 's'}
                        <ArrowRight size={14} />
                      </button>
                    </div>

                    <div className="integration-marketplace-grid">
                      {items.map((entry) => (
                        <article key={entry.id} className="integration-market-card">
                          <div className="integration-market-card-top">
                            <div
                              className="integration-market-logo"
                              style={{
                                borderColor: `${entry.color}44`,
                                background: `${entry.color}12`,
                              }}
                            >
                              <ConnectorLogo type={entry.id} size={28} />
                            </div>
                            <span className={`integration-market-status${entry.connected ? ' is-connected' : ''}`}>
                              <span className="integration-market-status-dot" />
                              {entry.connected > 0
                                ? `Connected (${entry.connected})`
                                : 'Available'}
                            </span>
                          </div>
                          <div className="integration-market-title">{entry.label}</div>
                          <p className="integration-market-desc">{entry.desc}</p>
                          <button
                            type="button"
                            className="integration-connect-btn"
                            onClick={() => openAdd(entry.id)}
                          >
                            Connect
                            <ArrowRight size={14} />
                          </button>
                        </article>
                      ))}
                    </div>
                  </section>
                );
              })
            )}
          </div>
        )}

        {addOpen && (
          <div className="modal-backdrop" onClick={closeAdd}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
              <div className="modal-header">
                <div>
                  <div style={{ fontWeight: 700 }}>
                    {registerResult ? 'Connection registered' : 'Add connection'}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {registerResult
                      ? 'Copy the IDs below for Compose & Sync'
                      : 'Fill fields from the API CreateToolRequest example for this connector'}
                  </div>
                </div>
                <button type="button" className="icon-btn" disabled={savingTool} onClick={closeAdd}>
                  <X size={16} />
                </button>
              </div>

              {registerResult ? (
                <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  <div className="int-banner is-ok" style={{ margin: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                    <div>
                      Registered <strong>{registerResult.name}</strong>
                      {' · '}
                      {labelForType(registerResult.connector_type)}
                      {' · '}
                      {roleLabel(registerResult.role)}
                    </div>
                    {registerResult.verified && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: '#DCFCE7', color: '#166534', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700 }}>
                        <CheckCircle2 size={12} /> Credentials &amp; Permissions Verified
                      </span>
                    )}
                  </div>

                  <div className="int-register-result">
                    {[
                      { key: 'tool_id', label: 'tool_id', value: registerResult.tool_id },
                      { key: 'connection_id', label: 'connection_id', value: registerResult.connection_id },
                      { key: 'name', label: 'name', value: registerResult.name },
                      { key: 'connector_type', label: 'connector_type', value: registerResult.connector_type },
                      { key: 'kind', label: 'kind', value: registerResult.kind },
                      { key: 'role', label: 'role', value: roleLabel(registerResult.role) },
                      { key: 'status', label: 'status', value: registerResult.status },
                    ].filter((row) => row.value).map((row) => (
                      <div key={row.key} className="int-register-row">
                        <div className="int-register-label">{row.label}</div>
                        <button
                          type="button"
                          className="int-id-btn"
                          onClick={() => copyText(String(row.value))}
                          title="Copy"
                        >
                          <code>{String(row.value)}</code>
                          {copiedId === String(row.value) ? <Check size={12} /> : <Copy size={12} />}
                        </button>
                      </div>
                    ))}
                  </div>

                  <pre className="int-pre" style={{ maxHeight: 160, margin: 0 }}>
                    {JSON.stringify(registerResult.raw, null, 2)}
                  </pre>

                  <div className="int-form-actions">
                    <button
                      type="button"
                      className="export-btn"
                      onClick={() => {
                        closeAdd();
                        setTab('connections');
                      }}
                    >
                      View Connections
                    </button>
                    <button
                      type="button"
                      className="int-primary-btn"
                      onClick={() => {
                        const keepType = registerResult.connector_type;
                        setRegisterResult(null);
                        setConnectionName('');
                        setFormValues({});
                        setConnectTypeId(keepType);
                        setConnectLocked(true);
                        setConnectionRole(defaultRoleForConnector(
                          connectorTypes.find((t) => t.id === keepType) || { id: keepType },
                        ));
                      }}
                    >
                      Register another
                    </button>
                  </div>
                </div>
              ) : (
                <form className="modal-body int-wizard-form" onSubmit={handleSaveTool}>
                  {saveError && (
                    <div className="int-banner is-error">
                      {typeof saveError === 'string' ? saveError : JSON.stringify(saveError)}
                    </div>
                  )}

                  {testingCreds && (
                    <div className="int-banner is-warn" style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0' }}>
                      <LoadingSpinner size={13} inline />
                      <span>Verifying credentials &amp; checking permissions on remote endpoint…</span>
                    </div>
                  )}

                  {credTestResult?.ok && (
                    <div className="int-banner is-ok" style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '8px 0', border: '1px solid #A7F3D0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, color: '#065F46' }}>
                        <CheckCircle2 size={16} color="#059669" />
                        Credentials &amp; Permissions Verified Successfully
                      </div>
                      <div style={{ fontSize: 12, color: '#065F46' }}>
                        {credTestResult.message || 'Remote authentication succeeded with required access privileges.'}
                      </div>
                      {credTestResult.permissions && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                          {Object.entries(credTestResult.permissions).map(([perm, status]) => (
                            <span key={perm} style={{ fontSize: 11, background: '#DCFCE7', color: '#166534', padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
                              ✓ {perm.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {credTestError && (
                    <div className="int-banner is-error" style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '8px 0', border: '1px solid #FECACA' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, color: '#991B1B' }}>
                        <AlertCircle size={16} color="#DC2626" />
                        Verification Failed: Invalid Credentials or Missing Permissions
                      </div>
                      <div style={{ fontSize: 12, color: '#991B1B', wordBreak: 'break-word' }}>
                        {credTestError}
                      </div>
                    </div>
                  )}

                  <div className="int-field">
                    <span>Connector</span>
                    {connectLocked && selectedType ? (
                      <div className="int-connector-locked">
                        <ConnectorLogo type={selectedType.id} size={28} />
                        <div>
                          <div style={{ fontWeight: 700 }}>{selectedType.label || labelForType(selectedType.id)}</div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                            {isTransformConnector(selectedType) ? 'Transform / ETL' : 'Database / Warehouse'}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <select
                        required
                        value={connectTypeId}
                        onChange={(e) => applyConnectorChange(e.target.value)}
                      >
                        <option value="">Select connector…</option>
                        {dbWarehouseTypes.length > 0 && (
                          <optgroup label="Databases & Warehouses (Source / Target)">
                            {dbWarehouseTypes.map((t) => (
                              <option key={t.id} value={t.id}>{t.label}</option>
                            ))}
                          </optgroup>
                        )}
                        {transformTypes.length > 0 && (
                          <optgroup label="Transform tools (ETL only)">
                            {transformTypes.map((t) => (
                              <option key={t.id} value={t.id}>{t.label}</option>
                            ))}
                          </optgroup>
                        )}
                      </select>
                    )}
                  </div>

                  <label className="int-field">
                    Connection name *
                    <input
                      required
                      value={connectionName}
                      onChange={(e) => setConnectionName(e.target.value)}
                      placeholder="e.g. inventory-source"
                    />
                    {isDuplicateConnectionName && (
                      <span style={{ color: '#EF4444', fontSize: 11.5, marginTop: 4, fontWeight: 500 }}>
                        ⚠️ A connection named “{connectionName.trim()}” already exists. Connection names must be unique.
                      </span>
                    )}
                  </label>

                  <label className="int-field">
                    Role *
                    <select
                      value={connectionRole}
                      onChange={(e) => setConnectionRole(e.target.value)}
                      disabled={!selectedType}
                    >
                      {!selectedType && <option value="">Select a connector first…</option>}
                      {roleOptions.map((r) => (
                        <option key={r.value} value={r.value}>{r.label}</option>
                      ))}
                    </select>
                    <span className="int-field-hint">
                      {isTransformConnector(selectedType)
                        ? 'Transform tools can only be TRANSFORM (ETL).'
                        : 'Databases and warehouses can be SOURCE or TARGET — not ETL.'}
                    </span>
                  </label>

                  {typeFields.map((field) => (
                    <label key={field.key} className="int-field">
                      {field.label}{field.required ? ' *' : ''}
                      {field.type === 'textarea' ? (
                        <textarea
                          required={field.required}
                          placeholder={field.placeholder || ''}
                          value={formValues[field.key] || ''}
                          onChange={(e) => setFormValues((v) => ({ ...v, [field.key]: e.target.value }))}
                        />
                      ) : (
                        <input
                          type={field.type === 'password' ? 'password' : 'text'}
                          required={field.required}
                          placeholder={field.placeholder || ''}
                          value={formValues[field.key] || ''}
                          onChange={(e) => setFormValues((v) => ({ ...v, [field.key]: e.target.value }))}
                        />
                      )}
                    </label>
                  ))}

                  <div className="int-form-actions">
                    <button type="button" className="export-btn" disabled={savingTool || testingCreds} onClick={closeAdd}>Cancel</button>
                    <button
                      type="button"
                      className="export-btn"
                      disabled={testingCreds || savingTool || !selectedType}
                      onClick={handleTestCredentials}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    >
                      {testingCreds ? <LoadingSpinner size={12} inline /> : <ShieldCheck size={14} color="#0284C7" />}
                      {testingCreds ? 'Testing…' : 'Test Connection'}
                    </button>
                    <button
                      type="submit"
                      className="int-primary-btn"
                      disabled={savingTool || testingCreds || !connectionName.trim() || !selectedType}
                    >
                      {savingTool ? 'Validating & Saving…' : 'Register tool'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}

        {inspectTool && (
          <div className="modal-backdrop" onClick={() => !savingSecret && setInspectTool(null)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
              <div className="modal-header">
                <div>
                  <div style={{ fontWeight: 700 }}>{dash(inspectTool.name)}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {labelForType(String(inspectTool.connector_type || '').toLowerCase())} · {roleFromTool(inspectTool)}
                    {inspectLoading ? ' · loading…' : ''}
                  </div>
                </div>
                <button type="button" className="icon-btn" disabled={savingSecret} onClick={() => setInspectTool(null)}>
                  <X size={16} />
                </button>
              </div>
              <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 4 }}>tool_id</div>
                  <button type="button" className="int-id-btn" onClick={() => copyText(toolIdOf(inspectTool))}>
                    <code>{toolIdOf(inspectTool) || '—'}</code>
                    {copiedId === toolIdOf(inspectTool) ? <Check size={12} /> : <Copy size={12} />}
                  </button>
                </div>
                <pre className="int-pre" style={{ maxHeight: 220 }}>
                  {JSON.stringify(
                    {
                      tool_id: toolIdOf(inspectTool),
                      name: inspectTool.name,
                      connector_type: inspectTool.connector_type,
                      kind: inspectTool.kind,
                      status: inspectTool.status,
                      config: inspectTool.config,
                    },
                    null,
                    2,
                  )}
                </pre>
                <form onSubmit={handleRotateSecret} className="int-wizard-form">
                  <label className="int-field">
                    Rotate secret
                    <input type="password" value={secretDraft} onChange={(e) => setSecretDraft(e.target.value)} placeholder="New password / token" />
                  </label>
                  <div className="int-form-actions">
                    <button type="button" className="export-btn" disabled={savingSecret} onClick={() => setInspectTool(null)}>Close</button>
                    <button type="submit" className="int-primary-btn" disabled={savingSecret || !secretDraft.trim()}>
                      {savingSecret ? 'Saving…' : 'Update secret'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
