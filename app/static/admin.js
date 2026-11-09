/* Admin settings page: poll render status while a job is running.
 * Without JavaScript the page still lists courses and the form still submits;
 * this file only keeps the status line fresh and reloads when a job ends. */

(() => {
  "use strict";

  const list = document.querySelector("[data-admin-list]");
  if (!list) return;

  const rows = Array.from(list.querySelectorAll("[data-admin-course]"));
  if (!rows.length) return;

  const statusUrl = "/admin/status";
  let wasBusy = list.dataset.adminBusy === "true";
  let timer = null;

  const formatElapsed = (seconds) => {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    if (minutes === 0) return `${rest} 秒`;
    return `${minutes} 分 ${rest} 秒`;
  };

  const disableGenerateButtons = (busy) => {
    list.dataset.adminBusy = busy ? "true" : "false";
    if (!busy) return;
    rows.forEach((row) => {
      const button = row.querySelector("[data-admin-generate]");
      if (button) button.disabled = true;
    });
  };

  const apply = (data) => {
    rows.forEach((row) => {
      const slug = row.dataset.adminCourse;
      const video = (data.videos || {})[slug];
      if (!video) return;

      row.dataset.adminState = video.state;
      const status = row.querySelector("[data-admin-status]");
      if (!status) return;
      if (video.state === "running") {
        status.textContent = `生成中，已用 ${formatElapsed(video.elapsedSeconds)}`;
      } else if (video.state === "ready") {
        status.textContent = "已生成";
      } else if (video.state === "failed") {
        status.textContent = "生成失败";
      } else {
        status.textContent = "未生成";
      }
    });

    disableGenerateButtons(Boolean(data.busy));
    const shouldReload = wasBusy && !data.busy;
    wasBusy = Boolean(data.busy);
    if (shouldReload) {
      window.location.reload();
      return;
    }
    schedule(data.busy ? 2500 : 5000);
  };

  const poll = async () => {
    timer = null;
    try {
      const response = await fetch(statusUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) {
        schedule(5000);
        return;
      }
      apply(await response.json());
    } catch (error) {
      schedule(8000);
    }
  };

  const schedule = (delay) => {
    if (timer !== null) return;
    timer = window.setTimeout(poll, delay);
  };

  if (wasBusy) schedule(1200);
})();
