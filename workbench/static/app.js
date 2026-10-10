"use strict";

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[c]));
const known = (value) => value === null || value === undefined || value === "" ? "未知" : String(value);
const DRAFT_KEY = "gradheat-workbench-draft-v1";
let meta, rows = [], selected = new Map(), details = new Map(), candidateInputs = {};
let view = "catalogue", requestNumber = 0, lastResult = null;
const defaults = () => ({
  title: "我的专业比较", profile: {target_year: 2027, modes: ["全日制"], degrees: ["学术学位", "专业学位"], notes: ""},
  weights: {research: 1, location: 1, cost: 1, career: 1, training: 1}
});
let draft = defaults();

function notify(text, error = false) {
  $("#message").textContent = text;
  $("#message").classList.toggle("error", error);
  $("#message").hidden = false;
}

async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(e => `${e.loc.slice(1).join(".")}：${e.msg}`).slice(0, 3).join("；") : data.detail;
    throw new Error(detail || `请求失败 ${response.status}`);
  }
  return data;
}

function sourceLinks(url, sha) {
  let link = "";
  try {
    const parsed = new URL(url);
    if (["https:", "http:"].includes(parsed.protocol)) {
      link = `<a href="${escapeHTML(parsed.href)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a>`;
    }
  } catch (_) { /* Missing source URL remains missing. */ }
  if (/^[a-f0-9]{64}$/.test(sha || "")) link += `<a href="/api/evidence/${sha}">下载已存原件</a>`;
  return `<div class="source-links">${link || "未记录可打开的原文"}</div>`;
}

function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({snapshot_id: meta.snapshot_id, ids: [...selected.keys()], draft, candidateInputs}));
  } catch (_) { notify("浏览器未能暂存草稿；你仍可使用“保存本次比较”写入本地记录。", true); }
}

function changed() { lastResult = null; $("#analysis").hidden = true; saveDraft(); }

function updateTray() {
  $("#selected-count").textContent = selected.size ? `已选 ${selected.size} / 8 个来源项目` : "尚未选择项目";
  $("#selected-labels").textContent = selected.size ? [...selected.values()].map(p => `${p.unit} ${p.major_code}`).join(" · ") : "从上方选择专业，开始你的比较。";
  $("#next-step").disabled = !selected.size;
  $("#clear-selection").disabled = !selected.size;
  $("#next-step").textContent = view === "catalogue" ? "开始并排核对 →" : "填写偏好情景 →";
}

function switchView(name) {
  view = name;
  for (const section of document.querySelectorAll(".view")) section.hidden = section.id !== name;
  for (const button of document.querySelectorAll(".step")) button.classList.toggle("active", button.dataset.step === name);
  if (name === "facts") renderFacts();
  if (name === "preferences") renderPreferences();
  if (name === "sessions") loadSessions().catch(e => notify(e.message, true));
  updateTray(); window.scrollTo({top: 0, behavior: "smooth"});
}

async function loadCatalogue() {
  const number = ++requestNumber;
  const params = new URLSearchParams({q: $("#search").value, group: $("#group").value,
    degree: $("#degree").value, mode: $("#mode").value, eligibility: $("#eligibility").value});
  const data = await api(`/api/programmes?${params}`);
  if (number !== requestNumber) return;
  rows = data.items;
  $("#results-count").textContent = `${data.total} 个目录来源分组 · ${data.units} 个单位`;
  $("#empty-catalogue").hidden = rows.length > 0; renderCatalogue();
}

function renderCatalogue() {
  $("#catalogue-body").innerHTML = rows.map(p => `<tr>
    <td><strong>${escapeHTML(p.unit)}</strong><small>${escapeHTML(p.department)}</small>${p.campus ? `<small>${escapeHTML(p.campus)}</small>` : ""}</td>
    <td><strong>${escapeHTML(p.major_name)}</strong><small>${escapeHTML(p.major_code)}</small>${p.comparison_pool_scope ? `<small>${escapeHTML(p.comparison_pool_scope)}</small>` : ""}</td>
    <td>${escapeHTML(known(p.degree_type))}<small>${escapeHTML(known(p.mode))}</small></td>
    <td><span class="plan">${escapeHTML(known(p.planned_major_raw))}</span><small>净名额待核</small></td>
    <td><button class="text-button" data-detail="${p.id}">查看资料</button>${p.source_versions > 1 ? `<small>${p.source_versions} 个可能重叠来源</small>` : ""}${p.publication_stage ? `<small class="prelim">${escapeHTML(p.publication_stage)}</small>` : ""}${p.eligible_11408 !== true ? '<small class="prelim">科目不匹配或待核</small>' : ""}</td>
    <td><button class="add-button ${selected.has(p.id) ? "selected" : ""}" data-toggle="${p.id}">${selected.has(p.id) ? "✓ 已选择" : "+ 加入比较"}</button></td>
  </tr>`).join("");
}

