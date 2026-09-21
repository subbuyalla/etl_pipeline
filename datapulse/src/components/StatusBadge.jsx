export default function StatusBadge({ status }) {
  if (!status) return null;
  const s = String(status).toLowerCase();

  const map = {
    success: 'badge badge-success',
    good: 'badge badge-success',
    fresh: 'badge badge-fresh',
    passed: 'badge badge-success',
    valid: 'badge badge-success',
    running: 'badge badge-running',
    warning: 'badge badge-warning',
    delayed: 'badge badge-delayed',
    investigating: 'badge badge-warning',
    invalid: 'badge badge-warning',
    failed: 'badge badge-danger',
    stale: 'badge badge-stale',
    error: 'badge badge-danger',
    cancelled: 'badge badge-info',
    open: 'badge badge-danger',
    resolved: 'badge badge-success',
    high: 'badge badge-high',
    medium: 'badge badge-medium',
    low: 'badge badge-low',
    critical: 'badge badge-danger',
    poor: 'badge badge-poor',
    'n/a': 'badge badge-info',
  };

  const cls = map[s] || 'badge badge-info';
  return <span className={cls}>{status}</span>;
}
