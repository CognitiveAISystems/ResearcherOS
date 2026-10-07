const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('researchOSDesktop', Object.freeze({
  chooseDirectory: (purpose) => ipcRenderer.invoke('researchos:choose-directory', purpose),
}));
