(() => {
  const $ = (id) => document.getElementById(id);
  const api = (path) => new URL(path, document.baseURI);
  let key = sessionStorage.getItem("notifSchedulerKey") || "";
  let project = "";

  async function call(path, options = {}) {
    const response = await fetch(api(path), {
      ...options,
      headers: { "X-API-Key": key, ...(options.body ? { "Content-Type": "application/json" } : {}) },
      cache: "no-store"
    });
    if (!response.headers.get("Content-Type")?.includes("application/json")) {
      throw new Error(`Scheduler API unavailable (HTTP ${response.status}). Check the Caddy route and tunnel.`);
    }
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
  }

  function notice(message, bad = false) {
    $("notice").textContent = message;
    $("notice").classList.toggle("bad", bad);
    $("notice").hidden = !message;
  }

  function lock() {
    key = "";
    sessionStorage.removeItem("notifSchedulerKey");
    $("workspace").hidden = true;
    $("unlock-panel").hidden = false;
    $("disconnect").hidden = true;
    $("connection-status").textContent = "Locked";
    $("connection-status").classList.remove("online");
    $("api-key").value = "";
  }

  async function unlock(candidate) {
    key = candidate;
    try {
      const result = await call("v1/projects");
      sessionStorage.setItem("notifSchedulerKey", key);
      $("unlock-error").hidden = true;
      $("unlock-panel").hidden = true;
      $("workspace").hidden = false;
      $("disconnect").hidden = false;
      $("connection-status").textContent = "Connected";
      $("connection-status").classList.add("online");
      $("api-key").value = "";
      const list = $("project-list");
      list.replaceChildren();
      result.projects.forEach((name) => {
        const option = document.createElement("option");
        option.value = name;
        list.append(option);
      });
      const remembered = sessionStorage.getItem("notifSchedulerProject");
      $("project").value = remembered || result.projects[0] || "";
      if ($("project").value) await openProject();
    } catch (error) {
      lock();
      $("unlock-error").textContent = error.message;
      $("unlock-error").hidden = false;
    }
  }

  function dateLabel(value) {
    return value ? new Date(value).toLocaleString() : "—";
  }

  function renderJobs(jobs) {
    $("job-count").textContent = `${jobs.length} shown`;
    const list = $("jobs-list");
    list.replaceChildren();
    if (!jobs.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No notifications yet. Create one above or trigger an event preset.";
      list.append(empty);
      return;
    }
    jobs.forEach((job) => {
      const row = document.createElement("div");
      row.className = "job";
      const main = document.createElement("div");
      main.className = "job-main";
      const title = document.createElement("div");
      title.className = "job-title";
      title.textContent = job.title || "Untitled notification";
      const message = document.createElement("div");
      message.className = "job-message";
      message.textContent = job.message;
      const meta = document.createElement("div");
      meta.className = "job-meta";
      meta.textContent = `${job.every_seconds ? "Repeats · " : ""}Next: ${dateLabel(job.send_at)}${job.last_sent_at ? ` · Last sent: ${dateLabel(job.last_sent_at)}` : ""}${job.last_error ? ` · Error: ${job.last_error}` : ""}`;
      main.append(title, message, meta);
      const right = document.createElement("div");
      right.className = "job-right";
      const status = document.createElement("span");
      status.className = `job-status ${job.status}`;
      status.textContent = job.status;
      right.append(status);
      if (job.status === "pending" || job.status === "sending") {
        const cancel = document.createElement("button");
        cancel.className = "cancel-button";
        cancel.type = "button";
        cancel.textContent = "Cancel";
        cancel.addEventListener("click", async () => {
          if (!confirm("Cancel this notification?")) return;
          try {
            await call(`v1/projects/${encodeURIComponent(project)}/notifications/${job.id}`, { method: "DELETE" });
            notice("Notification cancelled.");
            await refresh();
          } catch (error) { notice(error.message, true); }
        });
        right.append(cancel);
      }
      row.append(main, right);
      list.append(row);
    });
  }

  function renderEvents(events) {
    const list = $("events-list");
    list.replaceChildren();
    if (!Object.keys(events).length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No event presets configured for this project.";
      list.append(empty);
      return;
    }
    Object.entries(events).forEach(([name, preset]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "event-button";
      const info = document.createElement("span");
      const title = document.createElement("strong");
      title.textContent = name;
      const description = document.createElement("small");
      description.textContent = preset.title || preset.message;
      info.append(title, description);
      const arrow = document.createElement("span");
      arrow.textContent = "↗";
      button.append(info, arrow);
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await call(`v1/projects/${encodeURIComponent(project)}/events/${encodeURIComponent(name)}`, { method: "POST" });
          notice(`Event “${name}” queued for immediate delivery.`);
          await refresh();
        } catch (error) { notice(error.message, true); }
        finally { button.disabled = false; }
      });
      list.append(button);
    });
  }

  async function refresh() {
    if (!project) return;
    const path = `v1/projects/${encodeURIComponent(project)}`;
    const [jobs, presets] = await Promise.all([call(`${path}/notifications`), call(`${path}/events`)]);
    renderJobs(jobs.notifications);
    renderEvents(presets.events);
  }

  async function openProject() {
    const name = $("project").value.trim();
    if (!/^[A-Za-z0-9_-]{1,58}$/.test(name)) {
      notice("Use 1–58 letters, digits, underscores, or hyphens for a project name.", true);
      return;
    }
    project = name;
    sessionStorage.setItem("notifSchedulerProject", name);
    $("project-content").hidden = false;
    notice("");
    try { await refresh(); } catch (error) { notice(error.message, true); }
  }

  function updateMode() {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    $("schedule-fields").hidden = mode === "now";
    $("repeat-fields").hidden = mode !== "repeat";
    $("send-at").required = mode === "later";
  }

  $("unlock-form").addEventListener("submit", (event) => {
    event.preventDefault();
    unlock($("api-key").value);
  });
  $("disconnect").addEventListener("click", lock);
  $("open-project").addEventListener("click", openProject);
  $("project").addEventListener("keydown", (event) => { if (event.key === "Enter") openProject(); });
  $("project").addEventListener("input", () => {
    if ($("project").value.trim() !== project) {
      project = "";
      $("project-content").hidden = true;
    }
  });
  $("refresh").addEventListener("click", async () => {
    try { await refresh(); notice("Up to date."); } catch (error) { notice(error.message, true); }
  });
  document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener("change", updateMode));
  $("notification-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const tags = $("tags").value.split(",").map((tag) => tag.trim()).filter(Boolean);
    const body = { title: $("title").value, message: $("message").value, priority: Number($("priority").value), tags };
    if (mode !== "now" && $("send-at").value) body.send_at = new Date($("send-at").value).toISOString();
    if (mode === "repeat") body.every_seconds = Number($("interval").value);
    const submit = $("notification-form").querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await call(`v1/projects/${encodeURIComponent(project)}/notifications`, { method: "POST", body: JSON.stringify(body) });
      $("notification-form").reset();
      updateMode();
      notice(mode === "now" ? "Notification queued for immediate delivery." : "Notification scheduled.");
      await refresh();
    } catch (error) { notice(error.message, true); }
    finally { submit.disabled = false; }
  });
  if (key) unlock(key);
})();
