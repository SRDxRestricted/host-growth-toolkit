import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getListing } from '../api/listings';
import {
  ArrowLeft, ChevronLeft, ChevronRight, Check, ShieldCheck,
  MapPin, Users, BedDouble, Bath, Home,
  Image as ImageIcon, AlertTriangle
} from 'lucide-react';
import './ListingDetailPage.css';

export default function ListingDetailPage() {
  const { listingId } = useParams();
  const navigate = useNavigate();
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activePhoto, setActivePhoto] = useState(0);

  useEffect(() => {
    getListing(listingId)
      .then(data => {
        setListing(data);
        setError(null);
      })
      .catch(err => setError(err.message || 'Failed to load listing.'))
      .finally(() => setLoading(false));
  }, [listingId]);

  const photos = listing?.photos || [];
  const specChip = (icon, label) => (
    <div className="listing-detail-spec">
      {icon}
      <span>{label}</span>
    </div>
  );

  const prevPhoto = () => setActivePhoto(p => (p - 1 + photos.length) % photos.length);
  const nextPhoto = () => setActivePhoto(p => (p + 1) % photos.length);

  if (loading) {
    return (
      <div className="listing-detail-page animate-fade-in-up">
        <div className="skeleton-container">
          <div className="skeleton" style={{ height: '420px' }}></div>
          <div className="skeleton" style={{ height: '300px' }}></div>
        </div>
      </div>
    );
  }

  if (error || !listing) {
    return (
      <div className="listing-detail-page animate-fade-in-up">
        <button className="dl-back-btn" onClick={() => navigate('/dashboard/listings')}>
          <ArrowLeft size={18} />
          Back to Listings
        </button>
        <div className="glass-card listing-detail-error">
          <AlertTriangle size={40} color="#fbbf24" />
          <h3>Listing not found</h3>
          <p>{error || 'This listing no longer exists.'}</p>
        </div>
      </div>
    );
  }

  const paragraphs = (listing.full_description || '').split('\n\n').filter(p => p.trim());

  return (
    <div className="listing-detail-page animate-fade-in-up">
      <button className="dl-back-btn" onClick={() => navigate('/dashboard/listings')}>
        <ArrowLeft size={18} />
        Back to Listings
      </button>

      {/* Header */}
      <header className="dl-header">
        <div>
          <h1 className="page-title">{listing.name}</h1>
          {listing.listing_title && listing.listing_title !== listing.name && (
            <p style={{ opacity: 0.75, marginTop: '4px', fontStyle: 'italic' }}>{listing.listing_title}</p>
          )}
          {listing.host_neighbourhood && (
            <p className="dl-location"><MapPin size={16} /> {listing.host_neighbourhood}</p>
          )}
        </div>
        {listing.property_type && (
          <span className="dl-type-badge"><Home size={16} /> {listing.property_type}</span>
        )}
      </header>

      {/* Photo Gallery */}
      <div className="dl-gallery glass-card">
        <div className="dl-gallery-main">
          {photos.length > 0 ? (
            <>
              <img src={photos[activePhoto]} alt={`${listing.name} photo ${activePhoto + 1}`} />
              {photos.length > 1 && (
                <>
                  <button className="dl-gallery-nav prev" onClick={prevPhoto} aria-label="Previous photo">
                    <ChevronLeft size={24} />
                  </button>
                  <button className="dl-gallery-nav next" onClick={nextPhoto} aria-label="Next photo">
                    <ChevronRight size={24} />
                  </button>
                  <span className="dl-gallery-counter">{activePhoto + 1} / {photos.length}</span>
                </>
              )}
            </>
          ) : (
            <div className="dl-gallery-placeholder">
              <ImageIcon size={56} />
              <span>No photos uploaded</span>
            </div>
          )}
        </div>

        {photos.length > 1 && (
          <div className="dl-gallery-thumbs">
            {photos.map((src, i) => (
              <button
                key={i}
                className={`dl-thumb ${i === activePhoto ? 'active' : ''}`}
                onClick={() => setActivePhoto(i)}
              >
                <img src={src} alt={`Thumbnail ${i + 1}`} />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="dl-content">
        {/* Left column */}
        <div className="dl-main-col">
          {/* Specs */}
          <div className="glass-card dl-section">
            <h3>Property Specifications</h3>
            <div className="dl-specs">
              {specChip(<Users size={18} />, `${listing.accommodates} guests`)}
              {specChip(<BedDouble size={18} />, `${listing.bedrooms} bedrooms`)}
              {specChip(<BedDouble size={18} />, `${listing.beds} beds`)}
              {specChip(<Bath size={18} />, `${listing.bathrooms} bathrooms`)}
            </div>
          </div>

          {/* Highlights */}
          {listing.highlights?.length > 0 && (
            <div className="glass-card dl-section">
              <h3>Highlights</h3>
              <ul className="dl-highlights">
                {listing.highlights.map((h, i) => (
                  <li key={i}><Check size={16} className="dl-highlight-check" />{h}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Amenities */}
          {listing.amenities?.length > 0 && (
            <div className="glass-card dl-section">
              <h3>Amenities</h3>
              <div className="dl-amenities">
                {listing.amenities.map((a, i) => (
                  <span key={i} className="amenity-chip">{a}</span>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {listing.full_description && (
            <div className="glass-card dl-section">
              <h3>Full Description</h3>
              {paragraphs.map((para, i) => (
                <p key={i} className="dl-description-para">{para}</p>
              ))}
            </div>
          )}

          {/* Host notes captured when the listing was created */}
          {listing.description_notes && (
            <div className="glass-card dl-section">
              <h3>Host Notes</h3>
              <p className="dl-description-para">{listing.description_notes}</p>
            </div>
          )}

        </div>

        {/* Right column */}
        <div className="dl-side-col">
          {/* Photo QC verdicts */}
          {listing.photo_verdicts?.length > 0 && (
            <div className="glass-card dl-section">
              <h3><ShieldCheck size={18} color="#34d399" /> Photo Quality</h3>
              <div className="dl-verdict-list">
                {listing.photo_verdicts.map((v, i) => (
                  <div key={i} className={`dl-verdict ${v.is_good ? 'good' : 'bad'}`}>
                    {v.is_good ? <Check size={14} /> : <AlertTriangle size={14} />}
                    <span>{v.filename}</span>
                    <span className="dl-verdict-flags">{(v.flags || []).join(', ')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="glass-card dl-section dl-meta">
            <p>Created: {listing.created_at ? new Date(listing.created_at).toLocaleString() : '—'}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
