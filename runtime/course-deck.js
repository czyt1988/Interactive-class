/* AI Learning course shell.
 *
 * The deck is a small state machine around <hyperframes-player>. It owns the
 * cover, the stage chrome, navigation, the transcript drawer and progress.
 * It never reaches into the player's shadow DOM and never parses composition
 * HTML: everything it needs arrives in the inline `#course-data` manifest.
 */

const PLAYBACK_END_SLACK = 0.02;
const TRANSITION_MIN_MS = 180;
const TRANSITION_MAX_MS = 600;
const READY_TIMEOUT_MS = 10_000;
const PROGRESS_DEBOUNCE_MS = 900;

const PREF_CAPTIONS = "ai-learning:captions";
const PREF_SOUND = "ai-learning:sound";

/* ------------------------------------------------------------------ state */

const deck = {
  state: "cover",
  index: 0,
  playing: false,
  ended: false,
  seeking: false,
  resumeAfterSeek: false,
  reducedMotion: false,
  mode: "screens",
  soundOn: true,
  captionsOn: true,
  preview: null,
  progress: { screenId: null, updatedAt: null },
  completed: new Set(),
};

let data = null;
let player = null;
let el = {};
let transitionTimer = null;
let readyTimer = null;
let progressTimer = null;
let lastFocused = null;
// "toc" | "transcript" | null. Tracked separately from the [hidden] attribute:
// the 220ms close animation keeps the old panel in the DOM, so "is it hidden"
// is not a reliable answer while the other drawer is opening.
let drawerOpen = null;

function readPref(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === "on") return true;
    if (raw === "off") return false;
  } catch {
    /* storage can be blocked; fall back to the default */
  }
  return fallback;
}

function writePref(key, on) {
  try {
    localStorage.setItem(key, on ? "on" : "off");
  } catch {
    /* storage can be blocked; the toggle still works for this page */
  }
}

/* ------------------------------------------------------------------ utils */

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function formatClock(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function screenById(id) {
  return data.screens.find((screen) => screen.id === id) || null;
}

function screenUrl(id) {
  return `#s=${id}`;
}

function readHashScreen() {
  const match = /^#s=([a-z][a-z0-9-]*)$/.exec(location.hash || "");
  if (!match) return null;
  return screenById(match[1]) ? match[1] : null;
}

/**
 * Admin classroom preview: ?preview=<screen-id>&back=<admin path>.
 *
 * The page is a disposable course bundle built with exactly one clip selected.
 * Only same-origin admin paths are accepted as the return link.
 */
function readPreview() {
  const params = new URLSearchParams(location.search);
  const id = params.get("preview");
  if (!id) return null;
  const screen = screenById(id);
  if (!screen) return null;
  const back = params.get("back") || "";
  return {
    screenId: id,
    index: data.screens.findIndex((item) => item.id === id),
    back: back.startsWith("/admin/") ? back : "/admin",
    kind: screen.kind === "outro" ? "片尾" : "片头",
    title: screen.title,
  };
}

/* ----------------------------------------------------------------- progress */

const progressKey = () => `ai-learning:progress:${data.slug}`;

function readLocalProgress() {
  try {
    const raw = localStorage.getItem(progressKey());
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.screenId !== "string") return null;
    if (!screenById(parsed.screenId)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeLocalProgress(screenId, completed) {
  try {
    const previous = readLocalProgress();
    const completedScreens = new Set(previous?.completedScreens || []);
    if (completed) completedScreens.add(screenId);
    localStorage.setItem(
      progressKey(),
      JSON.stringify({
        screenId,
        completedScreens: Array.from(completedScreens),
        updatedAt: new Date().toISOString(),
      }),
    );
  } catch {
    /* storage can be blocked; playback must not depend on it */
  }
}

function canSyncProgress() {
  // A classroom preview must not write the learner's real progress.
  if (deck.preview) return false;
  const endpoint =
    (window.__COURSE_PROGRESS__ && window.__COURSE_PROGRESS__.endpoint) || data.progress?.endpoint || null;
  const origin =
    (window.__COURSE_PROGRESS__ && window.__COURSE_PROGRESS__.origin) || data.progress?.origin || null;
  if (!endpoint || !origin) return false;
  return location.origin === origin;
}

async function fetchServerProgress() {
  if (!canSyncProgress()) return null;
  try {
    const response = await fetch(`${data.progress.endpoint}/${data.slug}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function pushServerProgress(screenId, completed) {
  if (!canSyncProgress()) return;
  clearTimeout(progressTimer);
  progressTimer = setTimeout(async () => {
    try {
      await fetch(`${data.progress.endpoint}/${data.slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ screenId, completed }),
      });
    } catch {
      /* silent: local progress already written */
    }
  }, PROGRESS_DEBOUNCE_MS);
}

function rememberScreen(screenId, completed) {
  if (deck.preview) return;
  deck.progress = { screenId, updatedAt: new Date().toISOString() };
  if (completed) deck.completed.add(screenId);
  writeLocalProgress(screenId, completed);
  pushServerProgress(screenId, completed);
}

/* ------------------------------------------------------------------ player */

