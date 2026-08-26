const { contextBridge, ipcRenderer } = require('electron');
const fs = require('fs');
const path = require('path');

// The unattended scheduler can run as SYSTEM, whose temporary folder is not
// readable by the logged-in desktop user.  Prefer the shared project cache.
const sharedUiDataPath = process.env.REPONDEUR_UI_DATA_PATH
  || path.resolve(__dirname, '..', 'cache', 'ui', 'repondeur-data-prod.json');
const legacyUiDataPath = path.join(require('os').tmpdir(), 'projet-repondeur', 'repondeur-data-prod.json');
const uiDataPath = fs.existsSync(sharedUiDataPath) ? sharedUiDataPath : legacyUiDataPath;

function readUiData() {
  try {
    for (const candidate of [sharedUiDataPath, legacyUiDataPath]) {
      if (fs.existsSync(candidate)) {
        return JSON.parse(fs.readFileSync(candidate, 'utf8'));
      }
    }
    return null;
  } catch {
    return null;
  }
}

contextBridge.exposeInMainWorld('repondeur', {
  mode: 'prod',
  run: (args) => ipcRenderer.invoke('repondeur:run', Array.isArray(args) ? args : []),
  readUiData,
  uiDataPath,
  uiData: readUiData(),
});
