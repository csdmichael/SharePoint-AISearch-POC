import { createReadStream } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { createServer, STATUS_CODES } from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Static host for the production build (www) on Azure App Service (Node 22 LTS). Node built-ins only.
 * Settings come from static-server.json. PORT and HOST environment variables override the JSON values.
 */

const serverDir = path.dirname(fileURLToPath(import.meta.url));
const appDir = path.resolve(serverDir, '..');
const config = JSON.parse(await readFile(path.join(serverDir, 'static-server.json'), 'utf8'));
const rootDir = path.resolve(appDir, config.root);
const port = resolvePort(process.env.PORT, config.port);
const host = process.env.HOST?.trim() || config.host;

const server = createServer((request, response) => {
  handle(request, response).catch((error) => {
    console.error('Request failed:', error);
    if (response.headersSent) {
      response.destroy();
    } else {
      sendStatus(response, 500);
    }
  });
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
    server.closeIdleConnections();
  });
}

start().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});

async function start() {
  const rootInfo = await statOrNull(rootDir);
  if (!rootInfo?.isDirectory()) {
    throw new Error(`Static root not found: ${rootDir}. Run "npm run build" first.`);
  }
  const indexInfo = await statOrNull(path.join(rootDir, config.index));
  if (!indexInfo?.isFile()) {
    throw new Error(`Index file not found: ${path.join(rootDir, config.index)}.`);
  }
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      console.log(`Serving ${rootDir} on http://${host}:${port}`);
      resolve();
    });
  });
}

async function handle(request, response) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    sendStatus(response, 405, { Allow: 'GET, HEAD' });
    return;
  }

  const pathname = decodePathname(request.url);
  if (pathname === null) {
    sendStatus(response, 400);
    return;
  }

  const relative = pathname.replace(/^\/+/, '');
  const candidate = path.resolve(rootDir, relative);
  if (!isInside(rootDir, candidate)) {
    sendStatus(response, 403);
    return;
  }

  const file = await resolveFile(candidate);
  if (file) {
    await sendFile(request, response, file);
    return;
  }

  // Client-side routes have no extension, so they receive the SPA shell. Missing assets stay 404.
  if (config.spaFallback && path.extname(relative) === '') {
    await sendFile(request, response, path.join(rootDir, config.index));
    return;
  }

  sendStatus(response, 404);
}

async function resolveFile(candidate) {
  const info = await statOrNull(candidate);
  if (info?.isFile()) {
    return candidate;
  }
  if (info?.isDirectory()) {
    const indexFile = path.join(candidate, config.index);
    const indexInfo = await statOrNull(indexFile);
    return indexInfo?.isFile() ? indexFile : null;
  }
  return null;
}

async function sendFile(request, response, file) {
  const info = await stat(file);
  const extension = path.extname(file).toLowerCase();
  response.writeHead(200, {
    ...config.headers,
    'Content-Type': config.mimeTypes[extension] ?? config.defaultMimeType,
    'Content-Length': info.size,
    'Cache-Control': cacheControlFor(extension),
    'Last-Modified': info.mtime.toUTCString(),
  });
  if (request.method === 'HEAD') {
    response.end();
    return;
  }
  const stream = createReadStream(file);
  stream.on('error', (error) => response.destroy(error));
  stream.pipe(response);
}

function sendStatus(response, status, headers = {}) {
  response.writeHead(status, {
    ...config.headers,
    'Content-Type': 'text/plain; charset=utf-8',
    ...headers,
  });
  response.end(STATUS_CODES[status]);
}

function cacheControlFor(extension) {
  const rule = config.cacheControl.find((entry) => entry.extensions.includes(extension));
  return rule?.value ?? config.defaultCacheControl;
}

function decodePathname(rawUrl) {
  try {
    const pathname = decodeURIComponent(new URL(rawUrl ?? '/', 'http://localhost').pathname);
    return pathname.includes('\0') ? null : pathname;
  } catch {
    return null;
  }
}

function isInside(root, candidate) {
  return candidate === root || candidate.startsWith(root + path.sep);
}

async function statOrNull(target) {
  try {
    return await stat(target);
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') {
      return null;
    }
    throw error;
  }
}

function resolvePort(envValue, fallback) {
  const raw = envValue?.trim() ? envValue.trim() : String(fallback);
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`Invalid port "${raw}". Use an integer from 1 to 65535.`);
  }
  return value;
}
