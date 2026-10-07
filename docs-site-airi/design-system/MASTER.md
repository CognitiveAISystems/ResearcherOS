# ResearcherOS docs-site — Design System

## Product
Public landing for ResearcherOS (code / hub): one continuous page + deep-link detail pages.

## Pattern (UI/UX Pro Max)
**Scroll-Triggered Storytelling**
1. Intro hook (hero) — brand only
2. About — what it is
3. How to start — three paths
4. Skills — grid → detail pages
5. Lessons — list → detail pages
6. Sticky strip nav with active section

## Visual language = platform
Keep `web/styles.css` tokens (not indigo academic defaults from generic DS):
- Fonts: **Syne** + **Outfit**
- Gradients: pink → purple → cyan
- Light `#eef1f6` / Dark `#06060a`, mesh + grid
- Glass surfaces, 180–300ms hover, IntersectionObserver reveal
- Theme key `koi-theme` shared with UI

## Motion
- Section reveal on scroll (`cubic-bezier(0.16, 1, 0.3, 1)`, ~400ms)
- Sticky bottom strip; highlight current chapter
- `prefers-reduced-motion`: no reveal delay / no parallax

## Navigation
- Landing anchors: `#about` · `#start` · `#skills` · `#lessons`
- Detail pages (`skills/*`, `start/*`, `lessons/*`): always **← ResearcherOS** back to landing section
- No emoji icons; SVG only

## Detail pages (skills / tutorials)
UI/UX Pro Max: Minimal Single Column + Back Button (no fixed bottom strip on detail).

- Same mesh/grid tokens, Outfit/Syne
- Compact header wordmark (`.brand__logo` height ~1.55rem; **never** let global `img{max-width:100%}` stretch it)
- Nav in one row: About / How to start / Skills / GitHub / theme
- One H1; `← Skills`, `← How to start`, or `← Lessons` back link only (no crumbs + no second sticky strip)
- Article ~42rem; graph centered; glass example blocks
- Footer normal (not padded for a missing sticky bar)

## Visual audit (2026-07-16) — fixed
- Header logo inflated to full width (global img rule) → constrained `.brand__logo`
- Triple nav (header + crumbs + sticky strip) → header + back only
- Missing `.page-detail` / `.article` CSS → restored
- Graph left-biased empty card → centered

## Avoid
- Competing brand marks; duplicate sticky chapter strip on detail pages
- Jumping anchors without smooth scroll on landing
