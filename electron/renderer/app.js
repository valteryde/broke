const state = {
  profiles: [],
  selectedId: "",
  editingId: "",
  loginId: "",
  selectedIcon: "",
};

const listEl = document.getElementById("backend-list");
const detailEl = document.getElementById("backend-detail");
const statusEl = document.getElementById("status");
const heroBackendCountEl = document.getElementById("hero-backend-count");
const heroCurrentBackendEl = document.getElementById("hero-current-backend");
const formEl = document.getElementById("backend-form");
const backendModalEl = document.getElementById("backend-modal");
const loginFormEl = document.getElementById("login-form");
const loginModalEl = document.getElementById("login-modal");
const formTitleEl = document.getElementById("backend-form-title");

const nameEl = document.getElementById("backend-name");
const urlEl = document.getElementById("backend-url");
const notesEl = document.getElementById("backend-notes");

const loginTargetEl = document.getElementById("login-target");
const loginUsernameEl = document.getElementById("login-username");
const loginPasswordEl = document.getElementById("login-password");
const loginDeviceNameEl = document.getElementById("login-device-name");

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showStatus(type, message) {
  statusEl.classList.remove("hidden", "ok", "error", "info");
  statusEl.classList.add(type);
  statusEl.textContent = message;
}

function hideStatus() {
  statusEl.classList.add("hidden");
}

