// Gom toàn bộ DOM reference vào một object để các handler bên dưới không phải query lặp lại nhiều lần
const els = {
  nodesInput: document.querySelector("#nodesInput"),
  resourcesInput: document.querySelector("#resourcesInput"),
  mInput: document.querySelector("#mInput"),
  seedInput: document.querySelector("#seedInput"),
  replicationInput: document.querySelector("#replicationInput"),
  initializeBtn: document.querySelector("#initializeBtn"),
  resourceInput: document.querySelector("#resourceInput"),
  startNodeInput: document.querySelector("#startNodeInput"),
  lookupBtn: document.querySelector("#lookupBtn"),
  lookupOutput: document.querySelector("#lookupOutput"),
  failedNodesInput: document.querySelector("#failedNodesInput"),
  killBtn: document.querySelector("#killBtn"),
  addNodeBtn: document.querySelector("#addNodeBtn"),
  addResourceBtn: document.querySelector("#addResourceBtn"),
  selectedNodeActions: document.querySelector("#selectedNodeActions"),
  selectedNodeSummary: document.querySelector("#selectedNodeSummary"),
  nodeRemovalReport: document.querySelector("#nodeRemovalReport"),
  metricLookupsInput: document.querySelector("#metricLookupsInput"),
  metricTrialsInput: document.querySelector("#metricTrialsInput"),
  metricsBtn: document.querySelector("#metricsBtn"),
  metricsOutput: document.querySelector("#metricsOutput"),
  metricsSweepCharts: document.querySelector("#metricsSweepCharts"),
  metricsSweepChartsPlaceholder: document.querySelector("#metricsSweepCharts .chart-placeholder"),
  hopsChartSweep: document.querySelector("#hopsChartSweep"),
  hopsChartSweepOutput: document.querySelector("#hopsChartSweepOutput"),
  metricsCharts: [
    document.querySelector("#metricsHopsChart"),
    document.querySelector("#metricsLatencyChart"),
    document.querySelector("#metricsOverheadChart"),
  ],
  metricsTracePanel: document.querySelector("#metricsTracePanel"),
  metricsTraceBody: document.querySelector("#metricsTraceBody"),
  metricsTraceClose: document.querySelector("#metricsTraceClose"),
  resourceInfoPanel: document.querySelector("#resourceInfoPanel"),
  resourceInfoBody: document.querySelector("#resourceInfoBody"),
  resourceInfoClose: document.querySelector("#resourceInfoClose"),
  topologyExpandBtn: document.querySelector("#topologyExpandBtn"),
  topologyCloseBtn: document.querySelector("#topologyCloseBtn"),
  topologyOutput: document.querySelector("#topologyOutput"),
  topologyFrame: document.querySelector("#topologyFrame"),
  topologyChart: document.querySelector("#topologyChart"),
  topologyPlaceholder: document.querySelector("#topologyFrame .chart-placeholder"),
  topologyModal: document.querySelector("#topologyModal"),
  topologyModalImage: document.querySelector("#topologyModalImage"),
  formModal: document.querySelector("#formModal"),
  formModalTitle: document.querySelector("#formModalTitle"),
  formModalFields: document.querySelector("#formModalFields"),
  formModalCancelBtn: document.querySelector("#formModalCancelBtn"),
  formModalSubmitBtn: document.querySelector("#formModalSubmitBtn"),
  statusNodes: document.querySelector("#statusNodes"),
  statusResources: document.querySelector("#statusResources"),
  statusReplicas: document.querySelector("#statusReplicas"),
  statusSpace: document.querySelector("#statusSpace"),
  nodesOutput: document.querySelector("#nodesOutput"),
  resourcesOutput: document.querySelector("#resourcesOutput"),
  resourcesCountLabel: document.querySelector("#resourcesCountLabel"),
  resourceScopeLabel: document.querySelector("#resourceScopeLabel"),
  resourceTableFilter: document.querySelector("#resourceTableFilter"),
  fingerOutput: document.querySelector("#fingerOutput"),
  nodeList: document.querySelector("#nodeList"),
  toast: document.querySelector("#toast"),
  showPrimaryBtn: document.querySelector("#showPrimaryBtn"),
  showReplicaBtn: document.querySelector("#showReplicaBtn"),
  appLoading: null,
  appLoadingStatus: null,
};

const fingerPlaceholder = `
  <tr>
    <td colspan="4" class="empty-cell">Select a node to view its finger table.</td>
  </tr>
`;

// Thoát dữ liệu nhận từ API trước khi nhúng vào HTML để tránh lỗi hiển thị và tránh chèn HTML ngoài ý muốn
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Hiển thị thông báo ngắn để phản hồi trạng thái thao tác của người dùng
function showToast(message) {
  if (window.toastTimer) {
    window.clearTimeout(window.toastTimer);
  }
  els.toast.textContent = message;
  els.toast.classList.add("show");
  window.toastTimer = window.setTimeout(() => els.toast.classList.remove("show"), 3200);
}

// Gọi API dùng chung cho GET/POST/PUT/DELETE. Nếu backend trả lỗi, hàm ném exception để các handler hiển thị lỗi thống nhất
async function api(path, payload, method = "POST") {
  const hasPayload = payload !== undefined;
  const response = await fetch(path, {
    method: hasPayload ? method : "GET",
    headers: hasPayload ? { "Content-Type": "application/json" } : {},
    body: hasPayload ? JSON.stringify(payload) : undefined,
  });
  const contentType = response.headers.get("content-type") || "";
  const bodyText = await response.text();
  let data;
  if (contentType.includes("application/json")) {
    try {
      data = bodyText ? JSON.parse(bodyText) : {};
    } catch (error) {
      throw new Error("Server returned invalid JSON.");
    }
  } else {
    const looksLikeHtml = bodyText.trim().toLowerCase().startsWith("<!doctype");
    if (looksLikeHtml) {
      throw new Error("API returned HTML instead of JSON. Run the app with `py -3.10 app.py` and open http://127.0.0.1:5000/.");
    }
    throw new Error(bodyText || `Request failed with status ${response.status}.`);
  }
  if (!response.ok || !data.ok) {
    throw new Error(data.message || "Request failed.");
  }
  return data;
}

// Khóa nút trong lúc request đang chạy để người dùng không gửi trùng thao tác
function setBusy(button, busy, label) {
  if (!button) {
    return;
  }
  if (busy) {
    if (!button.dataset.label) {
      button.dataset.label = button.textContent;
    }
    button.textContent = label || button.dataset.label;
    button.disabled = true;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
  } else {
    button.disabled = false;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    if (button.dataset.label) {
      button.textContent = button.dataset.label;
    }
  }
}

let modalSubmitHandler = null;

// Mở biểu mẫu modal dùng chung để nhập tham số thao tác CRUD hoặc join node
function openFormModal(title, fields, submitLabel, onSubmit) {
  els.formModalTitle.textContent = title;
  els.formModalFields.innerHTML = fields
    .map(
      (field) => `
        <label>
          ${escapeHtml(field.label)}
          <input
            id="${escapeHtml(field.id)}"
            type="${escapeHtml(field.type || "text")}"
            value="${escapeHtml(field.value || "")}"
            placeholder="${escapeHtml(field.placeholder || "")}"
            ${field.readonly ? "readonly" : ""}
            ${field.required ? "required" : ""}
          />
        </label>
      `,
    )
    .join("");
  els.formModalSubmitBtn.textContent = submitLabel;
  modalSubmitHandler = async () => {
    const values = {};
    fields.forEach((field) => {
      const input = document.querySelector(`#${field.id}`);
      values[field.id] = input.value.trim();
      if (field.required && values[field.id] === "") {
        input.focus();
        throw new Error(`${field.label} is required.`);
      }
    });
    await onSubmit(values);
  };
  els.formModal.classList.add("is-open");
  els.formModal.setAttribute("aria-hidden", "false");
  const firstInput = els.formModalFields.querySelector("input:not([readonly])");
  if (firstInput) {
    firstInput.focus();
  }
}

// Đóng biểu mẫu modal và xóa handler của lần nhập đã hoàn thành
function closeFormModal() {
  els.formModal.classList.remove("is-open");
  els.formModal.setAttribute("aria-hidden", "true");
  els.formModalFields.innerHTML = "";
  modalSubmitHandler = null;
  setBusy(els.formModalSubmitBtn, false);
}