async function getDetail(id) {
  if (!details.has(id)) details.set(id, await api(`/api/programmes/${id}`));
  return details.get(id);
}

async function toggle(id) {
  if (selected.has(id)) selected.delete(id);
  else {
    if (selected.size >= 8) throw new Error("一次最多比较8个项目，请先移除一个项目。");
    const detail = await getDetail(id);
    selected.set(id, detail.display);
    if (!candidateInputs[id]) candidateInputs[id] = {personal_eligibility: "unknown", ratings: {}, notes: ""};
  }
  changed(); renderCatalogue(); updateTray();
  if (view === "facts") renderFacts();
  if (view === "preferences") renderPreferences();
}

function factRow(label, value) {
  return `<div class="fact-row"><span>${escapeHTML(label)}</span><b>${escapeHTML(known(value))}</b></div>`;
}

function claimHTML(claim) {
  return `<article class="claim"><strong>${escapeHTML(claim.year || claim.cohort)} · ${escapeHTML(claim.pool)}</strong><div>${escapeHTML(claim.claim)}</div>
    <p>${escapeHTML(claim.limitation || "适用范围待核")}</p><p>核验：${escapeHTML(claim.verification)}</p>
    ${(claim.sources || []).map(s => sourceLinks(s.url, s.sha256) + `<div class="locator">${escapeHTML(s.locator)} · ${escapeHTML((s.sha256 || "").slice(0, 12))}</div>`).join("")}</article>`;
}

function historyHTML(h) {
  return `<article class="history"><strong>${escapeHTML(h.year)} · ${escapeHTML(h.pool)}</strong><p>${escapeHTML(h.special)}</p>
    <div>提取人数 ${escapeHTML(known(h.n))} · ${escapeHTML(h.score_header || "原文成绩")}</div>
    <div>最低 / 最高：${escapeHTML(known(h.minimum))} / ${escapeHTML(known(h.maximum))}</div>
    <div>均值 / 中位数：${escapeHTML(known(h.mean))} / ${escapeHTML(known(h.median))}</div>
    <p>${escapeHTML(h.verification)}</p>${sourceLinks(h.source_url, h.source_sha256)}
    <details><summary>提取位置与原件版本</summary><div class="locator">${escapeHTML((h.locators || []).join("；"))}<br>SHA256 ${escapeHTML(h.source_sha256)}</div></details></article>`;
}

