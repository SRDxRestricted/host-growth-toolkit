import React from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an unhandled error:', error, errorInfo);
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return typeof this.props.fallback === 'function'
          ? this.props.fallback(this.state.error, this.handleReset)
          : this.props.fallback;
      }

      const isCompact = this.props.compact;
      const title = this.props.fallbackTitle || 'Something went wrong';
      const message = this.state.error?.message || 'An unexpected error occurred while rendering this section.';

      return (
        <div
          className={`glass-card error-boundary-fallback ${isCompact ? 'compact' : ''}`}
          style={{
            padding: isCompact ? '16px' : '28px',
            margin: '16px 0',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            borderRadius: '12px',
            color: 'rgba(255, 255, 255, 0.9)',
          }}
          role="alert"
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                display: 'grid',
                placeItems: 'center',
                backgroundColor: 'rgba(239, 68, 68, 0.2)',
                borderRadius: '8px',
                color: '#f87171',
                flexShrink: 0,
              }}
            >
              <AlertTriangle size={20} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <h4 style={{ margin: '0 0 6px 0', fontSize: isCompact ? '15px' : '17px', color: '#fca5a5' }}>
                {title}
              </h4>
              <p
                style={{
                  margin: '0 0 14px 0',
                  fontSize: '13.5px',
                  color: 'rgba(255, 255, 255, 0.75)',
                  lineHeight: '1.5',
                }}
              >
                {message}
              </p>
              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={this.handleReset}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    fontSize: '13px',
                    fontWeight: 600,
                    color: '#fff',
                    backgroundColor: '#e86420',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                  }}
                >
                  <RefreshCw size={14} /> Try again
                </button>
                {!isCompact && (
                  <button
                    type="button"
                    onClick={() => {
                      window.location.href = '/dashboard';
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '6px 14px',
                      fontSize: '13px',
                      fontWeight: 500,
                      color: 'rgba(255, 255, 255, 0.85)',
                      backgroundColor: 'rgba(255, 255, 255, 0.1)',
                      border: '1px solid rgba(255, 255, 255, 0.2)',
                      borderRadius: '6px',
                      cursor: 'pointer',
                    }}
                  >
                    <Home size={14} /> Dashboard
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
