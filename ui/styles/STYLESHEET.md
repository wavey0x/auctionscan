# UI Style Guide

This app uses a restrained, data-first interface: compact spacing, flat bordered
surfaces, and color only where quick scanning materially benefits from it.

This document is a guide to the live UI system. It is not a component
inventory. When this file and code diverge, the current implementation in `ui`
is the source of truth.

## Design Principles

- Optimize for scanning rounds, takes, and auction history before ornament.
- Prefer alignment, spacing, and type hierarchy over decorative surfaces.
- Keep the interface compact, professional, and stable under heavy data density.
- Use color sparingly for lifecycle state, system state, and meaningful emphasis.
- Preserve the same layout language across pages: flat panels, tight tables, and
  clear drilldown paths.
- Avoid sprawl. New surfaces should reuse existing visual language rather than
  inventing a new page type or card style.

## Theme Tokens

The source of truth should be CSS variables, with matching Tailwind aliases.

### Core colors

| Token | Light | Dark |
| --- | --- | --- |
| `--color-background` | `#FFFFFF` | `#1A1A1A` |
| `--color-surface` | `#F9FAFB` | `#1E1E1E` |
| `--color-primary` | `#111111` | `#FAFAFA` |
| `--color-secondary` | `#6A6A6A` | `#D8D8D8` |
| `--color-tertiary` | `#9A9A9A` | `#A0A0A0` |
| `--color-divider-strong` | `#CCCCCC` | `#404040` |
| `--color-divider-subtle` | `#E6E7EB` | `#2A2A2A` |

### Accent tokens

- `--color-active`: live round emphasis
- `--color-complete`: sold or settled emphasis
- `--color-kickable`: secondary attention state
- `--color-positive`: positive confirmation such as copy success
- `--color-negative`: degraded or failed system state
- `--color-warning`: expired state or caution state

Dark mode should be controlled by the `dark` class on the `<html>` element.

## Typography

The actual system is best described as sans shell, mono data.

- Use sans for layout, navigation, labels, helper copy, and panel structure.
- Use mono for numeric values, timestamps, identifiers, addresses, hashes, round
  IDs, take IDs, and token amounts.
- Data-heavy inline identity cells can mix logo plus mono label.
- Keep the type scale fixed rather than inventing per-page sizes:
  - `title`: 18px
  - `heading`: 16px
  - `body`: 13px
  - `meta`: 12px
  - `table-header`: 11px uppercase
  - `data`: 12px monospace

## Shell And Layout

- Use a sticky top shell with a thin divider.
- Primary content width should support data views first, not marketing-style
  narrow layouts.
- Footer utility links should stay centered and low-emphasis.
- Use `overflow-y: scroll` on `html` to prevent layout shift when scrollbars
  appear.
- Prefer a small number of strong surfaces over many weak ones.
- The main product pages should have clear roles:
  - `Rounds`: the scanning and filtering surface
  - `Auction`: the canonical auction-level overview and history surface
  - `Round`: the execution-review workspace

## Density

- Default to compact spacing.
- Most panels should feel closer to `p-3` or `p-4` than `p-6` or `p-8`.
- Rows should be tight, consistent, and easy to compare vertically.
- Avoid oversized hero treatments, decorative whitespace, and repetitive side
  panes.

## Navigation

- Header nav should use plain text links with an underline-style active state.
- Primary navigation should feel infrastructural, not promotional.
- Section-level navigation should use subtle border or underline changes instead
  of filled pills.
- Selection should feel closer to a terminal or admin console than a card
  gallery.

## Surfaces

- Use thin borders and light corner rounding.
- Avoid shadows as the default panel treatment.
- Prefer flat monochrome surfaces over tinted or frosted treatments.
- Group related information together instead of scattering the same context
  across multiple cards.

## Tables

- Tables are first-class product surfaces.
- Use sticky headers for long lists where possible.
- Keep row height tight and consistent.
- Right-align numeric columns.
- Left-align identity columns.
- Prefer row hover and row selection over heavy row fills.
- Dense table cells should avoid stacked helper text unless the second line
  materially changes interpretation.
