const number = value => Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 6 });
const node = (tag, text) => { const value = document.createElement(tag); if (text != null) value.textContent = text; return value; };
const svgNode = (tag, attributes = {}) => {
  const value = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, item] of Object.entries(attributes)) value.setAttribute(key, String(item));
  return value;
};

function table(headers, rows, caption) {
  const result = node('table'); result.append(node('caption', caption));
  const head = result.createTHead().insertRow();
  for (const label of headers) { const cell = node('th', label); cell.scope = 'col'; head.append(cell); }
  const body = result.createTBody();
  for (const values of rows) { const row = body.insertRow(); for (const value of values) row.insertCell().textContent = value; }
  return result;
}

function chart(data, version, cohort) {
  const section = node('section'); section.append(node('h3', `${version} · ${cohort.semester_id} · ${cohort.validation} sinh viên validation`));
  const series = Object.entries(data.curves).filter(([key]) => key.startsWith(`${version}-`));
  const values = series.flatMap(([, rows]) => rows).filter(r => Number.isFinite(r.validation_objective_per_student));
  if (!values.length) { section.append(node('p', 'Chưa có learning curve hợp lệ.')); return section; }
  const width = 1000, height = 300, left = 70, right = 60, top = 24, bottom = 52;
  const maxX = Math.max(1, ...values.map(r => r.relative_step));
  const baseline = values[0].hungarian_objective_per_student;
  const maxY = Math.max(.01, baseline, ...values.map(r => r.validation_objective_per_student)) * 1.12;
  const x = value => left + value / maxX * (width - left - right);
  const y = value => height - bottom - value / maxY * (height - top - bottom);
  const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-labelledby': `curve-${version}-title curve-${version}-desc` });
  const title = svgNode('title', { id: `curve-${version}-title` }); title.textContent = `Validation ${version} theo bước thêm trong từng round`;
  const desc = svgNode('desc', { id: `curve-${version}-desc` }); desc.textContent = 'Các đường PPO theo round, đối chiếu Hungarian. Utility không phải phần trăm chính xác; dữ liệu chi tiết ở bảng bên dưới.';
  svg.append(title, desc);
  const text = (content, attributes) => { const value = svgNode('text', { fill: '#466780', ...attributes }); value.textContent = content; svg.append(value); };
  for (let i = 0; i <= 4; i++) {
    const value = maxY * i / 4;
    svg.append(svgNode('line', { x1: left, x2: width - right, y1: y(value), y2: y(value), stroke: '#dceaf4' }));
    text(value.toFixed(3), { x: left - 10, y: y(value) + 4, 'text-anchor': 'end' });
    text(`${number(maxX * i / 4000)}k`, { x: x(maxX * i / 4), y: height - 26, 'text-anchor': 'middle' });
  }
  text('Bước thêm của round', { x: width / 2, y: height - 3, 'text-anchor': 'middle' });
  svg.append(svgNode('line', { x1: left, x2: width - right, y1: y(baseline), y2: y(baseline), stroke: '#334155', 'stroke-width': 2, 'stroke-dasharray': '8 5' }));
  const colors = ['#1167bd', '#0f766e', '#965e1f', '#7048a5'];
  const dashes = ['', '6 3', '2 3', '10 3 2 3'];
  series.forEach(([key, rows], index) => {
    const valid = rows.filter(r => Number.isFinite(r.validation_objective_per_student));
    svg.append(svgNode('polyline', { points: valid.map(r => `${x(r.relative_step)},${y(r.validation_objective_per_student)}`).join(' '), fill: 'none', stroke: colors[index % 4], 'stroke-width': 2.5, 'stroke-dasharray': dashes[index % 4] }));
    for (const row of valid) {
      const dot = svgNode('circle', { cx: x(row.relative_step), cy: y(row.validation_objective_per_student), r: 3, fill: colors[index % 4] });
      const label = svgNode('title'); label.textContent = `${key} · ${number(row.relative_step)} step · utility ${number(row.validation_objective_per_student)}`;
      dot.append(label); svg.append(dot);
    }
  });
  const scroll = node('div'); scroll.className = 'table-scroll semester-curve'; scroll.tabIndex = 0;
  scroll.setAttribute('aria-label', `Biểu đồ ${version}, có thể cuộn ngang`); scroll.append(svg);
  section.append(scroll, node('p', 'R1: xanh dương, nét liền · R2: xanh lục, nét đứt · R3: nâu, nét chấm · R4: tím, nét xen kẽ. Hungarian: xám, nét đứt dài.'));
  return section;
}

