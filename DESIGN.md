# Earnalism · Maison design system (landing direction, 22 November 2026)

Owner palette: **Ivory, Dark Burgundy, Metallic Gold**, with layered, artistic surfaces — never one flat background. Direction set without UXKIN references (not connected); it follows the owner brief and the existing self-hosted fonts. The approved product theme (Peacock Crest) stays in the app until the owner approves this direction for all screens.

**Idea:** a library you can enter three ways — read, listen, watch. Surfaces behave like a bound book: laid ivory paper, a burgundy binding band that sweeps across sections, and gold foil used only as fine edges and one sculpted mark per view.

## Color

| Token | Value | Role |
|---|---|---|
| `--paper` | `#FBF6EC` | Main reading surface (laid-paper texture on top) |
| `--paper-deep` | `#F1E6D2` | Recessed panels, second layer of paper |
| `--rose-wash` | `#EBD3CF` | Soft wash behind the hero and shelf (decorative) |
| `--binding` | `#5A1426` | Burgundy band, primary buttons, footer |
| `--binding-deep` | `#3A0C18` | Pressed state, dark band edge |
| `--ink` | `#2A0B14` | Body and heading text on paper (16.4:1 on paper) |
| `--ink-soft` | `#5E4148` | Secondary text on paper (8.2:1) |
| `--gold-text` | `#7A5A1E` | Gold-coloured text/icons on paper (6.4:1) |
| `--gold-on-binding` | `#E9D29A` | Gold text on burgundy (9.6:1) |
| `--foil` | `linear-gradient(115deg,#8C6A2A,#E8CF8A 38%,#B58D3F 62%,#F3E2B0 80%,#9A7631)` | Decorative foil only — never behind text |

Primary action: burgundy fill, ivory text (`#FBF6EC` on `#5A1426` = 11.0:1). Focus ring: 3px `--binding` outline with 2px paper offset (gold ring on burgundy bands).

## Typography

- Display: **Cormorant Garamond** 500/600 — titles and the hero line; tight tracking (-0.01em), never all caps.
- Interface: **DM Sans** 400/500/600 — navigation, buttons, labels, body copy on marketing sections.
- Reading: **Source Serif 4** — book excerpts.
- Bengali: **Noto Serif Bengali** (excerpts, specimen) and **Noto Sans Bengali** (interface strings in book titles).

Scale (rem): 0.875 · 1 · 1.125 · 1.375 · 1.75 · 2.5 · 3.75 · 5.25 (display, clamp on mobile). Body 1.0625rem/1.65, serif excerpts 1.125rem/1.75. Line length ≤ 66ch.

## Spacing, shape, depth

- 8px scale: 4, 8, 12, 16, 24, 32, 48, 72, 112. Section padding 112px desktop, 72px mobile. Content width 1180px; text column 640px.
- Radius: 2px for paper edges and specimens (books have square corners), 999px only for pill toggles, 14px for the folio and media frames.
- Depth: one shadow, `0 18px 40px -24px rgba(42,11,20,.45)`, for objects that sit on paper (spines, folio). Bands carry no shadow.

## Components

- Buttons: primary (burgundy fill), secondary (ink outline on paper, gold outline on burgundy), quiet (underlined text link). Hover deepens the fill; disabled 45% opacity with no hover.
- Spines (three-ways shelf): uneven heights, each a button that expands its panel (`aria-expanded`), one open at a time.
- Specimen card: square-cornered paper slip with a gold hairline edge.
- Navigation: logo on paper, three text links, one primary button. Footer on burgundy band.

## Imagery and motion

- No stock photos. Abstract inline SVG marks: folio, page lines, waveform, film frame with subtitle bar, gold thread for learning paths.
- One orchestrated moment: on load the folio's pages fan once (900ms). Everything else is static; hover only changes colour. `prefers-reduced-motion` removes the fan.
- Logo: official `static/maison/logo.png`, unmodified, always on paper.
