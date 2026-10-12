// Verify the packaged server without reading or changing the user's workspace.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

function get(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
      response.on('error', reject);
    });
    request.setTimeout(5000, () => request.destroy(new Error(`Timed out: ${url}`)));
    request.on('error', reject);
  });
}

async function verify(executable) {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'researchos-check-'));
  const child = spawn(path.resolve(executable), [], {
    cwd: data,
    env: { ...process.env, KOI_DATA_DIR: data },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let diagnostics = '';
  child.stderr.on('data', chunk => { diagnostics += chunk; });
  const exited = new Promise(resolve => child.once('close', resolve));
  let timer;
  try {
    const url = await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('Server startup timed out')), 30000);
      child.once('error', reject);
      child.once('exit', code => reject(new Error(`Server exited: ${code}\n${diagnostics}`)));
      let buffer = '';
      child.stdout.on('data', chunk => {
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          try {
            const message = JSON.parse(line);
            if (typeof message.url === 'string' && message.url.startsWith('http://127.0.0.1:')) resolve(message.url);
          } catch { /* skip diagnostics */ }
        }
      });
    });
    clearTimeout(timer);
    for (const resource of ['', 'api/health', 'desktop-onboarding.js']) {
      const response = await get(new URL(resource, url));
      if (response.status !== 200) throw new Error(`Packaged resource ${resource}: HTTP ${response.status}\n${diagnostics}`);
      if (resource === 'api/health' && JSON.parse(response.body).status !== 'ok') throw new Error('API is unhealthy');
    }
    console.log('Packaged server: UI, API and onboarding OK');
  } finally {
    clearTimeout(timer);
    child.kill('SIGTERM');
    const killTimer = setTimeout(() => child.kill('SIGKILL'), 10000);
    await exited;
    clearTimeout(killTimer);
    fs.rmSync(data, { recursive: true, force: true });
  }
}
verify(process.argv[2]).catch(error => { console.error(error.message); process.exitCode = 1; });
