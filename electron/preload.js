const { contextBridge, ipcRenderer } = require("electron");

const fullBridge = {
  listProfiles: () => ipcRenderer.invoke("profiles:list"),
  validateProfile: (backendUrl) => ipcRenderer.invoke("profiles:validate", backendUrl),
  saveProfile: (payload) => ipcRenderer.invoke("profiles:save", payload),
  deleteProfile: (id) => ipcRenderer.invoke("profiles:delete", id),
  selectProfile: (id) => ipcRenderer.invoke("profiles:select", id),
  deviceLogin: (payload) => ipcRenderer.invoke("auth:device-login", payload),
  openBackend: (profileId) => ipcRenderer.invoke("app:open-backend", profileId),
  readBootstrapPayload: (bootstrapUrl) => ipcRenderer.invoke("app:bootstrap-payload", bootstrapUrl),
  clearAuth: (profileId) => ipcRenderer.invoke("app:clear-auth", profileId),
  switchInstance: () => ipcRenderer.invoke("app:switch-instance"),
  onAuthRequired: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("auth-required", listener);
    return () => ipcRenderer.removeListener("auth-required", listener);
  },
};

const remoteBridge = {
  switchInstance: () => ipcRenderer.invoke("app:switch-instance"),
};

const bridge = window.location.protocol === "file:" ? fullBridge : remoteBridge;

contextBridge.exposeInMainWorld("brokeDesktop", bridge);
