const { app, BrowserWindow, ipcMain, Menu, net, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const keytar = require("keytar");
const {
  isAllowedBackendUrl,
  isAllowedBootstrapUrl,
  isAllowedExternalUrl,
  isAllowedNavigationUrl,
  isLocalRendererUrl,
  sameOrigin,
} = require("./security");

const SERVICE_NAME = "broke-desktop";
const PROFILE_FILE = "backends.json";
const DESKTOP_USER_AGENT = `BrokeDesktop/0.1 ${app.userAgentFallback}`;
const APP_ID = "com.broke.desktop";
const APP_ICON_PATH = path.join(__dirname, "assets", "app-icon.png");

let mainWindow = null;

function userDataPath() {
  return app.getPath("userData");
}

function profilePath() {
  return path.join(userDataPath(), PROFILE_FILE);
}

function ensureProfileStore() {
  const storePath = profilePath();
  if (!fs.existsSync(storePath)) {
    fs.writeFileSync(storePath, JSON.stringify({ version: 1, selectedId: "", items: [] }, null, 2));
  }
}

function readProfiles() {
  ensureProfileStore();
  const raw = fs.readFileSync(profilePath(), "utf-8");
  const parsed = JSON.parse(raw);
  parsed.items = Array.isArray(parsed.items) ? parsed.items : [];
  parsed.selectedId = typeof parsed.selectedId === "string" ? parsed.selectedId : "";
  return parsed;
}

function writeProfiles(next) {
  fs.writeFileSync(profilePath(), JSON.stringify(next, null, 2));
}

function toId() {
  return crypto.randomBytes(8).toString("hex");
}

function normalizeUrl(input) {
  const value = String(input || "").trim();
  const withProtocol = value.match(/^https?:\/\//i) ? value : `https://${value}`;
  const url = new URL(withProtocol);
  return url.origin;
}

function senderUrl(event) {
  return event.senderFrame?.url || event.sender?.getURL() || "";
}

function assertLocalRendererSender(event) {
  if (!isLocalRendererUrl(senderUrl(event))) {
    throw new Error("Forbidden");
  }
}

function assertLocalOrCurrentBackendSender(event) {
  const url = senderUrl(event);
  if (isLocalRendererUrl(url)) {
    return;
  }

  const store = readProfiles();
  const current = store.items.find((item) => item.id === store.selectedId);
  if (current && sameOrigin(url, current.backendUrl)) {
    return;
  }

  throw new Error("Forbidden");
}

function requestJson(url, options = {}) {
  return new Promise((resolve, reject) => {
    const request = net.request({
      method: options.method || "GET",
      url,
      session: mainWindow.webContents.session,
    });

    if (options.headers) {
      for (const [key, val] of Object.entries(options.headers)) {
        request.setHeader(key, val);
      }
    }

    request.setHeader("User-Agent", DESKTOP_USER_AGENT);

    request.on("response", (response) => {
      let body = "";
      response.on("data", (chunk) => {
        body += chunk.toString();
      });
      response.on("end", () => {
        let parsed = null;
        if (body) {
          try {
            parsed = JSON.parse(body);
          } catch (_err) {
            parsed = null;
          }
        }

        resolve({
          status: response.statusCode,
          body: parsed,
          raw: body,
          headers: response.headers,
        });
      });
    });

    request.on("error", (err) => reject(err));

    if (options.json) {
      const payload = JSON.stringify(options.json);
      request.setHeader("Content-Type", "application/json");
      request.write(payload);
    }

    request.end();
  });
}

function headerValues(headers, key) {
  const value = headers ? headers[String(key).toLowerCase()] : null;
  if (!value) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function parseSameSite(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "strict") {
    return "strict";
  }
  if (normalized === "lax") {
    return "lax";
  }
  if (normalized === "none") {
    return "no_restriction";
  }
  return "unspecified";
}

async function persistResponseCookies(targetUrl, headers) {
  const cookieHeaders = headerValues(headers, "set-cookie");
  if (!cookieHeaders.length) {
    return;
  }

  const target = new URL(targetUrl);
  for (const rawCookie of cookieHeaders) {
    const parts = String(rawCookie)
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean);

    if (!parts.length || !parts[0].includes("=")) {
      continue;
    }

    const [name, ...valueParts] = parts[0].split("=");
    const cookie = {
      url: target.origin,
      name,
      value: valueParts.join("="),
      path: "/",
      secure: target.protocol === "https:",
      httpOnly: false,
      sameSite: "lax",
    };

    for (const attribute of parts.slice(1)) {
      const [attrName, ...attrValueParts] = attribute.split("=");
      const attrKey = String(attrName || "").trim().toLowerCase();
      const attrValue = attrValueParts.join("=").trim();

      if (attrKey === "path" && attrValue) {
        cookie.path = attrValue;
      } else if (attrKey === "domain" && attrValue) {
        cookie.domain = attrValue.replace(/^\./, "");
      } else if (attrKey === "secure") {
        cookie.secure = true;
      } else if (attrKey === "httponly") {
        cookie.httpOnly = true;
      } else if (attrKey === "samesite") {
        cookie.sameSite = parseSameSite(attrValue);
      } else if (attrKey === "max-age" && attrValue) {
        const maxAge = Number(attrValue);
        if (!Number.isNaN(maxAge)) {
          cookie.expirationDate = Math.floor(Date.now() / 1000) + maxAge;
        }
      } else if (attrKey === "expires" && attrValue) {
        const expiresAt = Date.parse(attrValue);
        if (!Number.isNaN(expiresAt)) {
          cookie.expirationDate = Math.floor(expiresAt / 1000);
        }
      }
    }

    await mainWindow.webContents.session.cookies.set(cookie);
  }

  await mainWindow.webContents.session.cookies.flushStore();
}

async function hasBackendSessionCookie(backendUrl) {
  const cookies = await mainWindow.webContents.session.cookies.get({ url: backendUrl });
  return cookies.some((cookie) => cookie.name === "session" && cookie.value);
}

async function fetchBootstrap(backendUrl) {
  return requestJson(`${backendUrl}/api/desktop/bootstrap`);
}

async function fetchHandshake(backendUrl) {
  return requestJson(`${backendUrl}/api/desktop/handshake?nonce=${Date.now()}`);
}

async function validateBackend(backendUrl) {
  const normalized = normalizeUrl(backendUrl);
  if (!isAllowedBackendUrl(normalized)) {
    throw new Error("Only HTTPS backends are allowed (HTTP only for localhost).\n");
  }

  const bootstrap = await fetchBootstrap(normalized);
  if (bootstrap.status !== 200 || !bootstrap.body || bootstrap.body.product !== "broke") {
    throw new Error("This URL is not a valid Broke backend.");
  }

  const handshake = await fetchHandshake(normalized);
  if (handshake.status !== 200 || !handshake.body || handshake.body.product !== "broke") {
    throw new Error("Backend handshake failed.");
  }

  return {
    backendUrl: normalized,
    bootstrap: bootstrap.body,
    handshake: handshake.body,
  };
}

async function restoreSession(profile) {
  const token = await keytar.getPassword(SERVICE_NAME, profile.id);
  if (!token) {
    return { success: false, reason: "No saved device token" };
  }

  const response = await requestJson(`${profile.backendUrl}/api/desktop/session`, {
    method: "POST",
    json: { device_token: token },
  });

  if (response.status !== 200) {
    return { success: false, reason: "Session restore failed" };
  }

  await persistResponseCookies(profile.backendUrl, response.headers);

  const hasCookie = await hasBackendSessionCookie(profile.backendUrl);
  if (!hasCookie) {
    return { success: false, reason: "Session cookie was not persisted" };
  }

  return { success: true };
}

async function openBackend(profileId) {
  const store = readProfiles();
  const profile = store.items.find((item) => item.id === profileId);
  if (!profile) {
    throw new Error("Backend profile not found");
  }

  const restored = await restoreSession(profile);
  if (!restored.success) {
    await mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
    mainWindow.webContents.send("auth-required", { profileId, reason: restored.reason });
    return { opened: false, reason: restored.reason };
  }

  store.selectedId = profile.id;
  profile.lastUsedAt = new Date().toISOString();
  writeProfiles(store);

  await mainWindow.loadURL(`${profile.backendUrl}/news`);
  return { opened: true };
}

async function showBackendPicker() {
  await mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

function openCurrentInBrowser() {
  const store = readProfiles();
  const current = store.items.find((item) => item.id === store.selectedId);
  if (current && isAllowedExternalUrl(current.backendUrl)) {
    shell.openExternal(current.backendUrl);
  }
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac
      ? [
          {
            role: "appMenu",
            submenu: [
              { role: "about" },
              { type: "separator" },
              {
                label: "Switch Backend",
                accelerator: "CmdOrCtrl+Shift+B",
                click: async () => {
                  await showBackendPicker();
                },
              },
              {
                label: "Open Current In Browser",
                accelerator: "CmdOrCtrl+Shift+O",
                click: () => {
                  openCurrentInBrowser();
                },
              },
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : [
          {
            label: "Broke",
            submenu: [
              {
                label: "Switch Backend",
                accelerator: "CmdOrCtrl+Shift+B",
                click: async () => {
                  await showBackendPicker();
                },
              },
              {
                label: "Open Current In Browser",
                accelerator: "CmdOrCtrl+Shift+O",
                click: () => {
                  openCurrentInBrowser();
                },
              },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]),
    { role: "editMenu" },
    {
      role: "viewMenu",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      role: "windowMenu",
      submenu: [
        { role: "minimize" },
        { role: "zoom" },
        ...(isMac ? [{ type: "separator" }, { role: "front" }] : [{ role: "close" }]),
      ],
    },
    {
      role: "help",
      submenu: [
        {
          label: "Open Current In Browser",
          click: () => {
            openCurrentInBrowser();
          },
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 860,
    minWidth: 980,
    minHeight: 700,
    show: false,
    icon: APP_ICON_PATH,
    title: "Broke Desktop",
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    backgroundColor: "#ece9e4",
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.webContents.setUserAgent(DESKTOP_USER_AGENT);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    const store = readProfiles();
    const current = store.items.find((item) => item.id === store.selectedId);
    if (current && isAllowedNavigationUrl(url, current.backendUrl)) {
      const child = new BrowserWindow({
        width: 900,
        height: 700,
        minWidth: 400,
        minHeight: 300,
        show: false,
        icon: APP_ICON_PATH,
        title: "Broke Desktop",
        backgroundColor: "#ece9e4",
        webPreferences: {
          contextIsolation: true,
          sandbox: true,
          nodeIntegration: false,
          preload: path.join(__dirname, "preload.js"),
        },
      });
      child.webContents.setUserAgent(DESKTOP_USER_AGENT);
      child.once("ready-to-show", () => {
        child.show();
      });
      child.loadURL(url);
      return { action: "deny" };
    }
    if (isAllowedExternalUrl(url)) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    const store = readProfiles();
    const current = store.items.find((item) => item.id === store.selectedId);

    if (isAllowedNavigationUrl(url, current?.backendUrl || "")) {
      return;
    }

    event.preventDefault();
    if (isAllowedExternalUrl(url)) {
      shell.openExternal(url);
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  const store = readProfiles();
  if (store.selectedId) {
    openBackend(store.selectedId).catch(async () => {
      await mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
    });
  } else {
    mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  }

  buildMenu();
}

ipcMain.handle("profiles:list", async (event) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  return store;
});

ipcMain.handle("profiles:validate", async (event, backendUrl) => {
  assertLocalRendererSender(event);
  return validateBackend(backendUrl);
});

ipcMain.handle("profiles:save", async (event, payload) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  const id = payload.id || toId();
  const existing = store.items.find((item) => item.id === id);

  const next = {
    id,
    name: payload.name,
    backendUrl: payload.backendUrl,
    logoUrl: payload.logoUrl || "",
    iconName: payload.iconName || "",
    notes: payload.notes || "",
    instanceId: payload.instanceId || "",
    createdAt: existing ? existing.createdAt : new Date().toISOString(),
    lastUsedAt: existing ? existing.lastUsedAt : null,
  };

  if (existing) {
    Object.assign(existing, next);
  } else {
    store.items.push(next);
  }

  if (!store.selectedId) {
    store.selectedId = id;
  }

  writeProfiles(store);
  return { ok: true, id };
});

ipcMain.handle("profiles:delete", async (event, id) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  store.items = store.items.filter((item) => item.id !== id);
  if (store.selectedId === id) {
    store.selectedId = store.items[0] ? store.items[0].id : "";
  }
  writeProfiles(store);
  await keytar.deletePassword(SERVICE_NAME, id);
  return { ok: true };
});

ipcMain.handle("profiles:select", async (event, id) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  const existing = store.items.find((item) => item.id === id);
  if (!existing) {
    return { ok: false, error: "Backend not found" };
  }
  store.selectedId = id;
  writeProfiles(store);
  return { ok: true };
});

ipcMain.handle("auth:device-login", async (event, payload) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  const profile = store.items.find((item) => item.id === payload.profileId);
  if (!profile) {
    return { ok: false, error: "Backend profile not found" };
  }

  const handshake = await fetchHandshake(profile.backendUrl);
  if (handshake.status !== 200 || !handshake.body || !handshake.body.challenge_token) {
    return { ok: false, error: "Failed to get handshake token" };
  }

  const loginResponse = await requestJson(`${profile.backendUrl}/api/desktop/device-login`, {
    method: "POST",
    json: {
      username: payload.username,
      password: payload.password,
      device_name: payload.deviceName,
      device_id: payload.deviceId,
      challenge_token: handshake.body.challenge_token,
    },
  });

  if (loginResponse.status !== 200 || !loginResponse.body || !loginResponse.body.device_token) {
    return {
      ok: false,
      error: (loginResponse.body && loginResponse.body.error) || "Device login failed",
    };
  }

  await keytar.setPassword(SERVICE_NAME, profile.id, loginResponse.body.device_token);
  return { ok: true };
});

ipcMain.handle("app:open-backend", async (event, profileId) => {
  assertLocalRendererSender(event);
  try {
    return await openBackend(profileId);
  } catch (err) {
    return { opened: false, reason: err.message };
  }
});

ipcMain.handle("app:bootstrap-payload", async (event, bootstrapUrl) => {
  assertLocalRendererSender(event);
  try {
    if (!isAllowedBootstrapUrl(bootstrapUrl)) {
      return { ok: false, error: "Invalid bootstrap URL" };
    }
    const response = await requestJson(bootstrapUrl);
    if (response.status !== 200 || !response.body) {
      return { ok: false, error: "Failed to load bootstrap payload" };
    }
    return { ok: true, payload: response.body };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle("app:clear-auth", async (event, profileId) => {
  assertLocalRendererSender(event);
  const store = readProfiles();
  const profile = store.items.find((item) => item.id === profileId);
  if (!profile) {
    return { ok: false };
  }

  const token = await keytar.getPassword(SERVICE_NAME, profile.id);
  if (token) {
    await requestJson(`${profile.backendUrl}/api/desktop/device-revoke`, {
      method: "POST",
      json: { device_token: token },
    }).catch(() => null);
  }

  await keytar.deletePassword(SERVICE_NAME, profile.id);
  return { ok: true };
});

ipcMain.handle("app:switch-instance", async (event) => {
  assertLocalOrCurrentBackendSender(event);
  await showBackendPicker();
  return { ok: true };
});

app.whenReady().then(() => {
  app.setName("Broke Desktop");

  if (process.platform === "win32") {
    app.setAppUserModelId(APP_ID);
  }

  if (process.platform === "darwin") {
    app.dock.setIcon(APP_ICON_PATH);
  }

  app.setAboutPanelOptions({
    applicationName: "Broke Desktop",
    applicationVersion: "0.1.0",
    version: "0.1.0",
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
