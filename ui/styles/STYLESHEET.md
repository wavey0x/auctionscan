# UI Style Guide

Auctionscan is a compact, monochrome instrument for inspecting auctions. It is
monospace throughout, flat, dense, and quiet until something needs attention.
When this file and the code diverge, the implementation in `ui/src` is the
source of truth; update this file.

## Principles

1. **Figures first.** A screen is labels and numbers; no sentence explains what a table shows.
2. **One device, one meaning.** A chip, dot, bar or chevron does the same job on every screen,
   and an indicator is never replaced or narrated by words.
3. **Quiet normal, loud exception.** A sold round carries a small muted check. A live round is the
   one mark that moves; an expired lot is the one that warns.
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
  tracking (`label`, `text-table-header`). Chips, nav and values stay in normal case.
- Tabular figures wherever numbers stack. Regular weight; emphasis comes from colour and position,
  not bold.

| Size | Use |
| --- | --- |
| 11px | Labels, table headers, sub-lines, units |
| 12px | Table cells, controls, nav |
| 13px | Body |
| 15px | Outcome figures in the round drawer |
| 16px | Wordmark, entity headings, the round and pair in the drawer head |
| 17px | Strip figures (15px on phones) |

## Colour

Tokens live in `src/index.css` as CSS variables, with Tailwind aliases in `tailwind.config.js`.
Dark is the default theme; the toggle stores `ui_next_color_mode`.

| Role | Tokens | Used for |
| --- | --- | --- |
| Neutral | `background`, `surface`, `hover`, `selected`, `primary`, `secondary`, `tertiary`, `faint`, `divider*` | Text, rules, surfaces, meters |
| Accent | `accent` | Focus ring, open-row edge, active sort arrow, linked-identity hover, take marks on the price chart |
| Status | `active-mark`, `sold-mark`, `warning-mark`, `negative` | Live dot and meter, the sold check, expired dot and meter, failures |
| Direction | `positive`, `negative` | PnL figures, always with a sign |

- Active navigation uses a primary underline, not the accent.
- Status colour never fills a row. Never colour alone: a dot has its word, a PnL figure its sign.
- Round status has a shape as well as a tone: Live is a pulsing green dot, Sold a muted green circled
  check, Expired an amber dot, Settled a hollow ring. Every mark sits in the same 13px slot so the
  words align down a column.

## Shell and layout

- Sticky top bar on a solid background with a hairline rule: wordmark, underlined text nav (Rounds,
  Takers), search with a `/` shortcut, the data-age control and the theme toggle.
- The data-age control ("Updated 12s ago") opens a menu of networks with links to Status, Docs and
  API Docs. The footer repeats those links and is never fixed to the viewport.
- It is also the one place a failed refresh is reported. When a request that already has data on
  screen is not answered, the section keeps what it last loaded and says nothing; the control reads
  "Not updating" with a red dot until requests are answered again. A section shows an error with
  Retry only when it has nothing loaded to show.
- The shell is up to 1600px wide with 24px gutters (12px on phones). Data views get the width.

## Surfaces

- Cards, strips and panels: `surface` fill, 1px `divider` border, 6px corners, no shadow.
- Controls: 4px corners. Inputs are bordered and flat; focus changes the border, never a glow.
- Filter groups are flat segmented controls (`ChipGroup`, the pager): a hairline frame with the
  chosen keys filled in `selected`.
- Menus and the drawer are the only surfaces with a shadow (`--overlay-shadow`).

## Page anatomy

| Layer | Job |
| --- | --- |
| Strip | Optional entity totals on detail pages; the rounds list starts directly with its filters |
| Filters | One line of chip groups (round status with its counts, then chain) and a search field on the right. Version belongs in auction details, not list filters |
| Table | One card; see Tables |
| Drawer | One round's execution workspace |

The rounds list has no summary strip, totals or totals-window selector. Everything that filters
its rows is a chip group on one line: there are no tabs. Round status is the first group, each
chip carrying its count.

When the list's filters or page change, keep the previous rows and counts visible until the
response arrives. Rows that are waiting to be replaced dim after a short delay and open nothing, by
pointer or by keyboard; pagination waits for the requested page. Skeletons are for the initial
load only, so changing a filter never collapses the counts or swaps table geometry.