function createPlayerAdapter(element) {
  let lastRange = null;

  const adapter = {
    get ready() {
      return Boolean(element.ready);
    },
    get painted() {
      return Boolean(element.painted);
    },
    get time() {
      return Number(element.currentTime) || 0;
    },
    get duration() {
      return Number(element.duration) || 0;
    },
    get paused() {
      return element.paused !== false;
    },
    load({ src, runtimeSrc, poster }) {
      element.setAttribute("runtime-src", runtimeSrc);
      if (poster) element.setAttribute("poster", poster);
      element.setAttribute("src", src);
    },
    setRange(start, end) {
      if (lastRange && lastRange.start === start && lastRange.end === end) return;
      // Order matters: setting a new start before the old end creates an
      // inverted range, which the player clamps. Write the end first.
      element.setAttribute("range-end", String(end));
      element.setAttribute("range-start", String(start));
      lastRange = { start, end };
    },
    seek(seconds) {
      element.seek(seconds);
    },
    play() {
      element.play();
    },
    pause() {
      element.pause();
    },
    sendControl(action, payload = {}) {
      // The player mounts the composition in a same-origin iframe inside its
      // open shadow root. Unknown control actions are ignored by the pinned
      // runtime; the composition's own listener handles `course-captions`.
      const frame =
        element.iframe || (element.shadowRoot && element.shadowRoot.querySelector("iframe"));
      const target = frame && frame.contentWindow;
      if (!target) return false;
      try {
        target.postMessage({ source: "hf-parent", type: "control", action, ...payload }, "*");
        return true;
      } catch {
        return false;
      }
    },
    on(event, handler) {
      element.addEventListener(event, handler);
    },
    destroy() {
      element.removeAttribute("src");
    },
  };
  return adapter;
}

function clearTransition() {
  clearTimeout(transitionTimer);
  transitionTimer = null;
  el.transition.classList.remove("is-visible");
  el.transition.setAttribute("hidden", "");
}

function showTransition() {
  el.transition.removeAttribute("hidden");
  requestAnimationFrame(() => el.transition.classList.add("is-visible"));
  clearTimeout(transitionTimer);
  transitionTimer = setTimeout(clearTransition, TRANSITION_MAX_MS);
}

/* --------------------------------------------------------------- rendering */

function currentScreen() {
  return data.screens[deck.index];
}

function setBodyState(state) {
  deck.state = state;
  document.body.dataset.deckState = state;
  el.cover.hidden = state !== "cover";
  el.stageWrap.hidden = state === "cover" || state === "complete" || state === "error";
  el.complete.hidden = state !== "complete";
  el.error.hidden = state !== "error";
  if (state === "cover") el.cover.removeAttribute("aria-hidden");
}

function lessonNumber(index) {
  // Clip screens are playable chapters but not lesson numbers: with a 片头 at
  // index 0, the first lesson still reads 01, matching the cover and the TOC.
  let n = 0;
  for (let i = 0; i <= index && i < data.screens.length; i += 1) {
    if ((data.screens[i].kind || "lesson") === "lesson") n += 1;
  }
  return n;
}

function screenLabel(screen, index) {
  // Intro/outro clips are screens in the playback order but not numbered
  // chapters; show 片头/片尾 where a lesson shows "07".
  if (screen?.kind === "intro") return "片头";
  if (screen?.kind === "outro") return "片尾";
  return String(lessonNumber(index)).padStart(2, "0");
}

function renderChapter() {
  const screen = currentScreen();
  if (!screen) return;

  el.kicker.textContent =
    screen.kicker ||
    ((screen.kind || "lesson") === "lesson"
      ? `第 ${lessonNumber(deck.index)} 屏`
      : screenLabel(screen, deck.index));
  el.title.textContent = screen.title;
  el.summary.textContent = screen.summary;

  el.counter.textContent = `${screenLabel(screen, deck.index)} / ${String(
    data.screens.length,
  ).padStart(2, "0")}`;

  const total = Math.max(0.001, courseDuration());
  el.progressFill.style.width = `${((data.screens[deck.index]?.start || 0) / total) * 100}%`;

  el.prev.disabled = deck.index === 0;
  // The last screen keeps "next" enabled: that click is how the learner reaches
  // the completion page, so it becomes "完成" instead of disappearing.
  const isLast = deck.index === data.screens.length - 1;
  el.next.disabled = false;
  el.next.setAttribute("aria-label", isLast ? "完成课程，查看总结" : "下一屏");
  const nextLabel = $(".control__label", el.next);
  if (nextLabel) nextLabel.textContent = isLast ? "完成" : "下一屏";
  el.replay.disabled = false;

  $$(".outline__item").forEach((item) => {
    const active = item.dataset.screenId === screen.id;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });

  syncTocActive();

  el.transcriptTitle.textContent = screen.title;
  el.transcriptBody.replaceChildren();
  const paragraphs = String(screen.transcript || screen.summary || "")
    .split(/\n+/)
    .filter(Boolean);
  for (const paragraph of paragraphs) {
    const node = document.createElement("p");
    node.textContent = paragraph;
    el.transcriptBody.append(node);
  }
  if (!paragraphs.length) {
    const node = document.createElement("p");
    node.textContent = "这一屏还没有讲义。";
    el.transcriptBody.append(node);
  }

  if (screen.keywords?.length) {
    el.transcriptKeywords.replaceChildren(
      ...screen.keywords.map((keyword) => {
        const node = document.createElement("span");
        node.className = "keyword";
        node.textContent = keyword;
        return node;
      }),
    );
    el.transcriptKeywords.hidden = false;
  } else {
    el.transcriptKeywords.hidden = true;
  }

  updateAnnouncer();
}

