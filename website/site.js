// Nav goes solid once you scroll past the top of the hero.
const nav = document.querySelector(".nav");
// ☰ menu on phones: opens the section links full-screen; picking one closes it.
const navToggle = nav.querySelector(".nav-toggle");
const setMenu = (open) => {
  nav.classList.toggle("open", open);
  document.body.classList.toggle("menu-open", open);
  navToggle.setAttribute("aria-expanded", String(open));
};
navToggle.addEventListener("click", () => setMenu(!nav.classList.contains("open")));
nav.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", () => setMenu(false)));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

// Light / dark switch. Dark is the default; the choice is remembered on this
// device (the inline script in <head> applies it before first paint).
const themeBtn = document.querySelector(".theme-toggle");
const themeMeta = document.querySelector('meta[name="theme-color"]');
const applyTheme = (light) => {
  if (light) document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
  const next = light ? "dark" : "light";
  themeBtn.setAttribute("aria-label", `Switch to ${next} mode`);
  themeBtn.querySelector(".theme-label").textContent = `${next[0].toUpperCase()}${next.slice(1)} mode`;
  themeMeta.content = light ? "#f6f1e9" : "#0b0908";
  try { localStorage.setItem("theme", light ? "light" : "dark"); } catch (e) {}
};
applyTheme(document.documentElement.dataset.theme === "light");
themeBtn.addEventListener("click", () => applyTheme(document.documentElement.dataset.theme !== "light"));
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

// Phone sliders (photo galleries and video rows): a "3 / 9" counter in the
// .gallery-count right after each, following the item nearest the centre.
document.querySelectorAll(".gallery, .videos").forEach((row) => {
  const count = row.nextElementSibling;
  if (!count || !count.classList.contains("gallery-count")) return;
  const slides = [...row.children];
  const updateCount = () => {
    // Before any swipe (photos may not have loaded or have widths yet) it's simply the first.
    if (row.scrollLeft < 8) { count.textContent = `1 / ${slides.length}  ·  swipe`; return; }
    const mid = row.scrollLeft + row.clientWidth / 2;
    let i = 0, best = Infinity;
    slides.forEach((s, k) => {
      const d = Math.abs(s.offsetLeft + s.offsetWidth / 2 - mid);
      if (d < best) { best = d; i = k; }
    });
    count.textContent = `${i + 1} / ${slides.length}  ·  swipe`;
  };
  row.addEventListener("scroll", updateCount, { passive: true });
  updateCount();
});

// Upcoming: performances and workshops from the app, via /api/schedule
// (nginx -> backend). Tour stops are grouped under their tour's name; each
// stop links to Google Maps. Built with textContent only — the data is hers,
// but it still never gets interpreted as HTML.
const fmtDay = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
const link = (cls, text, href) => { const a = el("a", cls, text); a.href = href; a.target = "_blank"; a.rel = "noopener"; return a; };

function upcomingRow(it, inTour) {
  const li = document.createElement("li");
  li.append(el("span", "when", it.end_date ? `${fmtDay(it.date)} – ${fmtDay(it.end_date)}` : fmtDay(it.date)));
  const body = el("div");
  let what, where;
  if (it.type === "workshop") {
    what = `Workshop · ${it.title}`;
    where = it.time;
  } else {
    what = it.venue || it.city || (inTour ? "Venue to be announced" : it.title);
    where = [it.venue ? it.city : null, it.time].filter(Boolean).join(" · ");
  }
  body.append(el("div", "what", what));
  if (where) body.append(el("div", "where", where));
  li.append(body);
  if (it.link) li.append(link("register", "Details & register", it.link));
  else if (it.map_url) li.append(link("register", "Map", it.map_url));
  else li.append(el("span"));
  return li;
}

if (document.querySelector(".upcoming")) fetch("/api/schedule")
  .then((r) => (r.ok ? r.json() : []))
  .then((items) => {
    if (!items.length) return;
    const list = document.querySelector(".upcoming");
    const tours = new Map(); // tour_id -> its group's stop list, in date order
    for (const it of items) {
      if (!it.tour_id) { list.append(upcomingRow(it, false)); continue; }
      if (!tours.has(it.tour_id)) {
        const stops = items.filter((x) => x.tour_id === it.tour_id);
        const group = el("li", "tour-group");
        const head = el("div", "tour-head");
        head.append(el("h3", "", it.title));
        const last = stops[stops.length - 1].date;
        head.append(el("span", "tour-dates", last !== it.date ? `${fmtDay(it.date)} – ${fmtDay(last)}` : fmtDay(it.date)));
        if (it.tour_link) head.append(link("register", "Full schedule & map", it.tour_link));
        const ol = el("ol", "tour-stops");
        group.append(head, ol);
        list.append(group);
        tours.set(it.tour_id, ol);
      }
      tours.get(it.tour_id).append(upcomingRow(it, true));
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
