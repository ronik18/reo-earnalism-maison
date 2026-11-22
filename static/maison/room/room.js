/* Reading-room carousel: taste-first page turner. Pauses on hover, focus, touch, hidden tab and a
   visible Pause; never moves for reduced-motion visitors (OS setting or saved Maison preference). */
window.maisonEvents = window.maisonEvents || [];
(function initTurner() {
  const root = document.getElementById("turner");
  if (!root) return;
  const cards = [...root.querySelectorAll(".turn-card")], dots = [...root.querySelectorAll(".turn-dot")], n = cards.length;
  const pauseBtn = root.querySelector("#turn-pause"), live = root.querySelector(".sr-live"), stage = root.querySelector(".turn-stage");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const still = () => reduce.matches || document.body.classList.contains("reduced-motion");
  const holds = new Set();
  let i = 0, timer = null, userPaused = false;
  const track = (event, card) => window.maisonEvents.push({ event, card });
  function show(k, fromUser) {
    i = ((k % n) + n) % n;
    let moveFocus = false;
    cards.forEach((c, j) => {
      const d = ((j - i) % n + n) % n;
      c.classList.remove("is-active", "is-next1", "is-next2", "is-past");
      c.classList.add(d === 0 ? "is-active" : d === 1 ? "is-next1" : d === 2 ? "is-next2" : "is-past");
      const on = d === 0;
      if (!on && c.contains(document.activeElement)) moveFocus = true;
      c.setAttribute("aria-hidden", String(!on));
      c.inert = !on;
    });
    if (moveFocus) cards[i].querySelector(".turn-cta").focus();
    dots.forEach((d, j) => d.setAttribute("aria-current", String(j === i)));
    track("carousel_card_viewed", cards[i].dataset.card);
    if (fromUser) live.textContent = "Card " + (i + 1) + " of " + n + ": " + cards[i].querySelector("h3").textContent;
    schedule();
  }
  function schedule() {
    clearTimeout(timer); timer = null;
    if (still() || userPaused || holds.size) return;
    timer = setTimeout(() => show(i + 1, false), 7000);
  }
  const hold = (r) => { holds.add(r); schedule(); }, release = (r) => { holds.delete(r); schedule(); };
  root.querySelector("#turn-next").addEventListener("click", () => show(i + 1, true));
  root.querySelector("#turn-prev").addEventListener("click", () => show(i - 1, true));
  dots.forEach((d) => d.addEventListener("click", () => show(+d.dataset.i, true)));
  pauseBtn.addEventListener("click", () => {
    userPaused = !userPaused;
    pauseBtn.setAttribute("aria-pressed", String(userPaused));
    pauseBtn.querySelector("use").setAttribute("href", userPaused ? "#i-tri" : "#i-pause");
    schedule();
  });
  stage.addEventListener("mouseenter", () => hold("hover"));
  stage.addEventListener("mouseleave", () => release("hover"));
  root.addEventListener("focusin", () => hold("focus"));
  root.addEventListener("focusout", (e) => { if (!root.contains(e.relatedTarget)) release("focus"); });
  let x0 = null;
  stage.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse") return; x0 = e.clientX; hold("touch"); });
  stage.addEventListener("pointerup", (e) => {
    if (e.pointerType === "mouse") return;
    if (x0 !== null && Math.abs(e.clientX - x0) > 50) show(i + (e.clientX < x0 ? 1 : -1), true);
    x0 = null; release("touch");
  });
  stage.addEventListener("pointercancel", () => { x0 = null; release("touch"); });
  root.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { show(i + 1, true); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { show(i - 1, true); e.preventDefault(); }
  });
  document.addEventListener("visibilitychange", () => (document.hidden ? hold("hidden") : release("hidden")));
  reduce.addEventListener("change", schedule);
  cards.forEach((c) => c.querySelector(".turn-cta").addEventListener("click", () => track("carousel_cta_clicked", c.dataset.card)));
  show(0, false);
})();
