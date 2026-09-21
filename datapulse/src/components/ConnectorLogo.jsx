const FALLBACK = {
  snowflake: '#29B5E8',
  dbt: '#FF694B',
  dbt_cloud: '#FF694B',
  bigquery: '#669DF6',
  redshift: '#8C4FFF',
  postgres: '#4169E1',
  mysql: '#4479A1',
  airbyte: '#615EFF',
  airflow: '#017CEE',
};

const CONNECTOR_MONO = {
  snowflake: 'SF',
  dbt: 'dbt',
  dbt_cloud: 'dbt',
  bigquery: 'BQ',
  redshift: 'RS',
  postgres: 'PG',
  mysql: 'MY',
  airbyte: 'AB',
  airflow: 'AF',
};

/** Bust browser cache after logo SVG replacements */
const LOGO_VERSION = '3';

export default function ConnectorLogo({ type, size = 24 }) {
  const key = String(type || '').toLowerCase();
  const fileKey = key === 'dbt_cloud' ? 'dbt' : key;
  const src = `/logos/${fileKey}.svg?v=${LOGO_VERSION}`;
  const color = FALLBACK[key] || '#64748B';
  const mono = (CONNECTOR_MONO[key] || String(type || '?').slice(0, 2)).toUpperCase();

  return (
    <span
      style={{
        position: 'relative',
        width: size,
        height: size,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        style={{ objectFit: 'contain', display: 'block' }}
        onError={(e) => {
          e.currentTarget.style.display = 'none';
          const sib = e.currentTarget.nextSibling;
          if (sib) sib.style.display = 'inline-flex';
        }}
      />
      <span
        style={{
          width: size,
          height: size,
          borderRadius: 6,
          background: `${color}22`,
          color,
          fontSize: Math.max(9, size * 0.38),
          fontWeight: 700,
          display: 'none',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        aria-hidden
      >
        {mono}
      </span>
    </span>
  );
}

/** Tiny fallback when SVG missing */
export function ConnectorMonogram({ type, size = 24 }) {
  const key = String(type || '').toLowerCase();
  const label = (CONNECTOR_MONO[key] || String(type || '?').slice(0, 2)).toUpperCase();
  const color = FALLBACK[key] || '#64748B';
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: 6,
        background: `${color}22`,
        color,
        fontSize: Math.max(9, size * 0.38),
        fontWeight: 700,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {label}
    </span>
  );
}
