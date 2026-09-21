import React, { useState, useEffect } from 'react';
import { fetchPricingRecommendation, fetchPricingCalendar, fetchCompetitorPrices, getProperties } from '../api/pricing';
import NoPropertiesEmptyState from '../components/dashboard/NoPropertiesEmptyState';
import PricingHero from '../components/pricing/PricingHero';
import PricingFactors from '../components/pricing/PricingFactors';
import ComparableListings from '../components/pricing/ComparableListings';
import PricingControls from '../components/pricing/PricingControls';
import PricingCalendar from '../components/pricing/PricingCalendar';
import './PricingPage.css';

export default function PricingPage() {
  const [properties, setProperties] = useState([]);
  const [selectedProperty, setSelectedProperty] = useState(null);
  
  const today = new Date().toISOString().split('T')[0];
  const [selectedDate, setSelectedDate] = useState(today);
  
  const [recommendation, setRecommendation] = useState(null);
  const [calendarData, setCalendarData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [propsLoading, setPropsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [competitors, setCompetitors] = useState(null);
  const [competitorsLoading, setCompetitorsLoading] = useState(false);
  const [competitorsError, setCompetitorsError] = useState(null);

  useEffect(() => {
    async function loadProperties() {
      try {
        const props = await getProperties();
        setProperties(props);
        if (props.length > 0 && (!selectedProperty || !props.find(p => p.id === selectedProperty))) {
          // Prefer the host's active property (e.g. the listing they just
          // created and saved to the database); otherwise the first one.
          const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
          const preferred = user.property_id && props.find(p => p.id === user.property_id)
            ? user.property_id
            : props[0].id;
          setSelectedProperty(preferred);
        }
      } catch (err) {
        console.error("Failed to load properties", err);
      } finally {
        setPropsLoading(false);
      }
    }
    loadProperties();
  }, []);

  useEffect(() => {
    async function loadRecommendation() {
      if (!selectedProperty || !selectedDate) return;
      setLoading(true);
      setError(null);
      try {
        const recData = await fetchPricingRecommendation(selectedProperty, selectedDate);
        setRecommendation(recData);
      } catch (err) {
        setError('Failed to load pricing data. Please try again.');
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    loadRecommendation();
  }, [selectedProperty, selectedDate]);

  useEffect(() => {
    // Comparables are intentionally loaded on demand, so changing a property
    // never leaves another listing's competitors on screen.
    setCompetitors(null);
    setCompetitorsError(null);
  }, [selectedProperty]);

  useEffect(() => {
    async function loadCalendar() {
      if (!selectedProperty) return;
      try {
        const calData = await fetchPricingCalendar(selectedProperty);
        setCalendarData(calData);
      } catch (err) {
        console.error('Failed to load calendar data', err);
      }
    }
    loadCalendar();
  }, [selectedProperty]);

  const handleApplyPrice = (price) => {
    console.log(`Applied price £${price} for ${selectedDate}`);
  };

  const handleLoadCompetitors = async () => {
    if (!selectedProperty || competitorsLoading) return;
    setCompetitorsLoading(true);
    setCompetitorsError(null);
    try {
      setCompetitors(await fetchCompetitorPrices(selectedProperty));
    } catch (err) {
      console.error('Failed to load competitor prices', err);
      setCompetitorsError('Unable to load competitor prices. Please try again.');
    } finally {
      setCompetitorsLoading(false);
    }
  };

  const property = properties.find(p => p.id === selectedProperty) || null;
  const hasNoProperties = !propsLoading && properties.length === 0;

  return (
    <div className="pricing-page animate-fade-in-up">
      {!hasNoProperties && <div className="pricing-header">
        <div className="pricing-controls-row">
          <select 
            value={selectedProperty || ''}
            onChange={(e) => setSelectedProperty(e.target.value)}
            className="property-selector"
          >
            {properties.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input 
            type="date" 
            value={selectedDate} 
            onChange={(e) => setSelectedDate(e.target.value)}
            className="date-picker"
          />
        </div>
      </div>}

      {hasNoProperties ? (
        <NoPropertiesEmptyState />
      ) : <>

      {error && <div className="error-banner">{error}</div>}

      <div className="pricing-content">
        <div className="pricing-main-column">
          <PricingHero recommendation={recommendation} property={property} loading={loading} />
          <PricingFactors factors={recommendation?.factors} loading={loading} />
          <ComparableListings
            comparables={recommendation?.comparables}
            competitors={competitors}
            competitorsLoading={competitorsLoading}
            competitorsError={competitorsError}
            onLoadCompetitors={handleLoadCompetitors}
            loading={loading}
          />
        </div>
        
        <div className="pricing-side-column">
          <PricingControls 
            recommendation={recommendation} 
            property={property}
            selectedDate={selectedDate}
            onApplyPrice={handleApplyPrice}
          />
          <PricingCalendar 
            calendarData={calendarData} 
            selectedDate={selectedDate}
            onDateSelect={setSelectedDate}
            loading={loading}
          />
        </div>
      </div>
      </>}
    </div>
  );
}
