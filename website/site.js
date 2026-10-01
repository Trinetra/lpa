// Nav goes solid once you scroll past the top of the hero.
const nav = document.querySelector(".nav");
const onScroll = () => nav.classList.toggle("solid", window.scrollY > 40);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// Video list: YouTube thumbnails as backgrounds; clicking loads the embed
// into the single player (nothing from YouTube loads until someone clicks).
const player = document.getElementById("player");
const frame = player.querySelector(".player-frame");
const titleEl = player.querySelector(".player-title");
const buttons = document.querySelectorAll(".videos button");

buttons.forEach((b) => {
  b.style.setProperty("--thumb", `url(https://i.ytimg.com/vi/${b.dataset.video}/hqdefault.jpg)`);
  b.addEventListener("click", () => play(b.dataset.video));
});

function play(id) {
  const btn = document.querySelector(`.videos button[data-video="${id}"]`);
  frame.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0" title="${btn ? btn.textContent : "Video"}" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`;
  titleEl.textContent = btn ? btn.textContent : "";
  buttons.forEach((x) => x.classList.toggle("active", x === btn));
  player.hidden = false;
  player.scrollIntoView({ behavior: "smooth", block: "center" });
}

// "Watch excerpt" links in Works jump to the player with that video.
document.querySelectorAll(".play-link").forEach((a) =>
  a.addEventListener("click", (e) => { e.preventDefault(); play(a.dataset.video); })
);

// Gallery lightbox.
const box = document.getElementById("lightbox");
const boxImg = box.querySelector("img");
document.querySelectorAll(".gallery a").forEach((a) =>
  a.addEventListener("click", (e) => {
    e.preventDefault();
    boxImg.src = a.href;
    boxImg.alt = a.querySelector("img").alt;
    box.hidden = false;
  })
);
const close = () => { box.hidden = true; boxImg.src = ""; };
box.addEventListener("click", close);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
