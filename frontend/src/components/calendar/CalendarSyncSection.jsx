import { useEffect, useState, useCallback } from 'react';
import { CalendarDays, Check, Copy, Link as LinkIcon, RefreshCw, AlertCircle, X } from 'lucide-react';
import { getCalendarSync, importCalendarFeed, sanitizeCalendarUrl } from '../../api/calendarSync';
import ErrorBoundary from '../common/ErrorBoundary';
import './CalendarSyncSection.css';

function safeFormatDate(dateStr) {
  if (!dateStr || typeof dateStr !== 'string') return '';
  try {
    const isoString = dateStr.includes('T') ? dateStr : `${dateStr}T00:00:00`;
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  } catch {
    return dateStr;
  }
}

function CalendarSyncContent({ propertyId, onSyncSuccess }) {
  const [sync, setSync] = useState({ export_url: '', blocks: [], imports: [] });
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!propertyId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError('');
      const data = await getCalendarSync(propertyId);
      setSync({
        export_url: data?.export_url || '',
        blocks: Array.isArray(data?.blocks) ? data.blocks : [],
        imports: Array.isArray(data?.imports) ? data.imports : [],
      });
    } catch (err) {
      console.warn('Could not load calendar sync settings:', err);
      setError('Unable to load calendar sync settings. Availability may be out of date.');
    } finally {
      setLoading(false);
    }
  }, [propertyId]);

  useEffect(() => {
    load();
  }, [load]);

  const copyExportUrl = async () => {
    if (!sync?.export_url) return;
    try {
      await navigator.clipboard.writeText(sync.export_url);
      setMessage('Export link copied to clipboard.');
      setError('');
    } catch {
      setError('Could not copy link automatically. Please select and copy manually.');
    }
  };

  const syncNow = async (event) => {
    event.preventDefault();
    const cleanUrl = sanitizeCalendarUrl(url);

    if (!cleanUrl) {
      setError('Please enter a valid iCal feed URL.');
      return;
    }

    setSyncing(true);
    setError('');
    setMessage('');

    try {
      // Safely routed via backend proxy to prevent client-side CORS errors or unhandled rejections
      const result = await importCalendarFeed(propertyId, cleanUrl);

      setSync((current) => ({
        ...current,
        blocks: Array.isArray(result?.blocks) ? result.blocks : (current?.blocks || []),
        imports: [
          ...(current?.imports || []).filter((item) => item?.url !== cleanUrl),
          { url: cleanUrl },
        ],
      }));

      const importedCount = typeof result?.imported === 'number' ? result.imported : 0;
      const skippedCount = typeof result?.skipped_conflicts === 'number' ? result.skipped_conflicts : 0;
      setMessage(
        `Successfully synced ${importedCount} dates${skippedCount ? `; ${skippedCount} conflicts were safely skipped` : ''}.`
      );
      setUrl('');
      if (typeof onSyncSuccess === 'function') {
        onSyncSuccess(result);
      }
    } catch (err) {
      console.error('External iCal sync failed:', err);
      // Graceful error fallback state: notify user without breaking the component or React state
      const fallbackMsg =
        err?.message || 'Failed to sync external feed. Please check the URL and ensure the feed is public.';
      setError(fallbackMsg);
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="glass-card calendar-sync-section">
        <div className="skeleton" style={{ height: '180px' }} />
      </div>
    );
  }

  const blocks = Array.isArray(sync?.blocks) ? sync.blocks : [];
  const imports = Array.isArray(sync?.imports) ? sync.imports : [];

  return (
    <section className="glass-card calendar-sync-section">
      <div className="calendar-sync-heading">
        <div className="calendar-sync-icon">
          <CalendarDays size={18} />
        </div>
        <div>
          <h3>Calendar Sync</h3>
          <p>Keep availability aligned across HostIt and your external booking channels (Google Calendar, Airbnb, etc.).</p>
        </div>
      </div>

      <div className="calendar-sync-grid-row">
        <div className="calendar-export-card">
          <div>
            <label htmlFor="calendar-export-url">HostIt Export Link</label>
            <p>Paste this read-only iCal link into Google Calendar, Apple Calendar, Airbnb, or Vrbo to sync your bookings.</p>
          </div>
          <div className="calendar-export-url">
            <input
              id="calendar-export-url"
              value={sync?.export_url || ''}
              readOnly
              aria-label="HostIt iCal export URL"
            />
            <button type="button" onClick={copyExportUrl} title="Copy export link">
              <Copy size={16} /> Copy
            </button>
          </div>
        </div>

        <div className="calendar-import-card">
          <div>
            <label htmlFor="calendar-import-url">Import External iCal Feed</label>
            <p>Paste an external calendar URL (e.g. Google Calendar or Airbnb) to block dates automatically.</p>
          </div>
          <form className="calendar-import-form" onSubmit={syncNow}>
            <div className="calendar-import-row">
              <span>
                <LinkIcon size={16} />
              </span>
              <input
                id="calendar-import-url"
                type="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://.../basic.ics"
                required
                disabled={syncing}
              />
              <button className="calendar-sync-button" disabled={syncing || !url.trim()} type="submit">
                <RefreshCw size={16} className={syncing ? 'spin' : ''} />
                {syncing ? 'Syncing…' : 'Sync Now'}
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Fallback Toast / Error Notification */}
      {error && (
        <div
          className="calendar-sync-message error"
          role="alert"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            borderRadius: '8px',
            marginTop: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} style={{ color: '#f87171', flexShrink: 0 }} />
            <span style={{ color: '#fca5a5', fontSize: '13.5px' }}>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError('')}
            style={{
              background: 'none',
              border: 'none',
              color: 'rgba(255, 255, 255, 0.6)',
              cursor: 'pointer',
              padding: '2px',
              display: 'flex',
            }}
            aria-label="Dismiss error"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* Success Toast */}
      {message && (
        <div
          className="calendar-sync-message success"
          role="status"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 14px',
            backgroundColor: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid rgba(16, 185, 129, 0.35)',
            borderRadius: '8px',
            marginTop: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Check size={16} style={{ color: '#34d399', flexShrink: 0 }} />
            <span style={{ color: '#6ee7b7', fontSize: '13.5px' }}>{message}</span>
          </div>
          <button
            type="button"
            onClick={() => setMessage('')}
            style={{
              background: 'none',
              border: 'none',
              color: 'rgba(255, 255, 255, 0.6)',
              cursor: 'pointer',
              padding: '2px',
              display: 'flex',
            }}
            aria-label="Dismiss message"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {(blocks.length > 0 || imports.length > 0) && (
        <div className="calendar-sync-status">
          <h4>Synced availability</h4>
          {blocks.length > 0 ? (
            <div className="calendar-block-grid">
              {blocks.map((block, idx) => {
                const checkInFormatted = safeFormatDate(block.checkIn);
                const checkOutFormatted = safeFormatDate(block.checkOut);
                const blockKey = block.id || block.remote_uid || `block-${idx}`;

                return (
                  <div className="calendar-block" key={blockKey}>
                    <span>
                      {checkInFormatted && checkOutFormatted
                        ? `${checkInFormatted} – ${checkOutFormatted}`
                        : block.checkIn || 'External hold'}
                    </span>
                    <small>
                      {block.summary || 'Unavailable · external calendar'}
                    </small>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="calendar-sync-muted">No dates are currently blocked by your connected calendars.</p>
          )}
        </div>
      )}
    </section>
  );
}

export default function CalendarSyncSection({ propertyId, onSyncSuccess }) {
  return (
    <ErrorBoundary
      compact
      fallbackTitle="Calendar sync temporarily unavailable"
      fallback={(err, reset) => (
        <div
          className="glass-card calendar-sync-section"
          style={{
            padding: '20px',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            borderRadius: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#f87171' }}>
            <AlertCircle size={20} />
            <h4 style={{ margin: 0 }}>Calendar Sync Error</h4>
          </div>
          <p style={{ margin: '8px 0 14px 0', fontSize: '13.5px', color: 'rgba(255, 255, 255, 0.75)' }}>
            Failed to display calendar sync. Please check your network connection or try reloading this section.
          </p>
          <button
            type="button"
            onClick={reset}
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
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      )}
    >
      <CalendarSyncContent propertyId={propertyId} onSyncSuccess={onSyncSuccess} />
    </ErrorBoundary>
  );
}
