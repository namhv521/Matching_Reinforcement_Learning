import { requireSession } from "./portal.js";
import { balancedQuotas } from "./student-cohorts.js";

const $ = (id) => document.getElementById(id);
const escape = (value = "") => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const labels = { ppo: "PPO", dqn: "DQN", hungarian: "Hungarian · baseline", greedy: "Greedy", random: "Random" };
const state = { bootstrap: null, base: "", token: "", selected: new Set(), cohort: null, file: null, comparison: null, recommendation: null, algorithm: "ppo", busy: false, step: 0, playing: false, revision: 0, quotaVerified: false };
let timer;
let previewedWorkbook;
let replayScene, loadingReplay, pageClosed;
let chatPending = false;
let chatOpener;
const chatSuggestions = document.querySelectorAll("#chat-suggestions [data-question]");

function nameStudent(id) { return state.cohort?.students?.find((s) => s.student_id === id)?.student_name || id; }
function nameAdvisor(id) { return state.bootstrap?.advisors?.find((a) => a.advisor_id === id)?.advisor_name || id; }
function score(value) { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "Chưa biết"; }
function number(value, digits = 2) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("vi-VN", { maximumFractionDigits: digits }) : "—"; }
function warningText(value) { return typeof value === "string" ? value : value?.message || JSON.stringify(value); }
function warnings(values = []) { return values.length ? `<ul class="help">${values.map((w) => `<li>${escape(warningText(w))}</li>`).join("")}</ul>` : ""; }
function selectedIds() { return [...state.selected].sort(); }
function message(text, kind = "info") { $("message").hidden = !text; $("message").className = kind; $("message").textContent = text; }
function errorMessage(error) { return error.name === "AbortError" ? "Dịch vụ phản hồi quá lâu. Kiểm tra tiến trình local rồi thử lại." : error.message || "Không thể hoàn tất yêu cầu. Hãy thử lại."; }
function importErrorText(code) {
  const workbookErrors = {
    request_size_limit: "File vượt giới hạn dung lượng.",
    invalid_workbook: "Không đọc được Excel. Kiểm tra định dạng .xlsx, macro hoặc liên kết ngoài.",
    workbook_name_column_required: "Thêm cột Họ và tên ở hàng đầu tiên.",
    workbook_name_required: "Nhập tên sinh viên hoặc bỏ dòng nếu dòng này không dùng.",
    duplicate_workbook_column: "Giữ một cột cho mỗi trường dữ liệu.",
    workbook_text_required: "Đặt ô ở định dạng Văn bản và nhập lại giá trị.",
    workbook_formula_or_error: "Thay công thức hoặc lỗi Excel bằng giá trị văn bản.",
    workbook_sheet_limit: "Workbook có quá nhiều sheet.",
    workbook_column_limit: "Sheet có quá nhiều cột. Giữ tối đa 64 cột.",
  };
  if (workbookErrors[code]) return workbookErrors[code];
  return ({ header_contract: "Tiêu đề cột chưa đúng mẫu. Tải CSV mẫu và giữ nguyên các tên cột.", row_width: "Số ô trong dòng không khớp tiêu đề. Kiểm tra dấu phẩy và dấu ngoặc kép.", file_size_limit: "File vượt giới hạn dung lượng.", row_count_limit: "File vượt số hồ sơ cho phép. Hãy chia thành các đợt nhỏ hơn.", malformed_csv: "Cấu trúc CSV chưa hợp lệ. Hãy lưu lại theo mẫu CSV UTF-8.", empty_dataset: "File chưa có hồ sơ sinh viên.", duplicate_identity: "Mã sinh viên bị trùng trong file.", unknown_taxonomy_tag: "Nhãn chưa có trong danh mục được duyệt.", taxonomy_group_mismatch: "Nhãn không thuộc nhóm dữ liệu của cột này.", tag_evidence_required: "Nhãn cần loại bằng chứng, tham chiếu nguồn và chất lượng bằng chứng.", unsupported_eligibility_flags_require_explicit_policy: "Điều kiện phân công chưa có chính sách xác nhận; hãy để trống trường này.", thesis_terms_do_not_prove_proficiency: "Thuật ngữ trong đề tài chưa chứng minh mức thành thạo cá nhân." })[code] || "Giá trị chưa đúng định dạng hoặc thiếu thông tin bắt buộc. Kiểm tra ô theo mẫu.";
}

