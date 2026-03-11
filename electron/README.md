# Broke Desktop (Electron)

This folder contains the desktop client for Broke.

## What is implemented

- Branded onboarding and backend picker UI.
- Backend trust validation via:
  - `GET /api/desktop/bootstrap`
  - `GET /api/desktop/handshake`
- Device login flow via `POST /api/desktop/device-login`.
- Session restore flow via `POST /api/desktop/session`.
- Local backend profile management (JSON store in Electron userData).
- Secure device token storage with OS keychain (`keytar`).

## Run locally

```bash
cd electron
npm install
npm run dev
```

From repository root you can also use:

```bash
make electron-install
make electron-dev
```

## Package installers

```bash
make electron-package-mac
make electron-package-win
```

Or directly:

```bash
cd electron
npm run package:mac
npm run package:win
```

## Security defaults

- `contextIsolation: true`
- `sandbox: true`
- `nodeIntegration: false`
- External links are opened in the OS browser
- Navigation is restricted to local renderer and selected backend origin

## Bootstrap auto-add

If the app is opened with a query string containing `bootstrap=<url>`, it will fetch that payload and auto-add the backend profile.

## Notes

- `device_token` is stored in keychain only.
- Password is used only during one-time device login and is not persisted.
- Current shell opens the selected backend URL after session restore.