// Gửi dữ liệu modal sau khi kiểm tra trường bắt buộc và hiển thị lỗi thống nhất
async function submitFormModal() {
  if (!modalSubmitHandler || els.formModalSubmitBtn.disabled) {
    return;
  }
  setBusy(els.formModalSubmitBtn, true, "Saving...");
  try {
    await modalSubmitHandler();
    closeFormModal();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(els.formModalSubmitBtn, false);
  }
}

// Cập nhật metrics và topology tuần tự để tránh matplotlib lỗi khi hai request song song và tránh race trên nút Run Metrics / Topology
async function refreshArtifacts() {
  const activeNodes = Number(currentActiveNodeCount) || 0;
  if (activeNodes > 60) {
    if (els.metricsOutput) {
      els.metricsOutput.textContent = "";
    }
    if (els.topologyOutput) {
      els.topologyOutput.textContent = "Auto topology skipped for large rings. Click Generate Topology Graph when needed.";
    }
    els.topologyFrame.classList.remove("loading");
    if (els.topologyPlaceholder) {
      els.topologyPlaceholder.textContent = "";
      els.topologyPlaceholder.hidden = true;
    }
    setMetricChartsLoading("Metrics charts are available on demand.");
    return;
  }

  if (els.metricsOutput) {
    els.metricsOutput.textContent = "";
  }
  if (els.topologyOutput) {
    els.topologyOutput.textContent = "Generating topology graph...";
  }
  els.topologyFrame.classList.add("is-ready");
  els.topologyFrame.classList.add("loading");
  try {
    await generateTopology(true);
  } catch (error) {
    showToast(error.message || "Topology generation failed.");
  }
  setMetricChartsLoading("Click Run Metrics to generate strict protocol metrics.");
}

// Lưu snapshot hiển thị phía client được đồng bộ từ coordinator khi cần
let cachedResourceRows = [];
let resourceTotalCount = 0;
let selectedNodeId = null;
let selectedResourceId = null;
let currentActiveNodeCount = Number(els.nodesInput.value) || 10;
let currentActiveNodes = [];
let currentSites = [];
let artifactGeneration = 0;
let showPrimaryOnly = true;
let showReplicaOnly = true;

// Ghi nhận chế độ single-process không dùng metadata site riêng cho từng node
function nodeSite(nodeId) {
  const numericId = Number(nodeId);
  const site = currentSites.find((s) => Number(s.node_id) === numericId);
  const isStopped = site ? site.active === false : false;
  return { nodeId: numericId, status: isStopped ? "Stopped" : "Running" };
}

// Xác định owner của resource được chọn để đánh dấu node trên vòng hiển thị
function selectedResourceOwnerId() {
  if (selectedResourceId === null) {
    return null;
  }
  const selectedResource = cachedResourceRows.find((row) => row.resource_id === selectedResourceId);
  return selectedResource ? Number(selectedResource.owner_id) : null;
}

// Lọc bảng resource theo node và chuỗi tìm kiếm
function applyResourceTableFilter() {
  const q = (els.resourceTableFilter?.value || "").trim().toLowerCase();
  const nodeFilteredRows =
    selectedNodeId === null
      ? cachedResourceRows
      : cachedResourceRows.filter(
          (item) =>
            Number(item.owner_id) === Number(selectedNodeId) ||
            (Array.isArray(item.replica_node_ids) &&
              item.replica_node_ids.map(Number).includes(Number(selectedNodeId))),
        );
  const scopeFilteredRows = nodeFilteredRows.filter((item) => {
    if (selectedNodeId === null) return true;
    const isPrimary = Number(item.owner_id) === Number(selectedNodeId);
    const isReplica =
      Array.isArray(item.replica_node_ids) &&
      item.replica_node_ids.map(Number).includes(Number(selectedNodeId));
    if (showPrimaryOnly && isPrimary) return true;
    if (showReplicaOnly && isReplica) return true;
    return false;
  });
  const searchedRows = !q
    ? scopeFilteredRows
    : scopeFilteredRows.filter((item) => {
        const replicas = Array.isArray(item.replica_node_ids) ? item.replica_node_ids.join(" ") : "";
        const hay = `${item.resource_id} ${item.key} ${item.owner_id} ${replicas}`.toLowerCase();
        return hay.includes(q);
      });
  const renderResourceRow = (item) => {
    const replicas = Array.isArray(item.replica_node_ids) ? item.replica_node_ids.join(", ") : "";
    const hash = item.hashed_resource_id || "";
        return `
      <tr class="resource-row ${item.resource_id === selectedResourceId ? "is-selected" : ""}" data-resource-id="${escapeHtml(item.resource_id)}">
        <td class="col-resource-id">${escapeHtml(item.resource_id)}</td>
        <td class="col-hashed hashed-resource"><code>${escapeHtml(hash)}</code></td>
        <td class="col-key"><code>${escapeHtml(item.key)}</code></td>
        <td class="col-owner"><code>${escapeHtml(item.owner_id)}</code></td>
        <td class="col-replicas" title="${escapeHtml(replicas || "-")}"><span class="resource-replicas">${escapeHtml(replicas || "-")}</span></td>
        <td class="col-action">
          <button type="button" class="delete-resource-btn danger" data-resource-id="${escapeHtml(item.resource_id)}" title="Delete resource">Delete</button>
        </td>
      </tr>
    `;
  };
  els.resourcesOutput.innerHTML = searchedRows.length
    ? searchedRows.map(renderResourceRow).join("")
    : `<tr><td colspan="6" class="empty-cell">No resources match the current filter.</td></tr>`;
  els.resourcesOutput.querySelectorAll(".resource-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest(".delete-resource-btn")) return;
      selectResource(row.dataset.resourceId);
    });
  });
  els.resourcesOutput.querySelectorAll(".delete-resource-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteResourceFromTable(btn.dataset.resourceId, btn);
    });
  });
  if (els.resourcesCountLabel) {
    const total = resourceTotalCount;
    els.resourcesCountLabel.textContent = !q
      ? total ? `(${searchedRows.length} / ${total})` : "(0)"
      : `(${searchedRows.length} match / ${total} in ring)`;
  }
  updateResourceSelection();
}

// Cập nhật chi tiết node đang chọn (single-process friendly)
function updateNodeSelection() {
  const resourceOwnerId = selectedResourceOwnerId();
  document.querySelectorAll("#nodesOutput .node-pill").forEach((button) => {
    const nodeId = Number(button.dataset.nodeId);
    button.classList.toggle("is-selected", nodeId === Number(selectedNodeId));
    button.classList.toggle(
      "is-resource-owner",
      resourceOwnerId !== null && nodeId === resourceOwnerId,
    );
  });

  if (els.selectedNodeActions) {
    els.selectedNodeActions.hidden = selectedNodeId === null;
  }

  if (els.killBtn) {
    els.killBtn.hidden = selectedNodeId === null || nodeSite(selectedNodeId).status !== "Running";
  }

  if (els.selectedNodeSummary) {
    els.selectedNodeSummary.hidden = true;
    els.selectedNodeSummary.innerHTML = "";
  }

  if (els.addResourceBtn) {
    els.addResourceBtn.disabled = false;
    els.addResourceBtn.title = "Add a resource to the ring";
  }
  if (els.resourceScopeLabel) {
    els.resourceScopeLabel.textContent =
      selectedNodeId === null ? "All Resources" : `Resources on Node ${selectedNodeId}`;
  }
}

// Hiển thị lại toàn bộ resource khi người dùng bỏ bộ lọc theo node
function showAllResources() {
  selectedNodeId = null;
  selectedResourceId = null;
  if (els.resourceTableFilter) {
    els.resourceTableFilter.value = "";
  }
  els.fingerOutput.innerHTML = fingerPlaceholder;
  updateNodeSelection();
  applyResourceTableFilter();
}