function updateControls() {
  const ready = Boolean(state.bootstrap) && !state.busy;
  const cohortReady = ready && state.cohort?.valid && state.selected.size > 0;
  for (const id of ["template", "csv-file", "advisor-search", "select-all", "clear-selection"]) $(id).disabled = !ready;
  $("advisor-list").disabled = !ready;
  $("validate").disabled = !ready || !state.file;
  $("confirm-import").hidden = !previewedWorkbook;
  $("confirm-import").disabled = !ready || !previewedWorkbook;
  $("export-workbook").hidden = !state.cohort?.cohort_id || !/\.xlsx$/i.test(state.file?.name || "");
  $("export-workbook").disabled = !ready || $("export-workbook").hidden;
  $("confirm-policy").disabled = !cohortReady || !state.quotaVerified;
  $("recommend").disabled = !cohortReady;
  $("compare").disabled = !cohortReady || !state.quotaVerified || !$("confirm-policy").checked;
  $("checkpoint-version").disabled = !ready;
  $("export-json").disabled = !state.comparison || state.busy;
  $("export-csv").disabled = !currentResult()?.assignments?.length || state.busy;
  updateChatControls();
}
function busy(value, text = "") { state.busy = value; document.body.setAttribute("aria-busy", String(value)); updateControls(); if (text) message(text); }

async function api(path, body, { blob = false, binary = false } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`${state.base}/api/rebuild${path}`, { method: body === undefined ? "GET" : "POST", headers: { ...(body === undefined ? {} : { "Content-Type": binary ? "application/octet-stream" : "application/json" }) }, ...(body === undefined ? {} : { body: binary ? body : JSON.stringify(body) }), signal: controller.signal, credentials: "same-origin", redirect: "error" });
    if (response.ok && blob) return response.blob();
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) { location.replace("./login.html"); throw new Error("Phiên đăng nhập đã hết hạn."); }
      if (response.status === 403) throw new Error("Không có quyền thực hiện thao tác này.");
      throw new Error(typeof payload.detail === "string" ? payload.detail : payload.error?.message || payload.message || `Dịch vụ trả lỗi ${response.status}. Kiểm tra dữ liệu và thử lại.`);
    }
    return payload.data ?? payload;
  } finally { clearTimeout(timeout); }
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function jsonDetails(value) { return `<pre>${escape(JSON.stringify(value ?? {}, null, 2))}</pre>`; }

function clearResults() {
  stop(); state.comparison = null; state.recommendation = null; state.step = 0;
  $("comparison-result").className = "empty-state"; $("comparison-result").textContent = "Chưa có phân bổ cho hồ sơ và danh sách giảng viên hiện tại.";
  $("allocation-panel").hidden = true; $("recommendation-result").className = "empty-state"; $("recommendation-result").textContent = "Chọn “Xem top-K phù hợp” để lấy khuyến nghị cho danh sách hiện tại."; renderReplay(); updateControls();
}

async function connect() {
  busy(true, "Đang tải danh mục giảng viên và mô hình…");
  try {
    state.base = "";
    state.bootstrap = await api("/bootstrap");
    const retrospective = state.bootstrap.versions?.scope === 'retrospective_document_proxy';
    const versions = state.bootstrap.checkpoint_versions || [];
    $("checkpoint-field").hidden = !versions.length;
    $("checkpoint-version").replaceChildren(...versions.map(v => new Option(`${v} · vòng cuối`, v)));
    if (versions.includes("V3")) $("checkpoint-version").value = "V3";
    if (retrospective) $("model-summary").textContent = versions.length
      ? "Chọn V1, V2 hoặc V3 để so sánh PPO và DQN cùng các baseline trên snapshot của version đó."
      : "Các checkpoint hiển thị bên trên dùng dữ liệu hồi cứu.";
    $("model-source").textContent = retrospective ? "Nguồn: khóa luận và corpus giảng viên hồi cứu. PPO dùng encoder cố định và chia đều chỉ tiêu theo danh sách đã chọn; chưa xác nhận chất lượng hướng dẫn thực tế." : state.bootstrap.versions?.github_bundle_run_id ? "Nguồn: hồ sơ FIT NEU và GitHub đã duyệt. Điểm phù hợp dùng bộ đặc trưng cố định; PPO/DQN học cách phân bổ theo quota." : "Nguồn: hồ sơ FIT NEU đã duyệt. Điểm phù hợp dùng bộ đặc trưng cố định; PPO/DQN học cách phân bổ theo quota.";
    const baselineNotes = {
      hungarian: "Tối ưu tổng điểm theo chỉ tiêu",
      greedy: "Chọn theo điểm cao nhất còn chỗ",
      random: "Chọn ngẫu nhiên trong chỉ tiêu còn lại",
    };
    $("model-status").innerHTML = (state.bootstrap.algorithms || []).toSorted((a,b)=>["ppo","dqn","hungarian","greedy","random"].indexOf(a.id)-["ppo","dqn","hungarian","greedy","random"].indexOf(b.id)).map(a => `<div class="model-row"><b>${escape(labels[a.id] || a.id)}</b><small>${baselineNotes[a.id] || (retrospective ? 'Mô hình nghiên cứu · tài liệu hồi cứu' : 'Học tăng cường · dữ liệu nguồn đã duyệt')}</small><span class="${a.ready ? 'status-good' : 'status-warn'}">${a.ready ? 'Sẵn sàng' : 'Chưa khả dụng'}</span></div>`).join('');
    renderAdvisors(); renderQuota(); message("");
  } catch(error) {
    if (!state.bootstrap) $("assistant-status").textContent = "Chưa kết nối được. Tải lại trang để thử lại.";
    message(errorMessage(error), "error");
  }
  finally { busy(false); }
}

