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

## GitHub Actions packaging

This repo includes a dedicated workflow at `.github/workflows/desktop-release.yml`.

- After `CI - Code Quality & Tests` succeeds for a push to `main`, it builds unsigned desktop installers and publishes a rolling GitHub prerelease tagged `desktop-latest`

The rolling release contains:

- macOS: `.dmg`
- Windows: `.exe`

Stable asset URLs use the `desktop-latest` release tag:

- `https://github.com/<owner>/<repo>/releases/download/desktop-latest/broke-desktop-mac.dmg`
- `https://github.com/<owner>/<repo>/releases/download/desktop-latest/broke-desktop-setup.exe`

The current workflow produces unsigned installers. For production distribution, add signing secrets and platform icon files (`.icns` and `.ico`).

## Direct downloads from your Broke site

If you want `/desktop/download` on your Broke instance to send users straight to an installer, use the rolling GitHub release asset URLs rather than Actions artifacts.

Use one of these approaches instead:

- Host the installer files on the same server and set:
  - `BROKE_DESKTOP_INSTALLER_MAC_PATH`
  - `BROKE_DESKTOP_INSTALLER_WINDOWS_PATH`
- Or publish the installers at stable public URLs, such as the rolling GitHub release, and set:
  - `BROKE_DESKTOP_INSTALLER_MAC_URL`
  - `BROKE_DESKTOP_INSTALLER_WINDOWS_URL`

Optional filename overrides:

- `BROKE_DESKTOP_INSTALLER_MAC_NAME`
- `BROKE_DESKTOP_INSTALLER_WINDOWS_NAME`

Behavior:

- `/desktop/download` auto-detects macOS vs Windows from the browser user agent
- `?platform=mac` or `?platform=windows` can override detection
- If no platform-specific installer is configured, it falls back to the legacy single installer path or release URL

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
