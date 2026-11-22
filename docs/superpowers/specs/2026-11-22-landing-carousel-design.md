# Landing 3D carousel — design

Owner decisions, 22 November 2026. Goal chosen by the owner: **sign up free and start one chapter.** Status: proposed, awaiting owner approval.

## Intent

Turn a visitor's spare screen time into a first chapter. The carousel's single job is to move a guest from "browsing" to "reading Chapter 1" through a free sign-up that returns them to the exact page. Revenue comes later from a paid Earnalism Pass (prices not yet approved); every member gained now is the base that offer will sell to.

## Goals, non-goals, anti-goals

- Goal: raise the share of landing visitors who sign up **and** open Chapter 1 in the same session.
- Goal: make the "productive screen time" idea concrete — a real page you can read in five minutes, not a slogan.
- Non-goal: selling a paid plan, showing prices, or collecting payment details.
- Anti-goals: promising formats that are not released (audio and video are labelled "coming soon"); invented member counts, ratings or testimonials; a carousel that hides content behind motion or cannot be paused.

## Constraints

- Hero illustration stays intact; the carousel sits directly below the hero.
- Catalogue today: The Selfish Giant (English) and বিচারক (Bengali). Listen and Learn are not released.
- Accessibility: visible pause, never moves for reduced-motion users, stops on hover, focus and hidden tab, keyboard and swipe navigation, WCAG 2.2.2.
- Design language: handmade paper, 3D paper cards, capsule controls, Cormorant / DM Sans / Source Serif 4, approved palette.
- $0 spend; no ad accounts are connected, so there is no paid-traffic data yet.

## Approaches considered

1. **Cover-flow shelf** — a curved 3D row of book and lesson covers turning past a centre spot. Shows breadth, but with two released titles it looks empty and pushes browsing rather than one action.
2. **Taste-first page turner (chosen)** — four stacked paper "moments" that turn like pages in 3D. Each pairs a leisure moment with a real thing to do in it, and every card carries the same one action: *Start Chapter 1 free*. Honest with a small catalogue, sells the habit, and the first card is an actual opening paragraph so the visitor starts reading before signing up.
3. **Feature tour** — slides explaining Read / Listen / Learn features. Informative but feature-led; it repeats the hero and the cards below it and gives no reason to act now.

## Design

Placement: full-width band under the hero, on handmade paper, headline "Swap one scroll for one story."

Cards (each a 3D paper sheet, the next two peeking behind, turning on a left-edge hinge):

| # | Moment (headline) | What the card shows | Angle it tests |
|---|---|---|---|
| 1 | Five spare minutes? Read a page, not a feed. | The real opening paragraph of *The Selfish Giant* on a page with a drop cap and "about 5 min" | Time swap |
| 2 | Your language, your shelf. | বিচারক and The Selfish Giant side by side, Bengali set in Noto Serif Bengali | Identity / culture |
| 3 | Your place follows you. | A progress ribbon moving phone → laptop, "Pick up where you left off" | Habit / continuity |
| 4 | Learn one idea at a time. | A knowledge-series path, clearly marked **coming soon** | Self-growth (future) |

Every card: one primary button **Start Chapter 1 free** → sign-up that returns to Chapter 1 of the card's title (card 4 → The Selfish Giant); a quiet link **Explore the library**.

Behaviour: auto-advance every 7 s; pauses on hover, focus, touch and when the tab is hidden; visible Pause/Play capsule; arrows and four dots as a capsule control matching the menu; swipe on touch; arrow keys when focused; reduced motion → no auto-advance, cross-fade instead of page turn; screen readers get "Card 2 of 4" and a live region only when the user moves it.

Measurement: events `carousel_card_viewed`, `carousel_cta_clicked`, `auth_completed`, `chapter_started` with opaque card and title IDs (no personal data). Success = visitors who start Chapter 1 ÷ landing visitors, read per card. Once traffic exists, test card order and the card-1 headline (time swap vs culture) one variable at a time.

## Left to the builder

Exact turn easing and timing, peek offsets, and mobile card height — within the reduced-motion and accessibility rules above.
