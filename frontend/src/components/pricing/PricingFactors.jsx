import React from 'react';

export default function PricingFactors({ factors, loading }) {
  if (loading) {
    return (
      <div className="pricing-factors skeleton-container">
        <div className="skeleton title-skeleton"></div>
        <div className="skeleton row-skeleton"></div>
        <div className="skeleton row-skeleton"></div>
      </div>
    );
  }

  if (!factors || factors.length === 0) return null;

  const formatAmount = (amount, isBase) => {
    if (!Number.isFinite(amount)) return null;
    const absolute = Math.abs(amount).toFixed(1).replace(/\.0$/, '');
    return `${isBase || amount === 0 ? '' : amount > 0 ? '+' : '−'}£${absolute}`;
  };

  return (
    <div className="pricing-factors animate-fade-in-up stagger-2">
      <h3>Why this price</h3>
      <div className="factors-list">
        {factors.map((factor, index) => (
          <div key={index} className="factor-item">
            <div className={`impact-dot impact-${factor.impact}`}></div>
            <div className="factor-content">
              <div className="factor-header">
                <span className="factor-label">{factor.label}</span>
                {Number.isFinite(factor.amount)
                  ? <span className={`factor-amount ${factor.impact}`}>{formatAmount(factor.amount, factor.key === 'base')}</span>
                  : factor.pct && <span className={`factor-pct ${factor.pct > 0 ? 'positive' : factor.pct < 0 ? 'negative' : ''}`}>{factor.pct > 0 ? '+' : ''}{Number(factor.pct).toFixed(1)}%</span>}
              </div>
              <div className="factor-detail">{factor.description || factor.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
