import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import { Bath, BedDouble, Map, MapPin, Star, Users } from 'lucide-react';
import 'leaflet/dist/leaflet.css';
import { fetchCompetitorPrices, fetchPricingRecommendation, getProperties } from '../api/pricing';
import { getListings } from '../api/listings';
import './PortfolioMapPage.css';

const LONDON_CENTER = [51.5074, -0.1278];

function hasCoordinates(item) {
  return Number.isFinite(Number(item?.latitude)) && Number.isFinite(Number(item?.longitude));
}

function mapAccessKey() {
  const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
  return `hostit:portfolio-map:premium:${user.email || 'guest'}`;
}

function listingHealth(listing) {
  const checks = [
    listing.name,
    listing.property_type && listing.accommodates && listing.bedrooms,
    listing.location || listing.host_neighbourhood || listing.address,
    (listing.photos || []).length >= 3,
    (listing.amenities || []).length >= 3,
    (listing.highlights || []).length >= 3,
    listing.full_description,
  ];
  return Math.round((checks.filter(Boolean).length / checks.length) * 100);
}

function formatCount(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? number : number.toFixed(1);
}

function CompetitorPopup({ competitor }) {
  const priceDifference = Number(competitor.price) - Number(competitor.hostRate || 0);
  const hasHostRate = Number.isFinite(Number(competitor.hostRate)) && Number(competitor.hostRate) > 0;

  return (
    <div className="map-comparable-popup">
      <div className="map-popup-heading">
        <div>
          <p className="map-popup-kicker">Comparable listing</p>
          <strong>{competitor.name}</strong>
          <span className="map-popup-location"><MapPin size={13} />{competitor.location}</span>
        </div>
        <div className="map-popup-price">£{Math.round(competitor.price)}<small>/ night</small></div>
      </div>

      <p className="map-popup-type">{competitor.property_type} · {competitor.room_type}</p>
      <div className="map-popup-specs">
        <span><BedDouble size={14} />{formatCount(competitor.bedrooms)} bd · {formatCount(competitor.beds)} beds</span>
        <span><Bath size={14} />{formatCount(competitor.bathrooms)} bath</span>
        <span><Users size={14} />Sleeps {competitor.accommodates}</span>
        <span><Star size={14} />{competitor.rating} ({competitor.reviews_count || 0})</span>
      </div>

      {competitor.amenities?.length > 0 && (
        <div className="map-popup-amenities">
          {competitor.amenities.slice(0, 4).map((amenity) => <span key={amenity}>{amenity}</span>)}
        </div>
      )}

      <div className="map-popup-footer">
        <span>{competitor.dist_km ? `${competitor.dist_km} km away` : 'Nearby'}</span>
        {hasHostRate && <span>{priceDifference === 0 ? 'Matches your rate' : `${priceDifference > 0 ? '+' : '−'}£${Math.abs(priceDifference).toFixed(0)} vs ${competitor.hostPropertyName}`}</span>}
      </div>
    </div>
  );
}

