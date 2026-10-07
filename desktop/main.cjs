const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

let server = null;
let mainWindow = null;
let serverUrl = null;
let quitting = false;

function serverCommand() {
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'server', 'researchos-server');
    if (!fs.existsSync(executable)) throw new Error(`Bundled server missing: ${executable}`);
    const cwd = app.getPath('userData');
    fs.mkdirSync(cwd, { recursive: true });
    return { executable, args: [], cwd };
  }
  const root = path.resolve(__dirname, '..');
  const venvPython = path.join(root, '.venv', 'bin', 'python');
  const executable = process.env.RESEARCHOS_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python3');
  return { executable, args: ['-m', 'api.desktop_server', '--port', '0'], cwd: root };
}

function startServer() {
  return new Promise((resolve, reject) => {
    const { executable, args, cwd } = serverCommand();
    let ready = false;
    let buffer = '';
    server = spawn(executable, args, {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, KOI_DATA_DIR: app.getPath('userData') },
    });
    const timeout = setTimeout(() => reject(new Error('Server startup timed out')), 30000);
    server.stdout.setEncoding('utf8');
    server.stdout.on('data', (chunk) => {
      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        try {
          const message = JSON.parse(line);
          if (typeof message.url === 'string' && message.url.startsWith('http://127.0.0.1:')) {
            ready = true;
            clearTimeout(timeout);
            resolve(message.url);
          }
        } catch { /* keep stdout diagnostics separate from readiness */ }
      }
    });
    server.stderr.on('data', (chunk) => process.stderr.write(chunk));
    server.on('error', (error) => { clearTimeout(timeout); reject(error); });
    server.on('exit', (code) => {
      clearTimeout(timeout);
      if (!ready) reject(new Error(`Server exited before startup (code ${code})`));
      else if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
        dialog.showErrorBox('ResearcherOS', 'Локальный сервер остановился. Перезапустите приложение.');
      }
    });
  });
}

function createWindow(url) {
  serverUrl = url.replace(/\/$/, '');
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'ResearcherOS',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:\/\//i.test(target)) shell.openExternal(target);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (!target.startsWith(`${serverUrl}/`) && target !== serverUrl) {
      event.preventDefault();
      if (/^https?:\/\//i.test(target)) shell.openExternal(target);
    }
  });
  const onboardingFlag = path.join(app.getPath('userData'), '.show-onboarding');
  const showOnboarding = fs.existsSync(onboardingFlag);
  if (showOnboarding) fs.rmSync(onboardingFlag, { force: true });
  const initialUrl = showOnboarding
    ? `${serverUrl}/?onboarding=1`
    : serverUrl;
  mainWindow.loadURL(initialUrl);
}

ipcMain.handle('researchos:choose-directory', async (_event, purpose) => {
  const selectingRepo = purpose === 'repository';
  const result = await dialog.showOpenDialog(mainWindow, {
    title: selectingRepo ? 'Выберите Git-репозиторий с кодом' : 'Выберите папку для проектов ResearcherOS',
    properties: selectingRepo ? ['openDirectory'] : ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

app.whenReady().then(async () => {
  try {
    createWindow(await startServer());
  } catch (error) {
    dialog.showErrorBox('Не удалось запустить ResearcherOS', String(error.message || error));
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0 && serverUrl) createWindow(serverUrl);
});
app.on('before-quit', () => {
  quitting = true;
  if (server && !server.killed) server.kill('SIGTERM');
});
app.on('window-all-closed', () => app.quit());
