// Gom toàn bộ DOM reference vào một object để các handler bên dưới không phải
// query lặp lại nhiều lần
const els = {
  nodesInput: document.querySelector("#nodesInput"),
  resourcesInput: document.querySelector("#resourcesInput"),
  mInput: document.querySelector("#mInput"),
  seedInput: document.querySelector("#seedInput"),
  replicationInput: document.querySelector("#replicationInput"),
  basePortInput: document.querySelector("#basePortInput"),
  storageDirInput: document.querySelector("#storageDirInput"),
  initializeBtn: document.querySelector("#initializeBtn"),
  resourceInput: document.querySelector("#resourceInput"),
  startNodeInput: document.querySelector("#startNodeInput"),
  lookupBtn: document.querySelector("#lookupBtn"),
  lookupOutput: document.querySelector("#lookupOutput"),
  failedNodesInput: document.querySelector("#failedNodesInput"),
  killBtn: document.querySelector("#killBtn"),
  addNodeBtn: document.querySelector("#addNodeBtn"),
  restartNodeBtn: document.querySelector("#restartNodeBtn"),
  addResourceBtn: document.querySelector("#addResourceBtn"),
  selectedNodeActions: document.querySelector("#selectedNodeActions"),
  selectedNodeSummary: document.querySelector("#selectedNodeSummary"),
  nodeRemovalReport: document.querySelector("#nodeRemovalReport"),
  metricLookupsInput: document.querySelector("#metricLookupsInput"),
  metricTrialsInput: document.querySelector("#metricTrialsInput"),
  metricsBtn: document.querySelector("#metricsBtn"),
  metricsOutput: document.querySelector("#metricsOutput"),
  metricsCharts: [
    document.querySelector("#metricsHopsChart"),
    document.querySelector("#metricsLatencyChart"),
    document.querySelector("#metricsOverheadChart"),
  ],
  metricsChartPlaceholder: document.querySelector(".metrics-chart-shell .chart-placeholder"),
  topologyBtn: null,
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
  appLoading: document.querySelector("#appLoading"),
  appLoadingStatus: document.querySelector("#appLoadingStatus"),
};

const fingerPlaceholder = `
  <tr>
    <td colspan="4" class="empty-cell">Select a node to view its finger table.</td>
  </tr>
`;

// Thoát dữ liệu nhận từ API trước khi nhúng vào HTML để tránh lỗi hiển thị và
// tránh chèn HTML ngoài ý muốn
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

