const { contextBridge, ipcRenderer } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');

const uiDataPath = path.join(os.tmpdir(), 'projet-repondeur', 'repondeur-data-prod.json');

function readUiData() {
  try {
    if (!fs.existsSync(uiDataPath)) {
      return null;
    }
    return JSON.parse(fs.readFileSync(uiDataPath, 'utf8'));
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