export default function PortfolioMapPage() {
  const navigate = useNavigate();
  const [hasAccess, setHasAccess] = useState(() => localStorage.getItem(mapAccessKey()) === 'true');
  const [properties, setProperties] = useState([]);
  const [mapData, setMapData] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!hasAccess) return;
    let active = true;
    async function loadMap() {
      setLoading(true);
      setError('');
      try {
        const [hostProperties, savedListings] = await Promise.all([
          getProperties(),
          getListings().catch(() => []),
        ]);
        const enrichedProperties = hostProperties.map((property) => {
          const listing = savedListings.find((item) => item.id === property.id);
          return { ...property, ...(listing || {}), health: listingHealth(listing || property) };
        });
        const mappableProperties = enrichedProperties.filter(hasCoordinates);
        const results = await Promise.all(mappableProperties.map(async (property) => {
          const [pricing, competitorData] = await Promise.all([
            fetchPricingRecommendation(property.id, new Date().toISOString().slice(0, 10)),
            fetchCompetitorPrices(property.id),
          ]);
          return [property.id, { pricing, competitors: competitorData.competitors || [] }];
        }));
        if (active) {
          setProperties(enrichedProperties);
          setMapData(Object.fromEntries(results));
        }
      } catch (err) {
        console.error('Unable to load portfolio map', err);
        if (active) setError('We could not load the map data. Please try again.');
      } finally {
        if (active) setLoading(false);
      }
    }
    loadMap();
    return () => { active = false; };
  }, [hasAccess]);

  const mappableProperties = useMemo(() => properties.filter(hasCoordinates), [properties]);
  const propertyMarkers = mappableProperties.map((property) => ({
    ...property,
    pricing: mapData[property.id]?.pricing,
  }));
  const competitorMarkers = mappableProperties.flatMap((property) =>
    (mapData[property.id]?.competitors || [])
      .filter(hasCoordinates)
      .map((competitor) => ({
        ...competitor,
        propertyId: property.id,
        hostPropertyName: property.name,
        hostRate: mapData[property.id]?.pricing?.recommendedPrice,
      })),
  );

  const unlockMap = () => {
    // Prototype entitlement only. Replace with payment-provider confirmation
    // and backend membership validation before a production billing launch.
    localStorage.setItem(mapAccessKey(), 'true');
    setHasAccess(true);
  };

  if (!hasAccess) {
    return (
      <div className="portfolio-page">
        <section className="portfolio-gate">
          <div className="portfolio-gate-icon"><Map size={22} /></div>
          <p className="portfolio-eyebrow">Premium feature</p>
          <h1>Portfolio map</h1>
          <p>See your London listings and nearby comparable properties in one place.</p>
          <div className="portfolio-gate-price"><strong>€10</strong><span>per month</span></div>
          <div className="portfolio-gate-actions">
            <button className="portfolio-primary-button" onClick={unlockMap}>Pay for membership</button>
            <button className="portfolio-secondary-button" onClick={() => navigate('/dashboard')}>Not interested</button>
          </div>
          <small>Membership checkout is represented locally in this prototype.</small>
        </section>
      </div>
    );
  }

  return (
    <div className="portfolio-page">
      <header className="portfolio-header">
        <div>
          <p className="portfolio-eyebrow">Premium portfolio intelligence</p>
          <h1>Portfolio map</h1>
          <p>London listings and the comparable properties around them.</p>
        </div>
        <div className="portfolio-legend">
          <span><i className="legend-host" />Your listing</span>
          <span><i className="legend-competitor" />Comparable</span>
        </div>
      </header>

      {error && <div className="portfolio-error">{error}</div>}
      {loading && <div className="portfolio-loading">Loading your portfolio map…</div>}
      {!loading && !error && mappableProperties.length === 0 && (
        <div className="portfolio-empty">
          <MapPin size={22} />
          <p>Add a listing with a location to view it on the London map.</p>
        </div>
      )}
      {!loading && !error && mappableProperties.length > 0 && (
        <section className="portfolio-map-card">
          <MapContainer center={LONDON_CENTER} zoom={10} scrollWheelZoom className="portfolio-map">
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {competitorMarkers.map((competitor, index) => (
              <CircleMarker key={`${competitor.propertyId}-${competitor.id}-${index}`} center={[competitor.latitude, competitor.longitude]} radius={6} pathOptions={{ color: '#a8a29e', fillColor: '#57534e', fillOpacity: 0.9, weight: 1 }}>
                <Popup minWidth={300} maxWidth={340}><CompetitorPopup competitor={competitor} /></Popup>
              </CircleMarker>
            ))}
            {propertyMarkers.map((property) => (
              <CircleMarker key={property.id} center={[property.latitude, property.longitude]} radius={10} pathOptions={{ color: '#fff', fillColor: '#c2694d', fillOpacity: 1, weight: 2 }}>
                <Popup>
                  <strong>{property.name}</strong><br />
                  {property.location || property.address}<br />
                  Optimal rate: £{property.pricing?.recommendedPrice ?? '—'} / night<br />
                  Listing health: {property.health}/100<br />
                  Demand: {property.pricing?.demandLevel ? `${property.pricing.demandLevel.charAt(0).toUpperCase()}${property.pricing.demandLevel.slice(1)}` : '—'}
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="portfolio-map-summary">
            <span>{propertyMarkers.length} host listing{propertyMarkers.length === 1 ? '' : 's'}</span>
            <span>{competitorMarkers.length} nearby comparable{competitorMarkers.length === 1 ? '' : 's'}</span>
          </div>
        </section>
      )}
    </div>
  );
}