// Gọi API dùng chung cho GET/POST/PUT/DELETE. Nếu backend trả lỗi, hàm ném exception
// để các handler hiển thị lỗi thống nhất
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
  button.disabled = busy;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label;
  } else if (button.dataset.label) {
    button.textContent = button.dataset.label;
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

// Cập nhật metrics và topology tuần tự để tránh matplotlib lỗi khi hai request song song
// và tránh race trên nút Run Metrics / Topology
async function refreshArtifacts() {
  const activeNodes = Number(currentActiveNodeCount) || 0;
  if (activeNodes > 60) {
    els.metricsOutput.textContent = "Auto metrics skipped for large rings. Click Run Metrics when needed.";
    els.topologyOutput.textContent = "Auto topology skipped for large rings. Click Generate Topology Graph when needed.";
    els.topologyFrame.classList.remove("loading");
    if (els.topologyPlaceholder) {
      els.topologyPlaceholder.textContent = "";
      els.topologyPlaceholder.hidden = true;
    }
    setMetricChartsLoading("Metrics charts are available on demand.");
    return;
  }

  els.metricsOutput.textContent = "Updating average hops...";
  els.topologyOutput.textContent = "Generating topology graph...";
  els.topologyFrame.classList.add("is-ready");
  els.topologyFrame.classList.add("loading");
  try {
    await generateTopology(true);
  } catch (error) {
    showToast(error.message || "Topology generation failed.");
  }
  try {
    await runMetrics(true);
  } catch (error) {
    showToast(error.message || "Metrics generation failed.");
  }
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

// Single-process: no per-node site metadata.
function nodeSite(nodeId) {
  return { nodeId: Number(nodeId), status: "Running" };
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
    return `
      <tr class="resource-row ${item.resource_id === selectedResourceId ? "is-selected" : ""}" data-resource-id="${escapeHtml(item.resource_id)}">
        <td>${escapeHtml(item.resource_id)}</td>
        <td>${escapeHtml(item.key)}</td>
        <td><code>${escapeHtml(item.owner_id)}</code></td>
        <td class="resource-replicas">${escapeHtml(replicas || "-")}</td>
        <td>
          <button type="button" class="delete-resource-btn danger" data-resource-id="${escapeHtml(item.resource_id)}" title="Delete resource">Delete</button>
        </td>
      </tr>
    `;
  };
  els.resourcesOutput.innerHTML = searchedRows.length
    ? searchedRows.map(renderResourceRow).join("")
    : `<tr><td colspan="5" class="empty-cell">No resources match the current filter.</td></tr>`;
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

  // Restart is a distributed-process control; hide in single-process mode.
  if (els.restartNodeBtn) {
    els.restartNodeBtn.hidden = true;
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
  closeResourceDetailModal();
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
  closeResourceDetailModal();
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

// Chuẩn hóa điểm đo HTTP lookup thành định dạng chung của các card thống kê
function normalizeMetricPoint(point) {
  const totalLookups = finiteMetricNumber(metricValue(point, "attempted_lookups", metricValue(point, "total_lookups", 0)));
  const averageHops = finiteMetricNumber(metricValue(point, "average_hops", 0));
  const messageOverhead = finiteMetricNumber(
    metricValue(point, "message_overhead", Math.round(averageHops * totalLookups)),
  );
  const successfulLookups = finiteMetricNumber(metricValue(point, "successful_lookups", totalLookups));
  const failedLookups = finiteMetricNumber(metricValue(point, "failed_lookups", Math.max(0, totalLookups - successfulLookups)));
  const nodes = finiteMetricNumber(metricValue(point, "nodes", currentActiveNodeCount));
  return {
    ...point,
    nodes,
    log2_nodes: metricValue(point, "log2_nodes", nodes > 0 ? Math.log2(nodes).toFixed(3) : "0"),
    average_hops: averageHops,
    message_overhead: messageOverhead,
    attempted_lookups: totalLookups,
    total_lookups: totalLookups,
    successful_lookups: successfulLookups,
    failed_lookups: failedLookups,
    success_rate: metricValue(point, "success_rate", totalLookups ? (successfulLookups / totalLookups).toFixed(3) : "0"),
    average_latency_ms: metricValue(point, "average_latency_ms", "0.0000"),
    messages_per_lookup: metricValue(point, "messages_per_lookup", successfulLookups ? (messageOverhead / successfulLookups).toFixed(3) : "0"),
  };
}

// Tạo điểm đo cho một lookup vừa thực hiện khi backend chưa trả bản tổng hợp
function singleLookupMetricFromResult(result, metric) {
  if (metric) {
    return metric;
  }
  const hops = Number(result?.hops ?? 0);
  const nodes = Number(metric?.nodes ?? currentActiveNodeCount);
  return {
    nodes,
    log2_nodes: nodes > 0 ? Math.log2(nodes).toFixed(3) : "0",
    attempted_lookups: 1,
    total_lookups: 1,
    successful_lookups: 1,
    failed_lookups: 0,
    success_rate: 1,
    average_hops: hops,
    average_latency_ms: "0.0000",
    message_overhead: hops,
    messages_per_lookup: hops,
  };
}

// Hiển thị bảng số liệu metrics mà không có các thẻ thống kê
function renderMetricsSummary(point, currentNodes, rows = []) {
  const displayedNodes = Number(point.nodes ?? currentNodes);
  const tableRows = rows
    .map((row) => normalizeMetricPoint(row))
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.nodes)}</td>
          <td>${escapeHtml(row.average_hops)}</td>
          <td>${escapeHtml(row.log2_nodes)}</td>
          <td>${escapeHtml(row.average_latency_ms)}</td>
          <td>${escapeHtml(row.total_lookups)}</td>
          <td>${escapeHtml(row.successful_lookups)} / ${escapeHtml(row.failed_lookups)}</td>
          <td>${escapeHtml(row.message_overhead)}</td>
          <td>${escapeHtml(row.messages_per_lookup)}</td>
        </tr>
      `,
    )
    .join("");
  return `
    <div class="metrics-benchmark">
      <h3>Current HTTP Deployment Measurement (N = ${escapeHtml(currentNodes)})</h3>
      <div class="metrics-table-wrap">
        <table class="metrics-table">
          <thead>
            <tr>
              <th>N</th>
              <th>Average Hops</th>
              <th>log2(N)</th>
              <th>Latency ms</th>
              <th>Lookups</th>
              <th>Success / Failed</th>
              <th>Message Overhead</th>
              <th>Messages / Lookup</th>
            </tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    </div>
  `;
}

// Hiển thị metric gọn cho request lookup vừa đi qua các endpoint node
function renderLookupMetricSummary(metric) {
  const point = normalizeMetricPoint(metric || {});
  return `
    <div class="metric-summary lookup-metric-summary">
      <div class="metric-card">
        <span>log2(N)</span>
        <strong>${escapeHtml(point.log2_nodes)}</strong>
      </div>
      <div class="metric-card">
        <span>Latency ms</span>
        <strong>${escapeHtml(point.average_latency_ms)}</strong>
      </div>
      <div class="metric-card">
        <span>Message Overhead</span>
        <strong>${escapeHtml(point.message_overhead)}</strong>
      </div>
      <div class="metric-card">
        <span>Messages / Lookup</span>
        <strong>${escapeHtml(point.messages_per_lookup)}</strong>
      </div>
    </div>
  `;
}

// Đặt vùng ảnh về trạng thái chờ trong lúc backend dựng artifact mới
function setImageLoading(image, placeholder, loadingText) {
  if (placeholder) {
    placeholder.textContent = loadingText;
    placeholder.hidden = false;
  }
  image.removeAttribute("src");
  image.style.display = "none";
}

// Xóa artifact cũ sau khi deployment mới thay đổi topology hoặc dữ liệu
function clearGeneratedArtifacts() {
  artifactGeneration += 1;
  setMetricChartsLoading("Run metrics to generate new charts.");
  setImageLoading(els.topologyChart, els.topologyPlaceholder, "Generate topology graph to render the current network.");
  els.topologyOutput.textContent = "";
  els.topologyFrame.classList.remove("is-ready", "loading");
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

  // Render overlay summary on top of the topology image (not below).

  // Keep legacy output text empty to avoid UI duplication.
  els.topologyOutput.innerHTML = "";

  setImageReady(els.topologyChart, els.topologyPlaceholder, topology.chart_url, generation);
  return true;
}

// Đặt các biểu đồ metric về trạng thái chờ khi đang chạy lookup đo lường
function setMetricChartsLoading(loadingText) {
  if (els.metricsChartPlaceholder) {
    els.metricsChartPlaceholder.textContent = loadingText;
    els.metricsChartPlaceholder.hidden = false;
  }
  els.metricsCharts.forEach((image) => {
    if (!image) {
      return;
    }
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
  let loadedCount = 0;
  let failed = false;
  els.metricsCharts.forEach((image, index) => {
    if (!image || !urls[index]) {
      return;
    }
    image.onload = () => {
      if (generation !== artifactGeneration) {
        return;
      }
      loadedCount += 1;
      if (loadedCount === urls.filter(Boolean).length && els.metricsChartPlaceholder && !failed) {
        els.metricsChartPlaceholder.hidden = true;
      }
      image.style.display = "block";
    };
    image.onerror = () => {
      if (generation !== artifactGeneration) {
        return;
      }
      failed = true;
      if (els.metricsChartPlaceholder) {
        els.metricsChartPlaceholder.textContent = "Metrics chart is unavailable.";
        els.metricsChartPlaceholder.hidden = false;
      }
      image.style.display = "none";
    };
    if (generation === artifactGeneration) {
      image.src = urls[index];
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
  const killedNode = escapeHtml(report.killed_node_id);
  const oldPredecessor = escapeHtml(report.old_predecessor ?? "none");
  const oldSuccessor = escapeHtml(report.old_successor ?? "none");
  const activeNodes = escapeHtml(report.active_nodes ?? 0);
  const recoveredCount = Number(report.recovered_resources || 0);
  const lostCount = Number(report.lost_resources || 0);
  const updatedFingerEntries = Number(report.updated_finger_entries || 0);
  const updatedFingerTables = Number(report.updated_finger_tables || 0);
  const configuredReplicas = Number(report.replication_count || 0);
  const effectiveReplicas = Number(report.effective_replica_count || 0);
  const recoveredSamples = Array.isArray(report.recovered_resource_ids) ? report.recovered_resource_ids : [];
  const replicaRepairedCount = Number(report.replica_repaired_resources || 0);
  const replicaRepairedSamples = Array.isArray(report.replica_repaired_resource_ids)
    ? report.replica_repaired_resource_ids
    : [];
  const lostSamples = Array.isArray(report.lost_resource_ids) ? report.lost_resource_ids : [];
  const recoveredTotal = Number(report.recovered_resource_total_count ?? recoveredCount);
  const replicaRepairedTotal = Number(report.replica_repaired_resource_total_count ?? replicaRepairedCount);
  const lostTotal = Number(report.lost_resource_total_count ?? lostCount);
  // Hiển thị danh sách resource đại diện trong báo cáo failure recovery.
  const sampleList = (items, emptyText, totalCount = items.length) => {
    if (!items.length) {
      return `<div class="kill-resource-empty">${escapeHtml(emptyText)}</div>`;
    }
    const remaining = Math.max(0, Number(totalCount || 0) - items.length);
    const more = remaining > 0 ? `<span class="kill-resource-more">... +${escapeHtml(remaining)} more</span>` : "";
    return `<div class="kill-resource-samples">${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}${more}</div>`;
  };
  const recoveryText =
    recoveredCount > 0
      ? `${escapeHtml(recoveredCount)} primary resource(s) had owner node ${killedNode} and were promoted from active replica copies.`
      : "No resource owned by the killed node had an active replica to promote.";
  const replicaRepairText =
    replicaRepairedCount > 0
      ? `${escapeHtml(replicaRepairedCount)} resource(s) used node ${killedNode} only as a replica; the failed replica was removed and replacement replicas were rebuilt.`
      : `No surviving resource used node ${killedNode} only as a replica.`;
  const lossText =
    lostCount > 0
      ? `${escapeHtml(lostCount)} resource(s) were lost because no active replica copy was available.`
      : "No stored resource was lost.";

  els.nodeRemovalReport.innerHTML = `
    <div class="kill-report-header">
      <div>
        <h3>Stop Node Recovery Report</h3>
        <p>Process ${killedNode} stopped responding. Live peers stabilized through HTTP and promoted available JSON replicas.</p>
      </div>
      <div class="kill-report-header-actions">
        <span>${activeNodes} active node(s)</span>
        <button type="button" class="kill-report-toggle" aria-expanded="true">Collapse</button>
      </div>
    </div>
    <div class="kill-report-body">
      <div class="kill-summary-grid">
        <div>
          <strong>Stopped</strong>
          <span class="stopped-node-text">${killedNode}</span>
        </div>
        <div>
          <strong>Old predecessor</strong>
          <span>${oldPredecessor}</span>
        </div>
        <div>
          <strong>Old successor</strong>
          <span>${oldSuccessor}</span>
        </div>
        <div>
          <strong>Recovered / lost</strong>
          <span>${escapeHtml(recoveredCount)} / ${escapeHtml(lostCount)}</span>
        </div>
      </div>
      <div class="kill-recovery-note">
        <strong>Replica policy:</strong>
        Configured replicas = ${escapeHtml(configuredReplicas)}.
        Effective replicas after this kill = ${escapeHtml(effectiveReplicas)}
        because a resource can only be copied to active nodes other than its owner.
      </div>
      <ol class="kill-timeline">
        <li>
          <strong>1. Stop the node process</strong>
          <span>Endpoint of node ${killedNode} no longer answers HTTP requests and cannot receive forwarded routes.</span>
        </li>
        <li>
          <strong>2. Detect unreachable neighbors</strong>
          <span>Remaining peers use health checks and local successor lists to avoid forwarding to the stopped endpoint.</span>
        </li>
        <li>
          <strong>3. Stabilize local pointers</strong>
          <span>Peers exchange predecessor and notify messages over HTTP until successor links converge again.</span>
        </li>
        <li>
          <strong>4. Repair stale finger entries</strong>
          <span>${escapeHtml(updatedFingerTables)} peer(s) repaired ${escapeHtml(updatedFingerEntries)} Finger Table entry/entries that targeted the stopped endpoint through local Chord lookups.</span>
        </li>
        <li>
          <strong>5. Inspect live local replicas</strong>
          <span>The recovery step separates two cases: primary resources whose owner was node ${killedNode}, and replica copies that were merely stored on node ${killedNode}.</span>
        </li>
        <li>
          <strong>6. Promote recovered resources</strong>
          <span>${recoveryText}</span>
          ${sampleList(recoveredSamples, "No recovered primary resource sample.", recoveredTotal)}
        </li>
        <li>
          <strong>7. Restore replica placement</strong>
          <span>For promoted primary resources, the recovered value is written to the new owner and copied to the next ${escapeHtml(effectiveReplicas)} active successor node(s). For resources where node ${killedNode} was only a replica, that dead copy is removed from replica_node_ids and rebuilt on the next valid successor node.</span>
          <span>${replicaRepairText}</span>
          ${sampleList(replicaRepairedSamples, "No replica-only resource sample.", replicaRepairedTotal)}
        </li>
        <li class="${lostCount > 0 ? "kill-step-warning" : ""}">
          <strong>8. Report unrecoverable data</strong>
          <span>${lossText}</span>
          ${sampleList(lostSamples, "No lost resource sample.", lostTotal)}
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

// Render số node, resource mẫu, danh sách node active và preview Finger Table
// Hiển thị snapshot trạng thái do coordinator thu thập từ các node đang sống
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
  els.nodesOutput.innerHTML = sortedSites
    .map((node) => {
      const nodeId = Number(node.node_id);
      return `<button type="button" class="node-pill" data-node-id="${escapeHtml(nodeId)}">
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
  // Single-process mode: no base port / storage dir needed; inputs are readonly.
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
    if (!renderTopologyArtifact(data.topology)) {
      await generateTopology(true, false);
    }
    showToast(data.message);
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(els.initializeBtn, false);
  }
}

// Gọi lookup resource/key và hiển thị owner, hop count, path và log từng hop
async function lookupResource() {
  setBusy(els.lookupBtn, true, "Looking up...");
  els.lookupOutput.textContent = "Running lookup...";
  try {
    const startNodeValue = els.startNodeInput.value.trim();
    const data = await api("/api/lookup", {
      resource_id: els.resourceInput.value.trim(),
      start_node_id: startNodeValue === "" ? null : Number(startNodeValue),
    });
    const result = data.result;
    els.lookupOutput.classList.remove("lookup-output--missing");
    const ownerSite = nodeSite(result.owner_id);
    const path = (Array.isArray(result.path) ? result.path : []).map((nodeId) => {
      return `<span>${escapeHtml(nodeId)}</span>`;
    });
    const route = path.join("");
    const logs =
      Array.isArray(result.logs)
        ? result.logs.map((line) => `<li>${escapeHtml(line)}</li>`).join("")
        : "";
    const replicaText =
      Array.isArray(result.replica_node_ids) && result.replica_node_ids.length
        ? result.replica_node_ids.map((nodeId) => escapeHtml(nodeId)).join(", ")
        : "None";
    const missingBanner = "";
    els.lookupOutput.innerHTML = `
      ${missingBanner}
      <div class="lookup-result-summary">
        <div class="lookup-result-card lookup-result-card--owner">
          <span>Owner</span>
          <strong>${escapeHtml(result.owner_id)}</strong>
        </div>
        <div class="lookup-result-card lookup-result-card--key">
          <span>Key</span>
          <strong>${escapeHtml(result.key)}</strong>
        </div>
        <div class="lookup-result-card lookup-result-card--found">
          <span>Found on owner</span>
          <strong>${result.found ? "Yes" : "No"}</strong>
        </div>
        <div class="lookup-result-card lookup-result-card--replicas">
          <span>Replica nodes</span>
          <strong>${replicaText}</strong>
        </div>
        <div class="lookup-result-card lookup-result-card--hops">
          <span>Hops</span>
          <strong>${escapeHtml(result.hops)}</strong>
        </div>
      </div>
      ${renderLookupMetricSummary(singleLookupMetricFromResult(result, data.lookup_metric))}
      <div class="route">${route}</div>
      <ul class="lookup-log">${logs}</ul>
    `;

    // Re-generate topology with lookup path highlighted.
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
      `Stop node ${nodeToKill}?\n\nIts port will stop responding; remaining nodes will stabilize and recover from local replicas.`,
    )
  ) {
    return;
  }
  setBusy(els.killBtn, true, "Stopping...");
  try {
    const data = await api("/api/kill", {
      node_id: Number(nodeToKill),
    });
    selectedNodeId = null;
    renderState(data.state);
    renderNodeRemovalReport(data.report);
    await refreshArtifacts();
    showToast(data.message);
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(els.killBtn, false);
  }
}

// Làm mới snapshot và artifact sau thao tác join, restart hoặc CRUD
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
    [{ id: "portField", label: "Port", type: "number", placeholder: "Auto if empty" }],
    "Join",
    async ({ portField }) => {
      const portValue = portField.trim();
      const data = await api("/api/node", {
        port: portValue === "" ? null : Number(portValue),
      });
      selectedNodeId = Number(data.report.node_id);
      clearNodeRemovalReport();
      await refreshAfterChange(data.state, { rebuildArtifacts: true });
      showToast(data.message);
    },
  );
}

// Khởi chạy lại node đã dừng với cùng endpoint và kho JSON persisted
async function restartNode() {
  if (selectedNodeId === null) {
    showToast("Select a node first.");
    return;
  }
  const data = await api(`/api/node/${selectedNodeId}/restart`, {});
  clearNodeRemovalReport();
  await refreshAfterChange(data.state, { rebuildArtifacts: true });
  showToast(data.message);
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
      selectedNodeId = null;
      selectedResourceId = data.report.resource.resource_id;
      await refreshAfterChange(data.state);
      showToast(`${data.message} Owner: ${data.report.resource.owner_id}.`);
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
      selectedNodeId = Number(data.report.resource.owner_id);
      selectedResourceId = data.report.resource.resource_id;
      await refreshAfterChange(data.state);
      showToast(`${data.message} Owner: ${data.report.resource.owner_id}.`);
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

// Chạy benchmark đúng số node hiện tại và hiển thị bảng số liệu cùng ảnh biểu đồ matplotlib
async function runMetrics(silent = false) {
  const requestGeneration = artifactGeneration;
  setBusy(els.metricsBtn, true, silent ? "Auto..." : "Running...");
  els.metricsOutput.textContent = silent ? "Updating average hops..." : "Running metrics...";
  setMetricChartsLoading("Generating metrics charts...");
  try {
    const data = await api("/api/metrics", {
      lookups: Number(els.metricLookupsInput.value),
      trials: Number(els.metricTrialsInput.value),
    });
    const currentNodes = Number(data.current_nodes ?? currentActiveNodeCount);
    const metricRows = Array.isArray(data.metrics) ? data.metrics : [];
    if (requestGeneration !== artifactGeneration) {
      return;
    }
    const currentGrowthPoint = metricRows.find((row) => Number(row.nodes) === currentNodes);
    const currentMetric = data.current_metric || {};
    const pointSource = {
      ...(currentGrowthPoint || {}),
      ...currentMetric,
      max_lookup_trace: currentMetric.max_lookup_trace || (currentGrowthPoint && currentGrowthPoint.max_lookup_trace),
    };
    const point = normalizeMetricPoint(pointSource);
    currentActiveNodeCount = currentNodes;
    els.statusNodes.textContent = currentNodes;
    els.metricsOutput.innerHTML = renderMetricsSummary(point, currentNodes, metricRows);
    setMetricChartsReady(data.chart_urls || {
      hops: data.chart_url,
      latency: data.chart_url,
      overhead: data.chart_url,
    }, requestGeneration);
    if (!silent) {
      showToast(data.message);
    }
  } catch (error) {
    els.metricsOutput.textContent = error.message;
    if (els.metricsChartPlaceholder) {
      els.metricsChartPlaceholder.textContent = "Metrics chart is unavailable.";
      els.metricsChartPlaceholder.hidden = false;
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
  setBusy(els.topologyBtn, true, "Generating...");
  els.topologyOutput.textContent = "Generating topology graph...";
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
    els.topologyOutput.textContent = error.message;
    els.topologyFrame.classList.remove("loading");
    if (els.topologyPlaceholder) {
      els.topologyPlaceholder.textContent = "Topology graph is unavailable.";
      els.topologyPlaceholder.hidden = false;
    }
    if (!silent) {
      showToast(error.message);
    }
  } finally {
    setBusy(els.topologyBtn, false);
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

// Đóng modal chi tiết resource
function closeResourceDetailModal() {
  // Modal removed - kept for compatibility
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
bindClick(els.restartNodeBtn, restartNode);
bindClick(els.addResourceBtn, addResource);
bindClick(els.metricsBtn, () => runMetrics(false));
  // Topology expand/close
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

document.addEventListener("keydown", (event) => {
  if (!els.formModal || !els.formModal.classList.contains("is-open")) {
    return;
  }
  if (event.key === "Escape") {
    closeFormModal();
  }
  if (event.key === "Enter") {
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
// Resource detail modal handlers
if (els.resourceDetailCloseBtn) {
  els.resourceDetailCloseBtn.addEventListener("click", closeResourceDetailModal);
}
if (els.resourceDetailEditBtn) {
  els.resourceDetailEditBtn.addEventListener("click", () => {
    closeResourceDetailModal();
    updateResource();
  });
}
if (els.resourceDetailDeleteBtn) {
  els.resourceDetailDeleteBtn.addEventListener("click", () => {
    closeResourceDetailModal();
    deleteResource();
  });
}
if (els.resourceDetailModal) {
  els.resourceDetailModal.addEventListener("click", (event) => {
    if (event.target === els.resourceDetailModal) {
      closeResourceDetailModal();
    }
  });
}
if (els.resourceTableFilter) {
  els.resourceTableFilter.addEventListener("input", applyResourceTableFilter);
}

// Filter toggle handlers
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
if (els.basePortInput) {
  els.basePortInput.addEventListener("change", () => {
    renderState({
      active_node_count: currentActiveNodeCount,
      active_nodes: currentActiveNodes,
      resource_count: resourceTotalCount,
      replication_count: Number(els.replicationInput.value) || 0,
      failed_node_count: Number(els.failedNodesInput.value) || 0,
      m: Number(els.mInput.value) || 16,
      sample_resources: cachedResourceRows,
      sites: currentSites,
    });
  });
}
if (els.storageDirInput) {
  els.storageDirInput.addEventListener("change", () => {
    updateNodeSelection();
  });
}
// Tải snapshot ban đầu rồi sinh metrics và topology tuần tự cho deployment hiện tại
function setAppLoadingStatus(msg) {
  if (els.appLoadingStatus) {
    els.appLoadingStatus.textContent = msg;
  }
}

function hideAppLoading() {
  if (els.appLoading) {
    els.appLoading.classList.add("is-hidden");
    setTimeout(() => {
      if (els.appLoading) {
        els.appLoading.hidden = true;
      }
    }, 400);
  }
}

function showAppLoading() {
  if (els.appLoading) {
    els.appLoading.hidden = false;
    els.appLoading.classList.remove("is-hidden");
  }
}

showAppLoading();
setAppLoadingStatus("Restoring distributed ring...");

loadState()
  .then(() => {
    clearGeneratedArtifacts();
    setAppLoadingStatus("Generating topology...");
    return generateTopology(true, false);
  })
  .then(() => {
    setAppLoadingStatus("Done.");
    hideAppLoading();
  })
  .catch((error) => {
    setAppLoadingStatus("Error: " + error.message);
    setTimeout(hideAppLoading, 2000);
  });

