import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getListings } from '../api/listings';
import {
  Plus, Users, BedDouble, Bath, MapPin, Home,
  Image as ImageIcon, Loader2, Sparkles, AlertTriangle, ChevronRight, ExternalLink
} from 'lucide-react';
import './ListingsPage.css';

function AirbnbMark() {
  return <span className="platform-mark platform-mark-airbnb" aria-hidden="true"><img src="https://cdn.simpleicons.org/airbnb/FF385C" alt="" /></span>;
}

function BookingMark() {
  return <span className="platform-mark platform-mark-booking" aria-hidden="true"><img src="https://cdn.simpleicons.org/bookingdotcom/003580" alt="" /></span>;
}

export default function ListingsPage() {
  const navigate = useNavigate();
  const [listings, setListings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    getListings()
      .then(data => {
        if (!mounted) return;
        setListings(data);
        setError(null);
      })
      .catch(err => {
        if (!mounted) return;
        setError(err.message || 'Failed to load listings.');
      })
      .finally(() => mounted && setLoading(false));
    return () => { mounted = false; };
  }, []);

  const renderSpecChip = (icon, label) => (
    <div className="listing-spec">
      {icon}
      <span>{label}</span>
    </div>
  );

  return (
    <div className="listings-page animate-fade-in-up">
      <header className="listings-header">
        <div>
          <h1 className="page-title">Your Listings</h1>
          <p className="page-subtitle">Every property you create appears here, with its specs and photos</p>
          <div className="listing-platform-links" aria-label="Publish your property on other platforms">
            <a
              className="listing-platform-link"
              href="https://www.airbnb.com/host/homes"
              target="_blank"
              rel="noopener noreferrer"
            >
              <AirbnbMark />
              <span>Host on Airbnb</span>
              <ExternalLink size={14} aria-hidden="true" />
            </a>
            <a
              className="listing-platform-link"
              href="https://join.booking.com/"
              target="_blank"
              rel="noopener noreferrer"
            >
              <BookingMark />
              <span>Host on Booking.com</span>
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          </div>
        </div>
        <div className="listings-header-actions">
          <button className="btn-create-listing" onClick={() => navigate('/dashboard/listings/new')}>
            <Plus size={18} />
            Create New Listing
          </button>
        </div>
      </header>

      {loading ? (
        <div className="listings-grid skeleton-container">
          <div className="skeleton" style={{ height: '320px' }}></div>
          <div className="skeleton" style={{ height: '320px' }}></div>
          <div className="skeleton" style={{ height: '320px' }}></div>
        </div>
      ) : error ? (
        <div className="glass-card listings-empty">
          <AlertTriangle size={40} color="#fbbf24" />
          <h3>Couldn't load listings</h3>
          <p>{error}</p>
        </div>
      ) : listings.length === 0 ? (
        <div className="glass-card listings-empty">
          <Home size={48} color="rgba(255,255,255,0.4)" />
          <h3>No listings yet</h3>
          <p>Create your first listing with Wayzyy AI and it will show up here.</p>
          <button className="btn-create-listing" onClick={() => navigate('/dashboard/listings/new')}>
            <Sparkles size={18} />
            Create Listing
          </button>
        </div>
      ) : (
        <div className="listings-grid">
          {listings.map(listing => (
            <div
              key={listing.id}
              className="listing-card glass-card animate-fade-in-up"
              onClick={() => navigate(`/dashboard/listings/${listing.id}`)}
            >
              <div className="listing-card-photo">
                {listing.photos && listing.photos.length > 0 ? (
                  <img src={listing.photos[0]} alt={listing.name} />
                ) : (
                  <div className="listing-card-photo-placeholder">
                    <ImageIcon size={40} />
                  </div>
                )}
                <span className="listing-card-type">{listing.property_type || 'Property'}</span>
              </div>

              <div className="listing-card-body">
                <h3 className="listing-card-title">{listing.name}</h3>

                {listing.location && (
                  <p className="listing-card-location">
                    <MapPin size={14} />
                    {listing.location}
                  </p>
                )}

                <div className="listing-card-specs">
                  {renderSpecChip(<Users size={15} />, `${listing.accommodates} guests`)}
                  {renderSpecChip(<BedDouble size={15} />, `${listing.bedrooms} BR`)}
                  {renderSpecChip(<BedDouble size={15} />, `${listing.beds} beds`)}
                  {renderSpecChip(<Bath size={15} />, `${listing.bathrooms} BA`)}
                </div>

                {listing.amenities && listing.amenities.length > 0 && (
                  <div className="listing-card-amenities">
                    {listing.amenities.slice(0, 6).map((a, i) => (
                      <span key={i} className="amenity-chip">{a}</span>
                    ))}
                  </div>
                )}

                {listing.highlights && listing.highlights.length > 0 && (
                  <ul className="listing-card-highlights">
                    {listing.highlights.slice(0, 3).map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                )}

                <div className="listing-card-photos-count">
                  <ImageIcon size={14} />
                  {listing.photos?.length || 0} photo{(listing.photos?.length || 0) === 1 ? '' : 's'}
                </div>

                <span className="listing-card-view">View details <ChevronRight size={14} /></span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
