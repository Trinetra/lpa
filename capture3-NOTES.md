# Adavu Pose Capture (capture3.html) — working notes

Single-file, no-build browser tool. Load a video, capture poses, refine the
cutouts by hand, bulk-export PNGs. Last updated 2026-07-30.

This file records the things that are **not** visible in the code: why certain
decisions were made, what broke before, and what has never actually been tested.

---

## Where it lives

| | |
|---|---|
| Working copy | `capture3.html` (this folder) |
| Live copy | Netlify (URL held by RP) — **the one the dancer uses** |
| Predecessor | `capture2.html` — still working, left untouched |

**The live copy does not update itself.** Edits here are invisible to her until
the file is re-dragged onto Netlify. Easy to forget when she reports a bug that
"works on my machine."

### Why it must be hosted at all

Opening the file directly (`file://`) **will not work**. Browsers give every
`file://` page an opaque origin, so the CDN `import()` is blocked by CORS. This
is the real cause of the `no available backend found` / `Failed to fetch` errors
hit during development — the config was correct all along, the origin was wrong.
Serving over `http://` fixes it permanently.

Local alternative if ever needed (macOS ships Python 3):
`python3 -m http.server` in this folder → `localhost:8000/capture3.html`.

### Privacy

There is no `fetch`, upload, beacon, or WebSocket in the app. Video is read via a
local object URL; captures live in browser memory; the ZIP is built client-side.
**Hosting the page does not put her footage online** — the page is just code that
runs on her Mac. An unlisted Netlify URL is not a secret (anyone with the link
can load the *tool*), but her footage never leaves her machine.

---

## Runtime dependencies (all CDN, all at runtime)

| What | Where | When it loads |
|---|---|---|
| `@imgly/background-removal` 1.5.0 | esm.sh | first refine |
| @imgly model data (~10.5MB) | staticimgly.com | first refine |
| JSZip 3.10.1 | jsdelivr | first export |

She must be online. Not self-contained, and **not worth making so** — the model
data is hash-addressed chunks fetched at runtime, not something you paste into a
script tag; you'd redo it on every version bump.

`IMGLY_PUBLIC_PATH` is passed explicitly because esm.sh's bundling drops the
library's internal `PACKAGE_VERSION`, so it can't build its own model URL.

**First refine of a session downloads ~10.5MB** and feels slow, then is fast. If
she reports "the first one hangs" — that's this, not a bug.

> Note: capture3 uses @imgly only. The MediaPipe fast tier is **capture2**.

### The matte is soft — `solidifyCutout()` fixes it

@imgly returns a **soft matte**: fractional alpha across the whole subject, not
just its rim, so the dancer came back visibly washed out. `solidifyCutout()` runs
once in `runRefine` (before `baseline` is snapshotted, so Reset restores the
solidified version) and applies an alpha curve: `>= SOLID_AT` → 255,
`<= CLEAR_AT` → 0 (kills faint background haze), between → stretched across
0..255 as the anti-aliased rim.

**`SOLID_AT` is 128, not ~200, and that is the whole fix.** The washed-out
interior comes back around alpha 170. With the threshold up at 200 the entire
subject fell on the rim ramp and stayed translucent — measured 212 instead of 255,
i.e. the bug survived a fix that looked correct on the page. Anything the model
scored as more subject than background is treated as interior.

**Colour is re-read from the original JPEG**, not kept from the matte: @imgly's
RGB reads as premultiplied against transparent black, so raising alpha while
keeping its colour darkens the pixel. Same reason `stamp()`'s restore path copies
RGB while raising alpha.

---

## The flow

Load video → play/scrub → `C` captures the frame → popup asks for a **tag**
(e.g. `8a`, `9b`, matching her Word doc) → thumbnail appears and refines in the
background while she keeps capturing → click a thumbnail to hand-refine →
bulk export.

Refines are **serialised** (`refineQueue`), one inference at a time — parallel
inferences thrash and get slower, not faster.