function renderAdvisors() {
  const query = $("advisor-search").value.trim().toLocaleLowerCase("vi-VN");
  const advisors = state.bootstrap?.advisors || [];
  $("selection-count").textContent = `${state.selected.size} đã chọn`;
  const filtered = advisors.filter((a) => `${a.advisor_name} ${a.advisor_id}`.toLocaleLowerCase("vi-VN").includes(query));
  $("advisor-list").innerHTML = `<legend class="sr-only">Chọn giảng viên tham gia</legend>${filtered.map((a) => `<label class="advisor-option ${a.scorable ? "" : "unavailable"}"><input type="checkbox" data-advisor="${escape(a.advisor_id)}" ${state.selected.has(a.advisor_id) ? "checked" : ""} ${!a.scorable ? "disabled" : ""}><span><b>${escape(a.advisor_name || "Giảng viên chưa có tên")}</b>${a.scorable ? "" : "<small>Chưa có tín hiệu phù hợp để phân bổ</small>"}</span></label>`).join("") || `<p class="empty-state">${state.bootstrap ? "Không có giảng viên khớp tìm kiếm." : "Đang tải danh mục giảng viên…"}</p>`}`;
}

function renderQuota() {
  const count = state.cohort?.valid ? state.cohort.row_count : 0; const ids = selectedIds();
  if (!count || !ids.length) { $("quota-preview").textContent = "Nhập hồ sơ hợp lệ và chọn giảng viên để xem quota."; return; }
  const quotas = balancedQuotas(count, ids);
  $("quota-preview").innerHTML = `<strong>${count} sinh viên · ${ids.length} giảng viên · tổng ${count} chỗ</strong><div class="quota-list">${quotas.map((q) => `<span>${escape(nameAdvisor(q.id))}: <b>${q.quota}</b></span>`).join("")}</div><p class="help">Phần dư được chia theo thứ tự mã giảng viên chuẩn. Quota này chỉ có hiệu lực cho danh sách đang chọn.</p>`;
}

async function verifyQuota() {
  if (!state.cohort?.valid || !state.selected.size) return;
  const revision = state.revision;
  try {
    const value = await api("/quotas", { student_count: state.cohort.row_count, advisor_ids: selectedIds() });
    if (revision !== state.revision) return;
    const local = balancedQuotas(state.cohort.row_count, selectedIds());
    if (value.total_capacity !== state.cohort.row_count || local.some((q) => value.quotas.find((r) => r.advisor_id === q.id)?.capacity !== q.quota)) throw new Error("Quota dịch vụ không khớp preview. Hãy tải lại danh mục trước khi phân bổ.");
    state.quotaVerified = true;
    if (value.warnings?.length) message(value.warnings.map(warningText).join(" "));
  } catch (error) { if (revision !== state.revision) return; state.quotaVerified = false; $("confirm-policy").checked = false; message(errorMessage(error), "error"); }
  finally { if (revision === state.revision) updateControls(); }
}

function renderImport(value) {
  const errors = value.errors || [];
  $("import-result").className = "";
  const errorRows = errors.map((r) => `<tr><td>${escape(r.row)}</td><td>${escape(r.column)}</td><td>${escape(importErrorText(r.code))}<details><summary>Mã kiểm tra</summary>${escape(r.code || r.message)}</details></td></tr>`).join("");
  const studentRows = (value.students || []).slice(0, 10).map((s) => `<tr><td>${escape(s.student_name || s.student_id)}<small>${escape(s.student_id)}</small></td><td>${escape(s.thesis_title)}</td></tr>`).join("");
  const table = errors.length
    ? `<table><caption>Lỗi theo từng dòng</caption><thead><tr><th>Dòng</th><th>Cột</th><th>Vấn đề</th></tr></thead><tbody>${errorRows}</tbody></table>`
    : `<table><caption>Xem trước hồ sơ đã nhập</caption><thead><tr><th>Sinh viên</th><th>Đề tài</th></tr></thead><tbody>${studentRows}</tbody></table>`;
  const title = value.valid ? `${value.row_count} hồ sơ hợp lệ` : `${errors.length} lỗi cần sửa trước khi tiếp tục`;
  $("import-result").innerHTML = `<p class="${value.valid ? "status-good" : "status-error"}"><strong>${escape(title)}</strong></p>${warnings(value.warnings)}<div class="table-scroll">${table}</div>${!errors.length && value.row_count > 10 ? `<p class="help">Hiển thị 10/${value.row_count} hồ sơ.</p>` : ""}`;
}