## Tables

- One line per row. Identity on the left, figures right-aligned.
- Columns drop by priority as the table's container narrows instead of scrolling sideways:
  `col-xl` under 1040px, `col-md` under 860px, `col-lo` under 620px. Once a column is gone its
  meaning moves into the identity cell's `sub-line`; text that only belongs on phones goes in a
  `sub-lo` span. A round's takes add one tier, `col-xs` with `sub-xs`, under 440px.
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

Every row of a meter column carries the meter, whatever its status. Where an indicator already
says something, no text is added to narrate it: an expired round is a full amber time bar, and what
its lot did is read from the sold view, the Received and PnL columns, or the drawer.

## Round drawer

- A round opens in a drawer (500px, 560px from 1700px) floating over the right of the list without a
  scrim. Under 760px it is a bottom sheet over a dimmed page.
- Back, Esc, the close control and a click on nothing that acts close it. Another row, or ↑/↓, moves
  it there and replaces the history entry, so Back still closes the drawer.
- It reads top to bottom as a receipt, and says nothing twice. A finished round:
  1. **Head**, two lines that share one left edge. First the pair, each token with its logo; it has
     the line to itself, so names are not cut, and on a sheet too narrow for both it breaks after
     the arrow, so the two logos stack on one edge. Beneath, the round's state, its number and the auction address; the address reveals
     its utilities when pointed at. The version is a Details row, and the chain gets a mark only
     once there is more than one chain to tell apart.
  2. **Result**, one row: Sold, Received, PnL. Each is a label, a bare 15px figure and its dollar
     value on a quieter line, so the row reads as a sum: market value, proceeds, difference. The
     head names the tokens in the order the figures follow. A cell exists only when it has something
     to say: a round that ended without a take shows its Lot alone.
  3. **Facts**, one line: when it was kicked and how it ended (`sold in 10h 0m`). If the lot did not
     clear it says what happened to it: `nothing sold`, `38% sold · 445K GROVE left`, or
     `all but dust sold` when under 0.01% remained. An expiry is a fact about time, not about
     sales, so it never stands without this.
  4. **Takes**, one line each: take, taker, time since the kick, received, PnL. Opening a row shows
     the rest. An empty list is `none` beside the heading.
  5. **Price**: the price path as a bare shape.
  6. **Details**, collapsed by default: the start price, kick quote and average take on consecutive
     rows, then decay, cutoff, receiver and the contract version.
- A live round has different priorities, so it leads with what is still open:
  1. **Live row**, in place of the facts and in the result row's shape: Remaining over its value,
     Price now over its distance from the kick quote (`26.3× quote`, `+4.2% vs quote`), and Time
     left over the scheduled length. Every cell is a bare figure and one short line.
  2. **Price** moves up to sit directly under it and marks the present moment on the curve, which
     is why the row above carries no meter.
  3. **Result** appears beneath the chart once the first take lands, then **Takes** and **Details**.
- A token is named once, in the head, beside its logo. Figures beneath it are bare, in the summary
  and in rows of takes; the workspace's column headers carry the unit, and hovering a figure gives
  the exact amount with its symbol. Logos appear again only in an opened
  take. Dollar values in the drawer are written in full (`$1,627`), not compact. The live price is
  held to six significant digits so its width stays steady as it falls.
- A take's time is its distance from the kick (`+9h 57m`), which is also its place on the price
  path; the timestamp is on hover and in the opened row.
- The expand control widens it to an execution-review workspace (up to 1180px, remembered per
  browser, never on a sheet): every take column (tx, taker, time, sold, received, price, PnL), with
  the chart and the details side by side beneath.
- The price chart is a shape, not a figure to be read: the price stepping down from its start, the
  kick-time quote as a dashed line, each take as a dot, and a live round's present moment as a
  green dot. At rest it has no key, fill, axis, labels or grid.
- Pointing at the chart brings the figures back as one small stack: the moment under the pointer
  (`+3h 6m` and its timestamp), then Price, Quote, Start and, once there are takes, Avg take, each
  a label and a figure with the decimals aligned. The stack floats over the plot's far corner
  from the pointer and hangs from the plot's foot, so nothing around the chart moves and the
  section below is never covered. Section heads are always one line: a long note is cut, never
  wrapped.

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