// Hiển thị primary và replica thuộc node được chọn từ snapshot coordinator
function showResourcesForNode(nodeId) {
  const nextNodeId = Number(nodeId);
  if (selectedNodeId === nextNodeId) {
    showAllResources();
    return;
  }
  selectedNodeId = nextNodeId;
  selectedResourceId = null;
  if (els.resourceTableFilter) {
    els.resourceTableFilter.value = "";
  }
  updateNodeSelection();
  applyResourceTableFilter();
  if (nodeSite(selectedNodeId).status === "Running") {
    loadFingerPreview(selectedNodeId).catch((error) => showToast(error.message));
  } else {
    els.fingerOutput.innerHTML = fingerPlaceholder;
  }
}

// Đánh dấu dòng resource đang được người dùng chọn trong bảng dữ liệu
function updateResourceSelection() {
  document.querySelectorAll("#resourcesOutput .resource-row").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.resourceId === selectedResourceId);
  });
}

// Đọc một giá trị metric với fallback ổn định cho kết quả chưa đầy đủ
function metricValue(point, field, fallback = "0") {
  return point[field] === undefined || point[field] === null ? fallback : point[field];
}

// Chuẩn hóa giá trị metric số để tránh hiển thị NaN trong bảng báo cáo
function finiteMetricNumber(value, fallback = 0) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}


function formatNumber(val) {
  if (val === null || val === undefined) return "--";
  return String(val);
}

function normalizeLogText(log) {
  return String(log)
    .replace(/^\[?\d+\]?[\s:]+/, "")
    .replace(/\(resource '([^']+)'\) via HTTP\/REST via Flask API\.?/g, "$1")
    .replace(/\((resource-[^)]+)\)\.?/g, "$1")
    .trim();
}

function visibleHopLogs(logs) {
  return (Array.isArray(logs) ? logs : []).filter(
    (log) => !/Routing:\s*forwarded from node/i.test(String(log)),
  );
}

function logNodeLabel(text) {
  const match =
    text.match(/-> node\s+(\d+)/i) ||
    text.match(/successor\s+\[(\d+)\]/i);
  return match ? `<code class="finger-tag">${escapeHtml(match[1])}</code>` : "";
}

