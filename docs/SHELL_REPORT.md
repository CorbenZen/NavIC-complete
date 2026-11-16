# CBTMS shell update report

## Changes

- Sidebar footer overlap (A): sidebar is a full-height flex column with a separately scrolling nav and fixed header/footer regions. The nav can scroll to Settings on short screens.
- Collapse control/logo collision (B): the header control is now one round edge handle in both rail states; the collapsed rail uses the compact `tab.png` mark.
- Uneven header borders (C): sidebar and topbar use `--shell-header-h: 64px` and the same translucent bottom border.
- Misaligned section labels (D): section headings share the item content gutter; item icons use a fixed 24px column.
- Redundant, cramped footer (E): removed the WS chip and the repeated simulation row. The footer retains shared WebSocket status, available update time, and account details.
- The topbar now uses the shared glass tokens, blur, fallback rules, and stacking scale. The map and Leaflet container are isolated below shell navigation layers.
- `logo1.png` was copied to `frontend/public/images/logo.png`, the target of the existing `frontend/public/logo.png` symlink. `tab1.png` was copied to `frontend/public/tab.png`. Favicon and PWA icon family was regenerated from `tab1.png` onto white rounded-square tiles.

## Asset proof

- `logo1.png`: 2000×2000, sRGBA, opaque. Source and installed logo SHA-256: `0ff36e86532072c52703d1ed91def1a7626b0a0b707a36390712dfd3c6efc40f`. Previous image backup: `719cd2da2ecbbb388ecd9005e98dd1b70d29e87cc8423eb3ad9bea9db28a002d`.
- `tab1.png`: 600×600, sRGBA with transparency. Source and installed `tab.png` SHA-256: `dac46904478505317014a34668b2e19dbbfd5920d4b21e97ba36f096f58b0193`. Previous `tab.png` backup: `95043ebb3a9e306a92248de0effd7166ab7ca9ece57e84f15bea4b6757129231`.
- `magick identify frontend/public/favicon.ico` listed 16×16, 32×32, and 48×48 images. New and old icon hashes and exact dimensions are recorded in [SHELL_DECISIONS.md](SHELL_DECISIONS.md).
- Favicon and manifest paths are versioned in `frontend/index.html`, `frontend/public/manifest.json`, and the service worker cache list. The service-worker cache is `navic-cbtms-v3-shell`.

## Evidence and limitations

- `cd frontend && npm run check`: exited 0; ESLint reported 0 errors and 36 warnings, and Vite built 2171 modules. The build also printed the existing large-chunk warning and `use client` bundler warnings.
- `cd frontend && npm run contrast`: all 20 light/dark token checks printed PASS; full output is in [SHELL_DECISIONS.md](SHELL_DECISIONS.md).
- `node --check scripts/smoke_routes.mjs` and `node --check scripts/check_contrast.mjs`: exited 0.
- `magick identify` and `sha256sum`: output is recorded above and in [SHELL_DECISIONS.md](SHELL_DECISIONS.md).
- **NOT TESTED:** `npm run smoke` could not launch because Playwright's Chromium executable is absent at `/home/corben/.cache/ms-playwright/chromium_headless_shell-1255/chrome-headless-shell-linux64/chrome-headless-shell`. It exited 1 before visiting any route. The full route/viewport/theme/collapse interaction matrix, favicon HTTP request comparison, and tracking overlay checks therefore did not run.
- **NOT TESTED:** required screenshot files were not saved. `docs/screenshots/shell/` is empty. Screenshots in expanded/collapsed states and both themes require the Playwright Chromium binary; once installed, run `cd frontend && npx playwright install chromium && npm run smoke`.
- **NOT TESTED:** map-pan performance under the two glass layers. Follow S6 in [MANUAL_TESTS.md](MANUAL_TESTS.md) after the browser can be exercised.

## Files and backup

Changed frontend files include `frontend/react-jsx/components/navigation/Sidebar.jsx`, `frontend/react-jsx/layouts/Shell.jsx`, `frontend/react-jsx/App.jsx`, `frontend/react-jsx/components/common/Brand.jsx`, `frontend/css-styles/global/styles.css`, `frontend/index.html`, `frontend/public/manifest.json`, `frontend/public/sw.js`, logo/icon assets, `frontend/generate-icons.mjs`, `frontend/generate-icons.js`, `frontend/scripts/check_contrast.mjs`, and `frontend/scripts/smoke_routes.mjs`. `docs/MANUAL_TESTS.md` and `docs/API_DOCUMENTATION.md` were updated; this report and decision log were added.

No source files were archived. No runtime dependencies were added. Backups are under [backups/shell_20261115T124914Z](/home/corben/Projects/NavIC/backups/shell_20261115T124914Z), preserving the source paths. To roll back the source changes, restore the backed-up files from that directory; restore the image symlink and its target together. No database files or records were touched.

## Decisions to review

- The square, opaque white app logo is used in the expanded sidebar header; the dark transparent bus mark is used in the compact rail.
- The map keeps the same glass radius as the rest of the shell; panning smoothness is NOT TESTED.
- The icon artwork is centered on a white rounded-square backing with transparent space outside the tile. No source artwork was edited.