Bani/Movement are free text with `localStorage` autocomplete (`adavu-capture-vocab`),
not dropdowns. The original ask was "dropdowns populated from our db"; there is no
db wired in, and a fixed list would block an adavu she hasn't entered yet. The
vocab list grows as she types. **Revisit if a real vocabulary source appears.**

Export name: `bani-movement-tag.png`. Collisions get `-2`, `-3`; oldest capture
keeps the clean name so re-exporting a session is stable. Nothing is encoded in
the PNGs (per the brief).

**Export size slider** (`#fScale`, 10–100%, next to the export buttons) scales
every image down on the way into the ZIP. Read at export time, so moving it does
not touch anything already captured. **Scale is deliberately absent from the
filename** — re-exporting a session at a different size must overwrite cleanly
rather than accumulate variants. The readout shows the resulting pixel size as
well as the percentage, sampled from the first shot (all captures in a session
come from one video, so they share dimensions), which is why `renderShelf()`
refreshes it — the size is unknown until the first capture lands.

Downscaling a cutout **cannot** use `putImageData`: it ignores the destination
canvas size and never resamples. The cutout goes onto a full-size scratch canvas
first, then `drawImage` scales it with smoothing on. Verified at 100/50/25/10%:
exact dimensions, alpha preserved, subject still fully opaque.

---

## Session persistence (IndexedDB)

She lost a session to two accidental Back presses. Captures used to live only in
memory, and `beforeunload` does not save you: browsers deliberately suppress that
prompt for many Back navigations, and it cannot run async work anyway. It is kept
(nothing is on disk until export) but it is the backstop, not the mechanism.

**IndexedDB, not localStorage.** One 1080p capture is megabytes of JPEG + PNG;
the ~5MB localStorage quota would blow after a couple of shots. IDB stores Blobs
natively with hundreds of MB available.

Stored per shot: the source JPEG, the current cutout, and the AI baseline (so
**Reset still works after a restore**) — each as a Blob, not raw `ImageData`, which
would be ~8MB uncompressed per 1080p frame. **PNG is lossless, so alpha survives
the round trip exactly** — this matters because alpha *is* the hand-edited data.
Verified byte-exact: an erased stroke restored with its 525 feathered rim pixels
identical. (RGB does drift at partial alpha through premultiplication, which is
harmless — colour always comes from the original JPEG.)

**Not stored: the video.** Its object URL dies with the page and a `File` handle
cannot be revived, so restoring it would mean copying hundreds of MB into IDB on
every load. Captures restore fully and export fine; she only needs to re-pick the
clip to capture *more* from it, and the empty player says so.

`saveSession()` writes a full snapshot after every mutation — capture, refine,
stroke end, wand apply, undo, reset, delete. Writes are serialised through
`saveChain`, and a quota failure warns without breaking capture. Snapshot-per-save
is fine at tens of shots; a diffing scheme would be the optimisation if sessions
ever get big. Saves happen on **stroke end, not per stamp** — a full snapshot per
pixel would be absurd.

**Restore is offered, never automatic.** After an accidental Back press a silently
repopulated shelf leaves her unable to tell old shots from new. The banner names
the count and date; Discard clears the store. `seq` is advanced past every
restored id, or a new capture collides with a restored one and the editor opens
the wrong shot.

**The bfcache trap.** A Back press often resurrects the page from the bfcache:
State is intact and module code does **not** re-run, so neither `offerRestore()`
nor a render happens. Hence the `pageshow` handler — which offers a restore only
when the live session is empty, since if State survived her work is already on
screen and a banner would be noise. This was invisible in testing until a real
`history.back()` was driven; a reload test would have passed and shipped the bug.

## The editor (the heart of it)

Opens on a thumbnail. Shows the AI cutout; she fixes it by hand.

