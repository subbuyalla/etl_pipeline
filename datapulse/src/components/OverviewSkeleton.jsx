import React from 'react';

export default function OverviewSkeleton() {
  return (
    <div className="overview-skeleton" style={{ width: '100%', animation: 'fadeIn 0.2s ease' }}>
      {/* 5 KPI Cards Skeleton */}
      <div className="skeleton-kpi-grid">
        {[
          { label: 'Total Pipelines', color: 'rgba(99, 102, 241, 0.12)' },
          { label: 'Pipeline Runs', color: 'rgba(59, 130, 246, 0.12)' },
          { label: 'Success Rate', color: 'rgba(16, 185, 129, 0.12)' },
          { label: 'Failed Runs', color: 'rgba(239, 68, 68, 0.12)' },
          { label: 'Active Alerts', color: 'rgba(245, 158, 11, 0.12)' },
        ].map((item, idx) => (
          <div key={idx} className="skeleton-kpi-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  backgroundColor: item.color,
                }}
              />
              <div className="skeleton-box" style={{ width: 90, height: 13 }} />
            </div>
            <div className="skeleton-box" style={{ width: 100, height: 28, marginTop: 4 }} />
            <div className="skeleton-box" style={{ width: 130, height: 11, opacity: 0.7 }} />
          </div>
        ))}
      </div>

      {/* Observability 4 Pillars Health Skeleton */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div className="skeleton-box" style={{ width: 160, height: 16 }} />
          <div className="skeleton-box" style={{ width: 70, height: 16, borderRadius: 12 }} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          {['Freshness', 'Volume', 'Schema', 'Data Quality'].map((pillar, i) => (
            <div
              key={i}
              className="skeleton-card"
              style={{
                padding: '14px 16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div className="skeleton-box" style={{ width: 10, height: 10, borderRadius: '50%' }} />
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>{pillar}</span>
              </div>
              <div className="skeleton-box" style={{ width: 64, height: 20, borderRadius: 12 }} />
            </div>
          ))}
        </div>
      </div>

      {/* 2 Charts Grid Skeleton */}
      <div className="skeleton-chart-grid">
        <div className="skeleton-card" style={{ height: 320, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
            <div>
              <div className="skeleton-box" style={{ width: 180, height: 16, marginBottom: 6 }} />
              <div className="skeleton-box" style={{ width: 120, height: 12, opacity: 0.7 }} />
            </div>
            <div className="skeleton-box" style={{ width: 80, height: 26, borderRadius: 6 }} />
          </div>
          <div
            className="skeleton-box"
            style={{
              flex: 1,
              width: '100%',
              borderRadius: 8,
              opacity: 0.6,
            }}
          />
        </div>

        <div className="skeleton-card" style={{ height: 320, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
            <div>
              <div className="skeleton-box" style={{ width: 140, height: 16, marginBottom: 6 }} />
              <div className="skeleton-box" style={{ width: 90, height: 12, opacity: 0.7 }} />
            </div>
          </div>
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <div
              className="skeleton-box"
              style={{
                width: 140,
                height: 140,
                borderRadius: '50%',
                opacity: 0.6,
              }}
            />
          </div>
        </div>
      </div>

      {/* Table Skeleton */}
      <div className="skeleton-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <div className="skeleton-box" style={{ width: 160, height: 16, marginBottom: 6 }} />
            <div className="skeleton-box" style={{ width: 220, height: 12, opacity: 0.7 }} />
          </div>
          <div className="skeleton-box" style={{ width: 90, height: 28, borderRadius: 6 }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="skeleton-box" style={{ width: '100%', height: 36, opacity: 0.9 }} />
          {[1, 2, 3, 4, 5].map((row) => (
            <div key={row} className="skeleton-box" style={{ width: '100%', height: 42, opacity: 0.55 }} />
          ))}
        </div>
      </div>
    </div>
  );
}
