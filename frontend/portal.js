const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => Number(value).toLocaleString('vi-VN', { maximumFractionDigits: 3 });

export async function requireSession() {
  try {
    const response = await fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) { location.replace('./login.html'); return null; }
    return await response.json();
  } catch { document.body.insertAdjacentHTML('afterbegin', '<p role="alert">Không kết nối được dịch vụ. Hãy tải lại trang.</p>'); return null; }
}

export function wireLogout() {
  document.querySelectorAll('[data-logout]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true;
    try { const result = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }); if (!result.ok) throw new Error(); sessionStorage.removeItem('unimatch-rebuild-token'); location.replace('./login.html'); }
    catch { button.disabled = false; button.textContent = 'Thử đăng xuất lại'; }
  }));
}

async function login() {
  try {
    if ((await fetch('/api/auth/me')).ok) { location.replace('./landing.html'); return; }
  } catch { $('auth-notice').textContent='Không kết nối được dịch vụ đăng nhập. Kiểm tra mạng và tải lại trang.'; return; }
  let config;
  const buttons = [...document.querySelectorAll('[data-provider]')];
  function availability() { buttons.forEach(button => { button.disabled = !config?.providers[button.dataset.provider]; }); }
  for (const tab of [$('login-tab'), $('register-tab')]) {
    tab.addEventListener('click', () => {
      const register = tab.id === 'register-tab';
      for (const item of [$('login-tab'), $('register-tab')]) { item.setAttribute('aria-selected', String(item === tab)); item.tabIndex = item === tab ? 0 : -1; }
      $('auth-content').setAttribute('aria-labelledby', tab.id);
      $('auth-title').textContent = register ? 'Bắt đầu cùng UniMatch.' : 'Chào bạn trở lại.';
      $('auth-description').textContent = register ? 'Chọn tài khoản để tạo hồ sơ đăng nhập của bạn.' : 'Đăng nhập để bắt đầu hành trình khóa luận.';
    });
    tab.addEventListener('keydown', event => { if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? $('login-tab') : event.key === 'End' ? $('register-tab') : tab.id === 'login-tab' ? $('register-tab') : $('login-tab'); next.click(); next.focus(); } });
  }
  if (new URLSearchParams(location.search).has('error')) $('auth-status').textContent = 'Đăng nhập chưa hoàn tất. Hãy xác minh lại và thử lần nữa.';
  try {
    const response = await fetch('/api/auth/config'); if (!response.ok) throw new Error(); config = await response.json();
    const missing = Object.entries(config.providers).filter(([,ready]) => !ready).map(([provider]) => ({google:'Google',github:'GitHub',facebook:'Facebook'}[provider]));
    $('auth-notice').textContent = missing.length ? `Chưa cấu hình đăng nhập ${missing.join(', ')}. Người quản trị cần bổ sung cấu hình dịch vụ.` : 'Chọn tài khoản để tiếp tục.';
    availability();
    buttons.forEach(button => button.addEventListener('click', async () => {
      buttons.forEach(item => {item.disabled=true;}); $('auth-status').textContent='Đang chuyển đến dịch vụ đăng nhập…';
      try {
        const response = await fetch(`/api/auth/start/${button.dataset.provider}`, {method:'POST', headers:{'Content-Type':'application/json'},body:'{}'});
        const result = await response.json(); if (!response.ok) throw new Error();
        const url = new URL(result.url); if (!['accounts.google.com','github.com','www.facebook.com'].includes(url.hostname) || url.protocol !== 'https:') throw new Error(); location.assign(url.href);
      } catch { availability(); $('auth-status').textContent='Không thể bắt đầu đăng nhập. Hãy thử lại sau ít phút.'; }
    }));
  } catch { $('auth-notice').textContent='Không tải được cấu hình đăng nhập. Kiểm tra dịch vụ và tải lại trang.'; }
}