async function importStudents(event, confirm = false) {
  event.preventDefault();
  if (state.busy || !state.file || (confirm && previewedWorkbook !== state.file)) return;
  previewedWorkbook = null;
  busy(true, confirm ? "Đang lưu danh sách…" : "Đang kiểm tra danh sách…"); state.cohort = null; state.quotaVerified = false; clearResults();
  try {
    const limit = state.bootstrap?.limits?.max_csv_bytes || 10 * 1024 * 1024;
    if (state.file.size > limit) throw new Error(`File vượt giới hạn ${Math.round(limit / 1024 / 1024)} MB. Hãy chia nhỏ cohort.`);
    const workbook = /\.xlsx$/i.test(state.file.name);
    let value;
    if (workbook) {
      value = await api(`/students/workbook?confirm=${confirm}`, state.file, { binary: true });
      if (value.valid && !confirm) previewedWorkbook = state.file;
    } else {
      let csvText;
      try { csvText = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await state.file.arrayBuffer()); }
      catch { throw new Error("CSV chưa phải UTF-8 hợp lệ. Hãy lưu lại file theo định dạng CSV UTF-8 rồi thử lại."); }
      value = await api("/students/validate", { csv_text: csvText });
    }
    state.cohort = value.cohort_id ? value : null;
    renderImport(value);
    state.revision++; $("confirm-policy").checked = false; renderQuota();
    message(!value.valid ? "Sửa các dòng báo lỗi rồi chọn lại file." : previewedWorkbook ? "Kiểm tra danh sách rồi bấm Xác nhận danh sách." : "Danh sách đã được lưu. Chọn giảng viên để kiểm tra quota.", value.valid ? "success" : "error");
    if (state.cohort) await verifyQuota();
  } catch (error) { message(errorMessage(error), "error"); $("import-result").textContent = "Chưa có hồ sơ hợp lệ cho lần nhập này."; }
  finally { busy(false); }
}

async function recommend() {
  busy(true, "Đang tính khuyến nghị top-K từ dữ liệu đã kiểm chứng…");
  try {
    const value = await api("/recommend", { cohort_id: state.cohort.cohort_id, advisor_ids: selectedIds(), top_k: Number($("top-k").value) }); state.recommendation = value;
    $("recommendation-result").className = "";
    $("recommendation-result").innerHTML = (value.rankings || []).map((row) => `<article class="recommendation-person"><h3>${escape(nameStudent(row.student_id))}</h3><p class="help">${escape(row.student_id)}</p>${row.recommendations?.length ? `<ol class="recommendation-list">${row.recommendations.map((r) => `<li><div><strong>${escape(r.advisor_name || nameAdvisor(r.advisor_id))}</strong><span class="score-label">${score(r.score)}</span></div><details><summary>Giải thích mức phù hợp</summary>${jsonDetails(r.explanation)}</details></li>`).join("")}</ol>` : `<p class="help">Chưa đủ tín hiệu để xếp hạng trong danh sách đã chọn.</p>`}</article>`).join("") || "Chưa có khuyến nghị đủ bằng chứng.";
    message("Đã tính top-K. Đây là khuyến nghị riêng từng hồ sơ, chưa áp dụng quota toàn cohort.", "success");
  } catch (error) { message(errorMessage(error), "error"); }
  finally { busy(false); }
}