function updateAnnouncer() {
  const screen = currentScreen();
  if (!screen) return;
  const label =
    screen.kind === "intro" || screen.kind === "outro"
      ? screenLabel(screen, deck.index)
      : `第 ${lessonNumber(deck.index)} 屏`;
  el.announcer.textContent = `${label}，共 ${data.screens.length} 屏：${screen.title}`;
}

/** Mark the current screen in the directory, mirroring the cover outline. */
function syncTocActive() {
  for (const item of $$(".toc__item")) {
    const active = Number(item.dataset.index) === deck.index;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  }
}

function updatePlayState() {
  const playing = !player.paused;
  deck.playing = playing;
  el.play.setAttribute("aria-pressed", String(playing));
  el.play.setAttribute("aria-label", playing ? "暂停这一屏" : "播放这一屏");
  el.play.dataset.state = playing ? "playing" : "paused";
  const label = $(".control__label", el.play);
  if (label) label.textContent = playing ? "暂停" : "播放";
}

function updateClock() {
  const screen = currentScreen();
  if (!screen) return;
  // After "jump to the end" (or a natural end) the bar must read as complete,
  // even though the player clock stops a frame or two before the range edge.
  const within = deck.ended
    ? screen.duration
    : clamp(player.time - screen.start, 0, screen.duration);
  el.clockNow.textContent = formatClock(within);
  el.clockTotal.textContent = formatClock(screen.duration);

  // The scene scrubber is the one control that can jump through a screen. Its
  // thumb only moves while the learner is not dragging it.
  if (!deck.seeking) {
    el.sceneSeek.max = String(Math.max(0.1, screen.duration));
    el.sceneSeek.value = String(within);
  }
  el.sceneSeek.style.setProperty("--seek-progress", `${(within / Math.max(0.001, screen.duration)) * 100}%`);
  el.sceneSeek.setAttribute(
    "aria-valuetext",
    `${formatClock(within)} / ${formatClock(screen.duration)}`,
  );

  // Course progress grows continuously inside a screen instead of jumping by
  // one step per screen: the bar should read like a video timeline.
  const course = Math.max(0.001, courseDuration());
  const courseTime = clamp(screen.start + within, 0, course);
  el.progressFill.style.width = `${(courseTime / course) * 100}%`;
}

/* --------------------------------------------------------------- navigation */

function rangeFor(index) {
  const screen = data.screens[index];
  return { start: screen.start, end: screen.start + screen.duration, screen };
}

function isContinuous() {
  return deck.mode === "continuous";
}

function courseDuration() {
  const duration = Number(data.composition?.duration);
  if (Number.isFinite(duration) && duration > 0) return duration;
  const last = data.screens[data.screens.length - 1];
  return last ? last.start + last.duration : 0;
}

function applyRange(index) {
  if (isContinuous() && !deck.preview) {
    // Continuous mode plays the whole root timeline, exactly like a video.
    // Screens are only UI anchors on top of that single clock.
    player.setRange(0, courseDuration());
    return;
  }
  // A preview plays only the clip it was opened for, even on a continuous
  // course: it is a clip preview, not the start of the course.
  const { start, end } = rangeFor(index);
  player.setRange(start, end);
}

function screenIndexAt(time) {
  let index = 0;
  for (let i = 0; i < data.screens.length; i += 1) {
    if (time + 0.001 >= data.screens[i].start) index = i;
    else break;
  }
  return index;
}

function syncContinuousIndex(time, { completing = false } = {}) {
  if (!isContinuous() || deck.state !== "playing") return;
  const index = screenIndexAt(time);
  if (index === deck.index) return;
  // Crossing a boundary means the screen we just left is done. Mark it before
  // moving the UI forward so "继续上次" resumes at the right place.
  if (index > deck.index) {
    for (let i = deck.index; i < index; i += 1) rememberScreen(data.screens[i].id, true);
  }
  deck.index = index;
  renderChapter();
  updatePlayState();
  if (history.state?.screenId !== data.screens[index].id) {
    history.replaceState({ screenId: data.screens[index].id }, "", screenUrl(data.screens[index].id));
  }
  if (completing) updateAnnouncer();
}

function playScreen(index, { autoplay = true } = {}) {
  const bounded = clamp(index, 0, data.screens.length - 1);
  deck.index = bounded;
  const { start, screen } = rangeFor(bounded);

  applyRange(bounded);
  el.stageWrap.classList.remove("is-ended");
  renderChapter();
  rememberScreen(screen.id, false);
  if (history.state?.screenId !== screen.id) {
    history.pushState({ screenId: screen.id }, "", screenUrl(screen.id));
  }

  player.seek(start);
  if (autoplay) {
    player.play();
  }
  // Coming from the previous screen (or the completion page) must not inherit
  // its ended state, scrub position or filled course progress.
  deck.ended = false;
  deck.seeking = false;
  deck.resumeAfterSeek = false;
  el.stageWrap.classList.remove("is-ended");
  el.sceneSeek.max = String(Math.max(0.1, screen.duration));
  el.sceneSeek.value = "0";
  el.sceneSeek.style.setProperty("--seek-progress", "0%");
  el.sceneSeek.setAttribute(
    "aria-valuetext",
    `${formatClock(0)} / ${formatClock(screen.duration)}`,
  );
  el.clockNow.textContent = "0:00";
  el.clockTotal.textContent = formatClock(screen.duration);
  el.progressFill.style.width = `${(start / Math.max(0.001, courseDuration())) * 100}%`;
  updatePlayState();
}

