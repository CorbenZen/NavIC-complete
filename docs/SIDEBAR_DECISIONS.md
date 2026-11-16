# Sidebar redesign decisions

## Decisions

- Use one `--sidebar-w` variable on the app shell: 272px expanded, 80px rail, and 0px layout offset on mobile. The drawer overlays the page so opening it does not resize or horizontally scroll the content.
- Keep the existing banner image unchanged and place it in a dark rounded square tile. The image itself contains dark artwork, so the constant dark tile prevents it from blending into the light glass surface.
- Use a high-opacity translucent pane (93%) with an 18px backdrop blur. Lower opacity would make the bright ambient gradients reduce text and border contrast; the glass still picks up softened color and blur while keeping labels legible.
- Limit backdrop blur to the sidebar and its footer card. The map and page content are not filtered, avoiding a blur layer over Leaflet's frequently repainted map.
- Use the existing `NAV_GROUPS` as the shared route source for the sidebar, app route metadata, breadcrumbs, and command palette. Keep its current paths and role filtering.
- Persist only the expanded/rail preference under `cbtms-sidebar-collapsed`; responsive defaults apply when no preference exists. Mobile always starts as a closed drawer.
- Reuse a single `selectDeviceAttention()` selector for the dashboard's no-session/stale-device rows and the Devices badge. Do not create another request or polling loop.
- Show a live tracking dot only when the existing WebSocket state is online and a stored position is no older than two minutes. Source labels use the existing simulation summary and explicit hardware provenance.
- The optional recently visited list and collapsible navigation sections were skipped to keep the navigation focused and avoid introducing extra persisted state.
- No source files were archived because the former sidebar markup was replaced in `Shell.jsx`; there was no separate dead implementation to preserve.
- Added Playwright as a development-only dependency because the requested route/theme/responsive browser smoke test needs an automated browser. It is not included in the app runtime bundle. The normal install hit an existing peer conflict (`@eslint/js@10` expects ESLint 10 while the project has ESLint 9); `npm install --save-dev playwright --legacy-peer-deps` added only Playwright without changing the existing ESLint versions.

## Verification evidence

`npm run contrast` output (reads token colors directly from `styles.css`):

```text
PASS light body text: 16.04:1 (required 4.5:1)
PASS light section label: 7.34:1 (required 4.5:1)
PASS light icon: 10.21:1 (required 3:1)
PASS light active icon/focus: 7.46:1 (required 3:1)
PASS light badge text: 6.57:1 (required 4.5:1)
PASS light control border: 4.38:1 (required 3:1)
PASS dark body text: 16.28:1 (required 4.5:1)
PASS dark section label: 10.77:1 (required 4.5:1)
PASS dark icon: 12.91:1 (required 3:1)
PASS dark active icon/focus: 9.54:1 (required 3:1)
PASS dark badge text: 6.57:1 (required 4.5:1)
PASS dark control border: 4.22:1 (required 3:1)
```

`npm run check`: PASS. ESLint reported 0 errors and 36 warnings; Vite built 2,171 modules. Build output also includes the existing large-chunk and `use client` bundler notices.

`npm run smoke`: NOT TESTED. The command launched but stopped before route navigation because Playwright Chromium was absent. `npx playwright install chromium` could not reach `cdn.playwright.dev` (`getaddrinfo EAI_AGAIN`).

In-app browser observations at its 1100×900 viewport: expanded sidebar, rail after clicking the collapse control, persisted rail after reload, expanded rail after Ctrl+B, and command palette opening from the sidebar search trigger. The light theme screenshot showed weak inactive-link contrast on the first pass; explicit foreground tokens were applied and a subsequent screenshot showed dark readable inactive labels. These images were displayed in the working session but were not saved as the requested PNG files.

Required 1440px and 390px screenshot artifacts, all-route × both-theme × three-width browser smoke, keyboard focus tooltip, mobile drawer focus trap/overlay/Escape/route-change, and map pan performance: NOT TESTED. See `docs/MANUAL_TESTS.md` for exact next steps.