async function compare() {
  if (!$("confirm-policy").checked) return;
  busy(true, "Đang so sánh các phương pháp trên cùng danh sách…"); stop();
  try {
    const version = $("checkpoint-version").value;
    state.comparison = await api("/compare", { cohort_id: state.cohort.cohort_id, advisor_ids: selectedIds(), coordinator_confirmed: true, ...(version ? { checkpoint_version: version } : {}) });
    const entries = Object.entries(state.comparison.results || {}); const preferred = ["ppo", "dqn", "hungarian"].find((key) => state.comparison.results[key]?.trace?.length);
    state.algorithm = preferred || entries[0]?.[0] || "hungarian"; state.step = 0;
    $("comparison-result").className = "comparison-content";
    $("comparison-result").innerHTML = `<div class="comparison-cards">${entries.map(([id]) => {const r=state.comparison.results[id];return `<article class="comparison-model" data-model="${id}"><h3>${escape(labels[id] || id)}</h3><p>${id==='ppo'?'Học chính sách phân bổ':id==='dqn'?'Học giá trị từng lựa chọn':id==='hungarian'?'Tối ưu toàn cục':id==='greedy'?'Chọn cặp tốt nhất còn khả thi':'Lấy mẫu có seed'}</p><span class="metric">${number(r?.metrics?.mean_compatibility,3)}</span><p>Điểm phù hợp trung bình${r?.metrics?.scored_students !== undefined ? ` · ${number(r.metrics.scored_students,0)} SV có điểm` : ""}</p><meter min="0" max="1" value="${Number(r?.metrics?.mean_compatibility ?? 0)}" aria-label="Điểm tương thích trung bình" ${r?.metrics?.mean_compatibility == null ? "hidden" : ""}></meter><p>${r?.status==='feasible'?'Phân bổ hợp lệ':'Chưa có phân bổ hợp lệ'}</p></article>`;}).join('')}</div><table><caption>Kết quả từng thuật toán</caption><thead><tr><th>Thuật toán</th><th>Trạng thái</th><th class="number">Điểm mục tiêu</th><th class="number">Phù hợp trung bình</th><th class="number">Chênh tải chuẩn hóa</th><th class="number">Thời gian (giây)</th><th class="number">Phân bổ đủ</th><th class="number">Vi phạm quota</th></tr></thead><tbody>${entries.map(([id]) => { const r = state.comparison.results[id]; return `<tr><td><strong>${escape(labels[id] || id)}</strong></td><td>${escape(r.status === "feasible" ? "Hợp lệ" : r.status === "infeasible" ? "Không khả thi" : r.status)}${r.diagnostics || r.diagnostic ? `<details><summary>Chi tiết</summary>${jsonDetails(r.diagnostics || r.diagnostic)}</details>` : ""}</td><td class="number">${number(r.metrics?.objective, 3)}</td><td class="number">${number(r.metrics?.mean_compatibility, 3)}</td><td class="number">${number(r.metrics?.normalized_load_imbalance, 3)}</td><td class="number">${number(r.elapsed_seconds, 4)}</td><td class="number">${typeof r.metrics?.coverage === "number" ? `${number(r.metrics.coverage * 100)}%` : "—"}</td><td class="number">${number(r.metrics?.constraint_violations, 0)}</td></tr>`; }).join("")}</tbody></table>${warnings(state.comparison.warnings)}<p class="help">Phù hợp trung bình là điểm đặc trưng của các cặp đã phân bổ. Chênh tải chuẩn hóa là chênh lệch lớn nhất giữa tỷ lệ tải/quota của các giảng viên (thấp hơn là cân bằng hơn). Các chỉ số phục vụ so sánh cùng đầu vào, chưa phải độ chính xác hoặc kết quả hướng dẫn thực tế.</p>`;
    $("result-algorithm").innerHTML = entries.map(([key]) => `<option value="${escape(key)}" ${key === state.algorithm ? "selected" : ""}>${escape(labels[key] || key)}</option>`).join("");
    $("allocation-panel").hidden = !entries.length;
    $("student-comparison-id").replaceChildren(...state.cohort.students.map(
      s => new Option(`${s.student_name || s.student_id} · ${s.student_id}`, s.student_id)));
    renderStudentComparison();
    renderAssignments(); renderReplay(); message("Đã hoàn tất so sánh. Mở bảng phân bổ hoặc phát lại từng quyết định.", "success");
  } catch (error) { message(errorMessage(error), "error"); }
  finally { busy(false); }
}