function goTo(index, { announce = true } = {}) {
  const total = data.screens.length;
  if (index < 0) return;
  if (index >= total) {
    finish();
    return;
  }
  if (deck.state === "loading") return;

  const first = deck.state === "cover";
  clearTransition();
  if (!first) showTransition();
  setBodyState("playing");
  playScreen(index);
  if (announce) updateAnnouncer();
}

function next() {
  if (deck.index >= data.screens.length - 1) {
    finish();
    return;
  }
  goTo(deck.index + 1);
}

function prev() {
  if (deck.index <= 0) {
    if (isContinuous()) replay();
    return;
  }
  // Like a video player: pressing back near the start of a screen goes to the
  // previous screen, pressing it later restarts the current one.
  if (isContinuous()) {
    const { start } = rangeFor(deck.index);
    if (player.time - start > 1.5) {
      goTo(deck.index);
      return;
    }
  }
  goTo(deck.index - 1);
}

function replay() {
  if (isContinuous()) {
    deck.index = 0;
    deck.ended = false;
    deck.seeking = false;
    deck.resumeAfterSeek = false;
    applyRange(0);
    renderChapter();
    showTransition();
    player.seek(0);
    player.play();
    setBodyState("playing");
    updatePlayState();
    return;
  }
  const { start } = rangeFor(deck.index);
  showTransition();
  deck.ended = false;
  deck.seeking = false;
  deck.resumeAfterSeek = false;
  player.seek(start);
  player.play();
  setBodyState("playing");
  updatePlayState();
}

/** Replay only the clip this preview was opened for. */
function replayPreview() {
  if (!deck.preview || !player || !player.ready) return;
  const index = deck.preview.index;
  deck.index = index;
  deck.ended = false;
  deck.seeking = false;
  deck.resumeAfterSeek = false;
  applyRange(index);
  renderChapter();
  showTransition();
  player.seek(rangeFor(index).start);
  player.play();
  setBodyState("playing");
  updatePlayState();
}

function markScreenEnded() {
  const screen = currentScreen();
  if (!screen) return;
  deck.ended = true;
  deck.seeking = false;
  renderChapter();
  rememberScreen(screen.id, true);
  updatePlayState();
  el.stageWrap.classList.add("is-ended");
  el.sceneSeek.value = String(screen.duration);
  el.sceneSeek.style.setProperty("--seek-progress", "100%");
  el.sceneSeek.setAttribute(
    "aria-valuetext",
    `${formatClock(screen.duration)} / ${formatClock(screen.duration)}`,
  );
}

/** Start scrubbing: pause, remember whether to resume, and drop the ended state. */
function beginScrub() {
  if (deck.state !== "playing" || deck.seeking) return;
  deck.seeking = true;
  deck.resumeAfterSeek = !player.paused;
  deck.ended = false;
  player.pause();
  clearTransition();
  el.stageWrap.classList.remove("is-ended");
}

/** Seek the current screen while the learner drags the scene progress bar. */
function scrubTo(value) {
  if (deck.state !== "playing") return;
  const screen = currentScreen();
  if (!screen) return;
  if (!deck.seeking) beginScrub();
  const within = clamp(Number(value) || 0, 0, screen.duration);
  player.seek(screen.start + within);
  el.clockNow.textContent = formatClock(within);
  el.sceneSeek.style.setProperty(
    "--seek-progress",
    `${(within / Math.max(0.001, screen.duration)) * 100}%`,
  );
  el.sceneSeek.setAttribute(
    "aria-valuetext",
    `${formatClock(within)} / ${formatClock(screen.duration)}`,
  );
}

/** Release the scrubber: resume if it was playing, or settle on the final frame. */
function endScrub() {
  if (!deck.seeking || deck.state !== "playing") return;
  const screen = currentScreen();
  if (!screen) return;
  const within = clamp(Number(el.sceneSeek.value) || 0, 0, screen.duration);
  const resume = deck.resumeAfterSeek;
  deck.seeking = false;
  deck.resumeAfterSeek = false;
  if (within >= screen.duration - 0.1) {
    jumpToScreenEnd({ announce: false });
    return;
  }
  deck.ended = false;
  el.stageWrap.classList.remove("is-ended");
  if (resume) player.play();
  updateClock();
}

/**
 * Skip the rest of the current screen and show its final frame.
 *
 * Works in both playback modes: short courses stay on the current screen until
 * the learner presses next, while continuous (narrated) courses keep the same
 * single clock and simply pause on the final frame of the scene.
 */
function jumpToScreenEnd({ announce = true } = {}) {
  if (deck.state !== "playing") return;
  const { start, end } = rangeFor(deck.index);
  const target = Math.max(start, end - PLAYBACK_END_SLACK);
  deck.resumeAfterSeek = false;
  deck.seeking = false;
  // Mark the screen ended before seeking: seeking close to the range edge can
  // make the player emit its own `ended`, and the handler must not treat that
  // as a second, natural end.
  deck.ended = true;
  player.pause();
  clearTransition();
  player.seek(target);
  markScreenEnded();
  if (announce) {
    el.announcer.textContent = `已跳到第 ${deck.index + 1} 屏结尾：${currentScreen().title}`;
  }
}