export function renderSemesterTraining(data) {
  const byId = id => document.getElementById(id);
  byId('training-status').textContent = `Đã hoàn tất ${data.results.length}/${Object.keys(data.cohorts).length * data.rounds_per_version} lượt fit · ${number(data.steps_per_round)} step/round · một seed · test ngoài đã mở một lần.`;
  const summary = byId('training-summary'); summary.replaceChildren();
  for (const [version, cohort] of Object.entries(data.cohorts)) {
    const article = node('article'); article.className = 'training-model';
    article.append(node('h2', `${version} · ${cohort.semester_id}`));
    const list = node('dl'); const feedback = data.feedback_counts[version];
    for (const [label, value] of [['Sinh viên train / validation', `${cohort.train} / ${cohort.validation}`], ['Compute đã chạy', `${number(data.results.filter(r => r.version === version).reduce((sum, r) => sum + r.steps_added, 0))} step`], ['Có thông tin R2 / R3', `${feedback.r2} / ${feedback.r3}`]]) list.append(node('dt', label), node('dd', value));
    article.append(list); summary.append(article);
  }
  byId('training-chart').replaceChildren(...Object.entries(data.cohorts).map(([version, cohort]) => chart(data, version, cohort)));
  byId('training-explanation').textContent = `Tổng compute: ${number(data.total_compute_steps)} step. Checkpoint được giữ: ${data.selected_checkpoint}, bộ đếm trọng số ${number(data.selected_weight_steps)} step. Compute của candidate bị loại không được cộng vào checkpoint được giữ. Không so điểm trực tiếp giữa các cohort khác nhau.`;
  const decision = { accepted: 'Giữ bản mới', rejected: 'Giữ bản trước', inconclusive: 'Chưa đủ bằng chứng' };
  byId('training-table').replaceChildren(table(['Version', 'Round', 'Step thêm', 'Utility trước', 'Utility sau', 'Quyết định'], data.results.map(r => [r.version, `R${r.round}`, number(r.steps_added), r.parent_score == null ? '—' : number(r.parent_score), number(r.candidate_score), decision[r.decision] || r.decision]), 'Validation từng round trên cohort cố định của version'));
  byId('training-table').append(table(['Version / round', 'Step thêm', 'Utility validation', 'Hungarian'], Object.entries(data.curves).flatMap(([key, rows]) => rows.map(r => [key, number(r.relative_step), number(r.validation_objective_per_student), number(r.hungarian_objective_per_student)])), 'Chi tiết các điểm trên learning curve'));
  byId('training-table').tabIndex = 0;
  byId('training-table').setAttribute('aria-label', 'Bảng validation và learning curve, có thể cuộn');
  const container = byId('training-source');
  container.textContent = `Nguồn: ${data.run_id}. Hồ sơ giảng viên và khóa luận là proxy hồi cứu; chỉ tạo tín hiệu từ thông tin khảo sát có thật. Trạng thái đăng ký tự khai không đồng nghĩa giảng viên nhận/từ chối; R3 không tự đổi ràng buộc. Chưa xác nhận thời điểm khả dụng đầu kỳ hoặc chất lượng hướng dẫn thực tế.`;
  let external = document.getElementById('external-test-section');
  if (!external) { external = node('section'); external.id = 'external-test-section'; external.className = 'work-section'; container.parentElement.after(external); }
  external.replaceChildren(node('h2', `Test ngoài ${data.test.semester_id} · ${data.test.n_test} sinh viên`), node('p', 'Chỉ đánh giá sau khi đóng băng model. Không dùng kết quả này để train, chọn checkpoint hoặc chỉnh ngưỡng.'));
  const scroll = node('div'); scroll.className = 'table-scroll'; scroll.tabIndex = 0;
  scroll.setAttribute('aria-label', 'Bảng kết quả test ngoài, có thể cuộn ngang');
  scroll.append(table(['Phương pháp', 'Utility / sinh viên', 'Bao phủ', 'Vi phạm'], Object.entries(data.test.metrics).map(([name, result]) => [name.toUpperCase(), number(result.objective_per_student), `${number(result.metrics.coverage * 100)}%`, number(result.metrics.constraint_violations)]), 'Utility là mục tiêu phân công, không phải accuracy'));
  external.append(scroll);
}
