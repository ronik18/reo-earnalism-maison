// Classroom projection: step through paragraphs with a clicker, the arrow keys or Space.
// Display only: nothing is sent to the server and nothing about pupils is recorded.
const root = document.getElementById("classroom");
if (root) {
  const steps = Array.from(root.querySelectorAll<HTMLElement>("[data-step]"));
  let current = -1;
  const show = (index: number) => {
    if (!steps.length) return;
    const next = Math.max(0, Math.min(steps.length - 1, index));
    steps[current]?.classList.remove("is-current");
    steps[current]?.removeAttribute("aria-current");
    current = next;
    const step = steps[current];
    step.classList.add("is-current");
    step.setAttribute("aria-current", "step");
    step.focus({ preventScroll: true });
    step.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };
  const fullScreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void root.requestFullscreen?.();
  };
  document.getElementById("classroom-next")?.addEventListener("click", () => show(current + 1));
  document.getElementById("classroom-previous")?.addEventListener("click", () => show(current - 1));
  document.getElementById("classroom-full-screen")?.addEventListener("click", fullScreen);
  document.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement | null;
    if (event.altKey || event.ctrlKey || event.metaKey || target?.closest("input, textarea, select, button, a")) return;
    if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(event.key)) { event.preventDefault(); show(current + 1); }
    else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(event.key)) { event.preventDefault(); show(current - 1); }
    else if (event.key === "f" || event.key === "F") fullScreen();
  });
}
