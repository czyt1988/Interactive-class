/* Fit one 1920×1080 clip still into its iframe.
 *
 * Used only by the admin clip preview frame (/admin/clips/<id>/frame). The
 * scene itself is laid out at 1920×1080 with CSS; this scales the whole design
 * surface down to the iframe viewport, exactly like the course player does.
 * The page never runs course code or fetches anything.
 */
(function () {
  const root = document.getElementById("root");
  if (!root) return;

  const fit = () => {
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    root.style.transformOrigin = "top left";
    root.style.transform = `scale(${Math.max(0.01, scale)})`;
  };

  fit();
  window.addEventListener("resize", fit);
})();
