(() => {
  "use strict";

  const state = {
    token: "",
    capabilities: null,
    queue: null,
    builds: [],
    endpoint: null,
    selectedBuild: null,
    page: "overview",
    refreshTimer: null,
    refreshBusy: false,
  };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const terminalStates = new Set(["succeeded", "failed", "cancelled", "timed_out", "resource_limit_exceeded"]);
  const activeStates = new Set(["preparing", "running", "cancelling"]);

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${state.token}`);
    if (options.body && !(options.body instanceof ArrayBuffer) && typeof options.body !== "string") {
      headers.set("Content-Type", "application/json");
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, { ...options, headers, cache: "no-store" });
    const contentType = response.headers.get("content-type") || "";
    let payload;
    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      payload = await response.text();
    }
    if (!response.ok) {
      const detail = payload?.error;
      const message = detail?.message || detail?.code || (typeof payload === "string" ? payload : "Request failed");
      const error = new Error(message);
      error.status = response.status;
      error.code = detail?.code;
      throw error;
    }
    return payload;
  }

  function setError(element, message) {
    if (!element) return;
    element.textContent = message || "";
    element.hidden = !message;
  }

  function toast(message, type = "success") {
    const element = $("#toast");
    element.textContent = message;
    element.className = `toast visible ${type === "error" ? "toast-error" : ""}`;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => { element.className = "toast"; }, 3200);
  }

  function statusClass(stateName) {
    if (stateName === "succeeded") return "badge-success";
    if (stateName === "failed" || stateName === "timed_out" || stateName === "resource_limit_exceeded") return "badge-danger";
    if (stateName === "cancelled") return "badge-neutral";
    if (stateName === "queued") return "badge-queued";
    if (activeStates.has(stateName)) return "badge-running";
    return "badge-neutral";
  }

  function stateLabel(value) {
    return String(value || "unknown").replaceAll("_", " ");
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(Number(value) * 1000);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
  }

  function formatDuration(job) {
    const seconds = Number(job?.duration_seconds);
    if (!Number.isFinite(seconds)) return job?.state === "queued" ? "Queued" : "—";
    if (seconds < 60) return `${Math.round(seconds)}s`;
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  }

  function taskNames(job) {
    return (job?.execution?.tasks || ["build"]).join(", ");
  }

  function isLoopback() {
    return ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  }

  function endpoints() {
    const configured = state.endpoint?.public_url;
    const origin = configured || window.location.origin;
    return {
      origin: origin.replace(/\/$/, ""),
      mcp: `${origin.replace(/\/$/, "")}/mcp/`,
      rest: `${origin.replace(/\/$/, "")}/api/v1`,
      openapi: `${origin.replace(/\/$/, "")}/openapi.json`,
    };
  }

  function fillAgentSetup() {
    const values = endpoints();
    $("#mcpEndpoint").textContent = values.mcp;
    $("#restEndpoint").textContent = values.rest;
    $("#openApiEndpoint").textContent = values.openapi;
    $("#topbarEndpoint").textContent = new URL(values.origin).host;
    const config = {
      mcpServers: {
        gradlemcp: {
          type: "http",
          url: values.mcp,
          headers: { Authorization: "Bearer INJECT_FROM_YOUR_SECRET_STORE" },
        },
      },
    };
    $("#mcpConfigSnippet").textContent = JSON.stringify(config, null, 2);
    $("#curlSnippet").textContent = `curl -fsS \\\n  -H "Authorization: Bearer $GRADLEMCP_TOKEN" \\\n  "${values.rest}/capabilities"`;
    const warning = $("#endpointWarning");
    if (window.location.protocol !== "https:" && !isLoopback()) {
      warning.hidden = false;
      warning.querySelector("p").textContent = "This workspace is being used over public HTTP. Bearer tokens and source uploads are not encrypted in transit. Put GradleMCP behind HTTPS before using real credentials.";
    } else {
      warning.hidden = true;
    }
  }

  function fillToolchains() {
    const select = $("#toolchainSelect");
    const profiles = state.capabilities?.toolchains || {};
    select.replaceChildren(new Option("Auto-select from project", ""));
    for (const [name, profile] of Object.entries(profiles)) {
      const option = new Option(`${name} · Java ${profile.java} / Gradle ${profile.gradle}`, name);
      select.add(option);
    }
    $("#toolchainHint").textContent = `${Object.keys(profiles).length} approved profile${Object.keys(profiles).length === 1 ? "" : "s"} available.`;
    const uploadLimit = state.capabilities?.limits?.upload_mb;
    $("#fileHint").textContent = Number.isFinite(uploadLimit)
      ? `ZIP archive · up to ${uploadLimit} MB · immutable upload`
      : "Drop a .zip here or browse your files · upload limit depends on server policy";
    $("#versionTag").textContent = `v${state.capabilities?.version || "0.1"}`;
  }

  async function connect(rawToken) {
    state.token = rawToken.trim();
    if (!state.token) throw new Error("Enter an API token to connect.");
    state.capabilities = await request("/api/v1/capabilities");
    state.endpoint = await request("/api/v1/system/endpoint");
    $("#loginScreen").hidden = true;
    $("#tokenInput").value = "";
    $("#workspace").hidden = false;
    fillToolchains();
    fillAgentSetup();
    await refreshAll();
    state.refreshTimer = window.setInterval(() => refreshAll(), 7000);
  }

  function disconnect() {
    state.token = "";
    state.capabilities = null;
    state.queue = null;
    state.builds = [];
    state.endpoint = null;
    state.selectedBuild = null;
    window.clearInterval(state.refreshTimer);
    $("#workspace").hidden = true;
    $("#loginScreen").hidden = false;
    $("#tokenInput").value = "";
    setError($("#loginError"), "");
    $("#tokenInput").focus();
  }

  async function refreshAll() {
    if (!state.token || state.refreshBusy) return;
    state.refreshBusy = true;
    try {
      const [queue, builds, endpoint] = await Promise.all([
        request("/api/v1/queue"),
        request("/api/v1/builds?offset=0&limit=50"),
        request("/api/v1/system/endpoint"),
      ]);
      state.queue = queue;
      state.builds = builds;
      state.endpoint = endpoint;
      renderQueue();
      renderBuildLists();
      fillAgentSetup();
      await refreshHealth();
      if (state.selectedBuild) await updateBuildDetail(state.selectedBuild, false);
      $("#lastUpdated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    } catch (error) {
      if (error.status === 401) {
        toast("This API token has been revoked. Connect with a valid token.", "error");
        disconnect();
      } else {
        $("#serverState").textContent = "API unavailable";
        $("#serverIndicator").classList.add("indicator-error");
        toast(error.message || "Could not refresh server data.", "error");
      }
    } finally {
      state.refreshBusy = false;
    }
  }

  async function refreshHealth() {
    let ready = false;
    try {
      const response = await fetch("/ready", { cache: "no-store" });
      const payload = await response.json();
      ready = response.ok && payload.ready === true;
    } catch (_) {
      ready = false;
    }
    const chip = $("#healthChip");
    const indicator = $("#serverIndicator");
    chip.className = `status-chip ${ready ? "status-live" : "status-unknown"}`;
    chip.innerHTML = `<span class="live-dot"></span>${ready ? "Ready" : "Degraded"}`;
    indicator.classList.toggle("indicator-error", !ready);
    $("#serverState").textContent = ready ? "Ready to build" : "Check Docker / storage";
    $("#healthTitle").textContent = ready ? "All systems operational" : "Service needs attention";
    $("#healthText").textContent = ready ? "The API is responding and the worker runtime is available." : "The API is reachable, but readiness failed. Run ./gmc doctor on the server.";
  }

  function renderQueue() {
    const queue = state.queue || {};
    $("#metricQueued").textContent = String(queue.queued ?? "—");
    $("#metricQueueNote").textContent = queue.queued === 0 ? "No jobs waiting" : "Waiting for a worker slot";
    $("#metricActive").textContent = String(queue.active ?? "—");
    $("#metricCapacity").textContent = `${queue.active ?? 0} of ${queue.max_workers ?? 0} worker slots in use`;
    $("#metricWorkers").textContent = String(queue.available_workers ?? "—");
    $("#metricStorage").textContent = formatBytes(queue.disk_free_bytes);
    const running = (queue.active || 0) > 0;
    $("#serverIndicator").classList.toggle("indicator-busy", running);
  }

  function buildRow(job, compact = false) {
    const id = escapeHtml(job.id);
    const shortId = escapeHtml((job.id || "").slice(0, 8));
    const task = escapeHtml(taskNames(job));
    const status = escapeHtml(stateLabel(job.state));
    const created = escapeHtml(formatDate(job.created));
    const duration = escapeHtml(formatDuration(job));
    if (compact) {
      return `<button class="build-list-row" data-build-id="${id}"><span class="build-row-icon ${statusClass(job.state)}"><svg viewBox="0 0 24 24" fill="none"><path d="m12 3 9 5v8l-9 5-9-5V8l9-5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="m3.5 8.5 8.5 5 8.5-5M12 13.5V21" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg></span><span class="build-row-copy"><strong>${task}</strong><span>#${shortId} · ${created}</span></span><span class="status-badge ${statusClass(job.state)}">${status}</span><span class="row-chevron">›</span></button>`;
    }
    return `<tr class="build-table-row" data-build-id="${id}"><td><span class="job-id"><span class="job-mark">G</span><span><strong>#${shortId}</strong><small>${created}</small></span></span></td><td><span class="status-badge ${statusClass(job.state)}">${status}</span></td><td class="task-cell">${task}</td><td>${created}</td><td>${duration}</td><td><button class="icon-button row-open" data-build-id="${id}" aria-label="View build ${shortId}">→</button></td></tr>`;
  }

  function renderBuildLists() {
    const builds = state.builds || [];
    const activeCount = builds.filter((job) => !terminalStates.has(job.state)).length;
    $("#buildCount").textContent = String(activeCount);
    const recent = builds.slice(0, 6);
    $("#recentBuilds").innerHTML = recent.length
      ? recent.map((job) => buildRow(job, true)).join("")
      : `<div class="empty-state"><span class="empty-mark">+</span><strong>No builds yet</strong><span>Submit a ZIP to start your first isolated build.</span><button class="text-button" data-goto="compile">Create a build →</button></div>`;
    const filter = $("#stateFilter")?.value || "all";
    const filtered = builds.filter((job) => filter === "all"
      || (filter === "active" ? activeStates.has(job.state) : job.state === filter)
      || (filter === "queued" && job.state === "queued"));
    $("#buildListCount").textContent = `${filtered.length} job${filtered.length === 1 ? "" : "s"}`;
    $("#buildTable").innerHTML = filtered.length
      ? filtered.map((job) => buildRow(job)).join("")
      : `<tr><td colspan="6" class="empty-cell">No builds match this filter.</td></tr>`;
  }

  function showPage(page) {
    state.page = page;
    $$(".page-view").forEach((element) => { element.hidden = element.id !== `page-${page}`; });
    $$(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.page === page));
    const labels = { overview: "Overview", builds: "Builds", compile: "Compile project", agent: "Agent setup" };
    $("#pageHeading").textContent = labels[page] || "Workspace";
    $("#sidebar").classList.remove("sidebar-open");
    if (page === "builds") renderBuildLists();
    if (page === "agent") fillAgentSetup();
  }

  async function updateBuildDetail(buildId, show = true) {
    if (show) {
      state.selectedBuild = buildId;
      showPage("builds");
      $("#buildDetail").hidden = false;
      $("#detailTitle").textContent = `Build #${buildId.slice(0, 8)}`;
      $("#detailLogs").textContent = "Loading build details…";
      $("#detailArtifacts").replaceChildren();
      $("#buildDetail").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    const job = await request(`/api/v1/builds/${encodeURIComponent(buildId)}`);
    const execution = job.execution || {};
    $("#detailTitle").textContent = `Build #${job.id.slice(0, 8)}`;
    $("#detailMeta").innerHTML = `<span class="status-badge ${statusClass(job.state)}">${escapeHtml(stateLabel(job.state))}</span><span><small>Task</small><strong>${escapeHtml((execution.tasks || ["build"]).join(", "))}</strong></span><span><small>Created</small><strong>${escapeHtml(formatDate(job.created))}</strong></span><span><small>Duration</small><strong>${escapeHtml(formatDuration(job))}</strong></span><span><small>Toolchain</small><strong>${escapeHtml(execution.toolchain || "Auto")}</strong></span>`;
    const diagnostic = $("#detailDiagnostic");
    if (job.diagnostic && Object.keys(job.diagnostic).length) {
      diagnostic.hidden = false;
      diagnostic.innerHTML = `<strong>${escapeHtml(job.diagnostic.code || "Build diagnostic")}</strong><p>${escapeHtml(job.diagnostic.message || "Check the build logs.")}</p>${job.diagnostic.remediation ? `<small>${escapeHtml(job.diagnostic.remediation)}</small>` : ""}`;
    } else {
      diagnostic.hidden = true;
      diagnostic.textContent = "";
    }
    const actions = $("#detailActions");
    actions.innerHTML = activeStates.has(job.state) || job.state === "queued"
      ? `<button class="button button-danger small-button" id="cancelBuild">Cancel build</button><span class="muted">Cancellation is a request; wait for a terminal state.</span>`
      : `<span class="muted">${terminalStates.has(job.state) ? "Build is complete." : "Build is processing."}</span>`;
    const logs = await request(`/api/v1/builds/${encodeURIComponent(buildId)}/logs?offset=0&limit=65536`);
    $("#detailLogs").textContent = logs.text || (job.state === "queued" ? "This job is queued. Logs will appear when a worker starts." : "No log output yet.");
    const artifacts = await request(`/api/v1/builds/${encodeURIComponent(buildId)}/artifacts`);
    const list = $("#detailArtifacts");
    if (!artifacts.length) {
      list.innerHTML = `<span class="muted">No artifacts available for this build.</span>`;
    } else {
      list.innerHTML = artifacts.map((artifact) => `<div class="artifact-row"><span class="artifact-file"><span class="file-icon">↗</span><span><strong>${escapeHtml(artifact.path)}</strong><small>${escapeHtml(formatBytes(artifact.size))} · SHA-256 ${escapeHtml((artifact.sha256 || "").slice(0, 12))}…</small></span></span><button class="button button-quiet small-button" data-artifact-job="${escapeHtml(job.id)}" data-artifact-id="${escapeHtml(artifact.id)}">Download</button></div>`).join("");
    }
    const cancelButton = $("#cancelBuild");
    if (cancelButton) {
      cancelButton.addEventListener("click", async () => {
        cancelButton.disabled = true;
        try {
          await request(`/api/v1/builds/${encodeURIComponent(buildId)}/cancel`, { method: "POST" });
          toast("Cancellation requested. The job will update when termination is confirmed.");
          await refreshAll();
        } catch (error) { toast(error.message, "error"); }
      }, { once: true });
    }
  }

  async function downloadArtifact(jobId, artifactId, button) {
    button.disabled = true;
    try {
      const response = await fetch(`/api/v1/builds/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}`, {
        headers: { Authorization: `Bearer ${state.token}` }, cache: "no-store",
      });
      if (!response.ok) throw new Error(`Download failed (HTTP ${response.status}).`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      let downloadName = filename?.[1] ? decodeURIComponent(filename[1]) : (filename?.[2] || artifactId);
      downloadName = downloadName.replaceAll("/", "_").replaceAll("\\", "_").replaceAll("\0", "_");
      link.href = url;
      link.download = downloadName;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Artifact download started.");
    } catch (error) { toast(error.message, "error"); }
    finally { button.disabled = false; }
  }

  async function submitBuild(event) {
    event.preventDefault();
    const errorElement = $("#compileError");
    setError(errorElement, "");
    const button = $("#submitBuild");
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner spinner-light"></span> Preparing build…`;
    try {
      const file = $("#projectZip").files[0];
      let projectId = $("#projectId").value.trim();
      if (file) {
        if (!file.name.toLowerCase().endsWith(".zip")) throw new Error("Choose a .zip archive.");
        const limitMb = Number(state.capabilities?.limits?.upload_mb);
        if (Number.isFinite(limitMb) && file.size > limitMb * 1024 ** 2) {
          throw new Error(`This ZIP exceeds the server upload limit of ${limitMb} MB.`);
        }
        const upload = await request("/api/v1/projects", {
          method: "POST",
          headers: { "Content-Type": "application/zip" },
          body: await file.arrayBuffer(),
        });
        projectId = upload.project_id;
        $("#projectId").value = projectId;
        toast(`Project uploaded · ${projectId.slice(0, 8)}`);
      }
      if (!projectId) throw new Error("Choose a project ZIP or enter an existing project ID.");
      const tasks = $("#tasksInput").value.split(",").map((task) => task.trim()).filter(Boolean);
      if (!tasks.length) throw new Error("Enter at least one Gradle task, for example build.");
      const requestBody = {
        project_id: projectId,
        tasks,
        subdirectory: $("#subdirectoryInput").value.trim() || ".",
        artifact_patterns: $("#artifactsInput").value.split(",").map((pattern) => pattern.trim()).filter(Boolean),
        idempotency_key: `ui-${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`}`,
      };
      const toolchain = $("#toolchainSelect").value;
      if (toolchain) requestBody.toolchain = toolchain;
      await request("/api/v1/projects/compatibility", { method: "POST", body: requestBody });
      const job = await request("/api/v1/builds", { method: "POST", body: requestBody });
      toast("Build accepted and added to the queue.");
      await refreshAll();
      await updateBuildDetail(job.id, true);
    } catch (error) {
      setError(errorElement, error.message || "Could not submit this build.");
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const input = document.createElement("textarea");
    input.value = value;
    input.className = "clipboard-helper";
    document.body.append(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("Clipboard access is unavailable in this browser.");
  }

  function setupEvents() {
    $("#loginEndpoint").textContent = `Server: ${window.location.origin}`;
    $("#loginForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $("#connectButton");
      const token = $("#tokenInput").value;
      setError($("#loginError"), "");
      button.disabled = true;
      button.querySelector("span").textContent = "Connecting…";
      try { await connect(token); }
      catch (error) { state.token = ""; setError($("#loginError"), error.message || "Could not connect to this server."); }
      finally { button.disabled = false; button.querySelector("span").textContent = "Connect workspace"; }
    });
    $("#revealToken").addEventListener("click", () => {
      const input = $("#tokenInput");
      input.type = input.type === "password" ? "text" : "password";
      $("#revealToken").setAttribute("aria-label", input.type === "password" ? "Show token" : "Hide token");
    });
    $$(".nav-item").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
    $$('[data-goto]').forEach((button) => button.addEventListener("click", () => showPage(button.dataset.goto)));
    $("#refreshButton").addEventListener("click", refreshAll);
    $("#topRefresh").addEventListener("click", refreshAll);
    $("#buildRefresh").addEventListener("click", refreshAll);
    $("#stateFilter").addEventListener("change", renderBuildLists);
    $("#compileForm").addEventListener("submit", submitBuild);
    $("#logoutButton").addEventListener("click", disconnect);
    $("#topLogout").addEventListener("click", disconnect);
    $("#menuButton").addEventListener("click", () => $("#sidebar").classList.toggle("sidebar-open"));
    $("#closeDetail").addEventListener("click", () => { $("#buildDetail").hidden = true; state.selectedBuild = null; });
    $("#refreshLogs").addEventListener("click", () => state.selectedBuild && updateBuildDetail(state.selectedBuild, false));
    $("#projectZip").addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (file) {
        $("#fileName").textContent = file.name;
        const limitMb = Number(state.capabilities?.limits?.upload_mb);
        const tooLarge = Number.isFinite(limitMb) && file.size > limitMb * 1024 ** 2;
        $("#fileHint").textContent = tooLarge
          ? `${formatBytes(file.size)} · exceeds the ${limitMb} MB server limit`
          : `${formatBytes(file.size)} · Ready to upload`;
        $("#uploadDrop").classList.add("has-file");
      }
    });
    $("#uploadDrop").addEventListener("dragover", (event) => { event.preventDefault(); $("#uploadDrop").classList.add("dragging"); });
    $("#uploadDrop").addEventListener("dragleave", () => $("#uploadDrop").classList.remove("dragging"));
    $("#uploadDrop").addEventListener("drop", (event) => {
      event.preventDefault();
      $("#uploadDrop").classList.remove("dragging");
      const file = event.dataTransfer.files[0];
      if (file) {
        const input = $("#projectZip");
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    document.addEventListener("click", async (event) => {
      const copyButton = event.target.closest("[data-copy]");
      if (copyButton) {
        try { await copyText($("#" + copyButton.dataset.copy).textContent); toast("Copied to clipboard."); }
        catch (error) { toast(error.message, "error"); }
      }
      const jobElement = event.target.closest("[data-build-id]");
      if (jobElement) {
        const buildId = jobElement.dataset.buildId;
        try { await updateBuildDetail(buildId, true); }
        catch (error) { toast(error.message, "error"); }
      }
      const artifactButton = event.target.closest("[data-artifact-id]");
      if (artifactButton) downloadArtifact(artifactButton.dataset.artifactJob, artifactButton.dataset.artifactId, artifactButton);
    });
    $("#copyMcpConfig").addEventListener("click", async () => {
      try { await copyText($("#mcpConfigSnippet").textContent); toast("Client configuration copied."); }
      catch (error) { toast(error.message, "error"); }
    });
    $("#copyCurl").addEventListener("click", async () => {
      try { await copyText($("#curlSnippet").textContent); toast("cURL example copied."); }
      catch (error) { toast(error.message, "error"); }
    });
    $("#copyEndpoints").addEventListener("click", async () => {
      const value = endpoints();
      try { await copyText(`MCP: ${value.mcp}\nREST: ${value.rest}\nOpenAPI: ${value.openapi}`); toast("Endpoint details copied."); }
      catch (error) { toast(error.message, "error"); }
    });
  }

  setupEvents();
  $("#tokenInput").focus();
})();
