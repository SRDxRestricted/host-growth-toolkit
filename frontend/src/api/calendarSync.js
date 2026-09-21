const userEmail = () => {
  try {
    return JSON.parse(localStorage.getItem('wayzyy_user') || '{}').email || '';
  } catch {
    return '';
  }
};

const REQUEST_TIMEOUT_MS = 20000;

async function fetchWithTimeout(resource, options = {}) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal,
    });
    return response;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Sync request timed out. The calendar server took too long to respond.');
    }
    // Handles CORS blocks, DNS failures, offline errors
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new Error('Network error or CORS restriction. The request could not reach the server.');
    }
    throw error;
  } finally {
    clearTimeout(id);
  }
}

async function readResponse(response) {
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }

  if (!response.ok) {
    let message = body.detail || 'Calendar sync request failed.';
    if (response.status === 404) {
      message = 'Property or calendar feed not found.';
    } else if (response.status === 422) {
      message = body.detail || 'Invalid iCal link. Please provide a valid, public calendar URL.';
    } else if (response.status === 502) {
      message = 'Failed to sync external feed. Please check the URL and ensure the calendar is public.';
    }
    throw new Error(message);
  }

  return body;
}

export async function getCalendarSync(propertyId) {
  if (!propertyId) throw new Error('Property ID is required');
  const email = userEmail();
  const response = await fetchWithTimeout(
    `/api/properties/${encodeURIComponent(propertyId)}/calendar-sync?email=${encodeURIComponent(email)}`
  );
  return readResponse(response);
}

export function sanitizeCalendarUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return '';
  let trimmed = rawUrl.trim();
  // Standardize Apple/Google webcal:// schemes to https://
  if (trimmed.startsWith('webcal://')) {
    trimmed = 'https://' + trimmed.slice(9);
  }
  return trimmed;
}

export async function importCalendarFeed(propertyId, rawUrl) {
  if (!propertyId) {
    throw new Error('Property ID is required to sync calendar.');
  }

  const url = sanitizeCalendarUrl(rawUrl);
  if (!url) {
    throw new Error('Please enter a valid iCal feed URL.');
  }

  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    throw new Error('Calendar URL must begin with http:// or https:// (or webcal://).');
  }

  const response = await fetchWithTimeout(`/api/properties/${encodeURIComponent(propertyId)}/calendar-sync/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, email: userEmail() }),
  });

  return readResponse(response);
}
