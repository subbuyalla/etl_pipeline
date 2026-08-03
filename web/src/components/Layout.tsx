import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const links = [
  { to: "/", label: "Overview", end: true },
  { to: "/observability", label: "Observability" },
  { to: "/assistants", label: "Assistants" },
  { to: "/incidents", label: "Incidents" },
  { to: "/pipelines", label: "Pipelines" },
  { to: "/datasets", label: "Datasets" },
  { to: "/monitors", label: "Monitors" },
  { to: "/lineage", label: "Lineage" },
  { to: "/connectors", label: "Connectors" },
];

type Props = {
  tenantId: string;
  onTenantChange: (v: string) => void;
  children: ReactNode;
};

export function Layout({ tenantId, onTenantChange, children }: Props) {
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">EO</span>
          <div>
            <strong>Observability</strong>
            <p>ETL reliability</p>
          </div>
        </div>
        <nav className="nav">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <label className="tenant">
          <span>Tenant</span>
          <input value={tenantId} onChange={(e) => onTenantChange(e.target.value)} />
        </label>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
