/* Live watermark preview for the admin config page.
 *
 * The form still works without JavaScript: the server renders the saved
 * watermark into the preview. This script only mirrors edits as they happen, so
 * the admin does not have to save and rebuild to see a font size or opacity.
 */

(() => {
  const form = document.querySelector("[data-wm-form]");
  const canvas = document.querySelector("[data-wm-canvas]");
  if (!form || !canvas) return;

  const master = form.querySelector("[data-wm-enabled]");
  const repeatLayer = canvas.querySelector("[data-wm-repeat]");
  const repeatText = form.querySelector("[data-wm-repeat-text]");
  const repeatFont = form.querySelector("[data-wm-repeat-font]");
  const repeatColor = form.querySelector("[data-wm-repeat-color]");
  const repeatOpacity = form.querySelector("[data-wm-repeat-opacity]");
  const repeatGapX = form.querySelector("[data-wm-repeat-gap-x]");
  const repeatGapY = form.querySelector("[data-wm-repeat-gap-y]");
  const repeatRotate = form.querySelector("[data-wm-repeat-rotate]");

  const positions = ["top-left", "top-right", "bottom-left", "bottom-right"];
  const corners = positions.map((position) => ({
    position,
    text: form.querySelector(`[data-corner-text="${position}"]`),
    font: form.querySelector(`[data-corner-font="${position}"]`),
    color: form.querySelector(`[data-corner-color="${position}"]`),
    opacity: form.querySelector(`[data-corner-opacity="${position}"]`),
    preview: canvas.querySelector(`[data-wm-corner="${position}"]`),
  }));

  const number = (input, fallback) => {
    const value = Number.parseFloat(input?.value ?? "");
    return Number.isFinite(value) ? value : fallback;
  };

  // The color inputs always have a value; this fallback stays token-driven for
  // the brief moment before the browser normalizes them.
  const ink = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim();

  const sync = () => {
    canvas.classList.toggle("is-off", !master?.checked);

    for (const corner of corners) {
      if (!corner.preview) continue;
      const text = (corner.text?.value || "").trim();
      corner.preview.textContent = text;
      corner.preview.hidden = !text;
      corner.preview.style.setProperty("--wm-font-size", number(corner.font, 30));
      corner.preview.style.setProperty("--wm-color", corner.color?.value || ink);
      corner.preview.style.setProperty("--wm-opacity", number(corner.opacity, 0.6));
    }

    const text = (repeatText?.value || "").trim();
    if (repeatLayer) {
      repeatLayer.hidden = !text;
      for (const tile of repeatLayer.querySelectorAll("[data-wm-tile]")) {
        tile.textContent = text;
      }
    }
    canvas.style.setProperty("--wm-gap-x", number(repeatGapX, 320));
    canvas.style.setProperty("--wm-gap-y", number(repeatGapY, 200));
    canvas.style.setProperty("--wm-rotate", `${number(repeatRotate, -24)}deg`);
    canvas.style.setProperty("--wm-font-size", number(repeatFont, 28));
    canvas.style.setProperty("--wm-color", repeatColor?.value || ink);
    canvas.style.setProperty("--wm-opacity", number(repeatOpacity, 0.12));
  };

  form.addEventListener("input", sync);
  form.addEventListener("change", sync);
  sync();
})();
