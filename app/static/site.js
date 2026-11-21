/* AI Learning site behaviour. Progressive enhancement only: with JavaScript
 * off, the homepage stack is still a stack of slides, every link works and the
 * static catalogue simply lists every course.
 * Keep this file small and dependency-free. */

(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* The slide on top of the pile cycles; hover or focus holds the pile still
   * so the learner can read it. Reduced motion keeps one static pile. */
  const initDeck = () => {
    const deck = document.querySelector(".hero__deck");
    const stack = deck && deck.querySelector("[data-deck-stack]");
    if (!deck || !stack) return;

    const slides = Array.from(stack.querySelectorAll("[data-slide]"));
    if (slides.length < 2) return;

    const order = slides.map((_, index) => index);
    const paint = () => {
      order.forEach((slideIndex, slot) => {
        slides[slideIndex].dataset.slot = String(slot);
      });
    };
    paint();

    let timer = null;
    const advance = () => {
      order.push(order.shift());
      paint();
    };
    const start = () => {
      if (timer || reduceMotion.matches || document.hidden) return;
      timer = window.setInterval(advance, 4600);
    };
    const stop = () => {
      if (!timer) return;
      window.clearInterval(timer);
      timer = null;
    };

    if (!reduceMotion.matches) {
      start();
      deck.addEventListener("pointerenter", stop);
      deck.addEventListener("pointerleave", start);
      deck.addEventListener("focusin", stop);
      deck.addEventListener("focusout", start);
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) stop();
        else start();
      });
      if (typeof reduceMotion.addEventListener === "function") {
        reduceMotion.addEventListener("change", (event) => {
          stop();
          if (!event.matches) start();
        });
      }
    }

    /* Pointer parallax: a few degrees of tilt is enough to read the pile as
     * physical paper. Coarse pointers and reduced motion get the flat stack. */
    const finePointer = window.matchMedia("(pointer: fine)");
    if (!finePointer.matches || reduceMotion.matches) return;

    let frame = null;
    deck.addEventListener("pointermove", (event) => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        const rect = deck.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        stack.style.setProperty("--tilt-x", `${(-y * 5).toFixed(2)}deg`);
        stack.style.setProperty("--tilt-y", `${(x * 7).toFixed(2)}deg`);
      });
    });

    deck.addEventListener("pointerleave", () => {
      if (frame) {
        window.cancelAnimationFrame(frame);
        frame = null;
      }
      stack.style.removeProperty("--tilt-x");
      stack.style.removeProperty("--tilt-y");
    });
  };

  /* The static export has no server to filter the catalogue, so the same
   * query-string links filter the rendered cards in the browser. Dynamic
   * deployments keep their server-rendered filtering and skip this pass. */
  const initStaticCatalog = () => {
    const catalog = document.querySelector("[data-catalog-static]");
    if (!catalog) return;

    const cards = Array.from(catalog.querySelectorAll("[data-course-card]"));
    if (!cards.length) return;

    const params = new URLSearchParams(window.location.search);
    const level = params.get("level") || "";
    const tag = params.get("tag") || "";

    for (const card of cards) {
      const levelOk = !level || card.dataset.level === level;
      const tagOk = !tag || (card.dataset.tags || "").split(",").includes(tag);
      card.hidden = !(levelOk && tagOk);
    }

    for (const chip of catalog.querySelectorAll("[data-filter-level]")) {
      chip.classList.toggle("chip--active", (chip.dataset.filterLevel || "") === level);
    }
    for (const chip of catalog.querySelectorAll("[data-filter-tag]")) {
      chip.classList.toggle("chip--active", (chip.dataset.filterTag || "") === tag);
    }
  };

  initDeck();
  initStaticCatalog();
})();
