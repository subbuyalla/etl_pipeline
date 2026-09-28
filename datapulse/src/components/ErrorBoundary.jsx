import React from 'react';
import { AlertTriangle, RotateCcw, Home } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an unhandled rendering error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px 24px',
          maxWidth: 720,
          margin: '40px auto',
          textAlign: 'center',
        }}>
          <div className="card" style={{
            padding: 32,
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: 12,
            background: 'var(--bg-card, #ffffff)',
            boxShadow: '0 8px 30px rgba(0, 0, 0, 0.08)',
          }}>
            <div style={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              background: 'rgba(239, 68, 68, 0.12)',
              color: '#EF4444',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
            }}>
              <AlertTriangle size={28} />
            </div>

            <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
              Something went wrong in this view
            </h2>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20, lineHeight: 1.5 }}>
              An unexpected error occurred while rendering this page. The rest of DataPulse is still running.
            </p>

            {this.state.error && (
              <div style={{
                background: 'rgba(0, 0, 0, 0.05)',
                border: '1px solid var(--border-color, #e2e8f0)',
                borderRadius: 8,
                padding: '12px 16px',
                textAlign: 'left',
                fontSize: 12,
                fontFamily: 'var(--font-mono, monospace)',
                color: '#EF4444',
                marginBottom: 24,
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                <strong>{this.state.error.name}:</strong> {this.state.error.message}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
              <button
                className="btn btn-primary"
                onClick={this.handleReload}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
              >
                <RotateCcw size={15} /> Reload View
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  this.handleReset();
                  window.location.href = '/';
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
              >
                <Home size={15} /> Return to Overview
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
