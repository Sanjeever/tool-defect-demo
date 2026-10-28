const $ = (selector) => document.querySelector(selector);
const qualityNames = { good: "好件", defect: "坏件", unknown: "待确认" };
const splitNames = {
  unassigned: "未分配",
  train: "训练集",
  val: "验证集",
  test: "测试集",
};
let workspace = { images: [], specimens: [] };
let page = "capture",
  selectedImage = null,
  boxes = [],
  dirty = false;
let previewActive = false,
  previewPromise = null,
  cameraBusy = false,
  cameraUrl = null;
let previewTimer = null,
  captureSaving = false,
  annotationVersion = 0;
let jobs = [],
  selectedJob = null,
  plan = null,
  draft = null;

function report(error) {
  $("#error").textContent = error.message || String(error);
  $("#error").hidden = false;
}
function clearError() {
  $("#error").hidden = true;
}
const action = (handler) => async (event) => {
  clearError();
  try {
    await handler(event);
  } catch (error) {
    report(error);
  }
};
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json();
    const message = Array.isArray(body.detail)
      ? body.detail
          .map((item) => `${item.loc.slice(1).join(".")}: ${item.msg}`)
          .join("；")
      : body.detail;
    throw new Error(message || `请求失败（${response.status}）`);
  }
  return response;
}
async function json(path, method = "GET", body) {
  return (
    await api(path, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  ).json();
}
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function setOptions(select, values, first) {
  const previous = select.value;
  select.replaceChildren();
  if (first !== undefined) select.append(new Option(first, ""));
  values.forEach((value) => select.append(new Option(value, value)));
  if (values.includes(previous) || previous === "") select.value = previous;
}
async function refresh() {
  workspace = await json("/api/state");
  $("#nav-count").textContent = workspace.images.length;
  $("#workspace-count").textContent =
    `${workspace.images.length} 张图片 / ${workspace.specimens.length} 个实体`;
  const types = [...new Set(workspace.specimens.map((item) => item.tool_type))];
  setOptions($("#type-options"), types);
  setOptions($("#library-type"), types, "全部类型");
  updateSpecimenOptions();
  renderRecent();
  renderImageList();
}
function updateSpecimenOptions() {
  const items = workspace.specimens.filter(
    (item) => item.tool_type === $("#capture-type").value,
  );
  setOptions(
    $("#specimen-options"),
    items.map((item) => item.specimen_id),
  );
  const current = items.find(
    (item) => item.specimen_id === $("#capture-specimen").value,
  );
  if (current)
    $(`input[name="capture-quality"][value="${current.quality}"]`).checked =
      true;
}
async function changePage(next) {
  await saveAnnotation();
  stopPreview();
  page = next;
  document.querySelectorAll(".page").forEach((element) => {
    element.hidden = element.id !== `page-${next}`;
  });
  document
    .querySelectorAll(".nav-item")
    .forEach((element) =>
      element.classList.toggle("active", element.dataset.page === next),
    );
  $("#page-title").textContent = {
    capture: "采集",
    library: "图片与标注",
    training: "训练",
  }[next];
  clearError();
  if (next === "library" && !selectedImage && workspace.images.length)
    await selectImage(workspace.images[0].id);
  if (next === "training") {
    await checkDataset();
    await refreshJobs();
  }
}
function cameraSettings() {
  return {
    sn: $("#camera-sn").value.trim(),
    packet_delay: Number($("#packet-delay").value),
    sdk_root: $("#sdk-root").value.trim(),
  };
}
function cameraButtons(busy) {
  cameraBusy = busy;
  $("#preview-once").disabled = busy;
  $("#enumerate").disabled = busy;
  $("#capture-button").disabled = captureSaving || (busy && !previewActive);
  $("#preview-toggle").disabled = busy && !previewActive;
}
function stopPreview() {
  previewActive = false;
  clearTimeout(previewTimer);
  $("#preview-toggle").textContent = "连续预览";
  cameraButtons(cameraBusy);
}
async function showCamera(blob, status) {
  const url = URL.createObjectURL(blob);
  const image = $("#camera-image");
  image.src = url;
  await image.decode();
  if (cameraUrl) URL.revokeObjectURL(cameraUrl);
  cameraUrl = url;
  image.hidden = false;
  $("#camera-empty").hidden = true;
  $("#camera-state").textContent = status;
  $("#camera-dot").classList.remove("idle");
  $("#camera-dimensions").textContent =
    `${image.naturalWidth} × ${image.naturalHeight} · Mono8`;
}
async function previewFrame() {
  cameraButtons(true);
  $("#camera-state").textContent = "采集中…";
  try {
    const response = await api("/api/camera/preview", {
      method: "POST",
      body: JSON.stringify(cameraSettings()),
    });
    await showCamera(
      await response.blob(),
      previewActive ? "连续预览" : "单帧预览",
    );
  } catch (error) {
    stopPreview();
    $("#camera-state").textContent = "采集失败";
    $("#camera-dot").classList.add("idle");
    throw error;
  } finally {
    cameraButtons(false);
  }
}
async function previewLoop() {
  if (!previewActive) return;
  previewPromise = previewFrame();
  try {
    await previewPromise;
  } catch (error) {
    report(error);
  } finally {
    previewPromise = null;
  }
  if (previewActive) previewTimer = setTimeout(previewLoop, 500);
}
function renderRecent() {
  const container = $("#recent-images");
  container.replaceChildren();
  if (!workspace.images.length) {
    container.append(node("div", "recent-empty", "尚无已归档图片"));
    return;
  }
  workspace.images.slice(0, 4).forEach((item) => {
    const card = node("button", "recent-card");
    const image = node("img");
    image.src = `/api/images/${item.id}/file`;
    image.alt = `${item.specimen_id} ${qualityNames[item.quality]}`;
    const label = node("div");
    label.append(
      node("span", "", item.specimen_id),
      node("span", "", qualityNames[item.quality]),
    );
    card.append(image, label);
    card.onclick = action(async () => {
      await changePage("library");
      await selectImage(item.id);
    });
    container.append(card);
  });
}
function renderImageList() {
  const container = $("#image-list");
  container.replaceChildren();
  const filtered = workspace.images.filter(
    (item) =>
      (!$("#library-type").value ||
        item.tool_type === $("#library-type").value) &&
      (!$("#library-quality").value ||
        item.quality === $("#library-quality").value),
  );
  if (!filtered.length)
    container.append(node("div", "recent-empty", "没有匹配图片"));
  filtered.forEach((item) => {
    const card = node(
      "button",
      `image-card${item.id === selectedImage?.id ? " active" : ""}`,
    );
    card.dataset.id = item.id;
    card.setAttribute(
      "aria-label",
      `${item.specimen_id} ${qualityNames[item.quality]} ${item.path.split("/").pop()}`,
    );
    const image = node("img");
    image.src = `/api/images/${item.id}/file`;
    image.alt = "";
    image.loading = "lazy";
    const label = node("div", "image-card-text");
    label.append(
      node("span", "", item.specimen_id),
      node(
        "span",
        item.included ? "image-mark" : "",
        item.included ? "已选入" : qualityNames[item.quality],
      ),
    );
    card.append(
      image,
      label,
      node(
        "span",
        "image-card-time mono",
        item.path.split("/").pop().replace("top_", "").replace(".png", ""),
      ),
    );
    card.onclick = action(() => selectImage(item.id));
    container.append(card);
  });
}
async function selectImage(imageId) {
  await saveAnnotation();
  selectedImage = workspace.images.find((item) => item.id === imageId);
  if (!selectedImage) return;
  boxes = structuredClone(selectedImage.boxes);
  draft = null;
  const canvas = $("#annotation-canvas");
  canvas.setAttribute(
    "viewBox",
    `0 0 ${selectedImage.width} ${selectedImage.height}`,
  );
  const image = $("#annotation-image");
  image.setAttribute("href", `/api/images/${imageId}/file`);
  image.setAttribute("width", selectedImage.width);
  image.setAttribute("height", selectedImage.height);
  canvas.removeAttribute("hidden");
  $("#annotation-empty").hidden = true;
  $("#annotation-fields").hidden = false;
  $("#annotation-name").textContent =
    `${selectedImage.tool_type} / ${selectedImage.specimen_id}`;
  $("#annotation-dimensions").textContent =
    `${selectedImage.width} × ${selectedImage.height}`;
  $("#annotation-save-state").textContent = "已保存";
  $("#original-link").hidden = false;
  $("#original-link").href = `/api/images/${imageId}/file`;
  $("#image-included").checked = selectedImage.included;
  $("#specimen-key").textContent =
    `${selectedImage.tool_type} / ${selectedImage.specimen_id}`;
  $("#specimen-quality").value = selectedImage.quality;
  $("#specimen-split").value = selectedImage.split;
  $("#specimen-category").value = selectedImage.category;
  $("#box-label").value =
    selectedImage.category || selectedImage.boxes[0]?.label || "";
  $("#category-field").hidden = selectedImage.quality !== "defect";
  renderBoxes();
  renderImageList();
}
function markDirty() {
  dirty = true;
  annotationVersion++;
  $("#annotation-save-state").textContent = "未保存";
}
function svgNode(tag, attrs) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([key, value]) =>
    element.setAttribute(key, value),
  );
  return element;
}
function renderBoxes() {
  const layer = $("#annotation-boxes");
  layer.replaceChildren();
  [...boxes, ...(draft ? [draft] : [])].forEach((box, index) => {
    layer.append(
      svgNode("rect", {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
      }),
    );
    const text = svgNode("text", { x: box.x + 6, y: Math.max(23, box.y - 9) });
    text.textContent = `${index + 1} ${box.label}`;
    layer.append(text);
  });
  const list = $("#box-list");
  list.replaceChildren();
  boxes.forEach((box, index) => {
    const row = node("div", "box-item");
    row.append(node("span", "", `${index + 1}`));
    const label = node("input");
    label.value = box.label;
    label.maxLength = 80;
    label.setAttribute("aria-label", `标注框 ${index + 1} 名称`);
    label.oninput = () => {
      box.label = label.value;
      markDirty();
    };
    label.onchange = renderBoxes;
    const remove = node("button", "", "×");
    remove.setAttribute("aria-label", `删除标注框 ${index + 1}`);
    remove.onclick = () => {
      boxes.splice(index, 1);
      markDirty();
      renderBoxes();
    };
    row.append(label, remove);
    list.append(row);
  });
}
async function saveAnnotation() {
  if (!dirty || !selectedImage) return;
  $("#annotation-save-state").textContent = "保存中…";
  const included = $("#image-included").checked;
  const savedBoxes = structuredClone(boxes),
    savedVersion = annotationVersion;
  try {
    await json(`/api/images/${selectedImage.id}`, "PATCH", {
      included,
      boxes: savedBoxes,
    });
    selectedImage.boxes = savedBoxes;
    selectedImage.included = included;
    dirty = annotationVersion !== savedVersion;
    $("#annotation-save-state").textContent = dirty ? "未保存" : "已保存";
    renderImageList();
  } catch (error) {
    $("#annotation-save-state").textContent = "保存失败";
    throw error;
  }
}
function imagePoint(event) {
  const canvas = $("#annotation-canvas");
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(
    canvas.getScreenCTM().inverse(),
  );
  return {
    x: Math.round(Math.max(0, Math.min(selectedImage.width, point.x))),
    y: Math.round(Math.max(0, Math.min(selectedImage.height, point.y))),
  };
}
let dragStart = null;
$("#annotation-canvas").addEventListener(
  "pointerdown",
  action((event) => {
    if (!selectedImage || event.button !== 0) return;
    if (!$("#box-label").value.trim())
      throw new Error("请先填写缺陷名称，再拖动绘制矩形");
    dragStart = imagePoint(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    draft = {
      x: dragStart.x,
      y: dragStart.y,
      width: 0,
      height: 0,
      label: $("#box-label").value.trim(),
    };
  }),
);
$("#annotation-canvas").addEventListener("pointermove", (event) => {
  if (!dragStart) return;
  const point = imagePoint(event);
  Object.assign(draft, {
    x: Math.min(point.x, dragStart.x),
    y: Math.min(point.y, dragStart.y),
    width: Math.abs(point.x - dragStart.x),
    height: Math.abs(point.y - dragStart.y),
  });
  renderBoxes();
});
$("#annotation-canvas").addEventListener("pointerup", () => {
  if (!dragStart) return;
  if (draft.width >= 2 && draft.height >= 2) {
    boxes.push(draft);
    markDirty();
  }
  draft = null;
  dragStart = null;
  renderBoxes();
});
$("#annotation-canvas").addEventListener("pointercancel", () => {
  draft = null;
  dragStart = null;
  renderBoxes();
});
window.addEventListener("beforeunload", (event) => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

async function checkDataset() {
  $("#epochs-field").hidden = $("#train-model").value !== "classifier";
  plan = await json(
    `/api/dataset?tool_type=${encodeURIComponent($("#train-type").value.trim())}&model=${$("#train-model").value}`,
  );
  const table = node("table", "dataset-table");
  const head = node("thead");
  const headRow = node("tr");
  ["分组", "实体数", "正常图", "缺陷图"].forEach((title) =>
    headRow.append(node("th", "", title)),
  );
  head.append(headRow);
  table.append(head);
  const body = node("tbody");
  Object.entries(plan.counts).forEach(([split, counts]) => {
    const row = node("tr");
    [splitNames[split], counts.specimens, counts.good, counts.defect].forEach(
      (value) => row.append(node("td", "", value)),
    );
    body.append(row);
  });
  table.append(body);
  $("#dataset-summary").replaceChildren(table);
  const issues = $("#dataset-issues");
  issues.replaceChildren();
  if (plan.ready)
    issues.append(
      node(
        "span",
        "dataset-ready",
        $("#train-model").value === "patchcore"
          ? "数据目录满足训练入口要求。训练仅使用正常图，测试集保留用于独立评估。"
          : "数据目录满足训练入口要求。分类训练使用已标注类别的坏件，测试集保留用于独立评估。",
      ),
    );
  else {
    const list = node("ul");
    plan.issues.forEach((issue) => list.append(node("li", "", issue)));
    issues.append(list);
  }
  updateTrainButton();
}
function updateTrainButton() {
  const active = jobs.some((job) =>
    ["running", "stopping"].includes(job.status),
  );
  $("#start-training").disabled = !plan?.ready || active;
  $("#train-availability").textContent = active
    ? "已有任务运行中"
    : plan?.ready
      ? "首次训练可能下载预训练权重"
      : "请先完成图片审核与实体分组";
}
const jobNames = {
  running: "运行中",
  stopping: "停止中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已停止",
  interrupted: "中断",
};
async function refreshJobs() {
  jobs = await json("/api/jobs");
  if (!selectedJob && jobs.length) selectedJob = jobs[0].id;
  const list = $("#job-list");
  list.replaceChildren();
  $("#job-count").textContent = `${jobs.length} 个任务`;
  if (!jobs.length) list.append(node("div", "job-empty", "暂无训练任务"));
  jobs.forEach((job) => {
    const row = node(
      "div",
      `job-row${job.id === selectedJob ? " active" : ""}`,
    );
    const select = node("button", "text-button job-info");
    select.append(
      node(
        "span",
        "",
        `${job.model === "patchcore" ? "PatchCore" : "YOLO 分类"} · ${job.tool_type} · ${job.image_count} 张`,
      ),
      node("span", "mono", job.id),
    );
    select.onclick = action(async () => {
      selectedJob = job.id;
      await refreshJobs();
    });
    row.append(
      select,
      node(
        "span",
        `job-state ${job.status}`,
        job.status === "running" && job.phase === "preparing"
          ? "预处理中"
          : jobNames[job.status],
      ),
    );
    if (job.status === "running") {
      const stop = node("button", "text-button", "停止");
      stop.onclick = action(async () => {
        await json(`/api/jobs/${job.id}/stop`, "POST");
        await refreshJobs();
      });
      row.append(stop);
    }
    list.append(row);
  });
  updateTrainButton();
  if (selectedJob) await refreshLog();
}
async function refreshLog() {
  const job = jobs.find((item) => item.id === selectedJob);
  if (!job) return;
  $("#log-title").textContent = `任务日志 · ${jobNames[job.status]}`;
  const log = await json(`/api/jobs/${selectedJob}/log`);
  const element = $("#job-log");
  const atBottom =
    element.scrollHeight - element.scrollTop - element.clientHeight < 40;
  element.textContent =
    log.text.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "") ||
    (job.phase === "preparing" ? "正在准备数据…" : "等待训练日志…");
  if (atBottom) element.scrollTop = element.scrollHeight;
  const artifacts = $("#job-artifacts");
  artifacts.replaceChildren();
  [
    ["manifest.json", "数据清单"],
    ["run.log", "日志"],
    ...(job.checkpoint ? [[job.checkpoint, "模型文件"]] : []),
  ].forEach(([name, title]) => {
    const link = node("a", "text-button", title);
    link.href = `/api/jobs/${selectedJob}/artifact?name=${encodeURIComponent(name)}`;
    artifacts.append(link);
  });
}

document.querySelectorAll("[data-page]").forEach((button) => {
  button.onclick = action(() => changePage(button.dataset.page));
});
$("#open-library").onclick = action(() => changePage("library"));
$("#capture-type").onchange = updateSpecimenOptions;
$("#capture-specimen").onchange = updateSpecimenOptions;
$("#preview-once").onclick = action(async () => {
  stopPreview();
  if (previewPromise) await previewPromise;
  previewPromise = previewFrame();
  try {
    await previewPromise;
  } finally {
    previewPromise = null;
  }
});
$("#preview-toggle").onclick = action(async () => {
  if (previewActive) {
    stopPreview();
    return;
  }
  if (cameraBusy) return;
  previewActive = true;
  $("#preview-toggle").textContent = "停止预览";
  await previewLoop();
});
$("#enumerate").onclick = action(async () => {
  cameraButtons(true);
  try {
    const result = await json("/api/camera/devices", "POST", cameraSettings());
    setOptions(
      $("#device-options"),
      result["设备"].map((item) => item.sn),
    );
    $("#device-result").textContent = `${result["设备数量"]} 台设备`;
    if (result["设备"].length === 1)
      $("#camera-sn").value = result["设备"][0].sn;
  } finally {
    cameraButtons(false);
  }
});
$("#capture-button").onclick = action(async () => {
  if (captureSaving) return;
  captureSaving = true;
  stopPreview();
  cameraButtons(true);
  try {
    if (previewPromise) await previewPromise;
    cameraButtons(true);
    $("#camera-state").textContent = "拍摄并保存…";
    const result = await json("/api/camera/capture", "POST", {
      ...cameraSettings(),
      tool_type: $("#capture-type").value.trim(),
      specimen_id: $("#capture-specimen").value.trim(),
      quality: $('input[name="capture-quality"]:checked').value,
    });
    const response = await api(`/api/images/${result.id}/file`);
    await showCamera(await response.blob(), "已保存");
    $("#capture-result").textContent = result.path;
    await refresh();
  } catch (error) {
    $("#camera-state").textContent = "拍摄失败";
    throw error;
  } finally {
    captureSaving = false;
    cameraButtons(false);
  }
});
$("#import-images").onclick = action(async () => {
  $("#import-images").disabled = true;
  try {
    const result = await json("/api/import", "POST");
    await refresh();
    if (!selectedImage && workspace.images.length)
      await selectImage(workspace.images[0].id);
    $("#annotation-save-state").textContent =
      `已导入 ${result.imported} 张，审核后可选入数据集`;
  } finally {
    $("#import-images").disabled = false;
  }
});
$("#library-type").onchange = renderImageList;
$("#library-quality").onchange = renderImageList;
$("#image-included").onchange = markDirty;
$("#undo-box").onclick = () => {
  if (boxes.length) {
    boxes.pop();
    markDirty();
    renderBoxes();
  }
};
$("#save-annotation").onclick = action(saveAnnotation);
$("#specimen-quality").onchange = () => {
  $("#category-field").hidden = $("#specimen-quality").value !== "defect";
};
$("#save-specimen").onclick = action(async () => {
  if (!selectedImage) return;
  await saveAnnotation();
  const id = selectedImage.id;
  await json("/api/specimens", "PUT", {
    tool_type: selectedImage.tool_type,
    specimen_id: selectedImage.specimen_id,
    quality: $("#specimen-quality").value,
    split: $("#specimen-split").value,
    category:
      $("#specimen-quality").value === "defect"
        ? $("#specimen-category").value.trim()
        : "",
  });
  await refresh();
  await selectImage(id);
  $("#annotation-save-state").textContent = "实体分组已保存";
});
$("#check-dataset").onclick = action(checkDataset);
$("#train-model").onchange = action(checkDataset);
$("#train-type").onchange = action(checkDataset);
$("#start-training").onclick = action(async () => {
  $("#start-training").disabled = true;
  try {
    const roiText = $("#train-roi").value.trim();
    const roi = roiText ? roiText.split(/[,，\s]+/).map(Number) : null;
    if (
      roi &&
      (roi.length !== 4 || roi.some((value) => !Number.isInteger(value)))
    )
      throw new Error("ROI 需要四个整数：左,上,右,下");
    const job = await json("/api/jobs", "POST", {
      tool_type: $("#train-type").value.trim(),
      model: $("#train-model").value,
      device: $("#train-device").value,
      batch_size: Number($("#train-batch").value),
      epochs: Number($("#train-epochs").value),
      roi,
    });
    selectedJob = job.id;
    await refreshJobs();
  } finally {
    updateTrainButton();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopPreview();
});
setInterval(() => {
  if (page === "training" && !document.hidden) refreshJobs().catch(report);
}, 2000);
refresh().catch(report);
