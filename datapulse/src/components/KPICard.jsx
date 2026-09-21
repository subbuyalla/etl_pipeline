import { TrendingUp, TrendingDown } from 'lucide-react';
import SparkLine from './SparkLine';

export default function KPICard({ icon: Icon, iconClass = 'purple', label, value, delta, deltaLabel, isGoodDown = false, sparkData, sparkColor }) {
  const isPositive = delta > 0;
  const isGood = isGoodDown ? !isPositive : isPositive;

  return (
    <div className="kpi-card fade-in">
      <div className="kpi-card-top">
        <div className={`kpi-icon ${iconClass}`}>
          {Icon && <Icon size={18} />}
        </div>
        <span className="kpi-label">{label}</span>
      </div>
      <div className="kpi-value">{value ?? '—'}</div>
      {delta !== undefined && (
        <div className={`kpi-delta ${isGood ? 'up' : 'down'}`}>
          {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          <span>{delta > 0 ? '+' : ''}{delta}%</span>
          <span className="kpi-delta-label">{deltaLabel ?? 'vs yesterday'}</span>
        </div>
      )}
      {sparkData !== undefined && (
        <div className="sparkline-wrap">
          <SparkLine data={sparkData} color={sparkColor || (isGood ? '#22C55E' : '#EF4444')} />
        </div>
      )}
    </div>
  );
}
