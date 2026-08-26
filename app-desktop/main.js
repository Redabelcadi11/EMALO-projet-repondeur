const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const UI_MODE = process.env.REPONDEUR_UI_MODE === 'prod' ? 'prod' : 'poc';

function runPython(args) {
  return new Promise((resolve) => {
    const pythonExe = process.env.PYTHON || 'python';
    const child = spawn(
      pythonExe,
      [path.join(PROJECT_ROOT, 'electron_bridge.py'), ...args],
      { cwd: PROJECT_ROOT, windowsHide: true }
    );
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
    child.on('close', (code) => {
      const lines = stdout.trim().split(/\r?\n/).filter(Boolean);
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        resolve({ code, stderr, ...JSON.parse(lastLine) });
      } catch {
        resolve({ code, ok: code === 0, message: stdout.trim() || stderr.trim(), stdout, stderr });
      }
    });
    child.on('error', (error) => resolve({ code: 1, ok: false, message: error.message, stderr: error.message }));
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1080,
    minHeight: 720,
    autoHideMenuBar: true,
    backgroundColor: '#F5EFE2',
    icon: path.join(__dirname, 'renderer', 'assets', 'icons', 'emalo-achats-icon.png'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      preload: path.join(__dirname, UI_MODE === 'prod' ? 'preload-prod.js' : 'preload.js'),
    },
  });

  win.loadFile(path.join(__dirname, 'renderer', UI_MODE === 'prod' ? 'prod.html' : 'index.html'));
}

ipcMain.handle('repondeur:run', (_event, args) => runPython(args));

app.whenReady().then(() => {
  app.setName(UI_MODE === 'prod' ? 'Repondeur Commandes PROD' : 'Repondeur Commandes');
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