function getDeviceId() {
  const key = "broke-desktop-device-id";
  let value = localStorage.getItem(key);
  if (!value) {
    value = `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    localStorage.setItem(key, value);
  }
  return value;
}

function getDeviceName() {
  return localStorage.getItem("broke-desktop-device-name") || "My Desktop";
}

function setDeviceName(value) {
  localStorage.setItem("broke-desktop-device-name", value);
}

function renderList() {
  if (!state.profiles.length) {
    heroBackendCountEl.textContent = "0";
    heroCurrentBackendEl.textContent = "None selected";
    listEl.innerHTML = `
      <p class="backend-nav-empty">No saved backends</p>
    `;
    detailEl.innerHTML = `
      <div class="settings-card empty-state">
        <div class="card-section">
          <h3>No backends yet</h3>
          <p class="card-description">Add your first Broke backend to start switching between environments from the desktop client.</p>
        </div>
      </div>
    `;
    return;
  }

  const currentId = state.selectedId || state.profiles[0].id;
  const currentProfile = state.profiles.find((item) => item.id === currentId) || state.profiles[0];

  heroBackendCountEl.textContent = String(state.profiles.length);
  heroCurrentBackendEl.textContent = currentProfile.name;

  listEl.innerHTML = state.profiles
    .map((item) => {
      const name = escapeHtml(item.name);
      const isSelected = item.id === currentProfile.id;
      const iconName = item.iconName || "cloud";
      return `
      <button class="settings-nav-item backend-nav-item ${isSelected ? "active" : ""}" data-action="select" data-id="${item.id}" type="button">
        <i class="ph ph-${iconName}"></i>
        <span>${name}</span>
      </button>
      `;
    })
    .join("");

  detailEl.innerHTML = renderDetail(currentProfile);
}

function renderDetail(item) {
  const name = escapeHtml(item.name);
  const backendUrl = escapeHtml(item.backendUrl);
  const notes = item.notes ? `<p class="card-description backend-detail-notes">${escapeHtml(item.notes)}</p>` : "";
  const instanceId = item.instanceId ? `Instance ${escapeHtml(item.instanceId)}` : "Instance id pending";
  const lastUsed = item.lastUsedAt ? `Last used ${new Date(item.lastUsedAt).toLocaleString()}` : "Not opened yet";
  const iconName = item.iconName || "cloud";
  const iconMarkup = `<div class="backend-icon"><i class="ph ph-${iconName}"></i></div>`;

  return `
    <div class="settings-card backend-detail-card">
      <div class="card-section">
        <div class="backend-detail-header">
          <div class="backend-meta">
            ${iconMarkup}
            <div>
              <div class="backend-title-line">
                <div class="backend-title">${name}</div>
                <span class="backend-badge">Current</span>
              </div>
              <div class="backend-url">${backendUrl}</div>
            </div>
          </div>
          <div class="backend-actions">
            <button class="btn btn-primary" data-action="connect" data-id="${item.id}">
              <i class="ph ph-plug"></i>
              <span>Connect</span>
            </button>
            <button class="btn btn-secondary" data-action="edit" data-id="${item.id}">Edit</button>
            <button class="btn btn-danger" data-action="delete" data-id="${item.id}">Delete</button>
          </div>
        </div>
        ${notes}
        <div class="backend-detail-meta">
          <div class="settings-source-note">
            <i class="ph ph-fingerprint"></i>
            <span>${instanceId}</span>
          </div>
          <div class="settings-source-note">
            <i class="ph ph-clock-clockwise"></i>
            <span>${escapeHtml(lastUsed)}</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

function showForm(editId = "") {
  hideStatus();
  hideLogin();
  backendModalEl.classList.remove("hidden");
  state.editingId = editId;
  state.selectedIcon = "";

  // Reset all icon buttons
  document.querySelectorAll(".icon-option").forEach((btn) => {
    btn.classList.remove("active");
  });

  if (!editId) {
    formTitleEl.textContent = "Add Backend";
    nameEl.value = "";
    urlEl.value = "";
    notesEl.value = "";
    return;
  }

  const existing = state.profiles.find((item) => item.id === editId);
  if (!existing) {
    return;
  }

  formTitleEl.textContent = "Edit Backend";
  nameEl.value = existing.name;
  urlEl.value = existing.backendUrl;
  notesEl.value = existing.notes || "";
  state.selectedIcon = existing.iconName || "";

  // Highlight the selected icon
  const selectedBtn = document.querySelector(
    `.icon-option[data-icon="${state.selectedIcon}"]`
  );
  if (selectedBtn) {
    selectedBtn.classList.add("active");
  }
}

function hideForm() {
  backendModalEl.classList.add("hidden");
  state.editingId = "";
}

function showLogin(profileId, reason = "") {
  const profile = state.profiles.find((item) => item.id === profileId);
  if (!profile) {
    return;
  }

  hideStatus();
  hideForm();
  state.loginId = profileId;
  loginModalEl.classList.remove("hidden");
  loginTargetEl.textContent = `${profile.name} (${profile.backendUrl})${reason ? ` - ${reason}` : ""}`;
  loginDeviceNameEl.value = getDeviceName();
  loginPasswordEl.value = "";
  loginUsernameEl.focus();
}

function hideLogin() {
  loginModalEl.classList.add("hidden");
  state.loginId = "";
  loginPasswordEl.value = "";
}

async function refresh() {
  const payload = await window.brokeDesktop.listProfiles();
  state.profiles = payload.items || [];
  state.selectedId = payload.selectedId || "";
  renderList();
}

async function tryAutoBootstrap() {
  const params = new URLSearchParams(window.location.search);
  const bootstrap = params.get("bootstrap");
  if (!bootstrap) {
    return;
  }

  showStatus("info", "Loading installer bootstrap payload...");
  const response = await window.brokeDesktop.readBootstrapPayload(bootstrap);
  if (!response.ok) {
    showStatus("error", response.error || "Failed to read bootstrap payload");
    return;
  }

  const payload = response.payload;
  if (payload.product !== "broke") {
    showStatus("error", "Bootstrap payload is not from a Broke backend.");
    return;
  }

  const existing = state.profiles.find((item) => item.backendUrl === payload.backend_url);
  if (existing) {
    showStatus("ok", "Backend already added. You can connect now.");
    return;
  }

  const save = await window.brokeDesktop.saveProfile({
    name: payload.instance_name || "Broke Backend",
    backendUrl: payload.backend_url,
    logoUrl: payload.logo_url || "",
    iconName: "",
    notes: "Added from installer bootstrap",
    instanceId: payload.instance_id || "",
  });

  if (!save.ok) {
    showStatus("error", "Could not save backend from bootstrap.");
    return;
  }

  await refresh();
  showStatus("ok", "Backend added automatically from installer link.");
}

listEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const id = button.dataset.id;
  const action = button.dataset.action;
  const profile = state.profiles.find((item) => item.id === id);
  if (!profile) {
    return;
  }

  if (action === "select") {
    state.selectedId = id;
    await window.brokeDesktop.selectProfile(id);
    renderList();
    hideForm();
    hideLogin();
    return;
  }
});

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideStatus();

  try {
    showStatus("info", "Validating backend handshake...");
    const validated = await window.brokeDesktop.validateProfile(urlEl.value);
    const payload = {
      id: state.editingId || undefined,
      name: nameEl.value.trim(),
      backendUrl: validated.backendUrl,
      logoUrl: validated.bootstrap.logo_url || "",
      iconName: state.selectedIcon,
      notes: notesEl.value.trim(),
      instanceId: validated.bootstrap.instance_id || "",
    };

    const saveResult = await window.brokeDesktop.saveProfile(payload);
    if (!saveResult.ok) {
      throw new Error("Could not save backend profile");
    }

    await refresh();
    hideForm();
    showStatus("ok", "Backend validated and saved.");
  } catch (err) {
    showStatus("error", err.message || "Validation failed");
  }
});

loginFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  hideStatus();

  if (!state.loginId) {
    showStatus("error", "No backend selected for login.");
    return;
  }

  const deviceName = loginDeviceNameEl.value.trim();
  setDeviceName(deviceName);

  showStatus("info", "Performing one-time device login...");
  const result = await window.brokeDesktop.deviceLogin({
    profileId: state.loginId,
    username: loginUsernameEl.value.trim(),
    password: loginPasswordEl.value,
    deviceName,
    deviceId: getDeviceId(),
  });

  if (!result.ok) {
    showStatus("error", result.error || "Login failed");
    return;
  }

  showStatus("ok", "Device linked. Opening backend...");
  const opened = await window.brokeDesktop.openBackend(state.loginId);
  if (!opened.opened) {
    showStatus("error", opened.reason || "Could not open backend");
  }
});

window.brokeDesktop.onAuthRequired(async ({ profileId, reason }) => {
  await refresh();
  showLogin(profileId, reason || "Session restore failed");
});

detailEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const id = button.dataset.id;
  const action = button.dataset.action;
  const profile = state.profiles.find((item) => item.id === id);
  if (!profile) {
    return;
  }

  if (action === "edit") {
    showForm(id);
    return;
  }

  if (action === "delete") {
    const ok = window.confirm(`Delete backend "${profile.name}"?`);
    if (!ok) {
      return;
    }
    await window.brokeDesktop.deleteProfile(id);
    await refresh();
    showStatus("ok", "Backend removed.");
    return;
  }

  if (action === "connect") {
    await window.brokeDesktop.selectProfile(id);
    const opened = await window.brokeDesktop.openBackend(id);
    if (!opened.opened) {
      showLogin(id, opened.reason || "Authentication needed");
    }
  }
});

document.getElementById("modal-close-btn").addEventListener("click", () => hideForm());
document.getElementById("login-modal-close-btn").addEventListener("click", () => hideLogin());
document.getElementById("new-backend-btn").addEventListener("click", () => showForm());
document.getElementById("cancel-form-btn").addEventListener("click", () => hideForm());
document.getElementById("cancel-login-btn").addEventListener("click", () => hideLogin());

backendModalEl.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    hideForm();
  }
});

loginModalEl.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    hideLogin();
  }
});

document.querySelectorAll(".icon-option").forEach((btn) => {
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    document.querySelectorAll(".icon-option").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.selectedIcon = btn.dataset.icon;
  });
});

(async function boot() {
  await refresh();
  await tryAutoBootstrap();
})();
