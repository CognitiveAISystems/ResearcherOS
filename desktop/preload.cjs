const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('researchOSDesktop', Object.freeze({
  chooseWorkspace: () => ipcRenderer.invoke('researchos:choose-workspace'),
}));
