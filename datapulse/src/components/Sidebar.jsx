import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, GitBranch, Database, Network,
  AlertTriangle, BarChart2, Bell, FileText, Settings,
  Moon, Layers, PanelLeftClose, Clock, Shield, Activity,
  SlidersHorizontal, ChevronDown, ChevronRight,
} from 'lucide-react';
import { useLayoutEffect, useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';

// ── DataOps (Operations & Delivery) ──────────────────────────────────────────
const DATAOPS_CHILDREN = [
  { icon: GitBranch, label: 'Pipelines', to: '/pipelines' },
  { icon: SlidersHorizontal, label: 'Integrations', to: '/integrations' },
];

// ── Data Observability (Monitoring, Telemetry & Quality Intelligence) ─────────
const OBS_CHILDREN = [
  { icon: LayoutDashboard, label: 'Overview', to: '/observability' },
  { icon: Database, label: 'Assets Catalog', to: '/observability/assets' },
  { icon: Clock, label: 'Freshness', to: '/observability/freshness' },
  { icon: Activity, label: 'Volume', to: '/observability/volume' },
  { icon: Shield, label: 'Data Quality', to: '/observability/data-quality' },
  { icon: Layers, label: 'Schema', to: '/observability/schema' },
  { icon: Network, label: 'Lineage', to: '/observability/lineage' },
  { icon: BarChart2, label: 'Metrics', to: '/metrics' },
  { icon: FileText, label: 'Logs', to: '/logs' },
  { icon: AlertTriangle, label: 'Incidents', to: '/incidents' },
  { icon: Bell, label: 'Alerts', to: '/alerts' },
];

const STORAGE_KEY = 'vithi.sidebarCollapsed';

function readCollapsed() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function applyLayoutCollapsed(collapsed) {
  const layout = document.querySelector('.app-layout');
  if (layout) layout.classList.toggle('is-sidebar-collapsed', collapsed);
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
  } catch {
    /* ignore */
  }
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const location = useLocation();

  const isDataOpsPath =
    location.pathname === '/pipelines' ||
    location.pathname === '/integrations' ||
    location.pathname.startsWith('/dataops');

  const isObsPath =
    location.pathname.startsWith('/observability') ||
    location.pathname === '/metrics' ||
    location.pathname === '/logs' ||
    location.pathname === '/incidents' ||
    location.pathname === '/alerts' ||
    location.pathname === '/data-quality' ||
    location.pathname === '/lineage';

  const [dataOpsOpen, setDataOpsOpen] = useState(false);
  const [obsOpen, setObsOpen] = useState(false);
  const { isDark, toggleTheme } = useTheme();

  useLayoutEffect(() => {
    applyLayoutCollapsed(collapsed);
  }, [collapsed]);

  const openSidebar = (e) => {
    if (e && e.stopPropagation) e.stopPropagation();
    setCollapsed(false);
  };

  const closeSidebar = (e) => {
    if (e && e.stopPropagation) e.stopPropagation();
    setCollapsed(true);
  };

  return (
    <aside className={`sidebar${collapsed ? ' is-collapsed' : ''}`} aria-expanded={!collapsed}>
      <div
        className="sidebar-logo"
        onClick={collapsed ? openSidebar : undefined}
        style={collapsed ? { cursor: 'pointer' } : undefined}
      >
        <button
          type="button"
          className="sidebar-brand"
          onClick={collapsed ? openSidebar : undefined}
          title={collapsed ? 'Expand sidebar' : 'VITHI — DataOps & Observability'}
          aria-label={collapsed ? 'Expand sidebar' : 'VITHI — DataOps & Observability'}
        >
          <div className="sidebar-logo-icon">
            <Database size={16} color="#FFFFFF" />
          </div>
          {!collapsed && (
            <div className="sidebar-logo-text">
              <h1>VITHI</h1>
              <span>DataOps & Observability</span>
            </div>
          )}
        </button>

        {/* Close chip only when sidebar is open */}
        {!collapsed && (
          <button
            type="button"
            className="sidebar-collapse-btn is-close-action"
            onClick={closeSidebar}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose size={16} />
          </button>
        )}
      </div>

      <nav className="sidebar-nav" style={{ paddingTop: 10 }}>
        <ul>
          {/* ── 1. Top Unified Platform Overview ────────────────────── */}
          <li className="nav-item">
            <NavLink
              to="/"
              end
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              title={collapsed ? 'Overview' : undefined}
            >
              <LayoutDashboard size={16} />
              {!collapsed && <span>Overview</span>}
            </NavLink>
          </li>

          <div className="nav-group-divider" style={{ margin: '8px 10px', background: 'var(--border)' }} />

          {/* ── 2. DataOps (Collapsible Dropdown: Pipelines, Integrations) ── */}
          <li className="nav-item">
            <button
              type="button"
              className={`nav-link${isDataOpsPath ? ' active' : ''}`}
              onClick={() => {
                if (collapsed) setCollapsed(false);
                setDataOpsOpen(o => !o);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                width: '100%',
                cursor: 'pointer',
              }}
              title={collapsed ? 'DataOps (Pipelines, Integrations)' : (dataOpsOpen ? 'Collapse DataOps' : 'Expand DataOps')}
              aria-expanded={dataOpsOpen}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <GitBranch size={16} />
                {!collapsed && <span>DataOps</span>}
              </div>
              {!collapsed && (
                <span style={{ display: 'flex', alignItems: 'center', color: 'var(--text-secondary)' }}>
                  {dataOpsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
              )}
            </button>

            {/* Nested DataOps Items */}
            {!collapsed && dataOpsOpen && (
              <ul className="nav-sub">
                {DATAOPS_CHILDREN.map((child) => {
                  const ChildIcon = child.icon;
                  return (
                    <li key={child.to}>
                      <NavLink
                        to={child.to}
                        className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                        style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                      >
                        {ChildIcon && <ChildIcon size={13} style={{ opacity: 0.8 }} />}
                        <span>{child.label}</span>
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>

          <div className="nav-group-divider" style={{ margin: '8px 10px', background: 'var(--border)' }} />

          {/* ── 3. Data Observability (Collapsible Dropdown: Closed by default) ── */}
          <li className="nav-item" style={{ marginTop: 2 }}>
            <button
              type="button"
              className={`nav-link${isObsPath ? ' active' : ''}`}
              onClick={() => {
                if (collapsed) setCollapsed(false);
                setObsOpen(o => !o);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                width: '100%',
                cursor: 'pointer',
              }}
              title={collapsed ? 'Data Observability' : (obsOpen ? 'Collapse Data Observability' : 'Expand Data Observability')}
              aria-expanded={obsOpen}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Database size={16} />
                {!collapsed && <span>Data Observability</span>}
              </div>
              {!collapsed && (
                <span style={{ display: 'flex', alignItems: 'center', color: 'var(--text-secondary)' }}>
                  {obsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
              )}
            </button>

            {/* Nested Observability Items: Overview & 5 Pillars First, Telemetry After */}
            {!collapsed && obsOpen && (
              <ul className="nav-sub">
                {OBS_CHILDREN.map((child) => {
                  const ChildIcon = child.icon;
                  return (
                    <li key={child.to}>
                      <NavLink
                        to={child.to}
                        end={child.to === '/observability'}
                        className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                        style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                      >
                        {ChildIcon && <ChildIcon size={13} style={{ opacity: 0.8 }} />}
                        <span>{child.label}</span>
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>

          <div className="nav-group-divider" style={{ margin: '8px 10px', background: 'var(--border)' }} />

          {/* ── 4. Platform Settings ── */}
          <li className="nav-item">
            <NavLink
              to="/settings"
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              title={collapsed ? 'Settings' : undefined}
            >
              <Settings size={16} />
              {!collapsed && <span>Settings</span>}
            </NavLink>
          </li>
        </ul>
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-user" title={collapsed ? 'Data Admin' : undefined}>
          <div className="user-avatar">DA</div>
          {!collapsed && (
            <div className="user-info">
              <div className="name">Data Admin</div>
              <div className="role">Workspace Owner</div>
            </div>
          )}
        </div>

        <div
          className={`dark-mode-toggle${collapsed ? ' is-collapsed' : ''}`}
          title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {!collapsed && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Moon size={13} />
              <span>Dark mode</span>
            </div>
          )}
          {collapsed && <Moon size={14} />}
          <div
            className={`toggle-switch ${isDark ? 'on' : ''}`}
            onClick={toggleTheme}
            role="switch"
            aria-checked={isDark}
          />
        </div>

        {!collapsed && (
          <div className="sidebar-version">
            © 2024 VITHI. All rights reserved.<br />v2.1.0
          </div>
        )}
      </div>
    </aside>
  );
}
