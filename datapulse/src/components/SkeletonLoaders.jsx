import React from 'react';

/**
 * Reusable KPI Grid Skeleton
 */
export function KPIGridSkeleton({ count = 4 }) {
  const defaultColors = [
    'rgba(99, 102, 241, 0.12)',
    'rgba(16, 185, 129, 0.12)',
    'rgba(245, 158, 11, 0.12)',
    'rgba(239, 68, 68, 0.12)',
    'rgba(59, 130, 246, 0.12)',
  ];

  return (
    <div className="skeleton-kpi-grid" style={{ marginBottom: 20 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton-kpi-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                backgroundColor: defaultColors[i % defaultColors.length],
              }}
            />
            <div className="skeleton-box" style={{ width: 85, height: 13 }} />
          </div>
          <div className="skeleton-box" style={{ width: 95, height: 28, marginTop: 2 }} />
          <div className="skeleton-box" style={{ width: 130, height: 11, opacity: 0.7 }} />
        </div>
      ))}
    </div>
  );
}

/**
 * Reusable Chart Grid Skeleton
 */
export function ChartGridSkeleton({ count = 2, height = 280 }) {
  return (
    <div
      className="skeleton-chart-grid"
      style={{
        display: 'grid',
        gridTemplateColumns: count === 1 ? '1fr' : 'repeat(auto-fit, minmax(340px, 1fr))',
        gap: 16,
        marginBottom: 20,
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton-card" style={{ height, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
            <div>
              <div className="skeleton-box" style={{ width: 150, height: 15, marginBottom: 6 }} />
              <div className="skeleton-box" style={{ width: 100, height: 11, opacity: 0.7 }} />
            </div>
            <div className="skeleton-box" style={{ width: 70, height: 24, borderRadius: 6 }} />
          </div>
          <div
            className="skeleton-box"
            style={{
              flex: 1,
              width: '100%',
              borderRadius: 8,
              opacity: 0.65,
            }}
          />
        </div>
      ))}
    </div>
  );
}

/**
 * Reusable Table Skeleton
 */
export function TableSkeleton({ rows = 6, cols = 6, showHeader = true }) {
  return (
    <div className="skeleton-card" style={{ width: '100%', marginBottom: 20 }}>
      {showHeader && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <div className="skeleton-box" style={{ width: 170, height: 16, marginBottom: 6 }} />
            <div className="skeleton-box" style={{ width: 210, height: 11, opacity: 0.7 }} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div className="skeleton-box" style={{ width: 120, height: 30, borderRadius: 6 }} />
            <div className="skeleton-box" style={{ width: 80, height: 30, borderRadius: 6 }} />
          </div>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        <div className="skeleton-box" style={{ width: '100%', height: 38, opacity: 0.95, borderRadius: 6 }} />
        {Array.from({ length: rows }).map((_, r) => (
          <div
            key={r}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '10px 12px',
              borderBottom: '1px solid var(--border-subtle, rgba(0,0,0,0.04))',
            }}
          >
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className="skeleton-box"
                style={{
                  height: 16,
                  flex: c === 0 ? 2 : c === 1 ? 2.5 : 1,
                  opacity: 0.65,
                }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Full Dashboard Page Skeleton (KPIs + Charts + Table)
 */
export function DashboardPageSkeleton({ kpiCount = 4, chartCount = 2, tableRows = 5, tableCols = 6 }) {
  return (
    <div className="page-skeleton" style={{ width: '100%', animation: 'fadeIn 0.2s ease' }}>
      {kpiCount > 0 && <KPIGridSkeleton count={kpiCount} />}
      {chartCount > 0 && <ChartGridSkeleton count={chartCount} />}
      {tableRows > 0 && <TableSkeleton rows={tableRows} cols={tableCols} />}
    </div>
  );
}

/**
 * Observability Pillar Dashboard Skeleton
 */
export function ObservabilityDashboardSkeleton({ kpiCount = 4, hasPillars = false }) {
  return (
    <div className="obs-dashboard-skeleton" style={{ width: '100%', animation: 'fadeIn 0.2s ease' }}>
      {hasPillars && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12, marginBottom: 20 }}>
          {['Freshness', 'Volume', 'Schema', 'Quality'].map((p, i) => (
            <div key={i} className="skeleton-card" style={{ padding: '14px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="skeleton-box" style={{ width: 10, height: 10, borderRadius: '50%' }} />
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>{p}</span>
              </div>
              <div className="skeleton-box" style={{ width: 60, height: 20, borderRadius: 12 }} />
            </div>
          ))}
        </div>
      )}
      <KPIGridSkeleton count={kpiCount} />
      <ChartGridSkeleton count={2} height={260} />
      <TableSkeleton rows={5} cols={6} />
    </div>
  );
}
