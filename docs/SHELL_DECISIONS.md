# CBTMS shell decisions

## Layout and interaction choices

- **One shared header height:** `--shell-header-h: 64px` controls both the sidebar brand header and the topbar. This keeps their border lines aligned as the main shell changes width.
- **Scrollable navigation:** the sidebar is a full-height flex column; its nav is the flexible, independently scrolling region, while the brand header and footer do not shrink. This keeps Settings reachable on short displays.
- **Edge collapse handle:** one 28px round button sits across the sidebar edge at half the shared header height. The 80px rail centers the brand mark so the handle can sit beside it.
- **Single spacing rhythm:** section text and icon columns share the same 24px content alignment; rail items center their icon column. Section group spacing remains consistent in both states.
- **Footer state:** the footer uses the existing FleetContext WebSocket state, update timestamp, and signed-in user. It omits the duplicate `WS` chip and simulation mode row because the topbar already displays the shared connection and mode indicators.
- **Ambient backdrop:** blur is limited to the sidebar, topbar, footer surface, drawer, and edge handle. The map wrapper is isolated to keep Leaflet stacking inside the content layer. If map panning stutters, use the manual check in `docs/MANUAL_TESTS.md`; that performance check is NOT TESTED in this run.
- **Mobile behavior:** the existing shell hook and drawer implementation remain the source of responsive state. The browser interaction matrix is NOT TESTED because the Playwright Chromium executable is missing.

## Logo and browser icon choices

- `frontend/public/logo.png` is a symlink to `images/logo.png`; `ls -l` showed `logo.png -> images/logo.png`. I preserved the symlink and copied `logo1.png` to its target so both existing URL and imports remain intact.
- ImageMagick inspection showed `logo1.png` is 2000×2000, sRGBA and opaque. `tab1.png` is 600×600, sRGBA with transparency. The expanded sidebar uses the full app logo; the collapsed rail uses `tab.png`, which is byte-identical to `tab1.png`.
- The tab mark is dark navy with transparency, so the favicon family uses `tab1.png` centered on a white rounded-square tile with transparent space outside the tile. The supplied generated icons were not regenerated from `logo1.png`; `magick` generated the requested sizes from `tab1.png`.
- Existing maskable manifest entries were retained and now point to the corresponding tile-based 192px and 512px files. The index and service worker URLs use bumped cache versions.
- No runtime dependencies were added. The already-installed ImageMagick 7 `magick` CLI was used for image generation.

## Contrast script output

Command: `cd frontend && npm run contrast`

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
```

## Asset evidence

`magick identify` output:

```text
public/favicon.ico[0] ICO 16x16 16x16+0+0 8-bit sRGB 0.000u 0:00.000
public/favicon.ico[1] ICO 32x32 32x32+0+0 8-bit sRGB 0.000u 0:00.000
public/favicon.ico[2] ICO 48x48 48x48+0+0 8-bit sRGB 15086B 0.000u 0:00.000
```

`sha256sum` output (new file followed by its pre-edit backup where applicable):

```text
0ff36e86532072c52703d1ed91def1a7626b0a0b707a36390712dfd3c6efc40f  public/logo1.png
0ff36e86532072c52703d1ed91def1a7626b0a0b707a36390712dfd3c6efc40f  public/images/logo.png
719cd2da2ecbbb388ecd9005e98dd1b70d29e87cc8423eb3ad9bea9db28a002d  ../backups/shell_20261115T124914Z/frontend/public/images/logo.png
dac46904478505317014a34668b2e19dbbfd5920d4b21e97ba36f096f58b0193  public/tab1.png
dac46904478505317014a34668b2e19dbbfd5920d4b21e97ba36f096f58b0193  public/tab.png
95043ebb3a9e306a92248de0effd7166ab7ca9ece57e84f15bea4b6757129231  ../backups/shell_20261115T124914Z/frontend/public/tab.png
635c3724eb441045fcf93368a7abd7da7ac36bba1c126f440d1acecce2713e11  public/favicon.ico
73f69b873d2d3eeeec5bec3ea31c6e4c18587d2637a4a627eec2b4efad7c2ba9  ../backups/shell_20261115T124914Z/frontend/public/favicon.ico
a9dff1081fb0bb21230ffdba377ca9e712a388b11f59500c9acfb727cfd03a6d  public/favicon-32.png
33764b50146d5cb70f1856a6198623af93bf28f481ff608d18248dfe1b3667ae  ../backups/shell_20261115T124914Z/frontend/public/favicon-32.png
e5e9170f1ed489be2ba225e2ca0b3ff22d6f983528f937e0ae1fad81b2bdf0c3  public/apple-touch-icon.png
a8f63f2d45844d5d84a5c2e69f4b0a1f2eab91fa6ed59e30fa455388340dab8b  ../backups/shell_20261115T124914Z/frontend/public/apple-touch-icon.png
d906de9de99da3b4d5fcf62e7aa056056e7b15351db48fa067f32dbda38d978d  public/icon-192.png
b3ebbef3f7c9ff949c7e690e2df3e7721f01b6a6ba38edda0c6198782ff5ff52  ../backups/shell_20261115T124914Z/frontend/public/icon-192.png
c58a737b2c6461c3dc86233c3778cf1b8fb4ca8d1dfa4e9055b46da3b5dce94c  public/icon-512.png
11d56f0669ea2d5e927fa0fbc79e5645e69652a90e540fb15aa9f026190f3816  ../backups/shell_20261115T124914Z/frontend/public/icon-512.png
```

The public `logo.png` symlink was preserved. The image source and installed target hashes match, and the old logo hash is recorded from the backup.