async function training() {
  const refresh = $('refresh-training'); refresh.disabled = true;
  try {
    const response = await fetch('/api/rebuild/training', {cache:'no-store'});
    const data = await response.json(); if (!response.ok) throw new Error(response.status === 409 ? 'Báo cáo chưa khớp mô hình đang phục vụ.' : 'Chưa tải được báo cáo. Hãy thử lại.');
    if (data.mode === 'semester_nested') {
      const { renderSemesterTraining } = await import('./nested-research.js');
      renderSemesterTraining(data); return;
    }
    $('training-status').textContent = `Báo cáo lần chạy đã lưu · cập nhật ${new Date(data.updated_at*1000).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'})}. Không phải tiến trình train trực tiếp.`;
    $('training-summary').innerHTML = Object.entries(data.models).map(([key,model]) => `<article class="training-model" data-model="${key}"><h2>${key.toUpperCase()}</h2><strong>${number(model.trained_steps)}</strong> bước / seed<progress value="${model.trained_steps}" max="${model.target_steps}" aria-label="Tiến độ ${key.toUpperCase()}"></progress><dl><dt>Ngân sách</dt><dd>${number(model.target_steps)} bước</dd><dt>Số seed</dt><dd>${model.seeds}</dd><dt>Mô hình được chọn tại</dt><dd>${number(model.selected_steps)} bước</dd><dt>Ổn định trong cửa sổ đo</dt><dd>${model.plateau ? 'Đạt tiêu chí' : 'Chưa đạt'}</dd></dl><p>Độ dao động ${number(model.observed_range)}; ngưỡng ${number(model.criterion.max_mean_compatibility_range)} trong ${model.criterion.evaluations} lần đánh giá cuối.</p></article>`).join('');
    const width = 1000, height = 410, left = 62, right = 24, top = 25, bottom = 65;
    const all = Object.values(data.models).flatMap(model=>model.curve);
    const maxX = Math.max(...all.map(row=>row.steps)), maxY = Math.ceil(Math.max(data.baseline_objective,...all.map(row=>row.ci95[1]))*1.12);
    const x = value => left + value/maxX*(width-left-right), y = value => height-bottom-value/maxY*(height-top-bottom);
    const points = (rows,key) => rows.map(row=>`${x(row.steps)},${y(key(row))}`).join(' ');
    let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="curve-title curve-desc"><title id="curve-title">Điểm validation theo số bước huấn luyện</title><desc id="curve-desc">PPO và DQN vẫn dao động, dưới đường đối chiếu Hungarian. Số liệu đầy đủ có trong bảng bên dưới.</desc>`;
    for(let i=0;i<=maxY;i++) svg+=`<line x1="${left}" x2="${width-right}" y1="${y(i)}" y2="${y(i)}" stroke="#dceaf4"/><text x="${left-12}" y="${y(i)+5}" text-anchor="end" fill="#466780">${i}</text>`;
    for(let i=0;i<=4;i++){const step=maxX*i/4;svg+=`<text x="${x(step)}" y="${height-35}" text-anchor="middle" fill="#466780">${number(step/1000)}k</text>`;}
    svg+=`<text x="500" y="${height-5}" text-anchor="middle" fill="#466780">Số bước học / seed</text><line x1="${left}" x2="${width-right}" y1="${y(data.baseline_objective)}" y2="${y(data.baseline_objective)}" stroke="#188367" stroke-width="2" stroke-dasharray="8 5"/>`;
    for(const [key,model] of Object.entries(data.models)) {
      const color=key==='ppo'?'#1167bd':'#c17520';
      svg+=`<polygon points="${points(model.curve,row=>row.ci95[1])} ${points([...model.curve].reverse(),row=>row.ci95[0])}" fill="${color}" opacity=".1"/><polyline points="${points(model.curve,row=>row.mean)}" fill="none" stroke="${color}" stroke-width="3"/>`;
      for(const row of model.curve) svg+=`<circle cx="${x(row.steps)}" cy="${y(row.mean)}" r="${row.steps===model.selected_steps?7:3}" fill="${color}"><title>${key.toUpperCase()} · ${number(row.steps)} bước · điểm ${number(row.mean)}${row.steps===model.selected_steps?' · mô hình được chọn':''}</title></circle>`;
    }
    $('training-chart').innerHTML=svg+'</svg>';
    $('training-explanation').textContent=`Đối chiếu Hungarian: ${number(data.baseline_objective)} điểm. Chấm lớn là mốc được chọn để phục vụ. Cả hai mô hình chưa đạt tiêu chí ổn định trong ngân sách đã thử.`;
    $('training-source').textContent=`Nguồn: ${data.source}. ${data.validation_students} sinh viên validation, ${data.models.ppo.seeds} seed cho mỗi thuật toán. Lần chạy: ${data.run_id}.`;
    $('training-table').innerHTML=`<table><caption>Số liệu validation thực</caption><thead><tr><th>Mô hình</th><th>Bước</th><th>Điểm trung bình</th><th>Khoảng tin cậy 95%</th></tr></thead><tbody>${Object.entries(data.models).flatMap(([key,model])=>model.curve.map(row=>`<tr><td>${key.toUpperCase()}</td><td>${number(row.steps)}</td><td>${number(row.mean)}</td><td>${row.ci95.map(number).join(' – ')}</td></tr>`)).join('')}</tbody></table>`;
  } catch(error) { $('training-status').textContent=error.message; }
  finally { refresh.disabled=false; }
}

wireLogout();
if ($('auth-title')) await login();
else if (!$('import-form')) { const user=await requireSession(); if(user && $('training-chart')) { await training(); $('refresh-training').addEventListener('click',training); } }
if ($('campus')) {
  try {
    const {createCampus}=await import('./campus-scene.js'); const scene=createCampus($('campus')); const toggle=$('motion-toggle');
    if(scene){toggle.textContent=scene.paused?'Bật chuyển động':'Tạm dừng chuyển động';toggle.addEventListener('click',()=>{toggle.textContent=scene.toggle()?'Bật chuyển động':'Tạm dừng chuyển động';});addEventListener('pagehide',()=>scene.destroy(),{once:true});} else toggle.hidden=true;
  } catch { $('motion-toggle').hidden=true; }
}