function finish() {
  clearTransition();
  player.pause();
  if (drawerOpen) closeDrawer(drawerOpen, { restoreFocus: false });
  setBodyState("complete");
  if (isContinuous()) {
    for (const screen of data.screens) rememberScreen(screen.id, true);
  } else {
    const last = data.screens[data.screens.length - 1];
    if (last) rememberScreen(last.id, true);
  }
  el.completeTitle.textContent = data.title;
  el.completeLead.textContent = `你完成了全部 ${data.screens.length} 屏。`;
  renderTakeaways();
  el.complete.focus();
  updateAnnouncer();
}

function renderTakeaways() {
  el.takeaways.replaceChildren();
  const items = data.takeaways?.length ? data.takeaways : data.outcomes || [];
  for (const text of items) {
    const item = document.createElement("li");
    item.textContent = text;
    el.takeaways.append(item);
  }
  if (!items.length) {
    el.takeawaysSection.hidden = true;
  } else {
    el.takeawaysSection.hidden = false;
  }
}

/* ------------------------------------------------------------------- start */

function showPreviewBar(preview) {
  if (!el.previewBar) return;
  el.previewBar.hidden = false;
  if (el.previewKind) el.previewKind.textContent = `${preview.kind}预览`;
  if (el.previewLabel) el.previewLabel.textContent = preview.title;
  if (el.previewBack) el.previewBack.href = preview.back;
  if (el.exit) {
    el.exit.href = preview.back;
    const exitLabel = $(".control__label", el.exit);
    if (exitLabel) exitLabel.textContent = "返回设置";
  }
}

function startDeck({ fromHash = false } = {}) {
  if (deck.state !== "cover") return;
  setBodyState("loading");
  el.loading.hidden = false;
  clearTimeout(readyTimer);

  if (!player.ready) {
    player.load({
      src: "./composition/index.html",
      runtimeSrc: "./runtime/vendor/hyperframe.runtime.iife.js",
      poster: el.stage.dataset.poster || null,
    });
  }

  const targetIndex = fromHash ? deck.index : 0;
  applyRange(targetIndex);

  const begin = () => {
    clearTimeout(readyTimer);
    el.loading.hidden = true;
    setBodyState("playing");
    // The click on "开始学习" is the user gesture that unlocks audio. The
    // saved preference decides whether voice starts on; both switches can be
    // changed at any time from the control bar.
    if (data.audio) setMuted(!deck.soundOn);
    sendCaptionPreference(8);
    playScreen(targetIndex, { autoplay: !deck.reducedMotion });
  };

  if (player.ready && player.painted) {
    begin();
    return;
  }

  let begun = false;
  const beginOnce = () => {
    if (begun) return;
    begun = true;
    begin();
  };

  player.on("ready", beginOnce);
  player.on("painted", beginOnce);

  readyTimer = setTimeout(() => {
    if (deck.state === "loading") {
      showError("播放器在 10 秒内没有准备好。", "CHECK_TIMEOUT");
    }
  }, READY_TIMEOUT_MS);
}

/* ------------------------------------------------------------------ errors */

function showError(message, code) {
  clearTransition();
  clearTimeout(readyTimer);
  if (drawerOpen) closeDrawer(drawerOpen, { restoreFocus: false });
  setBodyState("error");
  el.errorMessage.textContent = message;
  el.errorCode.textContent = code ? `代码：${code}` : "";
  el.error.focus();
  const meta = `课程 ${data.slug} · HyperFrames ${data.build?.runtimeVersion || "?"}`;
  el.errorMeta.textContent = meta;
  // eslint-disable-next-line no-console
  console.error(`[ai-learning] ${data.slug}: ${message}`);
}

/* ---------------------------------------------------------------- controls */

function togglePlay() {
  if (deck.state === "cover") {
    startDeck();
    return;
  }
  if (deck.state === "complete" || deck.state === "error") return;
  // After a natural end (or after "jump to the end") the play button restarts
  // this screen; playing the remaining 0 seconds would look broken. Continuous
  // courses resume the single clock and advance into the next screen.
  if (deck.ended) {
    if (isContinuous()) {
      deck.ended = false;
      el.stageWrap.classList.remove("is-ended");
      player.play();
      return;
    }
    replay();
    return;
  }
  if (player.paused) player.play();
  else player.pause();
}

/* ---------------------------------------------------------------- drawers */

/* The transcript and the directory are two panels of one drawer system: same
 * scrim, same slide, same focus contract. Only one is open at a time, so the
 * learner never stacks two full-height panels over the player. */

function openDrawer(kind) {
  if (drawerOpen === kind) return;
  if (drawerOpen) closeDrawer(drawerOpen, { restoreFocus: false });
  const wrap = kind === "toc" ? el.tocWrap : el.transcriptWrap;
  lastFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  drawerOpen = kind;
  wrap.removeAttribute("hidden");
  requestAnimationFrame(() => {
    wrap.classList.add("is-open");
    (kind === "toc" ? el.tocClose : el.transcriptClose).focus();
  });
  document.body.classList.add("deck-drawer-open");
  if (kind === "toc") scrollCurrentTocItemIntoView();
}

