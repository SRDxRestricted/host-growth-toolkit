import React from 'react';
import { BedDouble, Bath, MapPin, Star, Users } from 'lucide-react';

const formatCount = (value) => Number.isInteger(value) ? value : Number(value || 0).toFixed(1);

export default function ComparableListings({
  comparables,
  competitors,
  competitorsLoading,
  competitorsError,
  onLoadCompetitors,
  loading,
}) {
  if (loading) {
    return (
      <div className="comparable-listings skeleton-container">
        <div className="skeleton title-skeleton"></div>
        <div className="skeleton row-skeleton"></div>
      </div>
    );
  }

  if (!comparables) return null;

  const median = comparables.medianPrice ?? 180;
  const budget = comparables.p25Price ?? Math.round(median * 0.75);
  const luxury = comparables.p75Price ?? Math.round(median * 1.35);
  const subtitle = comparables.message 
    || (comparables.count ? `${comparables.count} similar listings within ${comparables.radiusKm}km` : 'Based on local market listings');

  return (
    <div className="comparable-listings animate-fade-in-up stagger-3">
      <div className="comparables-header">
        <h3>Nearby comparables</h3>
        <p className="subtitle">{subtitle}</p>
      </div>
      
      <div className="comparables-stats">
        <div className="stat-box">
          <span className="stat-label">Budget</span>
          <span className="stat-value">£{budget}</span>
        </div>
        <div className="stat-box highlight">
          <span className="stat-label">Median</span>
          <span className="stat-value">£{median}</span>
        </div>
        <div className="stat-box">
          <span className="stat-label">Luxury</span>
          <span className="stat-value">£{luxury}</span>
        </div>
      </div>

      <div className="competitors-action-row">
        <div>
          <h4>See your competitors' prices</h4>
          <p>Compare similar local listings before setting your rate.</p>
        </div>
        <button
          type="button"
          className="btn-secondary competitors-button"
          onClick={onLoadCompetitors}
          disabled={competitorsLoading}
        >
          {competitorsLoading ? 'Finding listings…' : competitors ? 'Refresh prices' : "See competitors' prices"}
        </button>
      </div>

      {competitorsError && <p className="competitors-error">{competitorsError}</p>}

      {competitors?.competitors?.length > 0 && (
        <div className="competitor-results" aria-live="polite">
          <p className="competitor-results-note">
            {competitors.message || `${competitors.competitors.length} similar listings found nearby.`}
          </p>
          <div className="competitor-grid">
            {competitors.competitors.map((competitor) => (
              <article className="competitor-card" key={competitor.id}>
                <div className="competitor-card-header">
                  <div>
                    <h4>{competitor.name}</h4>
                    <span className="competitor-location"><MapPin size={14} />{competitor.location}</span>
                  </div>
                  <span className="competitor-price">£{Math.round(competitor.price)}<small>/ night</small></span>
                </div>
                <p className="competitor-type">{competitor.property_type} · {competitor.room_type}</p>
                <div className="competitor-details">
                  <span><BedDouble size={15} />{formatCount(competitor.bedrooms)} bed{Number(competitor.bedrooms) === 1 ? '' : 's'} · {formatCount(competitor.beds)} beds</span>
                  <span><Bath size={15} />{formatCount(competitor.bathrooms)} bath{Number(competitor.bathrooms) === 1 ? '' : 's'}</span>
                  <span><Users size={15} />Sleeps {competitor.accommodates}</span>
                  {competitor.rating && <span><Star size={15} />{competitor.rating} ({competitor.reviews_count || 0})</span>}
                </div>
                {competitor.amenities?.length > 0 && (
                  <div className="competitor-amenities">
                    {competitor.amenities.map((amenity) => <span key={amenity}>{amenity}</span>)}
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
