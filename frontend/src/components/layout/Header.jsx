import { useState, useEffect, useRef } from 'react'
import { MessageCircle, ChevronDown, X, Copy, Check } from 'lucide-react'
import { getProperties } from '../../api/pricing'

function Header() {
  const [propertyName, setPropertyName] = useState('');
  const [showWhatsApp, setShowWhatsApp] = useState(false);
  const [copied, setCopied] = useState(false);
  const popoverRef = useRef(null);

  useEffect(() => {
    getProperties().then(props => {
      if (props.length > 0) {
        setPropertyName(props[0].name);
      }
    });
  }, []);

  // Close popover when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setShowWhatsApp(false);
      }
    }
    if (showWhatsApp) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showWhatsApp]);

  const handleCopyNumber = () => {
    navigator.clipboard.writeText('+14155238886');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <header className="header">
      <div className="header-left">
      </div>
      
      <div className="header-right">
        {propertyName && (
          <div className="property-selector">
            <span className="property-name">{propertyName}</span>
            <ChevronDown size={16} style={{ color: "var(--gray-400)" }} />
          </div>
        )}
        <div className="whatsapp-btn-wrapper" ref={popoverRef}>
          <button
            className="icon-btn notification-btn whatsapp-icon-btn"
            onClick={() => setShowWhatsApp(!showWhatsApp)}
            title="Connect to WhatsApp"
          >
            <MessageCircle size={20} />
          </button>

          {showWhatsApp && (
            <div className="whatsapp-popover">
              <div className="whatsapp-popover-header">
                <h4 className="whatsapp-popover-title">Connect to WhatsApp</h4>
                <button className="whatsapp-popover-close" onClick={() => setShowWhatsApp(false)}>
                  <X size={16} />
                </button>
              </div>

              <p className="whatsapp-popover-desc">
                To test live bookings, send a WhatsApp message to our sandbox number:
              </p>

              <div className="whatsapp-phone-row">
                <span className="whatsapp-phone-number">+1 415 523-8886</span>
                <button className="whatsapp-copy-btn" onClick={handleCopyNumber}>
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>

              <div className="whatsapp-code-block">
                <span className="whatsapp-code-label">Send this exact message:</span>
                <code className="whatsapp-code">join shape-pale</code>
              </div>

              <p className="whatsapp-popover-hint">
                After joining, any message you send will appear in the Bookings Queue.
              </p>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

export default Header
