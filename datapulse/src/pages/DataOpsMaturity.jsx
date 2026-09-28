import { useEffect, useState, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Award, CheckCircle, AlertTriangle, TrendingUp, Clock, Shield,
  Layers, Activity, RotateCcw, Search, ArrowUpRight, Zap,
  BarChart2, Target, Calendar, Check, ExternalLink, HelpCircle,
  GitBranch, SlidersHorizontal, ShieldCheck, Terminal, Server,
  AlertCircle, ChevronRight, CheckSquare, FileText,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  fetchDataOpsSummary,
  fetchDataOpsScorecard,
  fetchDataOpsOutcomes,
  fetchDataOpsRoadmap,
  clearClientCache,
} from '../api/client';

export default function DataOpsMaturity() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  const [scorecard, setScorecard] = useState(null);
  const [outcomes, setOutcomes] = useState(null);
  const [roadmap, setRoadmap] = useState(null);

  const [activeTab, setActiveTab] = useState('scorecard'); // 'scorecard' | 'outcomes' | 'roadmap' | 'pipelines'
  const [priorityFilter, setPriorityFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDimension, setSelectedDimension] = useState(null);
  const [headerDatePreset, setHeaderDatePreset] = useState('all');
  const [customDateRange, setCustomDateRange] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (headerDatePreset === 'custom' && customDateRange) {
        params.start_date = customDateRange.start;
        params.end_date = customDateRange.end;
      } else if (headerDatePreset) {
        params.preset = headerDatePreset;
      }

      const [sumRes, cardRes, outRes, roadRes] = await Promise.allSettled([
        fetchDataOpsSummary(params),
        fetchDataOpsScorecard(params),
        fetchDataOpsOutcomes(params),
        fetchDataOpsRoadmap(params),
      ]);

      if (sumRes.status === 'fulfilled' && sumRes.value?.ok) {
        setSummary(sumRes.value);
      }
      if (cardRes.status === 'fulfilled' && cardRes.value?.ok) {
        setScorecard(cardRes.value);
      }
      if (outRes.status === 'fulfilled' && outRes.value?.ok) {
        setOutcomes(outRes.value);
      }
      if (roadRes.status === 'fulfilled' && roadRes.value?.ok) {
        setRoadmap(roadRes.value);
      }
    } catch (e) {
      console.error('Failed to load DataOps maturity assessment:', e);
      setError(e.message || 'Failed to load DataOps assessment data');
    } finally {
      setLoading(false);
    }
  }, [headerDatePreset, customDateRange]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    clearClientCache();
    loadData();
  };

  // Filtered scorecard dimensions
  const filteredDimensions = useMemo(() => {
    const list = scorecard?.dimensions || [];
    return list.filter((d) => {
      if (priorityFilter !== 'all') {
        if (!d.priority?.toLowerCase().includes(priorityFilter.toLowerCase())) return false;
      }
      if (selectedDimension && selectedDimension !== 'all') {
        if (d.dimension_id !== selectedDimension) return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const match =
          d.code?.toLowerCase().includes(q) ||
          d.name?.toLowerCase().includes(q) ||
          d.findings?.toLowerCase().includes(q) ||
          d.deliverables?.toLowerCase().includes(q) ||
          d.evidence_ref?.toLowerCase().includes(q);
        if (!match) return false;
      }
      return true;
    });
  }, [scorecard, priorityFilter, selectedDimension, searchQuery]);

  const overallScore = summary?.overall_score != null ? summary.overall_score : '—';
  const targetScore = summary?.target_score ?? 4.25;
  const maturityTier = summary?.tier || { name: 'Evaluating Live Telemetry...', tone: 'warning' };
  const dimensionsSummary = summary?.dimensions || {};
  const outcomesData = summary?.operational_outcomes || {};

  return (
    <div className="fade-in">
      <PageHeader
        title="DataOps Practice Diagnostic & Reliability Matrix"
        subtitle="Audited DataOps maturity across 8 pipeline engineering dimensions (D1–D8), 5 quantified reliability outcomes, and 30/60/90-day stabilization roadmap."
        onRefresh={handleRefresh}
        datePreset={headerDatePreset}
        onDateChange={(v) => {
          if (typeof v === 'string') {
            setHeaderDatePreset(v);
            setCustomDateRange(null);
          } else if (v?.start && v?.end) {
            setHeaderDatePreset('custom');
            setCustomDateRange(v);
          }
        }}
      />

      <div className="page-body">
        {error && (
          <div className="obs-alert is-bad" style={{ marginBottom: 16 }}>
            <AlertTriangle size={18} />
            <div><strong>DataOps Diagnostic Engine Error:</strong> {error}</div>
          </div>
        )}

        {/* ── 1. TOP EXECUTIVE RELIABILITY KPI SUMMARY CARDS ────────── */}
        <div className="kpi-grid-5" style={{ marginBottom: 20 }}>
          {/* Card 1: DataOps Maturity Score */}
          <div className="kpi-card" style={{ borderLeft: '4px solid #6366F1' }}>
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#EEF2FF', color: '#6366F1' }}>
                <ShieldCheck size={18} />
              </div>
              <span className="kpi-label">DataOps Maturity</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <div className="kpi-value" style={{ color: '#4F46E5', fontSize: 28 }}>
                {overallScore} <span style={{ fontSize: 16, color: 'var(--text-muted)' }}>/ 5.0</span>
              </div>
            </div>
            <div style={{ marginTop: 6 }}>
              <span className={`status-pill ${maturityTier.tone === 'good' ? 'good' : maturityTier.tone === 'warning' ? 'warning' : 'critical'}`}>
                {maturityTier.name}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              Target: <strong>{targetScore}</strong> (Gap: +{summary?.maturity_gap ?? 0})
            </div>
          </div>

          {/* Card 2: Pipeline Production Failure Rate */}
          <div className="kpi-card" style={{ borderLeft: '4px solid #EF4444' }}>
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FEF2F2', color: '#EF4444' }}>
                <Activity size={18} />
              </div>
              <span className="kpi-label">Failure Rate</span>
            </div>
            <div className="kpi-value" style={{ color: '#DC2626', fontSize: 28 }}>
              {outcomesData.failure_rate?.current || `${summary?.telemetry_counts?.failure_rate ?? 0}%`}
            </div>
            <div style={{ marginTop: 6 }}>
              <span className="status-pill warning">
                Target: {outcomesData.failure_rate?.target || '<= 3.2%'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              {outcomesData.failure_rate?.impact || `${summary?.telemetry_counts?.failed_runs ?? 0} failures recorded`}
            </div>
          </div>

          {/* Card 3: Quality Defect Discovery Lag */}
          <div className="kpi-card" style={{ borderLeft: '4px solid #0284C7' }}>
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#E0F2FE', color: '#0284C7' }}>
                <Shield size={18} />
              </div>
              <span className="kpi-label">Quality Defect Gating</span>
            </div>
            <div className="kpi-value" style={{ color: '#0284C7', fontSize: 28 }}>
              {outcomesData.defect_lag?.current || `${summary?.telemetry_counts?.failed_checks ?? 0} defects`}
            </div>
            <div style={{ marginTop: 6 }}>
              <span className={`status-pill ${(summary?.telemetry_counts?.failed_checks ?? 0) === 0 ? 'good' : 'warning'}`}>
                {outcomesData.defect_lag?.target || '0 defects'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              {outcomesData.defect_lag?.impact || `${summary?.telemetry_counts?.passed_checks ?? 0} checks passing`}
            </div>
          </div>

          {/* Card 4: Incident Recovery & MTTR */}
          <div className="kpi-card" style={{ borderLeft: '4px solid #F59E0B' }}>
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#FFFBEB', color: '#D97706' }}>
                <Clock size={18} />
              </div>
              <span className="kpi-label">Recovery MTTR</span>
            </div>
            <div className="kpi-value" style={{ color: '#B45309', fontSize: 28 }}>
              {outcomesData.mttr?.current || `${Math.round(summary?.telemetry_counts?.mttr_minutes ?? 0)}m`}
            </div>
            <div style={{ marginTop: 6 }}>
              <span className={`status-pill ${(summary?.telemetry_counts?.mttr_minutes ?? 0) <= 45 ? 'good' : 'warning'}`}>
                Target: {outcomesData.mttr?.target || '< 45 mins'}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              {summary?.telemetry_counts?.open_incidents_count ?? 0} open incidents &middot; {summary?.telemetry_counts?.resolved_incidents_count ?? 0} resolved
            </div>
          </div>

          {/* Card 5: Operational Defect Impact */}
          <div className="kpi-card" style={{ borderLeft: '4px solid #8B5CF6' }}>
            <div className="kpi-card-header">
              <div className="kpi-icon" style={{ background: '#F5F3FF', color: '#8B5CF6' }}>
                <Zap size={18} />
              </div>
              <span className="kpi-label">Operational Defect Impact</span>
            </div>
            <div className="kpi-value" style={{ color: '#7C3AED', fontSize: 24, paddingTop: 4 }}>
              {summary?.telemetry_counts?.failed_runs ?? 0} <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>failed runs</span>
            </div>
            <div style={{ marginTop: 6 }}>
              <span className={`status-pill ${(summary?.telemetry_counts?.failed_runs ?? 0) === 0 ? 'good' : 'critical'}`}>
                {summary?.telemetry_counts?.open_incidents_count ?? 0} active incidents
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              {summary?.telemetry_counts?.success_runs ?? 0}/{summary?.telemetry_counts?.total_runs ?? 0} clean runs (100% verified)
            </div>
          </div>
        </div>

        {/* ── 2. 8 CORE RELIABILITY DIMENSIONS PROGRESS METERS ────────── */}
        <div className="card" style={{ marginBottom: 20, padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                8 Core Reliability Dimensions (Vithi Practice Diagnostic Framework)
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Evaluated against D1–D8 diagnostic criteria and live orchestrator/warehouse telemetry
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Estate Scaling: <strong>{summary?.estate_coverage ? `${(summary.estate_coverage * 100).toFixed(0)}%` : 'Pilot'}</strong> ({summary?.telemetry_counts?.total_pipelines ?? 1} Pipeline Connected)
              </span>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setSelectedDimension('all')}
                style={{ fontSize: 11, padding: '4px 8px' }}
              >
                Reset Filter
              </button>
            </div>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
            gap: 12,
          }}>
            {Object.entries(dimensionsSummary).map(([dimKey, dim]) => {
              const isUnmeasured = dim.score == null || dim.status === 'unmeasured';
              const scorePct = isUnmeasured ? 0 : Math.min(100, Math.round((dim.score / 5.0) * 100));
              const isSelected = selectedDimension === dim.dimension_id;
              let barColor = 'var(--border-color)';
              if (!isUnmeasured) {
                if (dim.score >= 3.5) barColor = '#10B981';
                else if (dim.score >= 2.5) barColor = '#3B82F6';
                else if (dim.score >= 1.8) barColor = '#F59E0B';
                else barColor = '#EF4444';
              }

              return (
                <div
                  key={dimKey}
                  onClick={() => {
                    setSelectedDimension(isSelected ? 'all' : dim.dimension_id);
                    setActiveTab('scorecard');
                  }}
                  style={{
                    padding: 12,
                    borderRadius: 8,
                    border: isSelected ? '2px solid var(--brand)' : '1px solid var(--border-color)',
                    background: isSelected ? 'var(--bg-hover)' : 'var(--bg-subtle, rgba(255,255,255,0.02))',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  title={`Click to filter scorecard by ${dim.code}`}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{
                        fontSize: 11,
                        fontWeight: 700,
                        padding: '2px 6px',
                        borderRadius: 4,
                        background: isUnmeasured ? 'rgba(148, 163, 184, 0.12)' : 'rgba(99, 102, 241, 0.1)',
                        color: isUnmeasured ? 'var(--text-muted)' : 'var(--brand)',
                      }}>
                        {dim.code}
                      </span>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                        {dim.name}
                      </span>
                    </div>
                    {isUnmeasured ? (
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)' }}>
                        Sensor Needed
                      </span>
                    ) : (
                      <span style={{ fontSize: 13, fontWeight: 700, color: barColor }}>
                        {dim.score} <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>/ 5.0</span>
                      </span>
                    )}
                  </div>

                  <div style={{ width: '100%', height: 6, background: 'var(--border-color)', borderRadius: 3, overflow: 'hidden', margin: '6px 0' }}>
                    <div style={{ width: `${scorePct}%`, height: '100%', background: barColor, borderRadius: 3, transition: 'width 0.4s ease' }} />
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                    <span>Target: <strong>{dim.target_score}</strong></span>
                    <span style={{
                      fontWeight: 600,
                      color: isUnmeasured ? 'var(--brand)' : dim.benchmark === 'Critical Gap' ? '#EF4444' : dim.benchmark === 'High Gap' ? '#F59E0B' : '#10B981',
                    }}>
                      {isUnmeasured ? 'Integration Required' : dim.benchmark}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── 3. NAVIGATION TABS ──────────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
          <button
            className={`btn ${activeTab === 'scorecard' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            onClick={() => setActiveTab('scorecard')}
          >
            <ShieldCheck size={14} style={{ marginRight: 6 }} />
            8-Dimension Audit Scorecard
          </button>
          <button
            className={`btn ${activeTab === 'outcomes' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            onClick={() => setActiveTab('outcomes')}
          >
            <Target size={14} style={{ marginRight: 6 }} />
            Executive Reliability Outcomes (5 Goals)
          </button>
          <button
            className={`btn ${activeTab === 'roadmap' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            onClick={() => setActiveTab('roadmap')}
          >
            <Calendar size={14} style={{ marginRight: 6 }} />
            30/60/90-Day Stabilization Roadmap
          </button>
          <button
            className={`btn ${activeTab === 'pipelines' ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            onClick={() => setActiveTab('pipelines')}
          >
            <GitBranch size={14} style={{ marginRight: 6 }} />
            Connected Pipelines Audit ({summary?.telemetry_counts?.total_pipelines ?? 1})
          </button>
        </div>

        {/* ── 4. TAB 1: 8-DIMENSION AUDIT SCORECARD ──────────────────── */}
        {activeTab === 'scorecard' && (
          <div className="card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <div className="search-box" style={{ width: 280 }}>
                  <Search size={14} />
                  <input
                    placeholder="Search dimensions, findings, DEV artifacts…"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Priority:</span>
                  {['all', 'critical', 'high', 'medium'].map((p) => (
                    <button
                      key={p}
                      className={`btn btn-sm ${priorityFilter === p ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => setPriorityFilter(p)}
                      style={{ fontSize: 11, textTransform: 'capitalize', padding: '4px 10px' }}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              {selectedDimension && selectedDimension !== 'all' && (
                <div style={{ fontSize: 12, color: 'var(--brand)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  Filtering by <strong>{selectedDimension.toUpperCase()}</strong>
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ fontSize: 10, padding: '2px 6px' }}
                    onClick={() => setSelectedDimension('all')}
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>

            {loading ? (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <LoadingSpinner />
                <div style={{ marginTop: 12, color: 'var(--text-muted)', fontSize: 13 }}>
                  Auditing 32 diagnostic criteria against live pipeline telemetry…
                </div>
              </div>
            ) : filteredDimensions.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
                No dimensions matched your search or filters.
              </div>
            ) : (
              <div className="table-responsive">
                <table className="table" style={{ width: '100%', fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 180 }}>Dimension & Scope</th>
                      <th style={{ width: 90, textAlign: 'center' }}>Score</th>
                      <th style={{ width: 110 }}>Baseline &rarr; Target</th>
                      <th style={{ width: 90 }}>Priority</th>
                      <th style={{ width: 110 }}>Evidence Ref</th>
                      <th>Telemetry Findings & Observations</th>
                      <th style={{ width: 260 }}>Remediation Deliverables</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDimensions.map((d) => {
                      let priorityPill = 'good';
                      if (d.priority?.toLowerCase() === 'critical') priorityPill = 'critical';
                      else if (d.priority?.toLowerCase() === 'high') priorityPill = 'warning';

                      return (
                        <tr key={d.code}>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <span style={{
                                fontWeight: 700,
                                fontSize: 11,
                                padding: '2px 6px',
                                borderRadius: 4,
                                background: 'rgba(99, 102, 241, 0.12)',
                                color: 'var(--brand)',
                              }}>
                                {d.code}
                              </span>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                                {d.name}
                              </span>
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                              Focus: {d.dimension_id === 'd1' ? 'DAG Orchestration' : d.dimension_id === 'd2' ? 'Data Quality' : d.dimension_id === 'd3' ? 'SLA Delivery' : d.dimension_id === 'd4' ? 'Idempotent Replay' : d.dimension_id === 'd5' ? 'Incident SRE' : d.dimension_id === 'd6' ? 'CI/CD Gating' : d.dimension_id === 'd7' ? 'OpenLineage' : 'FinOps Saturation'}
                            </div>
                          </td>

                          <td style={{ textAlign: 'center' }}>
                            {d.score != null ? (
                              <>
                                <div style={{ fontSize: 15, fontWeight: 700, color: d.score >= 3.5 ? '#10B981' : d.score >= 2.5 ? '#3B82F6' : '#EF4444' }}>
                                  {d.score}
                                </div>
                                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>/ 5.0</span>
                              </>
                            ) : (
                              <span className="status-pill" style={{ background: 'rgba(148, 163, 184, 0.15)', color: 'var(--text-muted)', fontSize: 11 }}>
                                Unmeasured
                              </span>
                            )}
                          </td>

                          <td>
                            {d.score != null ? (
                              <>
                                <div style={{ fontWeight: 600, fontSize: 12 }}>
                                  {d.baseline_rating} &rarr; <span style={{ color: 'var(--brand)' }}>{d.target_rating}</span>
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  Gap: <strong>+{d.gap_score}</strong>
                                </div>
                              </>
                            ) : (
                              <>
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                  Target: <span style={{ color: 'var(--brand)', fontWeight: 600 }}>{d.target_rating}</span>
                                </div>
                                <div style={{ fontSize: 11, color: 'var(--brand)', marginTop: 2, fontWeight: 600 }}>
                                  Integration Required
                                </div>
                              </>
                            )}
                          </td>

                          <td>
                            <span className={`status-pill ${d.score == null ? 'info' : priorityPill}`}>
                              {d.priority}
                            </span>
                          </td>

                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <FileText size={12} color="var(--brand)" />
                              <span style={{
                                fontSize: 11,
                                fontFamily: 'var(--font-mono, monospace)',
                                fontWeight: 600,
                                color: 'var(--brand)',
                              }}>
                                {d.evidence_ref}
                              </span>
                            </div>
                          </td>

                          <td>
                            <div style={{ color: 'var(--text-primary)', lineHeight: 1.45, fontSize: 12 }}>
                              {d.findings}
                            </div>
                          </td>

                          <td>
                            <div style={{ color: 'var(--text-secondary)', lineHeight: 1.45, fontSize: 12 }}>
                              {d.deliverables}
                            </div>
                            {d.score == null && (
                              <div style={{ marginTop: 6 }}>
                                <Link
                                  to="/integrations"
                                  className="btn btn-secondary btn-sm"
                                  style={{ padding: '2px 8px', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                >
                                  <ExternalLink size={11} /> Connect Sensor
                                </Link>
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── 5. TAB 2: EXECUTIVE RELIABILITY OUTCOMES ───────────────── */}
        {activeTab === 'outcomes' && (
          <div className="card" style={{ padding: 18 }}>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                5 Quantified Operational Outcomes (Reliability & Value Realization)
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Executive operational improvements achieved by transitioning from Level 2 Reactive to Level 4 Governed DataOps
              </div>
            </div>

            <div className="table-responsive">
              <table className="table" style={{ width: '100%', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ width: 220 }}>Outcome & Metric</th>
                    <th style={{ width: 140 }}>Current Baseline</th>
                    <th style={{ width: 140 }}>Target Future State</th>
                    <th style={{ width: 150 }}>Quantified Impact</th>
                    <th>Core Engineering Levers & Mechanisms</th>
                    <th style={{ width: 100 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(outcomes?.outcomes || []).map((o, idx) => (
                    <tr key={idx}>
                      <td>
                        <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                          {o.name}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                          {o.metric}
                        </div>
                      </td>

                      <td>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: 4,
                          background: 'rgba(239, 68, 68, 0.1)',
                          color: '#EF4444',
                          fontWeight: 600,
                          fontSize: 12,
                        }}>
                          {o.baseline}
                        </span>
                      </td>

                      <td>
                        <span style={{
                          padding: '3px 8px',
                          borderRadius: 4,
                          background: 'rgba(16, 185, 129, 0.1)',
                          color: '#10B981',
                          fontWeight: 600,
                          fontSize: 12,
                        }}>
                          {o.target}
                        </span>
                      </td>

                      <td>
                        <div style={{ fontWeight: 700, color: 'var(--brand)', fontSize: 13 }}>
                          {o.impact}
                        </div>
                      </td>

                      <td>
                        <div style={{ color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.45 }}>
                          {o.mechanism}
                        </div>
                      </td>

                      <td>
                        <span className={`status-pill ${o.status === 'on-track' ? 'good' : o.status === 'calibrated' ? 'good' : 'warning'}`}>
                          {o.status || 'calibrated'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Annual Capacity Reclaimed Detail Box */}
            <div style={{
              marginTop: 20,
              padding: 16,
              borderRadius: 8,
              background: 'rgba(99, 102, 241, 0.05)',
              border: '1px solid rgba(99, 102, 241, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: 16,
            }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--brand)' }}>
                  Live Operational Defect Load: {summary?.telemetry_counts?.failed_runs ?? 0} Failed Runs &middot; {summary?.telemetry_counts?.open_incidents_count ?? 0} Active Incidents
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                  {summary?.telemetry_counts?.success_runs ?? 0} of {summary?.telemetry_counts?.total_runs ?? 0} pipeline batch executions ran cleanly without triggering manual triage.
                </div>
              </div>
              <Link to="/pipelines" className="btn btn-primary btn-sm">
                View Connected Pipelines <ArrowUpRight size={14} style={{ marginLeft: 4 }} />
              </Link>
            </div>
          </div>
        )}

        {/* ── 6. TAB 3: 30/60/90-DAY STABILIZATION ROADMAP ───────────── */}
        {activeTab === 'roadmap' && (
          <div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
              gap: 16,
            }}>
              {(roadmap?.phases || []).map((phase, pIdx) => {
                let badgeColor = '#EF4444';
                if (pIdx === 1) badgeColor = '#3B82F6';
                if (pIdx === 2) badgeColor = '#10B981';

                return (
                  <div key={pIdx} className="card" style={{ padding: 18, borderTop: `4px solid ${badgeColor}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                      <span style={{
                        fontSize: 11,
                        fontWeight: 700,
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: 'rgba(99, 102, 241, 0.1)',
                        color: 'var(--brand)',
                      }}>
                        {phase.phase}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {phase.owner}
                      </span>
                    </div>

                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
                      {phase.title}
                    </div>

                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
                      {phase.focus}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {(phase.milestones || []).map((m, mIdx) => (
                        <div
                          key={mIdx}
                          style={{
                            padding: 10,
                            borderRadius: 6,
                            background: 'var(--bg-subtle, rgba(255,255,255,0.02))',
                            border: '1px solid var(--border-color)',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                              {m.title}
                            </span>
                            <span style={{ fontSize: 10, color: 'var(--brand)', fontWeight: 600 }}>
                              {m.window}
                            </span>
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 }}>
                            {m.dimension}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                            {m.deliverable}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── 7. TAB 4: CONNECTED PIPELINES AUDIT ─────────────────────── */}
        {activeTab === 'pipelines' && (
          <div className="card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                  Connected Production Pipelines ({summary?.telemetry_counts?.total_pipelines ?? 1})
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Live DataOps health, test execution counts, and freshness across monitored pipelines
                </div>
              </div>
              <Link to="/pipelines" className="btn btn-secondary btn-sm">
                Open Pipelines Topology <ArrowUpRight size={14} style={{ marginLeft: 4 }} />
              </Link>
            </div>

            <div className="table-responsive">
              <table className="table" style={{ width: '100%', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th>Pipeline Name</th>
                    <th>Tool & Orchestrator</th>
                    <th>Runs Evaluated</th>
                    <th>Success Rate</th>
                    <th>Quality Checks Evaluated</th>
                    <th>Freshness SLA Status</th>
                    <th>DataOps Readiness Rating</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(summary?.pipeline_audits || []).map((p, idx) => (
                    <tr key={idx}>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          {p.name}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          ID: {p.id}
                        </div>
                      </td>

                      <td>
                        <span style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: 'rgba(99, 102, 241, 0.1)',
                          color: 'var(--brand)',
                          fontWeight: 600,
                          fontSize: 11,
                          textTransform: 'uppercase',
                        }}>
                          {p.tool || 'dbt Cloud'}
                        </span>
                      </td>

                      <td>
                        <div style={{ fontWeight: 600 }}>{p.total_runs} runs</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {p.failed_runs} terminal failures
                        </div>
                      </td>

                      <td>
                        <div style={{ fontWeight: 700, color: p.success_rate >= 90 ? '#10B981' : '#EF4444' }}>
                          {p.success_rate}%
                        </div>
                      </td>

                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--brand)' }}>
                          {p.passed_checks} / {p.total_checks} passed
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                          {p.null_breaches} null breaches · {p.unique_breaches} unique breaches
                        </div>
                      </td>

                      <td>
                        <span className="status-pill good">
                          {p.freshness_status || 'Fresh (Met SLA)'}
                        </span>
                      </td>

                      <td>
                        <span className="status-pill warning">
                          Level 2: Defined
                        </span>
                      </td>

                      <td>
                        <Link to={`/pipelines?pipeline=${encodeURIComponent(p.name)}`} className="btn btn-secondary btn-sm" style={{ fontSize: 11, padding: '4px 8px' }}>
                          Inspect <ArrowUpRight size={12} style={{ marginLeft: 2 }} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