function renderMetricTrace(point) {
  if (!point) {
    return "<div class=\"trace-empty\">No details available.</div>";
  }

  const trace = point?.max_lookup_trace || point;

  const n = Number(point.nodes ?? trace.nodes ?? 0);
  const avgHops = finiteMetricNumber(point.average_hops ?? trace.hops ?? 0);
  const log2N = n > 0 ? Math.log2(n).toFixed(3) : "0.000";
  const latency = finiteMetricNumber(point.average_latency_ms ?? 0);
  const totalLookups = finiteMetricNumber(point.total_lookups ?? point.attempted_lookups ?? 0);
  const success = finiteMetricNumber(point.successful_lookups ?? 0);
  const failed = finiteMetricNumber(point.failed_lookups ?? 0);
  const msgOverhead = finiteMetricNumber(point.message_overhead ?? avgHops * totalLookups);
  const msgsPerLookup = finiteMetricNumber(point.messages_per_lookup ?? 0);
  const traceHops = finiteMetricNumber(trace.hops ?? 0);
  const path = Array.isArray(trace.path) ? trace.path : [];
  const routeHopCount = Math.max(0, path.length - 1);
  const key = trace.key ?? "--";
  const ownerId = trace.owner_id ?? "--";

  const routeHTML = path.length
    ? path.map((nodeId, i) => {
        const num = formatNumber(nodeId);
        const arrow = i < path.length - 1
          ? `<span class="route-arrow"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg></span>`
          : "";
        const cls = i === 0 ? "route-pill--start" : i === path.length - 1 ? "route-pill--end" : "route-pill--mid";
        const badge = i === 0
          ? '<span class="route-pill__badge route-pill__badge--start">Start</span>'
          : i === path.length - 1
          ? '<span class="route-pill__badge route-pill__badge--end">Owner</span>'
          : `<span class="route-pill__badge">Hop ${i + 1}</span>`;
        return `<span class="route-pill ${cls}"><span class="route-pill__node">${num}</span>${badge}${arrow}</span>`;
      }).join("")
    : "";

  const logs = visibleHopLogs(trace.logs);
  const logRowsHTML = logs.map((l, i) => {
    const step = i + 1;
    const text = normalizeLogText(l);
    const isMiss = /not found|does not store/i.test(text);
    const rowClass = isMiss ? "lookup-log-row lookup-log-row--miss" : "lookup-log-row";
    const nodeLabel = logNodeLabel(text);
    return `<tr class="${rowClass}">
      <td class="lookup-log-cell lookup-log-cell--step"><span class="step-badge">${step}</span></td>
      <td class="lookup-log-cell lookup-log-cell--text">${escapeHtml(text)}</td>
      <td class="lookup-log-cell lookup-log-cell--finger">${nodeLabel}</td>
    </tr>`;
  }).join("");

  return `
    <div class="lookup-result">
      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Metric Point Details
        </h4>
        <div class="lookup-summary-table-wrap">
          <table class="lookup-summary-table">
            <thead>
              <tr>
                <th>N</th>
                <th>Avg Hops</th>
                <th>log2(N)</th>
                <th>Latency (ms)</th>
                <th>Total Lookups</th>
                <th>Success</th>
                <th>Failed</th>
                <th>Msg Overhead</th>
                <th>Msgs/Lookup</th>
                <th>Trace Hops</th>
                <th>Route Nodes</th>
                <th>Key</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              <tr class="lookup-result-row">
                <td><code class="val-primary">${formatNumber(n)}</code></td>
                <td><code>${avgHops}</code></td>
                <td><code>${log2N}</code></td>
                <td><code>${latency}</code></td>
                <td><code>${formatNumber(totalLookups)}</code></td>
                <td><code>${formatNumber(success)}</code></td>
                <td><code>${formatNumber(failed)}</code></td>
                <td><code>${formatNumber(msgOverhead)}</code></td>
                <td><code>${msgsPerLookup}</code></td>
                <td><code>${traceHops}</code></td>
                <td><code>${path.length}</code></td>
                <td><code>${formatNumber(key)}</code></td>
                <td><code>${formatNumber(ownerId)}</code></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Hop-by-Hop Logs <span class="lookup-section__count">(${logs.length} step${logs.length !== 1 ? "s" : ""})</span>
        </h4>
        <div class="lookup-log-table-wrap">
          <table class="lookup-log-table">
            <thead>
              <tr>
                <th class="lookup-log-th--step">#</th>
                <th class="lookup-log-th--text">Action / Reason</th>
                <th class="lookup-log-th--finger">Node</th>
              </tr>
            </thead>
            <tbody>
              ${logRowsHTML || `<tr><td colspan="3" class="lookup-log-empty">No hop logs.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>

      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Lookup Route <span class="lookup-section__count">(${routeHopCount} hop${routeHopCount !== 1 ? "s" : ""})</span>
        </h4>
        <div class="lookup-route-track">${routeHTML || "<span class=\"muted\">No route.</span>"}</div>
      </div>
    </div>
  `;
}

function openMetricsTrace(pointIndex) {
  if (!els.metricsTracePanel || !els.metricsTraceBody || !els.hopsChartSweep) return;
  let points = [];
  try { points = JSON.parse(els.hopsChartSweep.dataset.points || "[]"); } catch { points = []; }
  const point = points[pointIndex];
  els.metricsTraceBody.innerHTML = renderMetricTrace(point);
  els.metricsTracePanel.hidden = false;
}

function closeMetricsTrace() {
  if (!els.metricsTracePanel) return;
  els.metricsTracePanel.hidden = true;
  if (els.metricsTraceBody) els.metricsTraceBody.innerHTML = "";
}

function showResourceInfoOverlay(resource, trace = {}) {
  if (!els.resourceInfoPanel || !els.resourceInfoBody || !resource) return;
  const replicas = Array.isArray(resource.replica_node_ids) && resource.replica_node_ids.length
    ? resource.replica_node_ids.map((id) => `<code>${escapeHtml(id)}</code>`).join(", ")
    : '<span class="muted">None</span>';
  els.resourceInfoBody.innerHTML = `
    <div class="resource-info-grid">
      <div><span>Resource ID</span><code>${escapeHtml(resource.resource_id)}</code></div>
      <div><span>Hashed</span><code>${escapeHtml(resource.hashed_resource_id || "")}</code></div>
      <div><span>Key</span><code>${formatNumber(resource.key)}</code></div>
      <div><span>Owner</span><code>${formatNumber(resource.owner_id)}</code></div>
      <div><span>Replicas</span><div class="resource-info-replicas">${replicas}</div></div>
    </div>
  `;
  els.resourceInfoPanel.hidden = false;
}

function closeResourceInfoOverlay() {
  if (!els.resourceInfoPanel) return;
  els.resourceInfoPanel.hidden = true;
  if (els.resourceInfoBody) els.resourceInfoBody.innerHTML = "";
}

// Đặt vùng ảnh về trạng thái chờ trong lúc backend dựng artifact mới
function setImageLoading(image, placeholder, loadingText) {
  if (placeholder) {
    placeholder.textContent = loadingText;
    placeholder.hidden = false;
  }
  if (!image) {
    return;
  }
  image.removeAttribute("src");
  image.style.display = "none";
}

// Xóa artifact cũ sau khi deployment mới thay đổi topology hoặc dữ liệu
function clearGeneratedArtifacts() {
  artifactGeneration += 1;
  setMetricChartsLoading("Run metrics to generate new charts.");
  setImageLoading(els.topologyChart, els.topologyPlaceholder, "Generate topology graph to render the current network.");
  if (els.topologyOutput) {
    els.topologyOutput.textContent = "";
  }
  els.topologyFrame.classList.remove("is-ready", "loading");
  if (els.metricsSweepCharts) {
    els.metricsSweepCharts.hidden = true;
  }
  if (els.hopsChartSweep) {
    els.hopsChartSweep.hidden = true;
    if (els.hopsChartSweepOutput) {
      els.hopsChartSweepOutput.innerHTML = "";
    }
  }
}

// Gắn ảnh artifact đúng phiên bản để tránh kết quả request cũ ghi đè UI
function setImageReady(image, placeholder, src, generation = artifactGeneration) {
  image.onload = () => {
    if (generation !== artifactGeneration) {
      return;
    }
    if (placeholder) {
      placeholder.hidden = true;
    }
    image.style.display = "block";
  };
  image.onerror = () => {
    if (generation !== artifactGeneration) {
      return;
    }
    if (placeholder) {
      placeholder.textContent = "Image could not be loaded.";
      placeholder.hidden = false;
    }
    image.style.display = "none";
  };
  if (generation === artifactGeneration) {
    image.src = src;
  }
}

// Hiển thị topology được tổng hợp từ local state của các endpoint đang sống
function renderTopologyArtifact(topology, generation = artifactGeneration) {
  if (!topology || !topology.report || !topology.chart_url) {
    return false;
  }
  const report = topology.report || {};
  const nodeCount = Number(report.node_count);
  const failedCount = Number(report.failed_node_count);
  const safeNodeCount = Number.isFinite(nodeCount) ? nodeCount : 0;
  const safeFailedCount = Number.isFinite(failedCount) ? failedCount : 0;
  const safeFingerEdges = Number.isFinite(Number(report.finger_edges)) ? Number(report.finger_edges) : 0;
  const safePathEdges = Number.isFinite(Number(report.path_edges)) ? Number(report.path_edges) : 0;

  els.topologyFrame.classList.add("is-ready");
  els.topologyFrame.classList.remove("loading");

  // Hiển thị tóm tắt topology đè trên ảnh đồ thị

  // Giữ vùng output cũ rỗng để tránh trùng nội dung UI
  if (els.topologyOutput) {
    els.topologyOutput.innerHTML = "";
  }

  setImageReady(els.topologyChart, els.topologyPlaceholder, topology.chart_url, generation);
  return true;
}

// Đặt các biểu đồ metric về trạng thái chờ khi đang chạy lookup đo lường
function setMetricChartsLoading(loadingText) {
  if (els.metricsSweepChartsPlaceholder) {
    els.metricsSweepChartsPlaceholder.textContent = loadingText;
    els.metricsSweepChartsPlaceholder.hidden = false;
  }
  if (els.metricsSweepCharts) {
    els.metricsSweepCharts.hidden = false;
  }
  if (!Array.isArray(els.metricsCharts) || els.metricsCharts.length === 0) {
    return;
  }
  els.metricsCharts.forEach((image) => {
    if (!image) return;
    image.onload = null;
    image.onerror = null;
    image.removeAttribute("src");
    image.style.display = "none";
  });
}

// Hiển thị các biểu đồ metric đúng phiên bản deployment hiện tại
function setMetricChartsReady(chartUrls, generation = artifactGeneration) {
  const urls = [
    chartUrls?.hops,
    chartUrls?.latency,
    chartUrls?.overhead,
  ];

  if (els.metricsSweepChartsPlaceholder) {
    els.metricsSweepChartsPlaceholder.hidden = true;
  }

  if (els.metricsSweepCharts) {
    els.metricsSweepCharts.hidden = false;
  }

  if (!Array.isArray(els.metricsCharts) || els.metricsCharts.length === 0) {
    return;
  }

  els.metricsCharts.forEach((image, index) => {
    if (!image) return;
    const url = urls[index];

    if (!url) {
      image.removeAttribute("src");
      image.style.display = "none";
      return;
    }

    // Gắn handler trước khi đặt src để bắt kịp ảnh đã cache
    image.onload = () => {
      if (generation !== artifactGeneration) return;
      image.style.display = "block";
    };
    image.onerror = () => {
      if (generation !== artifactGeneration) return;
      image.style.display = "none";
    };

    // Đặt src sau cùng để handler sẵn sàng cho mọi kết quả tải ảnh
    if (generation === artifactGeneration) {
      image.src = url;
    }
  });
}

// Xóa báo cáo failure cũ khi topology mới được khởi tạo hoặc thay đổi
function clearNodeRemovalReport() {
  if (!els.nodeRemovalReport) {
    return;
  }
  els.nodeRemovalReport.hidden = true;
  els.nodeRemovalReport.innerHTML = "";
}

// Hiển thị kết quả stop process và phục hồi dữ liệu từ replica JSON còn sống
function renderNodeRemovalReport(report) {
  if (!els.nodeRemovalReport) {
    return;
  }
  const killedNode = String(report.killed_node_id ?? "");
  const oldPredecessor = String(report.old_predecessor ?? "none");
  const oldSuccessor = String(report.old_successor ?? "none");
  const activeNodes = Number(report.active_nodes ?? 0);
  const configuredReplicas = Number(report.replication_count ?? 0);
  const effectiveReplicas = Number(report.effective_replica_count ?? 0);

  // Primary resources owned by killed node — recovered from its replica copies
  const recoveredCount = Number(report.recovered_resource_total_count ?? 0);
  const recoveredSamples = Array.isArray(report.recovered_resource_ids) ? report.recovered_resource_ids : [];

  // Resources that only stored a replica on killed node — rebuild replica elsewhere
  const replicaRepairedCount = Number(report.replica_repaired_resource_total_count ?? 0);
  const replicaRepairedSamples = Array.isArray(report.replica_repaired_resource_ids)
    ? report.replica_repaired_resource_ids
    : [];

  // Liệt kê resource không còn replica để phục hồi
  const lostCount = Number(report.lost_resource_total_count ?? 0);
  const lostSamples = Array.isArray(report.lost_resource_ids) ? report.lost_resource_ids : [];

  // Hiển thị thống kê sửa finger table từ backend
  const updatedFingerTables = Number(report.updated_finger_tables ?? 0);
  const updatedFingerEntries = Number(report.updated_finger_entries ?? 0);

  // Rút gọn danh sách resource bằng hậu tố +N khi bị cắt
  const sampleList = (items, emptyText, totalCount = items.length) => {
    if (!items.length) {
      return `<div class="kill-resource-empty">${escapeHtml(emptyText)}</div>`;
    }
    const shown = items.map((item) => `<span>${escapeHtml(item)}</span>`).join("");
    const remaining = Math.max(0, Number(totalCount || 0) - items.length);
    const more = remaining > 0 ? `<span class="kill-resource-more">... +${remaining} more</span>` : "";
    return `<div class="kill-resource-samples">${shown}${more}</div>`;
  };

  // Chọn màu badge tóm tắt theo kết quả phục hồi
  const totalLost = lostCount;
  const summaryStatus = totalLost === 0
    ? '<span class="kill-status-badge kill-status-ok">All resources safe</span>'
    : `<span class="kill-status-badge kill-status-warn">${totalLost} resource(s) lost</span>`;

  els.nodeRemovalReport.innerHTML = `
    <div class="kill-report-header">
      <div>
        <h3>Node Recovery Report</h3>
        <p>Node <strong>${killedNode}</strong> has been marked as stopped. The Chord system automatically repairs ring links and recovers data from surviving replica copies.</p>
      </div>
      <div class="kill-report-header-actions">
        <span>${activeNodes} active node(s)</span>
        <button type="button" class="kill-report-toggle" aria-expanded="true">Collapse</button>
      </div>
    </div>
    <div class="kill-report-body">
      <div class="kill-summary-table-wrap">
        <table class="kill-summary-table">
          <thead>
            <tr>
              <th>Stopped Node</th>
              <th>Old Predecessor</th>
              <th>Old Successor</th>
              <th>Status</th>
              <th>Primary Recovered</th>
              <th>Replica Restored</th>
              <th>Data Loss</th>
              <th>Finger Tables Fixed</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code class="stopped-node-text">${killedNode}</code></td>
              <td><code>${oldPredecessor}</code></td>
              <td><code>${oldSuccessor}</code></td>
              <td>${summaryStatus}</td>
              <td><code>${recoveredCount}</code></td>
              <td><code>${replicaRepairedCount}</code></td>
              <td><code>${lostCount}</code></td>
              <td><code>${updatedFingerTables} tables / ${updatedFingerEntries} entries</code></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="kill-recovery-note">
        <strong>Replica policy:</strong>
        Configured ${configuredReplicas} replica copies. Effective ${effectiveReplicas}
        (each resource can only be copied to active nodes other than its owner).
      </div>
      <ol class="kill-timeline">
        <li>
          <strong>1. Mark node as stopped</strong>
          <span>Node ${killedNode} is set to <em>active = false</em>, added to <em>failed_nodes</em>, and all its successor / predecessor / finger table entries are cleared so it no longer participates in routing.</span>
        </li>
        <li>
          <strong>2. Reconnect the Chord ring</strong>
          <span>Old predecessor (${oldPredecessor}) and old successor (${oldSuccessor}) are linked directly: predecessor.successor = successor and successor.predecessor = predecessor. The circular ring is closed without scanning the entire network.</span>
        </li>
        <li>
          <strong>3. Fix stale finger table entries</strong>
          <span>${updatedFingerTables > 0
            ? `${updatedFingerTables} node(s) had ${updatedFingerEntries} finger entries pointing to node ${killedNode} (no longer valid). These entries are updated by finding a new valid successor through local Chord lookup.`
            : `No finger table entries pointed directly to node ${killedNode} (or the predecessor/successor reconnection automatically covered them).`
          }</span>
        </li>
        <li>
          <strong>4. Classify resources affected by the stopped node</strong>
          <span>The system scans all resources and separates them into 3 groups: (a) resources where node ${killedNode} is the owner — need promote from replica; (b) resources where node ${killedNode} is only a replica — need to remove dead replica and rebuild; (c) unrelated resources.</span>
        </li>
        <li>
          <strong>5. Promote primary resources from replicas</strong>
          ${recoveredCount > 0
            ? `<span>${recoveredCount} resources owned by node ${killedNode} are recovered: the latest value is read from the nearest surviving replica (by successor order), assigned a new owner, and copied to the next ${effectiveReplicas} successor nodes.</span>
               ${sampleList(recoveredSamples, "No primary resource samples.", recoveredCount)}`
            : `<span>No resources were promoted — all resources of node ${killedNode} either have surviving replicas, or no replicas are available.</span>`
          }
        </li>
        <li>
          <strong>6. Restore replica placement</strong>
          ${replicaRepairedCount > 0
            ? `<span>${replicaRepairedCount} resources had node ${killedNode} as a replica only — the dead replica is removed and a new replica is created on the nearest valid successor.</span>
               ${sampleList(replicaRepairedSamples, "No replica resource samples.", replicaRepairedCount)}`
            : `<span>No resources needed replica restoration — no resources had a replica on node ${killedNode}.</span>`
          }
        </li>
        <li class="${lostCount > 0 ? "kill-step-warning" : ""}">
          <strong>7. Report data loss</strong>
          ${lostCount > 0
            ? `<span>${lostCount} resources were lost completely — no surviving replica is available to recover from. Cause: replication_count is too low relative to the number of consecutively failed nodes.</span>
               ${sampleList(lostSamples, "No lost resource samples.", lostCount)}`
            : `<span>No resources were lost — every resource has at least one surviving replica.</span>`
          }
        </li>
      </ol>
    </div>
  `;
  els.nodeRemovalReport.hidden = false;
  const toggleButton = els.nodeRemovalReport.querySelector(".kill-report-toggle");
  if (toggleButton) {
    toggleButton.addEventListener("click", () => {
      const collapsed = els.nodeRemovalReport.classList.toggle("is-collapsed");
      toggleButton.textContent = collapsed ? "Expand" : "Collapse";
      toggleButton.setAttribute("aria-expanded", String(!collapsed));
    });
  }
}

// Đồng bộ bảng resource từ snapshot hiển thị, không sử dụng snapshot để định tuyến
async function syncResourcesForRingTable(state) {
  resourceTotalCount = Number(state.resource_count) || 0;
  const embedded = Array.isArray(state.sample_resources) ? state.sample_resources : [];

  if (resourceTotalCount === 0) {
    cachedResourceRows = [];
    selectedResourceId = null;
    if (els.resourceTableFilter) {
      els.resourceTableFilter.value = "";
    }
    updateNodeSelection();
    applyResourceTableFilter();
    return;
  }

  if (embedded.length === resourceTotalCount) {
    cachedResourceRows = embedded.slice();
  } else {
    try {
      const data = await api("/api/resources");
      cachedResourceRows = Array.isArray(data.resources) ? data.resources : [];
    } catch (error) {
      cachedResourceRows = embedded.slice();
      showToast(error.message || "Could not load full resource list.");
    }
  }

  if (selectedResourceId !== null && !cachedResourceRows.some((row) => row.resource_id === selectedResourceId)) {
    selectedResourceId = null;
  }
  updateNodeSelection();
  applyResourceTableFilter();
}

// Tải snapshot deployment hiện tại khi mở trang hoặc sau khi có thao tác thay đổi
async function loadState() {
  const data = await api("/api/state");
  renderState(data.state);
}

// Hiển thị số node, resource mẫu, danh sách node active và preview Finger Table
function renderState(state) {
  currentActiveNodeCount = Number(state.active_node_count) || 0;
  currentActiveNodes = Array.isArray(state.active_nodes) ? state.active_nodes.map(Number) : [];
  if (Array.isArray(state.nodes) && state.nodes.length) {
    currentSites = state.nodes;
  } else {
    currentSites = currentActiveNodes.map((nodeId) => ({ node_id: nodeId, active: true }));
  }
  els.statusNodes.textContent = state.active_node_count;
  els.statusResources.textContent = state.resource_count;
  els.statusReplicas.textContent = state.replication_count || 0;
  els.statusSpace.textContent = `2^${state.m || 16}`;
  els.failedNodesInput.value = Array.isArray(state.failed_nodes) ? state.failed_nodes.length : 0;

  if (els.addNodeBtn) {
    els.addNodeBtn.disabled = false;
    els.addNodeBtn.title = "";
  }

  els.nodeList.innerHTML = currentSites
    .map((node) => `<option value="${escapeHtml(node.node_id)}"></option>`)
    .join("");

  const sortedSites = currentSites.slice().sort((a, b) => Number(a.node_id) - Number(b.node_id));
  const failedSet = new Set(Array.isArray(state.failed_nodes) ? state.failed_nodes.map(Number) : []);
  els.nodesOutput.innerHTML = sortedSites
    .map((node) => {
      const nodeId = Number(node.node_id);
      const isStopped = failedSet.has(nodeId) || node.active === false;
      return `<button type="button" class="node-pill ${isStopped ? "is-stopped" : ""}" data-node-id="${escapeHtml(nodeId)}">
          <span>${escapeHtml(nodeId)}</span>
        </button>`;
    })
    .join("");

  els.nodesOutput.querySelectorAll(".node-pill").forEach((button) => {
    button.addEventListener("click", () => showResourcesForNode(button.dataset.nodeId));
  });

  if (selectedNodeId !== null && !currentSites.some((site) => Number(site.node_id) === Number(selectedNodeId))) {
    selectedNodeId = null;
  }
  updateNodeSelection();

  void syncResourcesForRingTable(state);

  if (selectedNodeId === null) {
    els.fingerOutput.innerHTML = fingerPlaceholder;
  } else if (nodeSite(selectedNodeId).status === "Running") {
    loadFingerPreview(selectedNodeId).catch((error) => showToast(error.message));
  }
}

// Đọc Finger Table và láng giềng trực tiếp từ endpoint của node đang chọn
async function loadFingerPreview(nodeId) {
  const data = await api(`/api/node/${nodeId}`);
  els.fingerOutput.innerHTML = data.node.finger_table
    .map(
      (entry) => `
        <tr>
          <td>${escapeHtml(entry.index)}</td>
          <td>${escapeHtml(entry.start)}</td>
          <td>${escapeHtml(entry.interval_end)}</td>
          <td>${escapeHtml(entry.node_id)}</td>
        </tr>
      `,
    )
    .join("");
  const predecessor = data.node.predecessor || {};
  const successor = data.node.successor || {};
  const detail = els.selectedNodeSummary.querySelector(".local-view-loading");
  if (detail) {
    detail.outerHTML = `
      <div class="neighbor-grid">
        <button type="button" class="neighbor-card neighbor-card--link" data-node-id="${escapeHtml(predecessor.node_id ?? "--")}">
          <span>Predecessor</span><strong>${escapeHtml(predecessor.node_id ?? "--")}</strong>
        </button>
        <div class="neighbor-card neighbor-card--current">
          <span>Current</span><strong>${escapeHtml(nodeId)}</strong>
        </div>
        <button type="button" class="neighbor-card neighbor-card--link" data-node-id="${escapeHtml(successor.node_id ?? "--")}">
          <span>Successor</span><strong>${escapeHtml(successor.node_id ?? "--")}</strong>
        </button>
      </div>
    `;
    els.selectedNodeSummary.querySelectorAll(".neighbor-card[data-node-id]").forEach((button) => {
      if (button.dataset.nodeId !== "--") {
        button.addEventListener("click", () => showResourcesForNode(button.dataset.nodeId));
      }
    });
  }
}

// Gửi cấu hình lên backend để tạo lại mạng Chord từ đầu
async function initializeNetwork() {
  const nodeCount = Number(els.nodesInput.value);
  // Ghi nhận chế độ single-process không cần base port hoặc storage dir
  setBusy(els.initializeBtn, true, "Initializing...");
  try {
    const data = await api("/api/initialize", {
      nodes: nodeCount,
      resources: Number(els.resourcesInput.value),
      m: Number(els.mInput.value),
      seed: Number(els.seedInput.value),
      replication_count: Number(els.replicationInput.value),
    });
    selectedNodeId = null;
    selectedResourceId = null;
    if (els.resourceTableFilter) {
      els.resourceTableFilter.value = "";
    }
    clearNodeRemovalReport();
    clearGeneratedArtifacts();
    renderState(data.state);
    els.lookupOutput.classList.remove("lookup-output--missing");
    els.lookupOutput.innerHTML = "";
    showToast(data.message);
    void generateTopology(true, false);
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(els.initializeBtn, false);
  }
}

function renderLookupResult(result) {
  const path = Array.isArray(result.path) ? result.path : [];
  const routeHopCount = Math.max(0, path.length - 1);
  const foundClass = result.found ? "" : " lookup-result-row--miss";
  const latency = result.latency_ms != null ? result.latency_ms : 0;

  const replicas = Array.isArray(result.replica_node_ids) && result.replica_node_ids.length
    ? result.replica_node_ids.map((id) => `<code>${escapeHtml(id)}</code>`).join(", ")
    : '<span class="muted">None</span>';

  // ── Lookup Route pills ─────────────────────────────────────────────────────
  const routeHTML = path.map((nodeId, i) => {
    const n = formatNumber(nodeId);
    const arrow =
      i < path.length - 1
        ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>`
        : "";
    const badge =
      i === 0
        ? '<span class="route-pill__badge route-pill__badge--start">Start</span>'
        : i === path.length - 1
        ? '<span class="route-pill__badge route-pill__badge--end">Owner</span>'
        : `<span class="route-pill__badge">Hop ${i + 1}</span>`;
    return `<span class="route-pill route-pill--${i === 0 ? "start" : i === path.length - 1 ? "end" : "mid"}"><span class="route-pill__node">${n}</span>${badge}${arrow}</span>`;
  }).join("");

  // ── Hop-by-Hop Logs ───────────────────────────────────────────────────────
  const logs = visibleHopLogs(result.logs);

  // Chuẩn hóa tiền tố log trước khi hiển thị trong bảng
  const logRowsHTML = logs.map((l, i) => {
    const step = i + 1;
    const text = normalizeLogText(l);
    const isMiss = /not found|does not store/i.test(text);
    const rowClass = isMiss ? "lookup-log-row lookup-log-row--miss" : "lookup-log-row";

    const nodeLabel = logNodeLabel(text);

    return `<tr class="${rowClass}">
      <td class="lookup-log-cell lookup-log-cell--step"><span class="step-badge">${step}</span></td>
      <td class="lookup-log-cell lookup-log-cell--text">${escapeHtml(text)}</td>
      <td class="lookup-log-cell lookup-log-cell--finger">${nodeLabel}</td>
    </tr>`;
  }).join("");

  return `
    <div class="lookup-result">
      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Lookup Summary
        </h4>
        <div class="lookup-summary-table-wrap">
          <table class="lookup-summary-table">
            <thead>
              <tr>
                <th>Owner</th>
                <th>Requested Key</th>
                <th>Found</th>
                <th>Replicas</th>
                <th>Hops</th>
                <th>Route</th>
                <th>Latency (ms)</th>
              </tr>
            </thead>
            <tbody>
              <tr class="lookup-result-row${foundClass}">
                <td><code class="val-primary">${formatNumber(result.owner_id)}</code></td>
                <td><code>${formatNumber(result.key)}</code></td>
                <td><span class="val-found ${result.found ? "val-found--yes" : "val-found--no"}">${result.found ? "Yes" : "No"}</span></td>
                <td class="val-replicas">${replicas}</td>
                <td><code>${escapeHtml(result.hops)}</code></td>
                <td><code>${path.length} nodes</code></td>
                <td><code>${typeof latency === "number" ? latency.toFixed(3) : latency}</code></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Hop-by-Hop Logs <span class="lookup-section__count">(${logs.length} step${logs.length !== 1 ? "s" : ""})</span>
        </h4>
        <div class="lookup-log-table-wrap">
          <table class="lookup-log-table">
            <thead>
              <tr>
                <th class="lookup-log-th--step">#</th>
                <th class="lookup-log-th--text">Action / Reason</th>
                <th class="lookup-log-th--finger">Node</th>
              </tr>
            </thead>
            <tbody>
              ${logRowsHTML || `<tr><td colspan="3" class="lookup-log-empty">No hop logs.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>

      <div class="lookup-section">
        <h4 class="lookup-section__title">
          Lookup Route <span class="lookup-section__count">(${routeHopCount} hop${routeHopCount !== 1 ? "s" : ""})</span>
        </h4>
        <div class="lookup-route-track">${routeHTML || "<span class=\"muted\">No route.</span>"}</div>
      </div>
    </div>
  `;
}

// Gọi lookup resource/key và hiển thị owner, hop count, path và log từng hop
async function lookupResource() {
  setBusy(els.lookupBtn, true, "Looking up...");
  els.lookupOutput.textContent = "Running lookup...";
  try {
    const startNodeValue = els.startNodeInput.value.trim();
    const lookupStartedAt = performance.now();
    const data = await api("/api/lookup", {
      resource_id: els.resourceInput.value.trim(),
      start_node_id: startNodeValue === "" ? null : Number(startNodeValue),
    });
    const lookupElapsedMs = Math.round((performance.now() - lookupStartedAt) * 1000) / 1000;
    const result = data.result;
    result.latency_ms = result.latency_ms ?? lookupElapsedMs;
    els.lookupOutput.classList.remove("lookup-output--missing");
    els.lookupOutput.innerHTML = renderLookupResult(result);
    await generateTopology(true, true, Array.isArray(result.path) ? result.path : null);
    showToast(data.message);
  } catch (error) {
    els.lookupOutput.classList.add("lookup-output--missing");
    els.lookupOutput.textContent = error.message;
    showToast(error.message);
  } finally {
    setBusy(els.lookupBtn, false);
  }
}

// Dừng một process node để kích hoạt stabilize và recovery qua các endpoint còn sống
async function killNode() {
  if (selectedNodeId === null) {
    showToast("Select a node first.");
    return;
  }
  const nodeToKill = selectedNodeId;
  if (
    !window.confirm(
      `Stop node ${nodeToKill}?\n\nIt will be marked as stopped (red). Remaining nodes will stabilize and recover from replicas.`,
    )
  ) {
    return;
  }
  setBusy(els.killBtn, true, "Stopping...");
  try {
    const data = await api("/api/kill", {
      node_id: Number(nodeToKill),
    });
    selectedNodeId = Number(nodeToKill);
    renderState(data.state);
    updateNodeSelection();
    renderNodeRemovalReport(data.report);
    // Only refresh topology after kill — do NOT auto-run metrics
    await generateTopology(true);
    showToast(data.message);
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(els.killBtn, false);
  }
}


// Làm mới snapshot và artifact sau thao tác join hoặc CRUD
async function refreshAfterChange(state, { rebuildArtifacts = false } = {}) {
  renderState(state);
  if (rebuildArtifacts) {
    await refreshArtifacts();
  }
}

// Khởi chạy node mới tại một port trống rồi cho node join thông qua bootstrap
async function addNode() {
  if (currentActiveNodeCount >= 100) {
    showToast("Distributed deployment is limited to 100 active sites.");
    return;
  }
  openFormModal(
    "Join Node",
    [{ id: "nodeIdField", label: "Node ID", type: "number", placeholder: "Auto if empty" }],
    "Join",
    async ({ nodeIdField }) => {
      const nodeIdValue = nodeIdField.trim();
      const data = await api("/api/node", {
        node_id: nodeIdValue === "" ? null : Number(nodeIdValue),
      });
      selectedNodeId = Number(data.report.node_id);
      clearNodeRemovalReport();
      await refreshAfterChange(data.state, { rebuildArtifacts: true });
      showToast(`${data.message} Node: ${data.report.node_id}.`);
    },
  );
}


// Ghi resource mới qua entry node để Chord định tuyến tới primary owner
async function addResource() {
  openFormModal(
    "Add Resource",
    [{ id: "resourceIdField", label: "Resource ID", type: "text", placeholder: "resource-new", required: true }],
    "Add",
    async ({ resourceIdField }) => {
      const data = await api("/api/resource", {
        resource_id: resourceIdField.trim(),
      });
      const resource = data.resource;
      selectedNodeId = null;
      selectedResourceId = resource?.resource_id ?? resourceIdField.trim();
      await refreshAfterChange(data.state);
      showResourceInfoOverlay(resource, data.trace);
      showToast(`${data.message} Owner: ${resource?.owner_id ?? "--"}.`);
    },
  );
}

// Đổi định danh resource bằng delete và put được định tuyến phân tán
async function updateResource() {
  if (selectedResourceId === null) {
    showToast("Select a resource first.");
    return;
  }
  openFormModal(
    "Edit Resource",
    [
      { id: "oldResourceIdField", label: "Current ID", type: "text", value: selectedResourceId, readonly: true },
      { id: "newResourceIdField", label: "New ID", type: "text", value: selectedResourceId, required: true },
    ],
    "Update",
    async ({ oldResourceIdField, newResourceIdField }) => {
      const data = await api(
        "/api/resource",
        {
          old_resource_id: oldResourceIdField.trim(),
          new_resource_id: newResourceIdField.trim(),
        },
        "PUT",
      );
      const resource = data.resource;
      selectedNodeId = Number(resource?.owner_id);
      selectedResourceId = resource?.resource_id ?? newResourceIdField.trim();
      await refreshAfterChange(data.state);
      showResourceInfoOverlay(resource, data.trace);
      showToast(`${data.message} Owner: ${resource?.owner_id ?? "--"}.`);
    },
  );
}

// Xóa resource tại owner và yêu cầu loại các replica liên quan qua HTTP
async function deleteResource(button = null) {
  if (selectedResourceId === null) {
    showToast("Select a resource first.");
    return;
  }
  if (!window.confirm(`Delete resource ${selectedResourceId}?`)) {
    return;
  }
  if (button) {
    setBusy(button, true, "Deleting...");
  }
  try {
    const data = await api(
      "/api/resource",
      {
        resource_id: selectedResourceId,
      },
      "DELETE",
    );
    selectedResourceId = null;
    await refreshAfterChange(data.state);
    showToast(data.message);
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) {
      setBusy(button, false);
    }
  }
}

// Chuẩn bị dữ liệu một dòng cho bảng hops_chart_sweep
function buildHopsSweepRow(point, index) {
  const rowIndex = index + 1;
  const n = Number(point.nodes ?? 0);
  const avgHops = finiteMetricNumber(metricValue(point, "average_hops", 0));
  const maxHops = finiteMetricNumber(metricValue(point, "max_hops", 0));
  const log2N = metricValue(point, "log2_nodes", n > 0 ? Math.log2(n).toFixed(3) : "0");
  const latency = finiteMetricNumber(metricValue(point, "average_latency_ms", 0));
  const totalLookups = finiteMetricNumber(metricValue(point, "total_lookups", metricValue(point, "attempted_lookups", 0)));
  const success = finiteMetricNumber(metricValue(point, "successful_lookups", 0));
  const failed = finiteMetricNumber(metricValue(point, "failed_lookups", 0));
  const msgOverhead = finiteMetricNumber(metricValue(point, "message_overhead", 0));
  const msgsPerLookup = finiteMetricNumber(metricValue(point, "messages_per_lookup", 0));

  return `
    <tr class="metrics-sweep-row" data-metrics-index="${index}">
      <td>${rowIndex}</td>
      <td>${n}</td>
      <td>${avgHops}</td>
      <td>${maxHops}</td>
      <td>${log2N}</td>
      <td>${latency}</td>
      <td>${totalLookups}</td>
      <td>${success} / ${failed}</td>
      <td>${msgOverhead}</td>
      <td>${msgsPerLookup}</td>
    </tr>
  `;
}

// Hiển thị toàn bộ hops_chart_sweep
function renderHopsChartSweep(sweepPoints) {
  if (!els.hopsChartSweep || !els.hopsChartSweepOutput) return;
  const maxRows = 50;
  const limited = sweepPoints.slice(0, maxRows);
  const rows = limited.map(buildHopsSweepRow).join("");
  els.hopsChartSweepOutput.innerHTML = rows || `<tr><td colspan="10" class="empty-cell">No data.</td></tr>`;
  els.hopsChartSweep.hidden = false;
  els.hopsChartSweep.dataset.points = JSON.stringify(sweepPoints || []);
  attachSweepRowClickHandlers();
}

function attachSweepRowClickHandlers() {
  if (!els.hopsChartSweepOutput) return;
  els.hopsChartSweepOutput.querySelectorAll(".metrics-sweep-row").forEach((row) => {
    row.addEventListener("click", () => {
      const idx = Number(row.dataset.metricsIndex);
      if (!Number.isFinite(idx)) return;
      openMetricsTrace(idx);
    });
  });
}


// Chạy benchmark đúng số node hiện tại và hiển thị bảng số liệu cùng ảnh biểu đồ matplotlib
async function runMetrics(silent = false) {
  const requestGeneration = artifactGeneration;
  setBusy(els.metricsBtn, true, "Running...");
  setMetricChartsLoading("Calculating metrics...");
  try {
    const data = await api("/api/metrics", {
      lookups: Number(els.metricLookupsInput.value),
      trials: Number(els.metricTrialsInput.value),
    });

    const sweepRows = Array.isArray(data.sweep_points) ? data.sweep_points : [];

    if (requestGeneration !== artifactGeneration) {
      return;
    }

    // Xóa vùng metrics cũ vì đã thay bằng bảng hops_chart_sweep
    if (els.metricsOutput) {
      els.metricsOutput.innerHTML = "";
    }

    setMetricChartsReady(
      {
        hops: data.charts?.hops || null,
        latency: data.charts?.latency || null,
        overhead: data.charts?.overhead || null,
      },
      requestGeneration,
    );

    renderHopsChartSweep(sweepRows);

    if (!silent) {
      showToast(data.message);
    }
  } catch (error) {
    if (els.metricsSweepChartsPlaceholder) {
      els.metricsSweepChartsPlaceholder.textContent = "Charts unavailable: " + error.message;
      els.metricsSweepChartsPlaceholder.hidden = false;
    }
    if (!silent) {
      showToast(error.message);
    }
  } finally {
    setBusy(els.metricsBtn, false);
  }
}

// Tạo topology graph từ snapshot node và chỉ highlight đường HTTP sau lookup
async function generateTopology(silent = false, includeLastPath = false, lookupPath = null) {
  const requestGeneration = artifactGeneration;
  if (!els.topologyFrame || !els.topologyChart) {
    return;
  }
  if (els.topologyOutput) {
    els.topologyOutput.textContent = "Generating topology graph...";
  }
  els.topologyFrame.classList.add("is-ready");
  els.topologyFrame.classList.add("loading");
  setImageLoading(els.topologyChart, els.topologyPlaceholder, "Generating topology graph...");
  try {
    const payload = { include_last_path: includeLastPath };
    if (includeLastPath && Array.isArray(lookupPath) && lookupPath.length) {
      payload.lookup_path = lookupPath;
    }
    const data = await api("/api/topology", payload);
    if (requestGeneration !== artifactGeneration) {
      return;
    }
    renderTopologyArtifact(data, requestGeneration);
    if (!silent) {
      showToast(data.message);
    }
  } catch (error) {
    if (els.topologyOutput) {
      els.topologyOutput.textContent = error.message;
    }
    els.topologyFrame.classList.remove("loading");
    if (els.topologyPlaceholder) {
      els.topologyPlaceholder.textContent = "Topology graph is unavailable.";
      els.topologyPlaceholder.hidden = false;
    }
    if (!silent) {
      showToast(error.message);
    }
  }
}

// Mở cửa sổ topology phóng lớn sau khi ảnh đồ thị đã được sinh
function openTopologyModal() {
  if (!els.topologyChart.src) {
    showToast("Generate topology first.");
    return;
  }
  els.topologyModalImage.src = els.topologyChart.src;
  els.topologyModal.classList.add("is-open");
  els.topologyModal.setAttribute("aria-hidden", "false");
}

// Đóng cửa sổ topology để trở lại bảng điều khiển chính
function closeTopologyModal() {
  els.topologyModal.classList.remove("is-open");
  els.topologyModal.setAttribute("aria-hidden", "true");
}

// Xóa resource trực tiếp từ bảng không cần chọn trước
async function deleteResourceFromTable(resourceId, button) {
  if (!resourceId) return;
  if (!window.confirm(`Delete resource ${resourceId}?`)) return;
  if (button) setBusy(button, true, "Deleting...");
  try {
    const data = await api(
      "/api/resource",
      { resource_id: resourceId },
      "DELETE",
    );
    selectedResourceId = null;
    await refreshAfterChange(data.state);
    showToast(data.message);
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) setBusy(button, false);
  }
}


// Chọn resource để highlight trong bảng mà không hiển thị modal
function selectResource(resourceId) {
  if (selectedResourceId === resourceId) {
    selectedResourceId = null;
  } else {
    selectedResourceId = resourceId;
  }
  applyResourceTableFilter();
  updateNodeSelection();
}

function bindClick(el, handler) {
  if (!el) {
    return;
  }
  el.addEventListener("click", handler);
}

bindClick(els.initializeBtn, initializeNetwork);
bindClick(els.lookupBtn, lookupResource);
bindClick(els.killBtn, killNode);
bindClick(els.addNodeBtn, addNode);
bindClick(els.addResourceBtn, addResource);
bindClick(els.metricsBtn, () => runMetrics(false));
bindClick(els.metricsTraceClose, closeMetricsTrace);
bindClick(els.resourceInfoClose, closeResourceInfoOverlay);
// Gắn sự kiện mở và đóng cửa sổ topology
bindClick(els.topologyExpandBtn, openTopologyModal);
bindClick(els.topologyCloseBtn, closeTopologyModal);
bindClick(els.formModalCancelBtn, closeFormModal);
bindClick(els.formModalSubmitBtn, submitFormModal);

if (els.formModal) {
  els.formModal.addEventListener("click", (event) => {
    if (event.target === els.formModal) {
      closeFormModal();
    }
  });
}

if (els.resourceInfoPanel) {
  els.resourceInfoPanel.addEventListener("click", (event) => {
    if (event.target === els.resourceInfoPanel) {
      closeResourceInfoOverlay();
    }
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (els.resourceInfoPanel && !els.resourceInfoPanel.hidden) {
      closeResourceInfoOverlay();
      return;
    }
    if (els.formModal && els.formModal.classList.contains("is-open")) {
      closeFormModal();
    }
  }
  if (event.key === "Enter" && els.formModal && els.formModal.classList.contains("is-open")) {
    event.preventDefault();
    void submitFormModal();
  }
});
if (els.topologyModal) {
  els.topologyModal.addEventListener("click", (event) => {
    if (event.target === els.topologyModal) {
      closeTopologyModal();
    }
  });
}
if (els.resourceTableFilter) {
  els.resourceTableFilter.addEventListener("input", applyResourceTableFilter);
}

// Gắn sự kiện bật tắt bộ lọc tài nguyên
if (els.showPrimaryBtn) {
  els.showPrimaryBtn.addEventListener("click", () => {
    showPrimaryOnly = !showPrimaryOnly;
    els.showPrimaryBtn.classList.toggle("active", showPrimaryOnly);
    applyResourceTableFilter();
  });
}
if (els.showReplicaBtn) {
  els.showReplicaBtn.addEventListener("click", () => {
    showReplicaOnly = !showReplicaOnly;
    els.showReplicaBtn.classList.toggle("active", showReplicaOnly);
    applyResourceTableFilter();
  });
}
// Tải snapshot ban đầu, sinh topology và khôi phục metrics đã lưu nếu còn khớp ring hiện tại No global loading overlay (use per-section loading only)
function setAppLoadingStatus(_msg) {}

function hideAppLoading() {}

function showAppLoading() {}

loadState()
  .then(async () => {
    clearGeneratedArtifacts();
    await generateTopology(true, false);

    // Tải metrics đã lưu và chỉ chạy metrics protocol đầy đủ khi người dùng bấm Run Metrics
    let usedPersistedMetrics = false;
    try {
      const last = await api("/api/metrics/last");
      const saved = last?.metrics;
      if (saved && Array.isArray(saved.sweep_points) && saved.sweep_points.length > 0) {
        const savedActiveNodes = Number(saved.active_nodes) || 0;
        const currentNodes = Number(currentActiveNodeCount) || 0;
        // Chỉ tái sử dụng metrics khi số node khớp với ring hiện tại
        if (savedActiveNodes === currentNodes && currentNodes > 0) {
          renderHopsChartSweep(saved.sweep_points);
          setMetricChartsReady(
            {
              hops: saved.charts?.hops || null,
              latency: saved.charts?.latency || null,
              overhead: saved.charts?.overhead || null,
            },
            artifactGeneration,
          );
          usedPersistedMetrics = true;
        } else {
          // Ring was resized — fall through to auto-run (no notification shown)
        }
      }
    } catch {
      // No persisted metrics yet — fall through to auto-run below
    }

    if (!usedPersistedMetrics) {
      if (els.metricsOutput) {
        els.metricsOutput.textContent = "";
      }
      setMetricChartsLoading("Click Run Metrics to generate strict protocol metrics.");
    }
  })
  .catch((error) => {
    showToast(error.message);
  });