function dossierHTML(detail, year) {
  const p = detail.programme;
  const claims = detail.checked_claims.filter(c => Number(c.year || c.cohort) === year);
  const history = detail.history_candidates.filter(h => h.year === year);
  const gaps = detail.gaps.filter(g => g.year === year);
  let html = "";
  if (year === 2027) {
    html += factRow("学位类型", detail.display.degree_type || "未知");
    html += `<p class="small">类型依据：${escapeHTML(detail.display.degree_type_basis)}</p>`;
    html += factRow("初试科目", (p.subjects || []).join(" + "));
    html += factRow("原文计划（来源分组，不求和）", p.planned_major_raw);
    html += factRow("计划口径", p.quota_definition || p.quota_scope || "待核");
    html += factRow("普通统考净名额", "未知，未验收");
    html += factRow("校区 / 专项 / 项目", [p.campus, p.comparison_pool_scope].filter(Boolean).join("；") || "待核");
    html += factRow("2027排序范围与规则", "待核");
    if (p.publication_stage) html += factRow("目录发布阶段", p.publication_stage);
    if (p.note) html += factRow("目录备注", p.note);
    if (p.directions?.length) html += `<details><summary>查看研究方向（${p.directions.length}）</summary><ul>${p.directions.map(d => `<li>${escapeHTML(d)}</li>`).join("")}</ul></details>`;
    if (p.direction_details?.length) html += `<details><summary>方向原文计划</summary>${p.direction_details.map(d => factRow(d.direction, d.plan_raw)).join("")}</details>`;
    html += `<p class="small">目录核验：${escapeHTML(p.verification || "提取草稿")}</p>`;
    html += sourceLinks(p.source_url, p.source_sha256);
    for (const source of p.plan_sources || []) html += sourceLinks(source.url, source.sha256);
    html += `<details><summary>原文定位与版本</summary><div class="locator">${escapeHTML((p.locators || [p.locator]).join("；"))}<br>SHA256 ${escapeHTML(p.source_sha256)}</div></details>`;
  }
  html += `<h3>${year} 年该单位原文核对</h3><p class="small">这些资料可能覆盖其他院系、专业或类别，需核对适用范围。</p>`;
  html += claims.length ? claims.map(claimHTML).join("") : '<p class="small">当前未取得对应年份的核对资料。</p>';
  if (year !== 2027) {
    html += `<h3>名单统计候选 · ${history.length} 组</h3><p class="small">名单内录取者的描述，不能转换为报考者录取概率。</p>`;
    html += history.length ? history.slice(0, 6).map(historyHTML).join("") : '<p class="small">当前未取得该年份统计候选。</p>';
    if (history.length > 6) html += `<details><summary>查看剩余 ${history.length - 6} 组</summary>${history.slice(6).map(historyHTML).join("")}</details>`;
  }
  html += `<details><summary>资料缺失与核对边界</summary>${gaps.length ? `<ul>${gaps.map(g => `<li>${escapeHTML(g.field)}：${escapeHTML(g.status)}</li>`).join("")}</ul>` : '<p class="small">该年度下载缺失表无此单位条目，不代表专业范围与数据口径均已验收。</p>'}</details>`;
  return html;
}

function renderFacts() {
  const year = Number($("#fact-year").value);
  $("#facts-grid").innerHTML = selected.size ? [...selected].map(([id, p]) => `<section class="comparison-card">
    <div class="card-heading"><div><span class="pill good">${escapeHTML(p.degree_type)} · ${escapeHTML(p.mode)}</span><h3>${escapeHTML(p.unit)}</h3><div class="muted small">${escapeHTML(p.department)}</div><div>${escapeHTML(p.major_code)} ${escapeHTML(p.major_name)}</div></div><button class="text-button" data-toggle="${id}" aria-label="移除${escapeHTML(p.unit)}${escapeHTML(p.major_name)}">移除</button></div>
    ${details.get(id).source_versions > 1 ? '<p class="small prelim">此专业存在可能重叠的来源，计划不能相加。</p>' : ""}${dossierHTML(details.get(id), year)}
  </section>`).join("") : '<div class="empty">先在“筛选专业”中加入候选，再并排查看。</div>';
}

function applyProfile() {
  $("#title").value = draft.title; $("#profile-notes").value = draft.profile.notes;
  for (const [id, value, key] of [["profile-full", "全日制", "modes"], ["profile-part", "非全日制", "modes"], ["profile-academic", "学术学位", "degrees"], ["profile-professional", "专业学位", "degrees"]]) $(`#${id}`).checked = draft.profile[key].includes(value);
}

