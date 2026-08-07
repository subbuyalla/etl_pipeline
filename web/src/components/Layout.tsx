import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";

const links = [
  { to: "/", label: "Pipelines", end: true },
  { to: "/connectors", label: "Connectors", end: false },
];

type Props = {
  children: ReactNode;
};

export function Layout({ children }: Props) {
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brand-mark">ES</span>
          <div>
            <strong>ETL Studio</strong>
            <p>Pipelines & connectors</p>
          </div>
        </div>
        <nav className="nav">
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="rail-footer">
          <p className="muted small">
            Attach databases and ETL tools, then build pipelines: source → transform → target.
          </p>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
