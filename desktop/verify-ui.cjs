// Run: RESEARCHOS_TEST_URL=http://127.0.0.1:<port>/ electron verify-ui.cjs
// Uses an existing workspace; does not archive projects or modify research data.
const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const errors = [];
app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, width: 1440, height: 900 });
  window.webContents.on('console-message', (event) => {
    if (event.message?.includes('ResearcherOS init failed:')) errors.push(event.message);
  });
  await window.loadURL(new URL('?desktop=1', process.env.RESEARCHOS_TEST_URL).href);
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const state = await window.webContents.executeJavaScript(`({
      projects: document.querySelectorAll('.project-list__btn').length,
      nodes: document.querySelectorAll('.map-node').length,
      text: document.body.innerText,
    })`);
    if (errors.length || state.text.includes('Не удалось загрузить:')) {
      throw Error(errors.join('\n') || state.text);
    }
    if (state.projects && state.nodes) {
      if (process.env.RESEARCHOS_TEST_SCREENSHOT) {
        fs.writeFileSync(process.env.RESEARCHOS_TEST_SCREENSHOT,
          (await window.webContents.capturePage()).toPNG());
      }
      console.log(`UI loaded: ${state.projects} project buttons, ${state.nodes} map nodes`);
      app.quit();
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw Error('Project list or map did not render');
}).catch(error => { console.error(error); app.exit(1); });
