// Nav goes solid once you scroll past the top of the hero.
const nav = document.querySelector(".nav");
const onScroll = () => nav.classList.toggle("solid", window.scrollY > 40 || document.body.classList.contains("subpage"));
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// Videos: YouTube thumbnails as backgrounds; clicking loads the embed into
// the player of the same [data-player-scope] (the homepage Watch section, or
// one past event). Nothing from YouTube loads until someone clicks.
function play(scope, id) {
  const player = scope.querySelector(".player");
  const buttons = scope.querySelectorAll(".videos button");
  const btn = scope.querySelector(`.videos button[data-video="${id}"]`);
  const iframe = document.createElement("iframe");
  iframe.src = `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`;
  iframe.title = btn ? btn.textContent : "Video";
  iframe.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
  iframe.allowFullscreen = true;
  player.querySelector(".player-frame").replaceChildren(iframe);
  player.querySelector(".player-title").textContent = btn ? btn.textContent : "";
  buttons.forEach((x) => x.classList.toggle("active", x === btn));
  player.hidden = false;
  player.scrollIntoView({ behavior: "smooth", block: "center" });
}

document.querySelectorAll("[data-player-scope]").forEach((scope) =>
  scope.querySelectorAll(".videos button").forEach((b) => {
    b.style.setProperty("--thumb", `url(https://i.ytimg.com/vi/${b.dataset.video}/hqdefault.jpg)`);
    b.addEventListener("click", () => play(scope, b.dataset.video));
  })
);

// "Watch excerpt" links in Works play in the homepage Watch section.
document.querySelectorAll(".play-link").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); play(document.getElementById("watch"), a.dataset.video); })
);

// Gallery lightbox.
const box = document.getElementById("lightbox");
const boxImg = box.querySelector("img");
const sliderMode = window.matchMedia("(max-width: 700px)");
document.querySelectorAll(".gallery a").forEach((a) =>
  a.addEventListener("click", (e) => {
    e.preventDefault();
    if (sliderMode.matches) return; // phones swipe the slider instead
    boxImg.src = a.href;
    boxImg.alt = a.querySelector("img").alt;
    box.hidden = false;
  })
);
const close = () => { box.hidden = true; boxImg.src = ""; };
box.addEventListener("click", close);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

// Contact form — posts to /api/contact (proxied by nginx to the app backend),
// so her email address never appears on the page.
const form = document.getElementById("contact-form");
form?.addEventListener("submit", async (e) => {
  const formStatus = form.querySelector(".form-status");
  e.preventDefault();
  const btn = form.querySelector("button");
  btn.disabled = true;
  formStatus.textContent = "Sending…";
  try {
    const res = await fetch("/api/contact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    if (res.ok) {
      form.reset();
      formStatus.textContent = "Thank you — your message has been sent.";
    } else {
      const data = await res.json().catch(() => ({}));
      formStatus.textContent = typeof data.detail === "string" ? data.detail : "Please check your details and try again.";
    }
  } catch {
    formStatus.textContent = "Couldn't send right now — please try again.";
  }
  btn.disabled = false;
});

// Phone slider: "3 / 9" counter (the .gallery-count right after each
// .gallery) that follows the photo nearest the centre.
document.querySelectorAll(".gallery").forEach((gallery) => {
  const count = gallery.nextElementSibling;
  if (!count || !count.classList.contains("gallery-count")) return;
  const slides = [...gallery.querySelectorAll("a")];
  const updateCount = () => {
    // Before any swipe (photos may not have loaded or have widths yet) it's simply the first.
    if (gallery.scrollLeft < 8) { count.textContent = `1 / ${slides.length}  ·  swipe`; return; }
    const mid = gallery.scrollLeft + gallery.clientWidth / 2;
    let i = 0, best = Infinity;
    slides.forEach((s, k) => {
      const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid);
      if (d < best) { best = d; i = k; }
    });
    count.textContent = `${i + 1} / ${slides.length}  ·  swipe`;
  };
  gallery.addEventListener("scroll", updateCount, { passive: true });
  updateCount();
});

// Upcoming: performances and workshops from the app, via /api/schedule
// (nginx -> backend). Built with textContent only — the data is hers, but
// it still never gets interpreted as HTML.
const fmtDay = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
if (document.querySelector(".upcoming")) fetch("/api/schedule")
  .then((r) => (r.ok ? r.json() : []))
  .then((items) => {
    if (!items.length) return;
    const list = document.querySelector(".upcoming");
    const el = (tag, cls, text) => { const e = document.createElement(tag); e.className = cls; if (text) e.textContent = text; return e; };
    for (const it of items) {
      const li = document.createElement("li");
      li.append(el("span", "when", it.end_date ? `${fmtDay(it.date)} – ${fmtDay(it.end_date)}` : fmtDay(it.date)));
      const body = el("div", "");
      body.append(el("div", "what", it.type === "workshop" ? `Workshop · ${it.title}` : (it.venue || it.title)));
      const where = [it.type === "workshop" ? null : it.city, it.time].filter(Boolean).join(" · ");
      if (where) body.append(el("div", "where", where));
      li.append(body);
      if (it.link) {
        const a = el("a", "register", "Details & register");
        a.href = it.link; a.target = "_blank"; a.rel = "noopener";
        li.append(a);
      } else li.append(el("span", ""));
      list.append(li);
    }
    document.getElementById("upcoming").hidden = false;
    document.getElementById("nav-upcoming").hidden = false;
  })
  .catch(() => {});

// "Over forty years": 40 in 2026, one more each year after, spelled out.
const yearsInForm = 40 + (new Date().getFullYear() - 2026);
const ONES = ["", "-one", "-two", "-three", "-four", "-five", "-six", "-seven", "-eight", "-nine"];
const TENS = { 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy" };
const yearsWord = TENS[Math.floor(yearsInForm / 10)] ? TENS[Math.floor(yearsInForm / 10)] + ONES[yearsInForm % 10] : String(yearsInForm);
document.querySelectorAll("[data-years]").forEach((el) => { el.textContent = yearsWord; });
