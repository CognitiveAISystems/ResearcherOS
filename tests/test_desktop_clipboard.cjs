// Run: desktop/node_modules/.bin/electron tests/test_desktop_clipboard.cjs
const { app, BrowserWindow, session, clipboard } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

app.whenReady().then(async () => {
  const server = http.createServer((_req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end('<button id="copy" style="width:200px;height:100px">Copy</button>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const serverUrl = `http://127.0.0.1:${server.address().port}`;
  const source = fs.readFileSync(path.join(__dirname, '../desktop/main.cjs'), 'utf8');
  // Exercise the production handlers, including Chromium's actual permission checks.
  const handlers = source.slice(source.indexOf('    session.defaultSession.setPermissionRequestHandler('), source.indexOf('    createWindow(await startServer());'));
  assert.ok(handlers.includes('setPermissionCheckHandler'));
  const registered = {};
  new Function('session', 'serverUrl', handlers)({ defaultSession: {
    setPermissionRequestHandler: fn => { registered.request = fn; session.defaultSession.setPermissionRequestHandler(fn); },
    setPermissionCheckHandler: fn => { registered.check = fn; session.defaultSession.setPermissionCheckHandler(fn); },
  } }, serverUrl);
  const local = { getURL: () => `${serverUrl}/?desktop=1` };
  assert.equal(registered.check(local, 'clipboard-sanitized-write', serverUrl, { isMainFrame: true }), true);
  assert.equal(registered.check(local, 'clipboard-read', serverUrl, {}), false);
  assert.equal(registered.check(local, 'clipboard-sanitized-write', 'https://example.com', {}), false);
  assert.equal(registered.check({ getURL: () => `${serverUrl}0/` }, 'clipboard-sanitized-write', serverUrl, {}), false);
  assert.equal(registered.check(local, 'media', serverUrl, { mediaType: 'audio' }), true);
  assert.equal(registered.check(local, 'media', serverUrl, { mediaType: 'video' }), false);
  for (const [origin, permission, allowed] of [[serverUrl, 'clipboard-sanitized-write', true], [serverUrl, 'clipboard-read', false], ['https://example.com', 'clipboard-sanitized-write', false]]) {
    registered.request(local, permission, result => assert.equal(result, allowed), { requestingUrl: origin + '/' });
  }
  const window = new BrowserWindow({ width: 400, height: 300 });
  const previous = clipboard.readText();
  try {
    await window.loadURL(serverUrl);
    const appSource = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
    const copyFunction = appSource.slice(appSource.indexOf('async function copyCardReportPath('), appSource.indexOf('\nfunction bindKanbanCardEvents('));
    await window.webContents.executeJavaScript(`
      const state = { project: {} };
      const boardWriteProjectId = () => 'demo';
      const KoiApi = { getCardReportPath: async () => {
        await new Promise(resolve => setTimeout(resolve, 50));
        return {repo_path: '/clipboard-test/report.md'};
      } };
      ${copyFunction}
      document.querySelector('#copy').onclick = async () => {
        await copyCardReportPath({id:'card'}, {id:'board'});
        window.copyDone = true;
      };
      void 0;
    `);
    window.focus();
    window.webContents.sendInputEvent({ type: 'mouseDown', x: 40, y: 40, button: 'left', clickCount: 1 });
    window.webContents.sendInputEvent({ type: 'mouseUp', x: 40, y: 40, button: 'left', clickCount: 1 });
    const deadline = Date.now() + 5000;
    while (!await window.webContents.executeJavaScript('window.copyDone === true')) {
      assert.ok(Date.now() < deadline, 'Copy click did not finish');
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.equal(clipboard.readText(), '/clipboard-test/report.md');
    console.log('PASS: card report path reaches system clipboard; other origins, clipboard reads and camera remain denied');
  } finally {
    clipboard.writeText(previous);
    window.destroy();
    server.close();
  }
  app.quit();
}).catch(error => { console.error(error); app.exit(1); });