function renderPreferences() {
  applyProfile();
  $("#weights").innerHTML = Object.entries(meta.dimensions).map(([d, label]) => `<label class="weight-row">${escapeHTML(label)}<input type="number" id="weight-${d}" data-weight="${d}" min="0" max="10" step="0.5" value="${escapeHTML(draft.weights[d])}"></label>`).join("");
  $("#rating-cards").innerHTML = selected.size ? [...selected].map(([id, p]) => {
    const input = candidateInputs[id];
    return `<section class="panel"><h2>${escapeHTML(p.unit)} · ${escapeHTML(p.major_code)} ${escapeHTML(p.major_name)}</h2><p class="small">${escapeHTML(p.department)} · ${escapeHTML(p.mode)}；每个评分留空表示未知。</p>
      <label class="eligibility-label">个人报考资格（自报）<select data-candidate="${id}" data-field="personal_eligibility">
        ${[["unknown", "待核验"], ["self_reported_pass", "自报满足条件（未审核）"], ["self_reported_fail", "自报不满足条件"]].map(([v, label]) => `<option value="${v}" ${input.personal_eligibility === v ? "selected" : ""}>${label}</option>`).join("")}</select></label>
      <div class="table-wrap"><table class="rating-table"><thead><tr><th>适配维度</th><th>下限</th><th>上限</th><th>你的依据 / 假设</th></tr></thead><tbody>
        ${Object.entries(meta.dimensions).map(([d, label]) => `<tr><td>${escapeHTML(label)}</td><td><input type="number" min="0" max="10" step="0.5" aria-label="${escapeHTML(p.unit)} ${escapeHTML(label)}下限" data-candidate="${id}" data-dimension="${d}" data-bound="low" value="${escapeHTML(input.ratings[d]?.low ?? "")}" placeholder="未知"></td><td><input type="number" min="0" max="10" step="0.5" aria-label="${escapeHTML(p.unit)} ${escapeHTML(label)}上限" data-candidate="${id}" data-dimension="${d}" data-bound="high" value="${escapeHTML(input.ratings[d]?.high ?? "")}" placeholder="未知"></td><td><input class="basis" type="text" maxlength="600" aria-label="${escapeHTML(p.unit)} ${escapeHTML(label)}评分依据" data-candidate="${id}" data-dimension="${d}" data-bound="basis" value="${escapeHTML(input.ratings[d]?.basis || "")}" placeholder="个人判断，可选"></td></tr>`).join("")}
      </tbody></table></div><label>项目备注<textarea data-candidate="${id}" data-field="notes" rows="2" maxlength="2000">${escapeHTML(input.notes)}</textarea></label></section>`;
  }).join("") : '<div class="empty">先选择候选项目，再填写适配度。</div>';
  $("#evaluate").disabled = !selected.size; $("#save").disabled = !selected.size;
}

function collectInput() {
  const input = structuredClone(draft);
  for (const d of Object.keys(meta.dimensions)) {
    if (String(input.weights[d]).trim() === "" || !Number.isFinite(Number(input.weights[d]))) throw new Error("请填写所有维度的权重；不计入的维度填0。");
    input.weights[d] = Number(input.weights[d]);
  }
  input.candidates = [...selected.keys()].map(id => {
    const raw = candidateInputs[id], ratings = {};
    for (const [d, rating] of Object.entries(raw.ratings)) {
      const low = String(rating.low ?? "").trim(), high = String(rating.high ?? "").trim();
      if (low === "" && high === "") continue;
      if (low === "" || high === "") throw new Error(`${selected.get(id).unit}的“${meta.dimensions[d]}”需同时填写下限和上限；确定评分可填相同数值。`);
      ratings[d] = {low: Number(low), high: Number(high), basis: rating.basis || ""};
    }
    return {programme_id: id, personal_eligibility: raw.personal_eligibility, ratings, notes: raw.notes};
  });
  return input;
}