- **Restore** paints the original photo back (a clipped hand)
- **Erase** makes pixels transparent (leftover background)
- **Wand** (`W`) click-selects a whole region
- `Alt` swaps restore/erase · `B` brush · `Enter` apply · `Esc` cancel
- `[` `]` brush size · `Ctrl+Z` undo · scroll or `+`/`−` zoom · `0` fit ·
  `Space`/middle-drag pan

### Load-bearing details

**Only alpha is ever written.** Colour comes from the original JPEG, so repeated
strokes can't degrade the image. Restore *must* copy RGB while raising alpha —
without it, erased pixels return as transparent black.

**Wand tolerance is measured against the clicked (seed) colour, not each
neighbour.** This is the whole reason it stops at an edge. Neighbour-comparison
is the classic bug: on a smoothly-lit backdrop the fill walks across the entire
frame one imperceptible step at a time and selects everything. Verified: on a
gradient ramp the fill stops at x=9 where the maths says, not x=99.

**Why a click-wand and not the magnetic lasso that was asked for.** A magnetic
lasso needs a traced closed path and snaps to the nearest strong edge at every
step — around splayed fingers it fights every costume fold and shadow. Her
failures are blobs (clipped hand, patch of floor); clicking inside one is a
single gesture with the same payoff. If a traced lasso is ever genuinely wanted,
it's additive, not a rewrite.

**Zoom is a CSS transform on the canvas**, which keeps its natural pixel size —
the buffer is never resampled, so brush maths stays in image space. Only
`ptFromEvent` inverts the transform. Get that wrong and the brush paints in the
wrong place at zoom; it's tested exact to 8× with large pan offsets.

**The backdrop swatches and the wand's green/red tint are screen-only.** Export
reads `shot.cutout`, which only `applyWand` and `stamp` write. Verified: a white
backdrop cannot bake into a PNG.

**`fitToStage()` runs *after* the modal is unhidden** — a hidden stage has no
measurable size.

**The brush cursor is a DOM ring (`#brushRing`), not canvas pixels.** The OS arrow
gave no clue where a stamp would land, so in brush mode the real cursor is hidden
(`cursor:none` via `.brush-cursor`) and the ring stands in for it. It must stay a
DOM overlay: `paint()` would wipe anything drawn on the canvas, and anything
written into `eshot.cutout` could bake into an export. Diameter is `brush * zoom`
because `brush` is a diameter in image space — so the ring is exactly the area a
click affects, at any zoom. `updateRing()` therefore has to be called from
`applyView`, the size slider, `[`/`]`, `setMode`, Alt, Space, pan start/end and
`closeEditor` (that last one or `cursor:none` sticks on the stage). It hides for
wand (own crosshair) and panning (grab hand), and tints red when the effective
action is erase — including while Alt is held.

**Wand masks are sized to their shot** and are cleared on open/close; carrying
one to a smaller image would index past the end.

---

## Bugs already fixed — don't reintroduce

- **`putImageData` ignores `globalAlpha`** and clobbers what's underneath. The
  "Show original" ghost silently did nothing. Anything composited with alpha
  must go through a scratch canvas + `drawImage`.
- **`slugify` deleted diacritics**: `Naṭṭa 1` → `na-a-1`, `Kaḷākṣetra` →
  `ka-k-etra` — distinct adavus collided onto one filename. Fixed with NFD +
  combining-mark strip. **This changed filenames for names with diacritics.**
- **PNG tEXt JSON corruption** (capture2): escaping ran *after* `JSON.stringify`,
  emitting `\ṭ` instead of `ṭ` — unparseable chunk for exactly this corpus.
  Escape *during* serialization.
- **`origData` was never assigned** — Restore would throw on first stroke.

---

## Testing

Tests live in the session scratchpad and **extract the real functions from the
HTML** (brace-matched by name) rather than duplicating logic — which is why they
catch things. Worth recreating if this is picked up again.