function closeDrawer(kind = drawerOpen, { restoreFocus = true } = {}) {
  if (!kind) return;
  const wrap = kind === "toc" ? el.tocWrap : el.transcriptWrap;
  wrap.classList.remove("is-open");
  setTimeout(() => {
    // Reopening the same drawer (or opening the other one) within the closing
    // animation must not leave the fresh panel hidden.
    if (drawerOpen !== kind) wrap.setAttribute("hidden", "");
  }, 220);
  if (drawerOpen === kind) drawerOpen = null;
  if (!drawerOpen) document.body.classList.remove("deck-drawer-open");
  if (!restoreFocus) return;
  // The trigger is the honest fallback: `lastFocused` can be a panel button of
  // the drawer we just closed (switching drawers by keyboard) or <body> when the
  // drawer was opened with a shortcut, and neither can take focus back.
  const trigger = kind === "toc" ? el.tocButton : el.transcriptButton;
  const insidePanel =
    lastFocused instanceof HTMLElement &&
    (el.tocWrap.contains(lastFocused) || el.transcriptWrap.contains(lastFocused));
  const target =
    lastFocused instanceof HTMLElement && lastFocused !== document.body && !insidePanel
      ? lastFocused
      : trigger;
  target.focus();
}

function openTranscript() {
  openDrawer("transcript");
}

function closeTranscript() {
  closeDrawer("transcript");
}

function openToc() {
  openDrawer("toc");
}

function closeToc() {
  closeDrawer("toc");
}

/** Keep the current screen visible when the directory opens on screen 19. */
function scrollCurrentTocItemIntoView() {
  const active = $('.toc__item[aria-current="step"]', el.tocWrap);
  if (active) active.scrollIntoView({ block: "nearest" });
}

async function toggleFullscreen() {
  const target = el.stageWrap;
  try {
    if (!document.fullscreenElement) {
      await target.requestFullscreen();
    } else {
      await document.exitFullscreen();
    }
  } catch {
    /* fullscreen can be blocked; nothing to do */
  }
}

function setMuted(muted) {
  if (!el.player) return;
  if (muted) el.player.setAttribute("muted", "");
  else el.player.removeAttribute("muted");
  deck.soundOn = !muted;
  if (el.sound) {
    el.sound.setAttribute("aria-pressed", String(!muted));
    el.sound.setAttribute("aria-label", muted ? "打开配音（M）" : "关闭配音（M）");
    el.sound.setAttribute("title", muted ? "打开配音（M）" : "关闭配音（M）");
  }
}

function toggleMute() {
  if (!el.sound || !el.player) return;
  const muted = !el.player.hasAttribute("muted");
  writePref(PREF_SOUND, muted);
  setMuted(muted);
}

function sendCaptionPreference(tries = 0) {
  if (!player || !el.captions) return;
  if (player.sendControl("course-captions", { visible: deck.captionsOn })) return;
  if (tries > 0) setTimeout(() => sendCaptionPreference(tries - 1), 250);
}

function syncCaptionButton() {
  if (!el.captions) return;
  el.captions.setAttribute("aria-pressed", String(deck.captionsOn));
  el.captions.setAttribute(
    "aria-label",
    deck.captionsOn ? "隐藏字幕（C）" : "显示字幕（C）",
  );
  el.captions.setAttribute("title", deck.captionsOn ? "字幕开（C）" : "字幕关（C）");
}

function setCaptions(on) {
  deck.captionsOn = on;
  writePref(PREF_CAPTIONS, on);
  syncCaptionButton();
  sendCaptionPreference(8);
}

function toggleCaptions() {
  if (!el.captions) return;
  setCaptions(!deck.captionsOn);
}

function exitCourse(event) {
  // Modified clicks should keep their native meaning (new tab / download).
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
    return;
  }
  event.preventDefault();
  // Leaving must work even while the player is still loading or has failed:
  // stop every scheduled transition/timer, silence the player, then let the
  // browser follow the plain link target (the href is rendered server-side).
  clearTransition();
  clearTimeout(readyTimer);
  readyTimer = null;
  try {
    player.pause();
  } catch {
    /* the player may not be loaded yet */
  }
  try {
    player.destroy();
  } catch {
    /* already destroyed */
  }
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {
      /* fullscreen may already be gone */
    });
  }
  if (drawerOpen) closeDrawer(drawerOpen, { restoreFocus: false });
  window.location.href = el.exit.getAttribute("href");
}

/* ------------------------------------------------------------------- wiring */

function wirePlayer() {
  player = createPlayerAdapter(el.player);

  let lastTime = 0;
  player.on("timeupdate", () => {
    const time = player.time;
    if (isContinuous()) {
      syncContinuousIndex(time);
    }
    const { start, end } = rangeFor(deck.index);
    updateClock();
    // A seek finished: the first timeupdate inside the new range is the
    // earliest honest moment to lift the transition veil.
    if (deck.state === "playing" && time >= start - 0.05 && time <= end + 0.05) {
      if (time !== lastTime) clearTransition();
    }
    lastTime = time;
  });

  player.on("ended", () => {
    // A stale `ended` can arrive after a seek near the range edge, after a
    // jump-to-end, or while switching screens. Only accept it when it belongs
    // to the current screen's own end.
    if (deck.ended) return;
    const endedScreen = currentScreen();
    if (!endedScreen) return;
    const endedRange = rangeFor(deck.index);
    if (Math.abs(player.time - endedRange.end) > 0.25) return;

    if (deck.preview) {
      // Stop at the end of the previewed clip instead of walking into the course
      // or opening the completion page.
      markScreenEnded();
      return;
    }

    if (isContinuous()) {
      deck.ended = true;
      finish();
      return;
    }
    const screen = endedScreen;
    markScreenEnded();
    if (screen.autoAdvance && deck.index < data.screens.length - 1 && !deck.reducedMotion) {
      setTimeout(() => {
        if (deck.index < data.screens.length - 1) next();
      }, 900);
      return;
    }
    el.next.focus();
  });

  player.on("play", () => {
    el.stageWrap.classList.remove("is-ended");
    deck.ended = false;
    updatePlayState();
    updateClock();
  });

  player.on("pause", updatePlayState);

  player.on("error", (event) => {
    const detail = event?.detail?.message || "播放器报了错误。";
    showError(`动画没有加载出来：${detail}`, "PLAYER_ERROR");
  });

  player.on("rangeclamped", (event) => {
    const { rangeStart, rangeEnd, duration } = event.detail || {};
    // eslint-disable-next-line no-console
    console.warn(
      `[ai-learning] range clamped for ${data.slug}: ${rangeStart}-${rangeEnd} of ${duration}`,
    );
  });

  player.on("ready", () => {
    clearTimeout(readyTimer);
    el.loading.hidden = true;
    sendCaptionPreference(8);
  });
}

