/**
 * Server-side proxy so the backend host stays in Vercel env (API_BACKEND_URL).
 *
 * Upstream path is passed as ?__u=/api/v1/... via vercel.json rewrites.
 * (Catch-all /api/bridge/[...path] only matched a single segment on this project.)
 */
export default async function handler(req, res) {
  const base = (process.env.API_BACKEND_URL || '').replace(/\/$/, '');
  if (!base) {
    res.status(500).json({
      ok: false,
      error: 'API_BACKEND_URL is not set in Vercel environment variables',
    });
    return;
  }

  const incoming = new URL(req.url, 'http://localhost');
  let suffix = incoming.searchParams.get('__u') || '';
  if (!suffix) {
    // Direct calls like /api/bridge?__u=... already parsed; also accept path=
    suffix = incoming.searchParams.get('path') || '';
  }
  suffix = String(suffix).replace(/^\/+/, '');
  if (!suffix) {
    res.status(400).json({
      ok: false,
      error: 'Missing upstream path (__u). Use /api/v1/... which rewrites here.',
    });
    return;
  }

  const target = new URL(`${base}/${suffix}`);
  incoming.searchParams.forEach((value, key) => {
    if (key === '__u' || key === 'path') return;
    target.searchParams.append(key, value);
  });

  const headers = { accept: req.headers.accept || 'application/json' };
  if (req.headers['content-type']) headers['content-type'] = req.headers['content-type'];

  const init = { method: req.method, headers };
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.body != null) {
    init.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  }

  try {
    const upstream = await fetch(target, init);
    const text = await upstream.text();
    const contentType = upstream.headers.get('content-type') || 'application/json';
    res.setHeader('content-type', contentType);
    res.status(upstream.status).send(text);
  } catch (err) {
    res.status(502).json({
      ok: false,
      error: 'Upstream API request failed',
      detail: err instanceof Error ? err.message : String(err),
    });
  }
}
