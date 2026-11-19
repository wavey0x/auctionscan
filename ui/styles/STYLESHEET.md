# UI Style Guide

Auctionscan is a compact, monochrome instrument for inspecting auctions. It is
monospace throughout, flat, dense, and quiet until something needs attention.
When this file and the code diverge, the implementation in `ui/src` is the
source of truth; update this file.

## Principles

1. **Figures first.** A screen is labels and numbers; no sentence explains what a table shows.
2. **One device, one meaning.** A tab, chip, dot, bar or chevron does the same job on every screen.
3. **Quiet normal, loud exception.** Finished rounds are neutral. A live round is the one mark that
   moves; an expired lot is the one that warns.
4. **Compact, never cramped.** 38px rows (44px on touch), strict alignment, nothing that identifies a
   row is lost when columns drop.
5. **Restraint over polish.** Solid fills, hairline borders, small corners. No gradients, highlights or
   raised controls. Depth is reserved for things that float: menus and the round drawer.

## Typography

- Monospace everywhere (IBM Plex Mono, shipped with the app): wordmark, navigation, filters, labels,
  table headers and data. Tailwind's `font-sans` maps to the mono stack on purpose.
- Sans (`prose-text`, `font-prose`) only for longer explanatory text, such as the pricing method page.
- The wordmark is plain `AUCTION SCAN`.
- Labels, table headers, card titles and drawer section heads are 11px uppercase with 0.08em
  tracking (`label`, `text-table-header`). Tabs, nav and values stay in normal case.
- Tabular figures wherever numbers stack. Regular weight; emphasis comes from colour and position,
  not bold.

| Size | Use |
| --- | --- |
| 11px | Labels, table headers, sub-lines, units |
| 12px | Table cells, controls, nav, tabs |
| 13px | Body |
| 16px | Wordmark, entity headings, the round number in the drawer |
| 17px | Strip figures (15px on phones) |

## Colour

Tokens live in `src/index.css` as CSS variables, with Tailwind aliases in `tailwind.config.js`.
Dark is the default theme; the toggle stores `ui_next_color_mode`.

| Role | Tokens | Used for |
| --- | --- | --- |
| Neutral | `background`, `surface`, `hover`, `selected`, `primary`, `secondary`, `tertiary`, `faint`, `divider*` | Text, rules, surfaces, meters |
| Accent | `accent` | Focus ring, open-row edge, active sort arrow, linked-identity hover, take marks on the price chart |
| Status | `active-mark`, `warning-mark`, `negative` | Live dot and meter, expired dot and meter, failures |
| Direction | `positive`, `negative` | PnL figures, always with a sign |

- Active navigation and tabs use a primary underline, not the accent.
- Status colour never fills a row. Never colour alone: a dot has its word, a PnL figure its sign.
- Round status: Live is a pulsing green dot, Sold a neutral dot, Expired amber, Settled a hollow ring.

## Shell and layout

- Sticky top bar on a solid background with a hairline rule: wordmark, underlined text nav (Rounds,
  Takers), search with a `/` shortcut, the data-age control and the theme toggle.
- The data-age control ("Updated 12s ago") opens a menu of networks with links to Status, Docs and
  API Docs. The footer repeats those links and is never fixed to the viewport.
- The shell is up to 1600px wide with 24px gutters (12px on phones). Data views get the width.

## Surfaces

- Cards, strips and panels: `surface` fill, 1px `divider` border, 6px corners, no shadow.
- Controls: 4px corners. Inputs are bordered and flat; focus changes the border, never a glow.
- Filter groups are flat segmented controls (`ChipGroup`, `Segmented`): a hairline frame with the
  chosen keys filled in `selected`.
- Menus and the drawer are the only surfaces with a shadow (`--overlay-shadow`).

## Page anatomy

| Layer | Job |
| --- | --- |
| Strip | One card of at most five totals for the filters in scope, label above figure |
| Tabs | Choose the rows (round status); each carries its count |
| Filters | One line: chain and version groups, a search field on the right |
| Table | One card; see Tables |
| Drawer | One round's execution workspace |

## Tables

- One line per row. Identity on the left, figures right-aligned.
- Columns drop by priority as the table's container narrows instead of scrolling sideways:
  `col-xl` under 1040px, `col-md` under 860px, `col-lo` under 620px. Once a column is gone its
  meaning moves into the identity cell's `sub-line`; text that only belongs on phones goes in a
  `sub-lo` span.
- Rounds keep Auction and PnL at every width. Round, progress and kick time go first, then status,
  lot and received, which move into the sub-line on phones.
- Long token amounts clip inside `cell-clip` with an ellipsis; the full amount is on hover.
- Headers are sticky, uppercase and flat.
- Hover is `hover`; the open row is `selected` with a 2px accent edge on its first cell.
- Copy and explorer icons surface on row hover or focus, stay visible on touch, and are dropped on
  phones. Rows open with a click, Enter, or ↑/↓ then Enter. A row that opens something ends in `›`.
- Sort arrows show only on the active column.
- Loading is skeleton rows in the shape of the table.

Linked identity hover stays: within one table, hovering an auction, token or taker address outlines
each matching address in that table with a dashed accent border.

## Meters

Flat 4px fills with square ends. A bar on a track is a share of a limit (time elapsed, lot sold, sync
progress); a bar without a track (`.bar.is-relative`) is size against the column's largest. Meters
keep their row's tone: live green, expired amber, everything else neutral. An early close is a tick.

## Round drawer

- A round opens in a drawer (500px, 560px from 1700px) floating over the right of the list without a
  scrim. Under 760px it is a bottom sheet over a dimmed page.
- Back, Esc, the close control and a click on nothing that acts close it. Another row, or ↑/↓, moves
  it there and replaces the history entry, so Back still closes the drawer.
- Order: head, summary (lot, received, PnL, price now or execution, kicked), time and sold meters,
  **takes**, a compact price chart, then kick-time settings collapsed by default.
- The expand control widens it to an execution-review workspace (up to 1180px, remembered per
  browser): every take column (tx, taker, time, sold, received, price, PnL), with the chart and the
  settings side by side beneath.
- The price chart draws the start price stepping down by its decay, the kick-time quote as a dashed
  line, the minimum price when in range, each take as a dot, and a live round's current price.
  Hovering reads the price at any moment of the round.

## Motion

Allowed: the skeleton shimmer, the live dot's slow pulse, one pulse on the data-age dot when a newer
block lands, the drawer and sheet transitions, and 100–150ms hover changes. No number-refresh
effects, no intro animations, nothing else moving at rest. `prefers-reduced-motion` turns all of it
off.

## Numbers and words

- Money in lists is compact at three significant digits (`formatCompactUsd`): `$23.4M`, `$6.70M`,
  `$161K`. The exact value is on hover.
- PnL percent is signed with a true minus (`−0.24%`); its USD delta follows in a quieter figure.
- A figure computed from incomplete pricing carries a small `partial` note with the coverage on hover.
- Dense tables show relative ages (`4h ago`) or `MMM d HH:mm`; the full timestamp is in the title.
- Version badges are small bordered marks with a `v` prefix.
- Token logos are backend-driven; unknown tokens use the shared fallback logo.