function analysisHTML(result) {
  const labels = Object.fromEntries(result.cards.map(c => [c.id, c.label]));
  const names = ids => ids.length ? ids.map(id => escapeHTML(labels[id])).join("<br>") : "尚无法确定";
  const status = {blocked: "不符合筛选条件 · 已排除", pending: "资格待核 · 结论有条件", self_reported_pass: "用户自报符合 · 未审核"};
  return `<h2>在你给定的条件下</h2><p class="small">${escapeHTML(result.interpretation)}</p><p class="small">资料截至 ${escapeHTML(result.source.as_of)} · 快照 ${escapeHTML(result.source.snapshot_id)} · 本次为偏好分析草稿。</p>
    <div class="score-grid">${result.cards.map(card => {
      const score = result.baseline.intervals[card.id];
      return `<article class="score-card"><strong>${escapeHTML(card.label)}</strong><p>${escapeHTML(status[card.hard_constraint_status])}</p>
        ${score ? `<div class="score">${score.low.toFixed(2)} — ${score.high.toFixed(2)}</div><div class="small muted">偏好适配区间 / 10</div><p>已填评分覆盖权重 ${(score.specified_weight * 100).toFixed(0)}%；其余维度保留未知。</p>` : `<p class="prelim">${card.blocked_reasons.map(escapeHTML).join("；")}</p>`}
        ${result.baseline.certain_best.includes(card.id) ? '<span class="pill good">本次偏好区间内确定最优</span>' : result.baseline.potential_best.includes(card.id) ? '<span class="pill">本次偏好区间内可能最优</span>' : ""}<p>普通统考净名额、2027排序范围仍待核。</p></article>`;
    }).join("")}</div>
    <p>在本轮有限权重测试中均为确定最优：<br><strong>${names(result.stable_certain_best)}</strong></p>
    <p class="small">“确定最优”表示在填写的偏好区间内不低于其余候选，不表示录取更稳。范围重叠时保留多个可能最优项目。</p>
    <details><summary>查看 ${result.sensitivity.length} 个权重变动情景</summary><div class="table-wrap sensitivity"><table><thead><tr><th>改动</th><th>可能最优</th><th>确定最优</th></tr></thead><tbody>${result.sensitivity.map(s => `<tr><td>${escapeHTML(meta.dimensions[s.dimension])} × ${s.factor}</td><td>${names(s.potential_best)}</td><td>${names(s.certain_best)}</td></tr>`).join("")}</tbody></table></div></details>
    <details><summary>本次分析的假设与边界</summary><ul>${result.assumptions.map(a => `<li>${escapeHTML(a)}</li>`).join("")}</ul></details>`;
}

async function compare() {
  lastResult = await api("/api/compare", collectInput());
  $("#analysis").innerHTML = analysisHTML(lastResult); $("#analysis").hidden = false;
  $("#analysis").scrollIntoView({behavior: "smooth", block: "start"});
}

async function saveComparison() {
  const result = await api("/api/sessions", collectInput());
  notify(result.reused ? "本次输入与已保存记录一致，已复用原记录。" : "比较已保存到本地，资料快照和偏好输入一并保留。");
  switchView("sessions");
}

async function loadSessions() {
  const data = await api("/api/sessions");
  $("#session-list").innerHTML = data.items.length ? data.items.map(s => `<article class="panel session-card"><div><h3>${escapeHTML(s.title)}</h3><p>${s.candidate_count} 个来源项目 · ${escapeHTML(new Date(s.created_at).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai"}))}</p><p>快照 ${escapeHTML(s.snapshot_id)} · ${escapeHTML(s.analysis_version)}</p></div><div class="actions"><button class="secondary" data-session="${s.session_id}">查看记录</button><button class="text-button" data-resume="${s.session_id}">复制为新草稿</button><a href="/api/sessions/${s.session_id}/export?format=md">下载报告</a><a href="/api/sessions/${s.session_id}/export?format=json">下载 JSON</a></div></article>`).join("") : '<div class="empty">还没有保存记录。先选专业、填写偏好，再保存比较。</div>';
}

async function openSession(id) {
  const data = await api(`/api/sessions/${id}`);
  $("#detail-content").innerHTML = `<h2>${escapeHTML(data.title)}</h2><div class="notice">这是当时保存的记录，展示旧快照与旧输入。当前草稿保持不变。</div>${analysisHTML(data.result)}<details><summary>查看完整报告与原始输入依据</summary><pre class="report-text">${escapeHTML(data.report_md)}</pre></details>`;
  $("#detail-dialog").showModal();
}

async function resumeSession(id) {
  const data = await api(`/api/sessions/${id}`), input = data.result.input;
  if (data.snapshot_id !== meta.snapshot_id) throw new Error("这份记录属于其他资料快照。可以查看或下载旧记录；请在当前快照重新选择项目。");
  const restored = await Promise.all(input.candidates.map(c => getDetail(c.programme_id)));
  selected = new Map(restored.map(d => [d.programme.id, d.display]));
  draft = {title: input.title, profile: input.profile, weights: input.weights};
  candidateInputs = Object.fromEntries(input.candidates.map(c => [c.programme_id, {personal_eligibility: c.personal_eligibility, ratings: c.ratings, notes: c.notes}]));
  changed(); renderCatalogue(); switchView("preferences");
  notify("已复制为新草稿。修改输入后可重新计算和保存，原记录保留。");
}

