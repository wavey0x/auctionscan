# UI Style Guide

Auctionscan is a data-first interface: dense one-line rows, figures in mono,
and depth only where it orders the page. When this file and the code diverge,
the implementation in `ui/src` is the source of truth; update this file.

## Principles

1. **Figures first.** A screen is labels and numbers; no sentence explains what a table shows.
2. **One device, one meaning.** A tab, chip, dot, bar or chevron does the same job on every screen.
3. **Quiet normal, loud exception.** Finished rounds are neutral. A live round is the one mark that
   moves; an expired lot is the one that warns.
4. **Compact, never cramped.** 38px rows (44px on touch), strict alignment, nothing that identifies a
   row is truncated away.
5. **Gloss on chrome, never on data.** Surfaces may catch light. A mark that encodes a value is flat.

## Screen anatomy

Every list screen is the same stack. A layer with nothing to say is left out.

| Layer | Job |
| --- | --- |
| Top bar | Wordmark, screens as pills, search, data age, theme. Sticky and translucent; lifts with a shadow once content scrolls under it |
| Strip | One card of at most five figures for the filters in scope. Label above figure, sentence case |
| Tabs | Choose the rows (round status). Each carries its count as a plain mono figure |
| Filters | One line under the tabs: chip tracks for chain and version, a quiet search field on the right |
| Table | One card. See Tables |
| Drawer | One round's workspace, floating over the right of the list |

Footer links (Status, Pricing method, API docs) sit at the bottom of the page and are also in the
data-age menu. Nothing is fixed to the bottom of the viewport.

## Colour

Tokens live in `src/index.css` as CSS variables, with Tailwind aliases in `tailwind.config.js`.
Dark is the default theme; the toggle stores `ui_next_color_mode`.

| Role | Tokens | Used for |
| --- | --- | --- |
| Neutral | `background`, `surface`, `inset`, `hover`, `selected`, `track`, `key`, `primary`, `secondary`, `tertiary`, `faint`, `divider*` | Text, rules, surfaces, meters |
| Accent | `accent` | You are here or can act: active tab underline, open-row edge, focus ring, sort arrow, a link pointed at, linked-identity hover, take marks on the price chart |
| Status | `active-mark`, `warning-mark`, `negative` | Live dot and meter, expired dot and meter, failures |
| Direction | `positive`, `negative` | PnL figures only, always with a sign |

- Status colour never sits on a whole row.
- Faint is for zeros, dashes and decoration. A word the reader needs is at least `tertiary`.
- Never colour alone: a dot has its word, a PnL figure has its sign.

Round status: Live is a pulsing green dot, Sold a neutral solid dot, Expired an amber dot,
Settled a hollow ring.

## Type

- Sans (system stack) for names, labels and controls. Mono (IBM Plex Mono, shipped with the app) for
  every figure, address, hash, date and round or take id.
- Tabular figures wherever numbers stack.
- Sentence case for every label, header, tab and control. No uppercase tracking.

| Size | Use |
| --- | --- |
| 11px | Labels, table headers, units, sub-lines |
| 12px | Table cells, controls |
| 13px | Body, tabs, nav |
| 17–18px | Page titles |
| 20px | Strip figures (16px on phones) |
| 24px | The drawer's headline figure |

## Surface and depth

| Level | What | Treatment |
| --- | --- | --- |
| 0 Page | Background | Flat `--color-background` |
| 1 Card | Strip, tables, headers | Hairline ring, contact and ambient shadow, a 1px top highlight and a top-light gradient (`.card`, `.strip`) |
| 2 Overlay | Lifted top bar, menus, drawer | Stronger shadow; blurred translucent fill where content scrolls beneath |

Radius: 12px drawer, 10px cards, 8px menus, 7px chip tracks and nav pills, 5–6px controls, 2px bars.

Allowed motion: the card top light, the top bar's blur and lift, one shimmer on loading skeletons,
the live dot's slow pulse, one pulse on the data-age dot when a newer block lands, bars growing in
once on first paint, and one band of light across a figure that changed on refresh (`Changed`).
Hover and press 120–150ms; drawer 260ms. `prefers-reduced-motion` turns all of it off.

Not allowed: gradients or glow on bars, lines or dots; coloured shadows; gloss on table rows;
anything else that moves while the page is at rest.

## Tables

- One line per row. Identity on the left, figures right-aligned in mono.
- Columns drop by priority as the table's container narrows (`col-xl`, `col-md`, `col-lo`); tables
  never scroll sideways. Once a column is gone, its meaning moves into the identity cell's `sub-line`.
- Headers are sticky and blur what passes beneath.
- Hover is `inset`; the open row is `hover` with a 2px accent edge on its first cell.
- Copy and explorer icons surface on row hover or focus, stay visible on touch, and are dropped on
  phones.
- A row that opens something ends in a `›` (`OpenMark`); an expandable row's chevron turns down.
- Rows are keyboard reachable: Tab to a row, Enter opens it, ↑/↓ move between rows.
- Sort arrows show only on the active column, in the accent.
- Loading is skeleton rows in the shape of the table (`SkeletonRows`), not grey blocks.

Linked identity hover stays: within one table, hovering an auction, token or taker address outlines
every matching address in that table with a dashed accent border.

## Meters

Flat 4px fills. A bar on a track is a share of a limit (time elapsed, lot sold, sync progress). A bar
without a track (`.bar.is-relative`) is size against the largest row in the column. Meters keep their
row's tone: live green, expired amber, everything else neutral. An early close is a small tick.

## Round drawer

- A round opens in a drawer (`RoundDrawer`), 500px (560px from 1700px), floating over the right of
  the list with no scrim, so the list never moves. Under 700px it is a bottom sheet over a dimmed page.
- Back, Esc, the close control and a click on nothing that acts all close it. A click on another
  row, or ↑/↓, moves it there and replaces the history entry, so Back still closes the drawer.
- Order: head (round, status, auction, share link, close), summary (lot as the headline figure;
  sold, received, PnL, kicked beside it), time and sold meters, the price chart, settings, takes.
- The price chart draws the start price stepping down by its decay, the kick-time quote as a dashed
  line, the minimum price when it is in range, each take as a dot, and a live round's current price.
  Hovering reads the price at any moment of the round.

## Numbers and words

- Money in lists is compact at three significant digits (`formatCompactUsd`): `$23.4M`, `$6.70M`,
  `$161K`. The exact value is on hover.
- Percent PnL is signed with a true minus (`−0.24%`); its USD delta follows in a quieter figure.
- A figure computed from incomplete pricing carries a small `partial` note, with the coverage on hover.
- Dense tables show relative ages (`4h ago`) or `MMM d HH:mm`; the full timestamp is in the title.
- Version badges are small bordered mono marks with a `v` prefix.
- Token logos are backend-driven; unknown tokens use the shared fallback logo.
