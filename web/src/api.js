/**
 * API client module for communicating with the StayTrace backend.
 * Uses relative paths by default to leverage Vite development proxy or reverse proxy.
 */

const API_BASE = (import.meta.env.VITE_API_URL || 'https://staytrace-api.onrender.com').replace(/\/$/, '')

export async function checkHealth() {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) {
    throw new Error(`Health check failed (${res.status})`)
  }
  return res.json()
}

export async function trackParcel(trackingNumber, carrier = null) {
  const body = {
    tracking_number: trackingNumber.trim(),
  }
  if (carrier && carrier !== 'auto') {
    body.carrier = carrier
  }

  const res = await fetch(`${API_BASE}/api/track`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })

  const data = await res.json()
  if (!res.ok) {
    const errorMsg = data.error || data.details || `Error tracking package (${res.status})`
    const error = new Error(errorMsg)
    error.status = res.status
    error.data = data
    throw error
  }
  return data
}

export async function listParcels(carrier = '', status = '', limit = 50) {
  const params = new URLSearchParams()
  if (carrier && carrier !== 'all') params.append('carrier', carrier)
  if (status && status !== 'all') params.append('status', status)
  params.append('limit', limit.toString())

  const res = await fetch(`${API_BASE}/api/parcels?${params.toString()}`)
  if (!res.ok) {
    throw new Error(`Failed to list parcels (${res.status})`)
  }
  return res.json()
}

export async function getParcel(trackingNumber) {
  const res = await fetch(`${API_BASE}/api/parcels/${encodeURIComponent(trackingNumber)}`)
  const data = await res.json()
  if (!res.ok) {
    const error = new Error(data.error || `Failed to get parcel (${res.status})`)
    error.status = res.status
    throw error
  }
  return data
}

export async function deleteParcel(trackingNumber) {
  const res = await fetch(`${API_BASE}/api/parcels/${encodeURIComponent(trackingNumber)}`, {
    method: 'DELETE',
  })
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.error || `Failed to delete parcel (${res.status})`)
  }
  return data
}

// ===== Ocean / Container Shipment Tracking =====

export async function trackContainer(containerNumber, shippingLine = null) {
  const body = {
    container_number: containerNumber.trim(),
  }
  if (shippingLine && shippingLine !== 'auto') {
    body.shipping_line = shippingLine
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 60000)

  let res
  try {
    res = await fetch(`${API_BASE}/api/track/container`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') {
      const error = new Error('SOURCE UNAVAILABLE — TRY AGAIN')
      error.timedOut = true
      throw error
    }
    throw err
  } finally {
    clearTimeout(timer)
  }

  const data = await res.json()
  if (!res.ok) {
    const errorMsg = data.error || data.details || `Error tracking shipment (${res.status})`
    const error = new Error(errorMsg)
    error.status = res.status
    error.data = data
    throw error
  }
  return data
}

export async function listContainers(shippingLine = '', status = '', limit = 50) {
  const params = new URLSearchParams()
  if (shippingLine && shippingLine !== 'all') params.append('shipping_line', shippingLine)
  if (status && status !== 'all') params.append('status', status)
  params.append('limit', limit.toString())

  const res = await fetch(`${API_BASE}/api/containers?${params.toString()}`)
  if (!res.ok) {
    throw new Error(`Failed to list containers (${res.status})`)
  }
  return res.json()
}

export async function getContainer(containerNumber) {
  const res = await fetch(`${API_BASE}/api/containers/${encodeURIComponent(containerNumber)}`)
  const data = await res.json()
  if (!res.ok) {
    const error = new Error(data.error || `Failed to get container (${res.status})`)
    error.status = res.status
    throw error
  }
  return data
}

export async function runHealingDemo(scenario = 'redesigned') {
  const res = await fetch(`${API_BASE}/api/demo/heal?scenario=${encodeURIComponent(scenario)}`)
  if (!res.ok) {
    throw new Error(`Self-healing demo failed (${res.status})`)
  }
  return res.json()
}
