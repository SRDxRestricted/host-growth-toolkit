import React from 'react';

export default function ComparableListings({
  comparables,
  onViewMap,
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
          <h4>See neighbouring prices</h4>
          <p>Explore nearby comparable listings on your portfolio map.</p>
        </div>
        <button
          type="button"
          className="btn-secondary competitors-button"
          onClick={onViewMap}
        >
          View nearby map
        </button>
      </div>
    </div>
  );
}
