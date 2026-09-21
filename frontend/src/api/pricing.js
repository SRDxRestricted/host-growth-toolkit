/**
 * Wayzyy API Layer
 * ================
 * Abstraction over data fetching. Currently uses mock data.
 * When the Python/FastAPI backend is ready, swap implementations
 * here without touching any UI components.
 *
 * Every function returns a Promise to match real API behavior.
 */

import {
  host,
  earnings,
} from '../data/mockData';

// Simulate network latency (200-400ms)
const delay = (ms = 300) =>
  new Promise(resolve => setTimeout(resolve, 150 + Math.random() * ms));

// Base URL for the backend API – uses VITE_API_URL in production (Render),
// falls back to localhost for local development.
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function login(email, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Login failed');
  }
  const data = await res.json();
  localStorage.setItem('wayzyy_user', JSON.stringify(data.user));
  return data;
}

export async function signup(userData) {
  const res = await fetch(`${API_BASE}/api/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(userData)
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Signup failed');
  }
  const data = await res.json();
  localStorage.setItem('wayzyy_user', JSON.stringify(data.user || {}));
  return data;
}

export async function setupProperty(propertyData) {
  const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
  if (!user.email) throw new Error('Not logged in');
  
  const res = await fetch(`${API_BASE}/api/properties`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: user.email, ...propertyData })
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Setup failed');
  }
  const data = await res.json();
  user.property_id = data.property_id;
  localStorage.setItem('wayzyy_user', JSON.stringify(user));
  return data;
}

// ─── Host ───────────────────────────────────────────────────────
export async function getHost() {
  await delay(200);
  // In production: GET /api/host/me
  return host;
}

// ─── Properties ─────────────────────────────────────────────────
export async function getProperties() {
  const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
  const query = user.email ? `?email=${encodeURIComponent(user.email)}` : '';
  // Always prefer the backend list for the signed-in host.
  try {
    const res = await fetch(`${API_BASE}/api/properties${query}`);
    if (res.ok) {
      const data = await res.json();
      // An empty successful response means this account has no properties;
      // return it so the Pricing page can render its dedicated empty state.
      if (Array.isArray(data)) return data;
    }
  } catch (err) {
    console.warn('Backend properties unavailable, using fallback', err);
  }

  // A property saved during setup is enough to keep the UI usable if the
  // backend is temporarily unavailable. Never substitute demo properties.
  if (user.property_id || user.property_name) {
    return [{
      id: user.property_id || 'prop_custom_001',
      name: user.property_name || 'My Property',
      address: 'Added Property Location',
      minPrice: 50,
      maxPrice: 1000
    }];
  }

  return [];
}

export async function getProperty(propertyId) {
  const prop = (await getProperties()).find(property => property.id === propertyId);
  if (!prop) throw new Error(`Property ${propertyId} not found`);
  return prop;
}

// ─── Bookings ───────────────────────────────────────────────────
export async function getBookings(propertyId) {
  try {
    const endpoint = propertyId
      ? `/api/properties/${encodeURIComponent(propertyId)}/bookings`
      : '/api/bookings';
    const response = await fetch(endpoint);
    if (response.ok) {
      const data = await response.json();
      const liveBookings = Array.isArray(data.bookings) ? data.bookings : [];
      return propertyId ? liveBookings.filter(booking => booking.propertyId === propertyId) : liveBookings;
    }
  } catch (err) {
    console.warn('Backend bookings unavailable', err);
  }
  return [];
}

export async function getUpcomingBookings() {
  const today = new Date().toISOString().split('T')[0];
  const liveBookings = await getBookings();
  return liveBookings
    .filter(b => b.checkIn >= today)
    .sort((a, b) => a.checkIn.localeCompare(b.checkIn));
}

// ─── Earnings ───────────────────────────────────────────────────
export async function getEarnings() {
  await delay(200);
  // In production: GET /api/earnings/summary
  return earnings;
}

// ─── Pricing ────────────────────────────────────────────────────
const PRICING_API_URL = `${API_BASE}/api/pricing/recommend`;
const COMPETITORS_API_URL = `${API_BASE}/api/pricing/competitors`;
const PRICING_RETRY_ATTEMPTS = 3;
const PRICING_RETRY_DELAY_MS = 300;
const CALENDAR_REQUEST_CONCURRENCY = 5;

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// Keep every dashboard surface on the same display value. The pricing engine
// returns decimal values, while nightly rates are presented as whole pounds.
const toDisplayedPrice = (price) => Math.round(Number(price));

function isValidPricingDate(date) {
  if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
  const parsed = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date;
}

async function requestPricingRecommendation(propertyId, date) {
  if (!isValidPricingDate(date)) {
    throw new Error('Choose a valid date before requesting pricing.');
  }

  let lastError;

  for (let attempt = 1; attempt <= PRICING_RETRY_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(PRICING_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ property_id: propertyId, date })
      });

      if (res.ok) return res.json();

      const error = new Error(`API error: ${res.status}`);
      // Bad request and missing-property responses cannot recover through retrying.
      if (res.status < 500 || attempt === PRICING_RETRY_ATTEMPTS) throw error;
      lastError = error;
    } catch (error) {
      lastError = error;
      if (attempt === PRICING_RETRY_ATTEMPTS) {
        throw error;
      }
    }

    await wait(PRICING_RETRY_DELAY_MS * attempt);
  }

  throw lastError;
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex++;
      results[index] = await mapper(items[index]);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, worker)
  );
  return results;
}

export async function fetchPricingRecommendation(propertyId, date) {
  try {
    const user = JSON.parse(localStorage.getItem('wayzyy_user') || '{}');
    // The explicitly selected property (from the DB-backed selector) wins;
    // fall back to the host's active property only when none is given.
    const targetPropertyId = propertyId || user.property_id;
    const data = await requestPricingRecommendation(targetPropertyId, date);
    
    // Transform FastAPI data to match frontend's expected format
    return {
      recommendedPrice: toDisplayedPrice(data.recommended_price),
      priceRange: data.price_range,
      marketPressure: Math.round(data.market_pressure_score),
      demandLevel: data.demand_level,
      adjustmentPct: data.fusion_adjustment_pct || data.adjustment_pct,
      comparables: data.comparables ? {
        count: data.comparables.comparable_count || data.comparable_count || 0,
        radiusKm: data.comparables.message ? (data.comparables.message.match(/within ([\d.]+)km/)?.[1] || 1) : 1,
        message: data.comparables.message || '',
        p25Price: data.comparables.p25_price != null ? Math.round(data.comparables.p25_price) : null,
        medianPrice: data.comparables.median_price != null ? Math.round(data.comparables.median_price) : null,
        p75Price: data.comparables.p75_price != null ? Math.round(data.comparables.p75_price) : null,
      } : null,
      factors: data.factors
        .filter(f => !f.toLowerCase().includes('fusion v2'))
        .map(f => {
          let label = f.split(':')[0];
          let detail = f;
          let impact = 'neutral';
          let pct = null;
          
          const lowerF = f.toLowerCase();
          
          // Get the ACTUAL pricing adjustment (the last percentage in the string)
          const allPcts = [...f.matchAll(/([+-]\d+(\.\d+)?)%/g)];
          if (allPcts.length > 0) {
            pct = parseFloat(allPcts[allPcts.length - 1][1]);
          }
          
          if (pct > 0) impact = 'positive';
          else if (pct < 0) impact = 'negative';

          // Host-friendly rewrites
          if (lowerF.includes('base price') || lowerF.includes('random forest')) {
            label = 'Base property value';
            detail = 'Calculated from your property attributes and location.';
            pct = null; // Base price has no adjustment %
            impact = 'neutral';
          } else if (lowerF.includes('comp') || lowerF.includes('median')) {
            label = 'Local competition';
            detail = 'Based on prices of similar listings in your area.';
          } else if (lowerF.includes('mps') || lowerF.includes('pressure')) {
            label = 'Market demand';
            detail = 'Traveler interest and availability for these dates.';
          } else if (lowerF.includes('weekend')) {
            label = 'Weekend premium';
            detail = 'Higher typical demand for weekend stays.';
          } else if (lowerF.includes('event')) {
            const nameMatch = f.match(/\(([^)]+)\)/);
            const eventName = nameMatch ? nameMatch[1] : 'Local event';
            label = eventName;
            detail = `Higher demand expected due to ${eventName}.`;
          } else if (lowerF.includes('seasonality')) {
            label = 'Seasonality';
            detail = 'Typical demand for this time of year.';
          }
          
          return {
            label,
            detail,
            impact,
            pct
          };
        }),
      seasonality: data.seasonality_context,
      eventContext: data.event_active ? `${data.event_name} (${data.event_type})` : null
    };
  } catch (err) {
    console.error("FastAPI backend failed", err);
    throw err;
  }
}

export async function fetchCompetitorPrices(propertyId) {
  const res = await fetch(COMPETITORS_API_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ property_id: propertyId, limit: 4 }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || 'Unable to load comparable listings.');
  }

  return res.json();
}

const calendarCache = new Map();

function toPricingCalendarDay(day) {
  const [y, m, dy] = day.date.split('-').map(Number);
  const date = new Date(y, m - 1, dy);

  return {
    date: day.date,
    dayOfWeek: date.getDay(),
    isWeekend: date.getDay() === 5 || date.getDay() === 6,
    recommendedPrice: toDisplayedPrice(day.recommended_price),
    basePrice: toDisplayedPrice(day.base_price),
    marketPressure: Math.round(day.market_pressure_score),
    demandLevel: day.demand_level,
    event: day.event_active ? { name: day.event_name || 'Event' } : null,
  };
}

function toDateString(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

export async function fetchPricingCalendar(propertyId, startDate, days = 35) {
  const targetStartDate = startDate || new Date().toISOString().split('T')[0];
  const cacheKey = `${propertyId}:${targetStartDate}:${days}`;
  if (calendarCache.has(cacheKey)) {
    return calendarCache.get(cacheKey);
  }

  // Fast path: Single batch request to FastAPI /api/pricing/calendar
  try {
    const res = await fetch(`${API_BASE}/api/pricing/calendar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        property_id: propertyId,
        start_date: targetStartDate,
        days: days || 35,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.calendar)) {
        const transformed = data.calendar.map(toPricingCalendarDay);
        calendarCache.set(cacheKey, transformed);
        return transformed;
      }
    }
  } catch (err) {
    console.warn('Fast calendar endpoint unavailable, falling back', err);
  }

  // If the batch endpoint is unavailable, use the same per-date recommendation
  // endpoint used by the Pricing tab. Do not synthesize calendar prices: that
  // would make the two tabs disagree.
  try {
    const [y, m, dy] = targetStartDate.split('-').map(Number);
    const start = new Date(y, m - 1, dy);
    const dates = Array.from(
      { length: days || 35 },
      (_, index) => toDateString(new Date(start.getFullYear(), start.getMonth(), start.getDate() + index))
    );
    const fallbackResults = await mapWithConcurrency(
      dates,
      CALENDAR_REQUEST_CONCURRENCY,
      async (date) => {
        const recommendation = await fetchPricingRecommendation(propertyId, date);
        const [year, month, day] = date.split('-').map(Number);
        const calendarDate = new Date(year, month - 1, day);
        return {
          date,
          dayOfWeek: calendarDate.getDay(),
          isWeekend: calendarDate.getDay() === 5 || calendarDate.getDay() === 6,
          recommendedPrice: recommendation.recommendedPrice,
          basePrice: toDisplayedPrice(recommendation.priceRange?.[0] ?? recommendation.recommendedPrice),
          marketPressure: recommendation.marketPressure,
          demandLevel: recommendation.demandLevel,
          event: recommendation.eventContext ? { name: recommendation.eventContext } : null,
        };
      }
    );
    calendarCache.set(cacheKey, fallbackResults);
    return fallbackResults;
  } catch (fallbackErr) {
    console.error('Calendar fallback failed', fallbackErr);
    return [];
  }
}

export async function fetchPricingOpportunities(propertyId) {
  // Pricing opportunities have no live endpoint yet. Returning an empty list
  // is preferable to showing invented recommendations.
  return [];
}

// ─── Price Update ───────────────────────────────────────────────
export async function applyPrice(propertyId, date, price) {
  await delay(400);
  // In production: POST /api/properties/:id/price
  // Body: { date, price }
  return { success: true, propertyId, date, price };
}

export async function updatePriceBounds(propertyId, minPrice, maxPrice) {
  await delay(300);
  // In production: PATCH /api/properties/:id/price-bounds
  return { success: true, propertyId, minPrice, maxPrice };
}