function wireControls() {
  el.start.addEventListener("click", () => startDeck());
  el.resume.addEventListener("click", () => {
    const target = readLocalProgress()?.screenId;
    const index = target ? data.screens.findIndex((screen) => screen.id === target) : 0;
    deck.index = Math.max(0, index);
    startDeck({ fromHash: true });
  });

  el.prev.addEventListener("click", prev);
  el.next.addEventListener("click", next);
  if (el.exit) el.exit.addEventListener("click", exitCourse);
  el.play.addEventListener("click", togglePlay);
  el.replay.addEventListener("click", replay);
  el.skipEnd.addEventListener("click", () => jumpToScreenEnd());
  // Scene scrubbing: pointerdown pauses immediately so the frame follows the
  // thumb; `input` fires for dragging and keyboard arrows, `change` on release.
  el.sceneSeek.addEventListener("pointerdown", beginScrub);
  el.sceneSeek.addEventListener("input", () => scrubTo(Number(el.sceneSeek.value)));
  el.sceneSeek.addEventListener("change", endScrub);
  el.sceneSeek.addEventListener("pointerup", () => {
    if (deck.seeking) endScrub();
  });
  el.transcriptButton.addEventListener("click", openTranscript);
  el.transcriptClose.addEventListener("click", closeTranscript);
  const scrim = $(".drawer__scrim", el.transcriptWrap);
  if (scrim) scrim.addEventListener("click", closeTranscript);
  el.tocButton.addEventListener("click", () => {
    if (drawerOpen === "toc") closeDrawer("toc");
    else openToc();
  });
  el.tocClose.addEventListener("click", closeToc);
  const tocScrim = $(".drawer__scrim", el.tocWrap);
  if (tocScrim) tocScrim.addEventListener("click", closeToc);
  el.fullscreen.addEventListener("click", toggleFullscreen);
  if (el.sound) el.sound.addEventListener("click", toggleMute);
  if (el.captions) el.captions.addEventListener("click", toggleCaptions);
  if (el.previewReplay) el.previewReplay.addEventListener("click", replayPreview);
  el.retry.addEventListener("click", () => {
    el.error.hidden = true;
    player.destroy();
    window.location.reload();
  });
  el.errorBack.addEventListener("click", () => {
    setBodyState("cover");
    el.loading.hidden = true;
  });

  el.completeReplay.addEventListener("click", () => {
    deck.completed.clear();
    goTo(0);
  });
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable) return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) return;

    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        next();
        break;
      case "ArrowLeft":
        event.preventDefault();
        prev();
        break;
      case " ":
      case "Spacebar":
        event.preventDefault();
        togglePlay();
        break;
      case "End":
        event.preventDefault();
        jumpToScreenEnd();
        break;
      case "f":
      case "F":
        event.preventDefault();
        toggleFullscreen();
        break;
      case "c":
      case "C":
        event.preventDefault();
        toggleCaptions();
        break;
      case "m":
      case "M":
        event.preventDefault();
        toggleMute();
        break;
      case "t":
      case "T":
        event.preventDefault();
        if (drawerOpen === "transcript") closeDrawer("transcript");
        else openTranscript();
        break;
      case "o":
      case "O":
        event.preventDefault();
        if (drawerOpen === "toc") closeDrawer("toc");
        else openToc();
        break;
      case "Escape":
        if (drawerOpen) {
          event.preventDefault();
          closeDrawer(drawerOpen);
        }
        break;
      default:
        break;
    }
  });

  window.addEventListener("popstate", () => {
    const hashScreen = readHashScreen();
    if (!hashScreen) return;
    const index = data.screens.findIndex((screen) => screen.id === hashScreen);
    if (index >= 0 && index !== deck.index && deck.state !== "cover") {
      goTo(index, { announce: true });
    }
  });

  document.addEventListener("fullscreenchange", () => {
    el.fullscreen.setAttribute("aria-pressed", String(Boolean(document.fullscreenElement)));
  });
}

function wireOutline() {
  for (const item of $$(".outline__item")) {
    item.addEventListener("click", () => {
      const index = Number(item.dataset.index);
      if (Number.isNaN(index)) return;
      if (deck.state === "cover") {
        deck.index = index;
        startDeck({ fromHash: true });
        return;
      }
      goTo(index);
    });
  }
}