Current status: flood-fill 11/11 (edge-stop exact, gradient halt, contiguity,
OOB seeds, feather ramp, 1080p worst case ~53ms — which is why the tolerance
slider can re-run live). Wand E2E in real headless Chrome: PASS, on a synthetic
"clipped arm + leftover backdrop patch" cutout, including PNG round-trip.

**The lesson from this project: every real bug was caught by executing the code,
not reading it.** Three reading-based diagnoses in a row were wrong during the
refine investigation. Run it.

The 2026-07-30 round is another data point. The E2E harness serves the real file
over http and rewrites only the `import()` URL to a same-origin stub whose
`removeBackground` returns a matte with the *reported defect* (interior alpha 170,
premultiplied-dark RGB) — so the fix is tested against the actual symptom, and
`solidifyCutout`/`runRefine` run as shipped. Two things this caught that reading
had missed:

- `SOLID_AT = 200` left the interior at **212, not 255** — the fix didn't work.
  Only measuring the output showed it.
- Request interception does **not** reliably cover module `import()` (Chrome
  blocks on CORS before the handler runs). Rewrite the URL instead.

Two apparent failures were the *test's* fault, worth knowing before trusting a
red run: sampling a pixel inside the brush test's erase-stroke feather, and
asserting the clip's subject colour was `#30ff60` when ffmpeg `color=green` is
`#008000`. The export-scale block now captures a fresh, never-edited shot.
Mutation-checked: breaking `SOLID_AT` does turn the suite red.

The persistence round (same day) repeated the pattern exactly:

- The bfcache bug above was **only** visible by driving a real `history.back()`.
  A reload test passes and ships it.
- An apparent "alpha not preserved" failure was the test fingerprinting the
  thumbnail before `refreshThumb` had run — it was comparing the *pre-edit* image.
  The storage layer was byte-perfect all along. Wait for the thumb to settle.
- Worth keeping: a **SIGKILL test** (kill the browser process, relaunch on the
  same profile) is the only honest check that persistence survives a crash —
  bfcache and `beforeunload` both mask it.

---

## Not yet verified against real footage

Everything below is *untested by the actual user on actual clips*:

- **Wand tolerance defaults to 28**, chosen from synthetic test images. Evenly-lit
  backdrop should be fine; busy or shadowed may need it dragged up. The slider
  re-runs live under the cursor, so it's a dial, not a guess — that's the first
  thing to reach for when a selection looks wrong.
- Wand behaviour on real skin/costume/floor edges.
- Whether the ~53ms worst case holds at her real capture resolution.
- **`SOLID_AT`/`CLEAR_AT` (128/24) are tuned against a synthetic matte, not her
  footage.** The risk is at the extremes: wispy edges (loose hair, a dupatta) are
  the thing a 128 cut could harden, and `CLEAR_AT = 24` could clear very faint
  genuine detail. If solidified cutouts look cut-out-with-scissors around hair,
  raise `CLEAR_AT`/lower the ramp rather than reverting the whole thing.
- Which export percentage she actually wants for the Word doc — the slider
  defaults to 100% (no change from previous behaviour).
- **Storage quota at her real resolution.** Tested at 240×160; a long session of
  1080p captures is a different order of magnitude. Saving degrades gracefully
  (warns, keeps capturing) but a full session has never been measured against a
  real browser quota. If she reports the warning, that is what it means.
- Whether Safari is in play. It evicts IndexedDB from sites with ~7 days of no
  interaction, so a session left over a fortnight's gap may not be there. Chrome
  on her Mac does not do this.

Reported so far: "works pretty well" (zoom + backdrop), before the wand shipped.

---

## If picking this up cold

1. Read the editor section of `capture3.html` — it's the heart of the app.
2. Don't trust a fix you haven't run in a browser.
3. Re-drag to Netlify, or she won't see it.
4. Sessions now live in IndexedDB per origin. A **different Netlify URL is a
   different origin**, so moving the app to a new URL orphans any saved session —
   the work is not deleted, but the new URL cannot see it.
