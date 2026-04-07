/**
 * Returns the base URL for all API calls.
 *
 * When VITE_API_URL is set (e.g. during a Cloudflare deployment where the
 * backend Worker lives on a different origin), that value is used.
 * Otherwise, relative paths are used so that the Vite dev-server proxy and
 * same-origin production setups work without any configuration.
 */
export function apiBase() {
  return import.meta.env.VITE_API_URL || ''
}

/**
 * Construct a full URL for the given API path.
 * @param {string} path – e.g. '/api/members'
 */
export function apiUrl(path) {
  return `${apiBase()}${path}`
}