/** Directory rows: jump to the chosen screen and keep the keyboard usable. */
function wireToc() {
  for (const item of $$(".toc__item")) {
    item.addEventListener("click", () => {
      const index = Number(item.dataset.index);
      if (Number.isNaN(index)) return;
      // The panel must not cover the transition, and the jump itself is the
      // same goTo() the next/prev controls use (continuous mode included).
      closeDrawer("toc", { restoreFocus: false });
      if (deck.state !== "playing") {
        // Only reachable while the first frame is still loading; the bar stays
        // interactive under the veil, so put focus somewhere real.
        el.tocButton.focus();
        return;
      }
      goTo(index);
      el.play.focus();
    });
  }
}

/* --------------------------------------------------------------------- boot */

async function boot() {
  const node = document.getElementById("course-data");
  data = JSON.parse(node.textContent);
  deck.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  deck.mode = data.playback === "continuous" ? "continuous" : "screens";
  deck.soundOn = readPref(PREF_SOUND, true);
  deck.captionsOn = readPref(PREF_CAPTIONS, true);
  document.body.dataset.deckMode = deck.mode;

  window.__COURSE_PROGRESS__ = data.progress || window.__COURSE_PROGRESS__ || null;

  el = {
    cover: $("#cover"),
    stageWrap: $("#stage-wrap"),
    stage: $("#stage"),
    player: $("#hf-player"),
    loading: $("#loading"),
    transition: $("#transition"),
    kicker: $("#chapter-kicker"),
    title: $("#chapter-title"),
    summary: $("#chapter-summary"),
    counter: $("#chapter-counter"),
    progressFill: $("#course-progress-fill"),
    clockNow: $("#clock-now"),
    clockTotal: $("#clock-total"),
    sceneSeek: $("#scene-seek"),
    exit: $("#btn-exit"),
    prev: $("#btn-prev"),
    next: $("#btn-next"),
    skipEnd: $("#btn-skip-end"),
    play: $("#btn-play"),
    replay: $("#btn-replay"),
    transcriptButton: $("#btn-transcript"),
    transcriptWrap: $("#transcript"),
    transcriptClose: $("#transcript-close"),
    transcriptTitle: $("#transcript-title"),
    transcriptBody: $("#transcript-body"),
    transcriptKeywords: $("#transcript-keywords"),
    tocButton: $("#btn-toc"),
    tocWrap: $("#toc"),
    tocClose: $("#toc-close"),
    fullscreen: $("#btn-fullscreen"),
    sound: $("#btn-sound"),
    captions: $("#btn-captions"),
    announcer: $("#deck-announcer"),
    complete: $("#complete"),
    completeTitle: $("#complete-title"),
    completeLead: $("#complete-lead"),
    takeaways: $("#takeaways"),
    takeawaysSection: $("#takeaways-section"),
    completeReplay: $("#complete-replay"),
    error: $("#error"),
    errorMessage: $("#error-message"),
    errorCode: $("#error-code"),
    errorMeta: $("#error-meta"),
    retry: $("#btn-retry"),
    errorBack: $("#btn-error-back"),
    start: $("#btn-start"),
    resume: $("#btn-resume"),
    deepHint: $("#deck-deep-hint"),
    previewBar: $("#deck-preview"),
    previewKind: $("#deck-preview-kind"),
    previewLabel: $("#deck-preview-label"),
    previewReplay: $("#deck-preview-replay"),
    previewBack: $("#deck-preview-back"),
  };

  wirePlayer();
  wireControls();
  wireOutline();
  wireToc();

  // Apply saved switches before the first frame so the control bar and the
  // composition agree even when the learner reloads mid-course.
  if (data.audio) {
    syncCaptionButton();
    setMuted(!deck.soundOn);
  }

  // Cover state
  const local = readLocalProgress();
  if (local) {
    const completed = new Set(local.completedScreens || []);
    deck.progress = { screenId: local.screenId, updatedAt: local.updatedAt };
    for (const id of completed) deck.completed.add(id);
    const finished = completed.size >= data.screens.length;
    if (!finished) {
      const target = screenById(local.screenId);
      el.resume.hidden = false;
      el.resume.textContent = `继续上次：${target ? target.title : local.screenId}`;
    }
  }

  const hashScreen = readHashScreen();
  if (hashScreen) {
    deck.index = data.screens.findIndex((screen) => screen.id === hashScreen);
  }

  const preview = readPreview();
  if (preview) {
    deck.preview = preview;
    deck.index = preview.index;
    showPreviewBar(preview);
    document.body.dataset.deckPreview = "true";
  }

  renderChapter();
  setBodyState("cover");
  el.cover.hidden = false;
  el.loading.hidden = true;

  if (preview) {
    // An explicit preview click is the user gesture; go straight into the
    // classroom at the clip instead of showing the cover first.
    startDeck({ fromHash: true });
  }

  const server = !preview && canSyncProgress() ? await fetchServerProgress() : null;
  if (server) {
    const completed = new Set(server.completedScreens || []);
    for (const id of completed) deck.completed.add(id);
    if (server.completedScreens?.length >= data.screens.length) {
      el.resume.hidden = true;
    }
  }

  if (hashScreen && !preview) {
    // Deep links land on the first frame of that screen, paused.
    deck.index = data.screens.findIndex((screen) => screen.id === hashScreen);
    renderChapter();
    el.deepHint.hidden = false;
    el.deepHint.textContent = `已定位到第 ${deck.index + 1} 屏：${currentScreen().title}。按“开始”播放。`;
    el.start.textContent = "从这一屏开始";
  }

  document.body.dataset.deckReady = "true";
  window.__DECK__ = deck;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
