# Earnalism Maison · Peacock Crest theme kit

Theme layer only. Menus, copy, content and component structure stay as they are in the Maison prototype.
The full spec is the handoff doc "Earnalism Maison: Peacock Crest theme handoff". The design canvas is the visual reference.

## Files

| File | What it is |
| --- | --- |
| `tokens.css` | Colour, type, spacing, radius, chrome and focus tokens as CSS custom properties |
| `tokens.json` | The same tokens plus ornament opacities, in design-token JSON |
| `theme.css` | The five theme layers, chrome, image frames and focus rules, built on the tokens |
| `example.html` | Minimal page using only `tokens.css` and `theme.css`, for a quick check at any width |
| `svg/kantha-tile.svg` | 72×72 wallpaper tile: gold stitch diamond at .10 plus rose corner dots at .5 |
| `svg/alpana.svg` | Alpana mandala, R 170 in a 480 box. The halo's opacity is applied in CSS. |
| `svg/alpana-halo.svg` | Same mandala with its glow baked in, for platforms without CSS gradients |
| `svg/peacock-crest.svg` | 260×68 crest: two peacocks facing a lotus with dashed side rules |
| `svg/jali-panel.svg` | 200×360 sidebar panel: jali lattice, double gold frame, alpana medallion |
| `svg/jali-tile.svg` | 44×44 jali tile, if the panel needs to be a different size |
| `svg/peacock.svg`, `svg/lotus.svg` | Single motifs, for spot use such as empty states and end cards |

## Rules that matter most

1. Never recolour, outline or invert the logo. It always sits on the ivory header.
2. Ornament is decorative: `aria-hidden="true"`, `pointer-events:none`, never above .12 effective opacity behind text.
3. Ford Gold (#B99A57) is for strokes, rules and frames only, never text.
4. On ivory surfaces the focus ring is rose (#894353). Brass on ivory is only 1.68:1.
5. No ornament on the reader page (S08), inside sheets and modals, or inside S26 state illustrations.

## Native apps

- **iOS:** import the SVGs into an asset catalog with "Preserve Vector Data" on. Tile the kantha with `UIColor(patternImage:)`.
- **Android:** convert the SVGs to VectorDrawables. `peacock-crest.svg` and `peacock.svg` use a clipPath for the hatched bodies, so check them after conversion.
- On both platforms, if a converter drops `opacity` on groups, set the alpha on the view instead.