document.addEventListener("click", async event => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.dataset.step) switchView(button.dataset.step);
    if (button.dataset.toggle) await toggle(button.dataset.toggle);
    if (button.dataset.detail) {
      const detail = await getDetail(button.dataset.detail);
      $("#detail-content").innerHTML = `<h2>${escapeHTML(detail.programme.unit)} · ${escapeHTML(detail.programme.major_name)}</h2><p>${escapeHTML(detail.programme.department)} · ${escapeHTML(detail.programme.major_code)}</p>${dossierHTML(detail, 2027)}`;
      $("#detail-dialog").showModal();
    }
    if (button.dataset.session) await openSession(button.dataset.session);
    if (button.dataset.resume) await resumeSession(button.dataset.resume);
    if (button.id === "close-detail") $("#detail-dialog").close();
    if (button.id === "show-sessions") switchView("sessions");
    if (button.id === "next-step") switchView(view === "catalogue" ? "facts" : "preferences");
    if (button.id === "clear-selection") { selected.clear(); changed(); renderCatalogue(); switchView("catalogue"); }
    if (button.id === "evaluate") await compare();
    if (button.id === "save") await saveComparison();
  } catch (e) { notify(e.message, true); }
});

document.addEventListener("input", event => {
  const field = event.target;
  if (field.dataset.weight) draft.weights[field.dataset.weight] = field.value;
  else if (field.dataset.candidate) {
    const input = candidateInputs[field.dataset.candidate];
    if (field.dataset.dimension) {
      const d = field.dataset.dimension;
      if (!input.ratings[d]) input.ratings[d] = {low: "", high: "", basis: ""};
      input.ratings[d][field.dataset.bound] = field.value;
    } else input[field.dataset.field] = field.value;
  } else if (field.id === "title") draft.title = field.value;
  else if (field.id === "profile-notes") draft.profile.notes = field.value;
  else if (field.id.startsWith("profile-")) {
    draft.profile.modes = [$("#profile-full").checked && "全日制", $("#profile-part").checked && "非全日制"].filter(Boolean);
    draft.profile.degrees = [$("#profile-academic").checked && "学术学位", $("#profile-professional").checked && "专业学位"].filter(Boolean);
  } else return;
  changed();
});

let searchTimer;
$("#search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadCatalogue().catch(e => notify(e.message, true)), 180); });
for (const id of ["group", "degree", "mode", "eligibility"]) $(`#${id}`).addEventListener("change", () => loadCatalogue().catch(e => notify(e.message, true)));
$("#fact-year").addEventListener("change", renderFacts);

async function start() {
  meta = await api("/api/meta");
  $("#as-of").textContent = `资料截至 ${meta.as_of}`;
  $("#source-caption").textContent = `资料版本 ${meta.snapshot_id.slice(0, 10)}`;
  $("#coverage").innerHTML = `<div><strong>${meta.counts.subject_matched_units}</strong>科目匹配单位</div><div><strong>${meta.counts.subject_matched_groups}</strong>目录来源分组</div>`;
  $("#group").innerHTML += meta.groups.map(g => `<option>${escapeHTML(g)}</option>`).join("");
  try {
    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
    if (stored && stored.snapshot_id === meta.snapshot_id) {
      const restored = await Promise.all(stored.ids.map(id => getDetail(id)));
      selected = new Map(restored.map(d => [d.programme.id, d.display]));
      draft = stored.draft; candidateInputs = stored.candidateInputs;
    } else if (stored) {
      localStorage.setItem(`${DRAFT_KEY}-archive-${stored.snapshot_id}`, JSON.stringify(stored));
      notify("资料版本已变化，旧草稿已暂存到浏览器归档；已保存记录仍可打开。请重新选择当前项目。");
    }
  } catch (_) { notify("浏览器草稿未能恢复，已保存的本地记录仍可查看。", true); }
  await loadCatalogue(); updateTray();
}

start().catch(e => notify(`工作台加载失败：${e.message}`, true));
