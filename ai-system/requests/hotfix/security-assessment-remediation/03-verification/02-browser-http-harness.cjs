// Complementary HTTP evidence only: this is not a browser or a full Next server.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '../../../../..');
const webRequire = createRequire(path.join(root, 'webapp/package.json'));
const ts = webRequire('typescript');
const next = webRequire('next/server');
const source = fs.readFileSync(path.join(root, 'webapp/app/auth/refresh/route.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
let authenticated = true;
const exported = {};
vm.runInNewContext(compiled, {
  exports: exported, URL,
  fetch: () => { throw new Error('Provider access prohibited'); },
  require: (name) => {
    if (name === 'next/server') return next;
    if (name === 'next/headers') return { cookies: async () => ({}) };
    if (name === '@/src/lib/auth/server-session') return {
      readAuthTokens: () => ({}),
      resolveSessionFromTokens: async () => authenticated
        ? { status: 'authenticated', tokens: {} } : { status: 'anonymous' },
      writeAuthCookies: (cookies) => cookies.set('local-fixture', 'present'),
      clearAuthCookies: (cookies) => cookies.delete('local-fixture'),
    };
    throw new Error(`Unexpected dependency: ${name}`);
  },
});
const listen = (server) => new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(0, 'localhost', () => resolve(`http://localhost:${server.address().port}`));
});
const close = (server) => new Promise((resolve) => server.close(resolve));
let destinationHits = 0;
const destination = http.createServer((_request, response) => {
  destinationHits += 1;
  response.end('Controlled destination');
});
let origin;
const application = http.createServer(async (request, response) => {
  try {
    if (request.url.startsWith('/auth/refresh')) {
      const result = await exported.GET(new next.NextRequest(new URL(request.url, origin)));
      response.writeHead(result.status, Object.fromEntries(result.headers));
      response.end();
    } else {
      response.end('Local landing');
    }
  } catch (error) {
    response.writeHead(500);
    response.end(error.name);
  }
});
async function main() {
  try {
    const other = await listen(destination);
    origin = await listen(application);
    const host = new URL(other).host;
    const cases = [
      ['dashboard', '/dashboard', '/dashboard'],
      ['query-fragment', '/reports?range=week#summary', '/reports?range=week#summary'],
      ['percent-query', '/reports?discount=25%25', '/reports?discount=25%25'],
      ['percent-path', '/reports/25%25', '/reports/25%25'],
      ['protocol-relative', `//${host}/capture`, '/dashboard'],
      ['backslash', `/\\${host}/capture`, '/dashboard'],
      ['encoded-backslash', `/%5C${host}/capture`, '/dashboard'],
      ['double-encoded-backslash', `/%255C${host}/capture`, '/dashboard'],
      ['absolute', `${other}/capture`, '/dashboard'],
      ['control', '/\t/capture', '/dashboard'],
      ['encoded-control', '/%0a/capture', '/dashboard'],
      ['malformed-encoding', '/%broken', '/dashboard'],
      ['missing', null, '/dashboard'],
      ['no-session', `//${host}/capture`, '/login'],
    ];
    for (const [name, value, expected] of cases) {
      authenticated = name !== 'no-session';
      const start = new URL('/auth/refresh', origin);
      if (value !== null) start.searchParams.set('next', value);
      const response = await fetch(start, { redirect: 'manual' });
      assert.equal(response.status, 307, name);
      const location = response.headers.get('location');
      assert.equal(location, new URL(expected, origin).href, name);
      assert.ok(response.headers.get('set-cookie')?.includes('local-fixture'), name);
      if (!authenticated) assert.ok(response.headers.get('set-cookie').includes('1970'), name);
      // Follow only a validated local Location, preventing any unexpected external traffic.
      assert.equal(new URL(location).origin, origin, name);
      assert.equal((await fetch(location)).status, 200, name);
      process.stdout.write(`${name}: PASS (307 -> ${expected}; cookie operation present)\n`);
    }
    assert.equal(destinationHits, 0);
    process.stdout.write(`controlled_destination_hits=${destinationHits}; cases=${cases.length}; browser=false\n`);
  } finally {
    await Promise.all([close(application), close(destination)]);
  }
}
main().catch((error) => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
