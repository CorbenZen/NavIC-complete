# Menu and topbar repair decisions

## Implementation decisions

- **Cause of the rail square:** the backed-up stylesheet contains `.sidebar.is-rail .sidebar-brand-row::after` with `content: ''`, a 28×28 size, border, radius, and glass background. It is an empty CSS pseudo-element, not an empty button or browser portal. The old style block also contains a collapse selector that no longer matches the current JSX. Both are preserved in `_archive/20261115T132602Z/frontend/css-styles/global/rail-artifacts.css`; the active stylesheet no longer contains these selectors.
- **Playwright element evidence:** NOT TESTED. The requested `document.elementFromPoint(55, 155)?.outerHTML`, computed-style, and ancestor output is implemented in `scripts/smoke_routes.mjs`, but neither Playwright browser executable could launch. The exact browser `outerHTML` was not captured; the pseudo-element cause above comes from source inspection of the pre-edit stylesheet backup.
- **One popup layer:** user and theme menus and sidebar/topbar hint tooltips all render through `ShellPopover` into `document.body`. This avoids the filtered sidebar becoming the containing block for positioned descendants and lets the panel blur the page behind it. A document event closes any other open menu and suppresses tooltips while a menu is open.
- **Placement:** topbar menus use `bottom-end`; the expanded footer menu uses `top-start`; the collapsed footer menu uses `right-end` with a 12px gap from the rail; narrow viewports use a viewport-clamped sheet. Placement is recalculated after viewport resize and captured ancestor scroll.
- **Menu behavior:** click outside closes; Escape closes and restores focus; Tab leaves and closes; route changes remount the triggers; menu items use native buttons with `role="menuitem"`, ArrowUp/ArrowDown/Home/End focus movement, and Enter/Space native activation.
- **Topbar:** the 1px observer sentinel drives `data-scrolled`. Stable scrollbar gutter and the 24px desktop padding keep actions inside the content edge. The hamburger remains hidden at 768px and wider. At narrow widths the demo-auth warning text stays visible while simulation/link status compresses as requested.
- **Glass colors:** menus use `--glass-bg-strong` (`rgba(255,255,255,0.88)` light; `rgba(18,20,24,0.82)` dark), 20px blur, shared border/highlight/shadow tokens, opaque fallback, and reduced-transparency fallback. Menu-specific danger text colors were darkened/lightened after the contrast run found the earlier values below 4.5:1.
- **Dependencies:** no runtime or development dependency was added. The already installed `lucide-react` exports for the menu icons were checked with Node before use.

## Contrast output

Command: `cd frontend && npm run contrast`. The script composites menu glass and hover surfaces over the bright accent sample `#3ea6ff` and a white card (`#ffffff`).

```text
PASS light body text: 16.04:1 (required 4.5:1)
PASS light section label: 7.34:1 (required 4.5:1)
PASS light icon: 10.21:1 (required 3:1)
PASS light active icon/focus: 7.46:1 (required 3:1)
PASS light badge text: 6.57:1 (required 4.5:1)
PASS light topbar text: 17.79:1 (required 4.5:1)
PASS light topbar icon: 10.21:1 (required 3:1)
PASS light topbar status pill text: 6.12:1 (required 4.5:1)
PASS light topbar pill border: 6.12:1 (required 3:1)
PASS light control border: 4.38:1 (required 3:1)
PASS light menu text: 14.60:1 (required 4.5:1)
PASS light menu icon: 9.29:1 (required 3:1)
PASS light menu danger text: 5.81:1 (required 4.5:1)
PASS light menu hover text: 12.47:1 (required 4.5:1)
PASS light menu hover icon: 7.94:1 (required 3:1)
PASS dark body text: 16.28:1 (required 4.5:1)
PASS dark section label: 10.77:1 (required 4.5:1)
PASS dark icon: 12.91:1 (required 3:1)
PASS dark active icon/focus: 9.54:1 (required 3:1)
PASS dark badge text: 6.57:1 (required 4.5:1)
PASS dark topbar text: 14.80:1 (required 4.5:1)
PASS dark topbar icon: 12.91:1 (required 3:1)
PASS dark topbar status pill text: 9.90:1 (required 4.5:1)
PASS dark topbar pill border: 4.38:1 (required 3:1)
PASS dark control border: 4.22:1 (required 3:1)
PASS dark menu text: 9.73:1 (required 4.5:1)
PASS dark menu icon: 7.72:1 (required 3:1)
PASS dark menu danger text: 5.40:1 (required 4.5:1)
PASS dark menu hover text: 7.41:1 (required 4.5:1)
PASS dark menu hover icon: 5.88:1 (required 3:1)
```

## Browser availability

`npm run smoke` output:

```text
NOT TESTED Chromium: Playwright browser launch failed: browserType.launch: Executable doesn't exist at /home/corben/.cache/ms-playwright/chromium_headless_shell-1255/chrome-headless-shell-linux64/chrome-headless-shell
NOT TESTED Firefox: Playwright browser launch failed: browserType.launch: Executable doesn't exist at /home/corben/.cache/ms-playwright/firefox-1572/firefox/firefox
SMOKE FAIL (12 routes × 2 themes × 2 browsers × 4 viewports)
FAILURE Chromium browser unavailable
FAILURE Firefox browser unavailable
```

Browser installation was attempted with Playwright in `/tmp/cbtms-playwright`, but its download failed with `getaddrinfo EAI_AGAIN cdn.playwright.dev`. A direct Playwright launch attempt against `/usr/bin/firefox` exited with SIGSEGV. Therefore the rail point inspection, route and viewport layout matrix, menu interactions, visual blur, Chromium screenshots, and Firefox screenshot are all NOT TESTED. Exact manual steps are in `docs/MANUAL_TESTS.md`.
