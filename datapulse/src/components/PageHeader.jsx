import { Calendar, RefreshCw, Download, ChevronDown, Check, X } from 'lucide-react';
import { useState, useMemo, useRef, useEffect } from 'react';
import { clearClientCache } from '../api/client';

/**
 * Controlled date header: parent owns `datePreset` / custom range so Reset Filters
 * and page state stay in sync with the picker UI.
 */
export default function PageHeader({
  title,
  subtitle,
  onRefresh,
  onDateChange,
  latestTimestamp,
  datePreset,
  customStart: customStartProp = '',
  customEnd: customEndProp = '',
  presets: presetsProp,
  hideDateRange = false,
}) {
  const [env, setEnv] = useState('Production');
  const [refreshing, setRefreshing] = useState(false);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [internalPreset, setInternalPreset] = useState(datePreset || 'all');
  const [customStart, setCustomStart] = useState(customStartProp || '');
  const [customEnd, setCustomEnd] = useState(customEndProp || '');
  const popoverRef = useRef(null);

  const isControlled = datePreset !== undefined;
  const selectedPreset = isControlled ? (datePreset || 'all') : internalPreset;

  // Overview passes API presets; other pages omit prop and keep local defaults until updated
  const presets = presetsProp !== undefined
    ? (Array.isArray(presetsProp) ? presetsProp : [])
    : [
        { id: 'all', label: 'All Time' },
        { id: '15m', label: 'Last 15 Minutes' },
        { id: '24h', label: 'Last 24 Hours' },
        { id: '7d', label: 'Last 7 Days' },
        { id: '30d', label: 'Last 30 Days' },
      ];

  useEffect(() => {
    setCustomStart(customStartProp || '');
    setCustomEnd(customEndProp || '');
  }, [customStartProp, customEndProp]);

  useEffect(() => {
    if (isControlled) setInternalPreset(datePreset || 'all');
  }, [isControlled, datePreset]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (popoverRef.current && !popoverRef.current.contains(event.target)) {
        setDatePickerOpen(false);
      }
    }
    if (datePickerOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [datePickerOpen]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      clearClientCache();
      if (onRefresh) await onRefresh();
    } catch (e) {
      console.error('Refresh error:', e);
    } finally {
      setTimeout(() => setRefreshing(false), 700);
    }
  };

  const dateRangeLabel = useMemo(() => {
    if (selectedPreset === 'custom' && customStart && customEnd) {
      return `${customStart} – ${customEnd}`;
    }
    const fromCatalog = presets.find(p => p.id === selectedPreset);
    if (fromCatalog?.label) return fromCatalog.label;

    const end = latestTimestamp ? new Date(latestTimestamp) : new Date();
    if (selectedPreset === '24h') {
      const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
      return `${start.toLocaleDateString([], { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString([], { month: 'short', day: 'numeric' })}`;
    }
    if (selectedPreset === '7d') {
      const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
      return `${start.toLocaleDateString([], { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString([], { month: 'short', day: 'numeric' })}`;
    }
    if (selectedPreset === '30d') {
      const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
      return `${start.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })} – ${end.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`;
    }
    return selectedPreset || 'Select Date Range';
  }, [selectedPreset, customStart, customEnd, latestTimestamp, presets]);

  const handleSelectPreset = (presetId) => {
    if (!isControlled) setInternalPreset(presetId);
    setDatePickerOpen(false);
    if (onDateChange) onDateChange(presetId);
  };

  const handleApplyCustom = () => {
    if (customStart && customEnd) {
      if (!isControlled) setInternalPreset('custom');
      setDatePickerOpen(false);
      if (onDateChange) onDateChange({ start: customStart, end: customEnd });
    }
  };

  return (
    <header className="page-header">
      <div className="page-header-left">
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>

      <div className="page-header-right">
        <div className="header-btn">
          <span style={{ color: 'var(--text-secondary)' }}>Environment:</span>
          <select value={env} onChange={e => setEnv(e.target.value)}>
            <option value="Production">Production</option>
            <option value="Staging">Staging</option>
            <option value="Development">Development</option>
          </select>
        </div>

        {!hideDateRange && (
        <div style={{ position: 'relative' }} ref={popoverRef}>
          <button
            type="button"
            className="header-btn"
            style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}
            onClick={() => setDatePickerOpen(o => !o)}
            title="Click to change date range"
          >
            <span>{dateRangeLabel}</span>
            <Calendar size={14} style={{ color: '#10B981' }} />
            <ChevronDown size={12} style={{ color: 'var(--text-muted)' }} />
          </button>

          {datePickerOpen && (
            <div className="date-picker-popover">
              <div className="date-picker-popover-header">
                <span className="date-picker-popover-title">Date Range Presets</span>
                <button className="date-picker-close-btn" onClick={() => setDatePickerOpen(false)}>
                  <X size={14} />
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {presets.length === 0 ? (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '6px 4px' }}>
                    Loading date presets from API…
                  </div>
                ) : presets.map(p => (
                  <button
                    key={p.id}
                    className={`preset-btn ${selectedPreset === p.id ? 'active' : ''}`}
                    onClick={() => handleSelectPreset(p.id)}
                  >
                    <span>{p.label}</span>
                    {selectedPreset === p.id && <Check size={14} color="#059669" />}
                  </button>
                ))}
              </div>

              <div className="date-picker-divider" />

              <span className="custom-range-label">Custom Range</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  type="date"
                  className="custom-date-input"
                  value={customStart}
                  onChange={e => setCustomStart(e.target.value)}
                />
                <input
                  type="date"
                  className="custom-date-input"
                  value={customEnd}
                  onChange={e => setCustomEnd(e.target.value)}
                />
                <button
                  className="apply-date-btn"
                  onClick={handleApplyCustom}
                  disabled={!customStart || !customEnd}
                >
                  Apply Range
                </button>
              </div>
            </div>
          )}
        </div>
        )}

        <button className="icon-btn" onClick={handleRefresh} title="Refresh data">
          <RefreshCw size={13} className={refreshing ? 'spin' : ''} />
        </button>

        <button className="export-btn" onClick={() => window.print()}>
          <Download size={13} />
          <span>Export</span>
        </button>
      </div>
    </header>
  );
}