- Chain columns should prefer icon-only rendering in dense lists.
- Status text in dense tables should be one word where possible.
- Pair or token cells in dense tables should show logo, symbol, and inline
  utility actions, not verbose metadata.

## Table Navigation Behavior

- Dense table rows should usually be the primary navigation target.
- Row click should preserve browser-native behavior:
  - normal click opens in place
  - middle click opens in a new tab
  - modifier-click should behave like a normal link
- If a row is clickable, inline identity links inside the row must still
  function independently.
- Do not add extra chevrons or duplicate drill-in affordances when row click
  already provides the primary action.

## Linked Identity Hover

Linked identity hover is a first-class scanning aid in dense tables.

- Scope is same table only.
- Identity matching is address-based only.
- Supported linked identities:
  - auction addresses
  - token addresses
  - taker addresses
- Matching should not bleed across other tables on the same page.
- Visual treatment is a dashed royal-blue border around the identity value.
- Do not tint the full row.
- Do not apply the pattern to headers, hero blocks, or side panels unless they
  become true table rows.

## Primary Product Surfaces

### Rounds list

- The main rounds table is the dominant scanning surface.
- Filtering and pagination should feel integrated into the table, not bolted on
  beside it.
- The table should prioritize operational fields over decorative summary fields.

### Round workspace

- The round summary should be dense and operational, not theatrical.
- Takes remain the dominant surface because execution review is the core task.
- Auction information should appear as supporting context.
- Take inspection should prefer an in-place drawer or adjacent drilldown over
  route churn.

### Auction page

- The auction page is the canonical auction-level surface.
- It should own configuration, history, recent rounds, and recent takes.
- It should avoid becoming a second round workspace.

### Search

- Search should look like a utility for fast navigation and lookup, not a
  consumer-style discovery page.
- Results should remain compact enough to scan without large cards.

## Forms And Filters

- Inputs are bordered, flat, and monochrome.
- Focus state is a border transition, not glow or shadow.
- Numeric and identifier-heavy fields should favor monospace readability.
- Filters should stay in one compact band when possible.
- Filters should auto-apply. Avoid explicit apply and reset buttons unless a
  control is genuinely expensive.
- The rounds page filter model is the reference shape:
  - status
  - chain
  - one generic filter input
- The generic filter input may accept:
  - token or pair-like text
  - full auction address
  - full take or kick transaction hash

## Progress And Timing

There are two meter patterns in the current UI. Do not treat them as
interchangeable.

### Detailed workspace meter

- Used on the round page header.
- Can show both:
  - `Time`
  - `Available`
- Uses thin bordered tracks.
- May show an early-close marker when a round sold out before scheduled expiry.
- The early-close marker should remain subtle and secondary.

### Compact table meter

- Used in dense tables where space is tighter.
- Default to a time-only meter when space is constrained.
- Show the early-close marker when applicable.
- Keep labels minimal and avoid turning the cell into a mini dashboard.

### Timing rules

- `scheduled_end_at` is the planned end of the round.
- `end_at` is the actual close time used by the UI.
- Sold or settled rounds may therefore close before the scheduled end.
- Dense table timestamps should default to short absolute local time using
  `MMM d HH:mm`.
- Full timestamps can remain available through `title` or a drawer, not as
  permanent secondary lines in dense rows.

## Identity And Linking

- Token logos are standard identity markers in dense surfaces.
- Logo handling should be backend-driven where possible.
- If no real token logo is known, use the shared fallback token logo rather than
  inventing initials or color chips.
- When an object has an in-app home, the primary text click should stay
  internal.
- External explorer navigation should use a separate inline icon.
- Copy should remain inline and always visible.
- Inline actions should not rely on hover-only reveal.
- Auction address text is a good reference pattern:
  - abbreviated mono text
  - primary internal link
  - separate explorer icon
  - separate copy icon
- Auction-address hover underline should stay softer than a generic body link.
- Transaction hashes should follow the same general hierarchy when they appear
  inline.

## Badges And Labels

- Auction version should use a very small bordered mono badge with low visual
  weight.
- Version badges should always render with a `v` prefix.
