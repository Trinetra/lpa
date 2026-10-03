"""Public website (www.pravaahacfm.com) content editing.

The site is static HTML served by nginx from WEBSITE_DIR (the repo's
``website/`` folder, bind-mounted into this container). The app's Website page
edits productions, videos and gallery photos; on every save we re-render those
three sections between ``<!-- cms:NAME -->`` markers in index.html, so the page
stays fully static (fast, and search engines see the content directly).

Uploaded gallery photos are resized here and written to WEBSITE_DIR/media/
under fresh random names, so Cloudflare's edge cache never serves a stale one.
"""
import html
import io
import os
import re
import secrets
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

WEBSITE_DIR = Path(os.environ.get("WEBSITE_DIR", "/website"))
MEDIA_DIR = "media"
SIZES = ((1600, ""), (800, "-sm"))  # long-edge limit, filename suffix

_YT_ID = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})|^([A-Za-z0-9_-]{11})$")


def youtube_id(value: str) -> str | None:
    """Accepts a full YouTube URL (watch, youtu.be, embed, shorts) or a bare id."""
    m = _YT_ID.search((value or "").strip())
    return (m.group(1) or m.group(2)) if m else None


_IG = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)")


def instagram_url(value: str) -> str | None:
    """Normalises an Instagram post/reel link (any share-link variant, e.g.
    ?img_index=1 or ?igsh=…) to its canonical permalink, or None."""
    m = _IG.search((value or "").strip())
    if not m:
        return None
    kind = "reel" if m.group(1) in ("reel", "reels") else m.group(1)
    return f"https://www.instagram.com/{kind}/{m.group(2)}/"


def _e(text) -> str:
    return html.escape(text or "", quote=True)


def render_works(productions: list) -> str:
    out = []
    for p in productions:
        title = f'<h3>{_e(p["title"])} <em>&mdash; {_e(p["subtitle"])}</em></h3>' if p.get("subtitle") \
            else f'<h3>{_e(p["title"])}</h3>'
        lines = ["      <li>", f'        <span class="year">{_e(str(p.get("year") or ""))}</span>', f"        {title}"]
        if p.get("description"):
            lines.append(f'        <p>{_e(p["description"])}</p>')
        if p.get("video_id"):
            label = p.get("video_label") or "Watch excerpt"
            lines.append(f'        <a class="play-link" href="#watch" data-video="{_e(p["video_id"])}">{_e(label)}</a>')
        lines.append("      </li>")
        out.append("\n".join(lines))
    return "\n".join(out)


def render_videos(videos: list) -> str:
    return "\n".join(
        f'      <li><button data-video="{_e(v["video_id"])}">{_e(v["title"])}</button></li>' for v in videos
    )


def render_gallery(photos: list) -> str:
    return "\n".join(
        f'      <a href="{_e(p["src"])}"><img src="{_e(p["src_sm"])}" alt="{_e(p.get("alt"))}" loading="lazy"></a>'
        for p in photos if not p.get("hidden")
    )


def _write_marked(filename: str, sections: dict) -> None:
    """Replaces each <!-- cms:NAME --> section of a site page (atomic replace)."""
    path = WEBSITE_DIR / filename
    page = path.read_text(encoding="utf-8")
    for name, body in sections.items():
        pattern = re.compile(rf"(<!-- cms:{name}\b[^>]*-->\n).*?(\n?<!-- /cms:{name} -->)", re.S)
        if not pattern.search(page):
            raise RuntimeError(f"{filename} is missing the cms:{name} markers")
        page = pattern.sub(lambda m: m.group(1) + body + ("\n" if body else "") + m.group(2).lstrip("\n"), page, count=1)
    tmp = path.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, path)


def write_sections(content: dict) -> None:
    """Re-renders the homepage's Works, Watch and Gallery sections."""
    _write_marked("index.html", {
        "works": render_works(content.get("productions", [])),
        "videos": render_videos(content.get("videos", [])),
        "gallery": render_gallery(content.get("gallery", [])),
    })


def _fmt_date(iso: str | None) -> str:
    try:
        d = date.fromisoformat(iso)
        return f"{d.day} {d.strftime('%B %Y')}"
    except (TypeError, ValueError):
        return ""


def render_archive(entries: list) -> str:
    """Past events page: published entries, newest first. Each gets its own
    video player scope and its own photo slider."""
    out = []
    for e in entries:
        when = _fmt_date(e.get("date"))
        if e.get("end_date") and e["end_date"] != e.get("date"):
            when = f"{when} – {_fmt_date(e['end_date'])}"
        where = ", ".join(x for x in (e.get("venue"), e.get("city")) if x)
        lines = ['  <article class="past" data-player-scope>', f'    <p class="eyebrow">{_e(when)}</p>',
                 f'    <h2>{_e(e.get("title"))}</h2>']
        if where:
            lines.append(f'    <p class="where">{_e(where)}</p>')
        if e.get("description"):
            lines.append(f'    <p class="prose-text">{_e(e["description"])}</p>')
        if e.get("photos"):
            lines.append('    <div class="gallery">')
            lines.append(render_gallery(e["photos"]))
            lines.append('    </div>')
            lines.append('    <p class="gallery-count" aria-hidden="true"></p>')
        if e.get("instagram"):
            # Official Instagram embeds, loaded by site.js only when scrolled
            # near — until then (or if Instagram is blocked) it's a plain link.
            lines.append('    <div class="insta-row">')
            for url in e["instagram"]:
                lines.append(f'      <div class="insta-card" data-insta="{_e(url)}"><a href="{_e(url)}" target="_blank" rel="noopener">View on Instagram</a></div>')
            lines.append('    </div>')
        if e.get("videos"):
            lines += ['    <div class="player" hidden>', '      <div class="player-frame"></div>',
                      '      <p class="player-title"></p>', '    </div>', '    <ul class="videos">',
                      render_videos(e["videos"]), '    </ul>',
                      '    <p class="gallery-count" aria-hidden="true"></p>']
        lines.append('  </article>')
        out.append("\n".join(lines))
    if not out:
        return '  <p class="center past-empty">Nothing here yet.</p>'
    return "\n".join(out)


def write_archive(entries: list) -> None:
    _write_marked("past-events.html", {"archive": render_archive(entries)})


def save_photo(data: bytes) -> dict:
    """Resizes an uploaded photo to the site's two sizes. Returns its gallery entry paths."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        raise ValueError("That file isn't a photo we can read (JPEG, PNG or WebP)")
    (WEBSITE_DIR / MEDIA_DIR).mkdir(exist_ok=True)
    name = secrets.token_hex(8)
    paths = {}
    for limit, suffix in SIZES:
        copy = img.copy()
        copy.thumbnail((limit, limit), Image.LANCZOS)
        rel = f"{MEDIA_DIR}/{name}{suffix}.jpg"
        copy.save(WEBSITE_DIR / rel, "JPEG", quality=82, optimize=True, progressive=True)
        paths["src_sm" if suffix else "src"] = rel
    return paths


def delete_photo_files(photo: dict) -> None:
    """Removes an uploaded photo's files. Photos from the original site (img/)
    are left on disk — only media/ uploads are ours to delete."""
    for key in ("src", "src_sm"):
        rel = photo.get(key) or ""
        if rel.startswith(f"{MEDIA_DIR}/") and "/" not in rel[len(MEDIA_DIR) + 1:]:
            (WEBSITE_DIR / rel).unlink(missing_ok=True)
