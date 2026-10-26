const { app, BrowserWindow, dialog, ipcMain, shell, session, systemPreferences } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

let server = null;
let mainWindow = null;
let serverUrl = null;
let quitting = false;

function serverCommand() {
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'server', process.platform === 'win32' ? 'researchos-server.exe' : 'researchos-server');
    if (!fs.existsSync(executable)) throw new Error(`Bundled server missing: ${executable}`);
    const cwd = app.getPath('userData');
    fs.mkdirSync(cwd, { recursive: true });
    return { executable, args: [], cwd };
  }
  const root = path.resolve(__dirname, '..');
  const venvPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const executable = process.env.RESEARCHOS_PYTHON || (fs.existsSync(venvPython) ? venvPython : process.platform === 'win32' ? 'python' : 'python3');
  return { executable, args: ['-m', 'api.desktop_server', '--port', '0'], cwd: root };
}

function guiPath() {
  if (process.platform !== 'darwin') return process.env.PATH || '';
  // Finder does not run path_helper, so MacTeX in /etc/paths.d is invisible.
  const parts = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const files = ['/etc/paths'];
  if (fs.existsSync('/etc/paths.d')) {
    for (const name of fs.readdirSync('/etc/paths.d').sort()) {
      files.push(path.join('/etc/paths.d', name));
    }
  }
  for (const file of files) {
    let text = '';
    try {
      text = fs.readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    for (const line of text.split('\n')) {
      const dirPath = line.trim();
      if (dirPath && !dirPath.startsWith('#') && !parts.includes(dirPath)) parts.push(dirPath);
    }
  }
  return parts.join(path.delimiter);
}

function startServer() {
  return new Promise((resolve, reject) => {
    const { executable, args, cwd } = serverCommand();
    let ready = false;
    let buffer = '';
    server = spawn(executable, args, {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: guiPath(), KOI_DATA_DIR: app.getPath('userData') },
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
    ? `${serverUrl}/?desktop=1&onboarding=1`
    : `${serverUrl}/?desktop=1`;
  mainWindow.loadURL(initialUrl);
  if (process.env.RESEARCHOS_SMOKE_TEST === '1') {
    const smokeTimeout = setTimeout(() => app.exit(1), 60000);
    mainWindow.webContents.once('did-finish-load', async () => {
      clearTimeout(smokeTimeout);
      const title = await mainWindow.webContents.getTitle();
      app.exit(title && /Research(?:er)?OS/i.test(title) ? 0 : 1);
    });
    mainWindow.webContents.once('did-fail-load', () => { clearTimeout(smokeTimeout); app.exit(1); });
  }
}

ipcMain.handle('researchos:choose-directory', async (_event, purpose) => {
  const selectingRepo = purpose === 'repository';
  const result = await dialog.showOpenDialog(mainWindow, {
    title: selectingRepo ? 'Выберите Git-репозиторий с кодом' : 'Выберите папку для проектов ResearcherOS',
    properties: selectingRepo ? ['openDirectory'] : ['openDirectory', 'createDirectory'],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle('researchos:request-microphone', async () => {
  if (process.platform !== 'darwin') return true;
  return systemPreferences.askForMediaAccess('microphone');
});

app.whenReady().then(async () => {
  try {
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
      const localPage = !!serverUrl && webContents.getURL().startsWith(serverUrl);
      const audioOnly = details?.mediaTypes?.length === 1 && details.mediaTypes[0] === 'audio';
      callback(permission === 'media' && localPage && audioOnly);
    });
    session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
      const localPage = !!serverUrl && webContents?.getURL().startsWith(serverUrl);
      return permission === 'media' && localPage && requestingOrigin.startsWith(serverUrl) && details?.mediaType === 'audio';
    });
    createWindow(await startServer());
  } catch (error) {
    if (process.env.RESEARCHOS_SMOKE_TEST === '1') {
      console.error(error);
      app.exit(1);
      return;
    }
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