function currentResult() { return state.comparison?.results?.[state.algorithm]; }
function renderStudentComparison() {
  const id = $("student-comparison-id").value;
  const rows = Object.entries(state.comparison?.results || {}).map(([algorithm, result]) => {
    const pair = result.assignments?.find(row => row.student_id === id);
    const point = pair?.score;
    return `<li><span>${escape(labels[algorithm] || algorithm)}</span><span>${escape(pair ? nameAdvisor(pair.advisor_id) : "Chưa có phân công")}</span><span>${score(point)}</span>${typeof point === "number" ? `<meter min="0" max="1" value="${point}" aria-label="Điểm tương thích"></meter>` : ""}</li>`;
  });
  $("student-comparison-chart").innerHTML = `<ul class="advisor-load-list">${rows.join("")}</ul>`;
}
function renderAssignments() {
  const rows = currentResult()?.assignments || [];
  const counts = new Map();
  for (const row of rows) counts.set(row.advisor_id, (counts.get(row.advisor_id) || 0) + 1);
  const capacities = state.comparison?.policy?.capacities || [];
  const advisorIds = currentResult()?.trace?.[0]?.advisor_ids || state.bootstrap?.advisors?.map(a => a.advisor_id) || [];
  $("advisor-load-chart").innerHTML = rows.length ? `<details><summary>Số sinh viên theo giảng viên</summary><ul class="advisor-load-list">${advisorIds.map((id, index) => {
    const quota = Number(capacities[index] || 0);
    const count = counts.get(id) || 0;
    return quota ? `<li><span>${escape(nameAdvisor(id))}</span><meter min="0" max="${quota}" value="${count}" aria-label="${escape(nameAdvisor(id))}"></meter><span>${count}/${quota} SV</span></li>` : "";
  }).join("")}</ul></details>` : "";
  $("assignments-table").innerHTML = rows.length ? `<table><caption>Đề xuất phân bổ · ${escape(labels[state.algorithm] || state.algorithm)}</caption><thead><tr><th>Sinh viên</th><th>Giảng viên</th><th class="number">Điểm phù hợp</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${escape(nameStudent(r.student_id))}<small>${escape(r.student_id)}</small></td><td>${escape(nameAdvisor(r.advisor_id))}${r.assignment_mode === "quota_only" ? "<small>Ghép theo quota còn lại</small>" : ""}</td><td class="number">${score(r.score ?? currentResult().trace?.find((t) => t.student_id === r.student_id)?.score)}</td></tr>`).join("")}</tbody></table>` : `<p class="empty-state">Thuật toán chưa tạo được phân bổ hợp lệ. Xem chẩn đoán ở bảng so sánh.</p>`; updateControls();
}

function stop() { clearInterval(timer); state.playing = false; if ($("play")) $("play").textContent = "Phát"; }
function renderReplay() {
  const trace = currentResult()?.trace || []; state.step = Math.max(0, Math.min(state.step, trace.length));
  $("step-count").textContent = `${state.step} / ${trace.length} bước`;
  $("previous-step").disabled = state.step === 0; $("next-step").disabled = !trace.length || state.step >= trace.length;
  $("play").disabled = !trace.length; $("reset-replay").disabled = !trace.length;
  const decision = trace[state.step - 1];
  const sceneRegistry = decision?.advisor_registry || trace[0]?.advisor_registry || [];
  if (trace.length && !replayScene && !loadingReplay) {
    loadingReplay = import("./campus-scene.js").then(({ createCampus }) => {
      if (pageClosed) return;
      replayScene = createCampus($("allocation-scene"), {replay:true});
      $("replay-motion").hidden = !replayScene;
      if (replayScene) $("replay-motion").textContent = replayScene.paused ? "Bật chuyển động 3D" : "Tạm dừng chuyển động 3D";
      if (replayScene) renderReplay();
    }).catch(() => { $("replay-motion").hidden = true; });
  }
  replayScene?.update(decision, sceneRegistry, sceneRegistry.map(nameAdvisor), state.step, trace[0]?.capacities || []);
  $("scene-explanation").textContent = decision ? `Bước ${state.step}: ${nameStudent(decision.student_id)} được đề xuất cho ${nameAdvisor(decision.advisor_id)}. Các thanh bên dưới cho biết số chỗ đã dùng.` : "Nhân vật đội mũ là sinh viên; người cầm sách là giảng viên. Nhấn Phát để xem từng đề xuất thực.";
  $("current-decision").className = decision ? "" : "empty-state";
  $("current-decision").innerHTML = decision ? `<strong>${escape(nameStudent(decision.student_id))}</strong> → <strong>${escape(nameAdvisor(decision.advisor_id))}</strong><p>Có ${decision.pre_action_mask?.filter(Boolean).length ?? "—"} giảng viên còn đủ điều kiện ở bước này. Điểm phù hợp của cặp: ${score(decision.score_known ? decision.score : null)}.</p><details><summary>Điểm thành phần và đầu ra mô hình</summary>${jsonDetails({ reward: decision.reward_components, preference: decision.preference_known ? decision.preference : "Chưa biết", policy_output: decision.policy_output || { status: "Không có đầu ra policy/Q được cung cấp" } })}</details>` : trace.length ? "Bắt đầu phát để xem sinh viên, lựa chọn hợp lệ và tải giảng viên ở từng bước." : "Trace sẽ xuất hiện sau lần phân bổ đầu tiên.";
  const registry = decision?.advisor_registry || trace[0]?.advisor_registry || []; const capacities = decision?.capacities || trace[0]?.capacities || []; const loads = decision?.loads_after || registry.map(() => 0);
  $("load-chart").innerHTML = registry.map((id, i) => capacities[i] > 0 ? `<div class="load-row"><span>${escape(nameAdvisor(id))}</span><b>${loads[i] || 0}/${capacities[i]}</b><progress value="${loads[i] || 0}" max="${capacities[i]}" aria-label="Tải ${escape(nameAdvisor(id))}"></progress></div>` : "").join("");
  $("trace-table").innerHTML = trace.length ? `<table><caption>Trace quyết định thực · ${escape(labels[state.algorithm] || state.algorithm)}</caption><thead><tr><th>Bước</th><th>Sinh viên</th><th>Giảng viên</th><th class="number">Điểm</th><th class="number">Reward</th><th>Trạng thái</th></tr></thead><tbody>${trace.map((r, i) => `<tr ${i + 1 === state.step ? 'aria-current="step"' : ""}><td>${i + 1}</td><td>${escape(nameStudent(r.student_id))}</td><td>${escape(nameAdvisor(r.advisor_id))}${r.assignment_mode === "quota_only" ? "<small>Ghép theo quota còn lại</small>" : ""}</td><td class="number">${score(r.score_known ? r.score : null)}</td><td class="number">${number(r.total_reward, 4)}</td><td>${i < state.step ? "Đã phát" : "Chưa phát"}</td></tr>`).join("")}</tbody></table>` : "";
}
function play() {
  if (state.playing) { stop(); return; }
  const trace = currentResult()?.trace || []; if (!trace.length) return;
  if (state.step >= trace.length) state.step = 0;
  state.playing = true; $("play").textContent = "Tạm dừng";
  timer = setInterval(() => { state.step++; renderReplay(); if (state.step >= trace.length) stop(); }, 1000 / Number($("replay-speed").value));
}

async function exportCsv() {
  const run = state.comparison?.run_id;
  const algorithm = state.algorithm;
  if (!run || state.busy) return;
  busy(true);
  try {
    const file = await api(`/runs/${encodeURIComponent(run)}/${encodeURIComponent(algorithm)}.csv`, undefined, { blob: true });
    download(file, `unimatch-${algorithm}-allocation.csv`);
  } catch (error) {
    message(errorMessage(error), "error");
  } finally {
    busy(false);
  }
}

function updateChatControls() {
  const ready = state.bootstrap?.assistant_ready === true;
  $("assistant-question").disabled = !ready;
  $("ask").disabled = !ready || chatPending;
  for (const button of chatSuggestions) button.disabled = $("ask").disabled;
  if (!state.bootstrap) return;
  const status = ready ? "Tra cứu danh mục giảng viên và dẫn nguồn" : "Trợ lý chưa khả dụng.";
  if ($("assistant-status").textContent !== status) $("assistant-status").textContent = status;
}

function setChatOpen(open, opener = $("chat-toggle")) {
  const panel = $("assistant");
  if (panel.hidden === !open) return;
  panel.hidden = !open;
  $("chat-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    chatOpener = opener;
    ($("assistant-question").disabled ? $("chat-close") : $("assistant-question")).focus({ preventScroll: true });
  } else {
    chatOpener?.focus({ preventScroll: true });
  }
}

function addChatMessage(text, user = false) {
  const node = document.createElement("article");
  node.className = user ? "chat-bubble user" : "chat-bubble";
  const title = document.createElement("h3");
  title.textContent = user ? "Bạn" : "UniMatch";
  const body = document.createElement("p");
  body.textContent = text;
  node.append(title, body);
  $("chat-history").append(node);
  return node;
}

async function ask(event) {
  event.preventDefault();
  const input = $("assistant-question");
  const question = input.value.trim();
  if ($("ask").disabled || !question) return;
  const history = $("chat-history");
  addChatMessage(question, true);
  input.value = "";
  input.focus();
  $("chat-suggestions").hidden = true;
  const pending = addChatMessage("Đang tìm nguồn đã duyệt…");
  history.scrollTop = history.scrollHeight;
  chatPending = true;
  updateChatControls();
  try {
    const value = await api("/assistant", { question, cohort_id: state.cohort?.cohort_id || null, top_k: 10 });
    pending.querySelector("p").textContent = value.answer || "Chưa có câu trả lời phù hợp.";
    for (const ranking of value.rankings || []) {
      const row = document.createElement("p");
      row.textContent = `${ranking.advisor_name} · ${ranking.score === null ? "Có nguồn khớp chủ đề" : "Điểm liên hệ chủ đề " + score(ranking.score)}`;
      pending.append(row);
    }
    const sources = document.createElement("ul");
    for (const citation of value.citations || []) {
      let url;
      try { url = new URL(citation.url || citation.source_url); } catch { continue; }
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) continue;
      const link = document.createElement("a");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = citation.title || "Nguồn";
      const item = document.createElement("li");
      item.append(link);
      if (citation.snippet && citation.snippet !== citation.title) {
        const snippet = document.createElement("p");
        snippet.textContent = citation.snippet;
        item.append(snippet);
      }
      sources.append(item);
    }
    if (sources.children.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `Nguồn tham khảo (${sources.children.length})`;
      details.append(summary, sources);
      pending.append(details);
    }
  } catch (error) {
    pending.querySelector("p").textContent = error.name === "AbortError"
      ? "Trợ lý phản hồi quá lâu. Bạn có thể gửi lại câu hỏi."
      : "Chưa tra cứu được nguồn. Bạn có thể gửi lại câu hỏi.";
  } finally {
    chatPending = false;
    updateChatControls();
    if (!$("assistant").hidden) history.scrollTop = pending.offsetTop;
  }
}

$("template").addEventListener("click", async () => { busy(true); try { download(await api("/templates/students.csv", undefined, { blob: true }), "unimatch-students-template.csv"); } catch (e) { message(errorMessage(e), "error"); } finally { busy(false); } });
$("csv-file").addEventListener("change", () => { state.file = $("csv-file").files[0] || null; previewedWorkbook = null; state.cohort = null; state.quotaVerified = false; state.revision++; $("file-info").textContent = state.file ? `${state.file.name} · ${number(state.file.size / 1024)} KB` : "Chưa chọn file."; $("confirm-policy").checked = false; $("import-result").textContent = "Chọn “Kiểm tra hồ sơ” để kiểm tra file mới."; clearResults(); renderQuota(); updateControls(); });
$("import-form").addEventListener("submit", importStudents);
$("confirm-import").addEventListener("click", event => importStudents(event, true));
$("export-workbook").addEventListener("click", async () => {
  const id = state.cohort?.cohort_id;
  if (!id || state.busy) return;
  busy(true, "Đang tạo Excel chuẩn…");
  try {
    const file = await api(`/cohorts/${encodeURIComponent(id)}/students.xlsx`, undefined, { blob: true });
    download(file, "unimatch-sinh-vien.xlsx");
    message("Excel chuẩn đã sẵn sàng để nhập lại.");
  } catch (error) {
    message(errorMessage(error), "error");
  } finally {
    busy(false);
  }
});
$("advisor-search").addEventListener("input", renderAdvisors);
$("advisor-list").addEventListener("change", (event) => { const id = event.target.dataset.advisor; if (!id) return; if (event.target.checked) state.selected.add(id); else state.selected.delete(id); selectionChanged(); });
function selectionChanged() { state.revision++; state.quotaVerified = false; $("confirm-policy").checked = false; clearResults(); renderAdvisors(); renderQuota(); updateControls(); void verifyQuota(); }
$("select-all").addEventListener("click", () => { state.selected = new Set(state.bootstrap.advisors.filter((a) => a.scorable).map((a) => a.advisor_id)); selectionChanged(); });
$("clear-selection").addEventListener("click", () => { state.selected.clear(); selectionChanged(); });
$("confirm-policy").addEventListener("change", updateControls);
$("recommend").addEventListener("click", recommend); $("compare").addEventListener("click", compare);
$("result-algorithm").addEventListener("change", () => { stop(); state.algorithm = $("result-algorithm").value; state.step = 0; renderAssignments(); renderReplay(); });
$("student-comparison-id").addEventListener("change", renderStudentComparison);
$("checkpoint-version").addEventListener("change", clearResults);
$("previous-step").addEventListener("click", () => { stop(); state.step--; renderReplay(); });
$("next-step").addEventListener("click", () => { stop(); state.step++; renderReplay(); });
$("reset-replay").addEventListener("click", () => { stop(); state.step = 0; renderReplay(); });
$("play").addEventListener("click", play); $("replay-speed").addEventListener("change", () => { if (state.playing) { stop(); play(); } });
$("export-json").addEventListener("click", () => download(new Blob([JSON.stringify(state.comparison, null, 2)], { type: "application/json" }), "unimatch-comparison.json"));
$("export-csv").addEventListener("click", exportCsv); $("assistant-form").addEventListener("submit", ask);
$("chat-toggle").addEventListener("click", () => setChatOpen($("assistant").hidden));
$("chat-close").addEventListener("click", () => setChatOpen(false));
document.querySelector("[data-open-chat]").addEventListener("click", (event) => {
  event.preventDefault();
  setChatOpen(true, event.currentTarget);
});
$("assistant").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    setChatOpen(false);
  }
});
$("chat-toggle").addEventListener("keydown", (event) => {
  if (event.key === "Escape") setChatOpen(false);
});
function openChatFromHash() {
  if (location.hash === "#assistant") setChatOpen(true);
}
addEventListener("hashchange", openChatFromHash);
const motionButton=$("replay-motion");
motionButton.hidden = true;
motionButton.addEventListener('click', () => {
  if (replayScene) motionButton.textContent = replayScene.toggle() ? 'Bật chuyển động 3D' : 'Tạm dừng chuyển động 3D';
});
addEventListener('pagehide',()=>{pageClosed=true;stop();replayScene?.destroy();},{once:true});
for (const button of chatSuggestions) {
  button.addEventListener("click", () => {
    $("assistant-question").value = button.dataset.question;
    $("assistant-form").requestSubmit();
  });
}
updateControls(); renderReplay();
const user=await requireSession();
if(user){$("user-greeting").textContent=`Chào ${user.name}`;await connect();openChatFromHash();}
