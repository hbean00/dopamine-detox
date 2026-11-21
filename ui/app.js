/* 도파민 디톡스 — UI */
(function () {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const DAYS = '월화수목금토일';
  const TARGET_KEYS = ['instagram', 'youtube', 'kakaotalk', 'webtoon'];
  const TARGET_LABEL = { instagram: 'Instagram', youtube: 'YouTube', kakaotalk: '카카오톡', webtoon: '웹툰' };
  const SOURCE_LABEL = { manual: '직접 시작', schedule: '반복 일정', focustodo: 'Focus To-Do 연동' };
  const OBJ = { instagram: 'Instagram을', youtube: 'YouTube를', kakaotalk: '카카오톡을', webtoon: '웹툰을' };
  const FTD_STATUS = { focus: '집중 중', break: '휴식 중', paused: '일시정지', idle: '대기', not_running: '실행 안 됨' };

  let api = null;
  let isMock = false;
  let S = null;              // 최근 상태
  let polling = false;
  let selectedMin = 60;
  let allowTarget = null;
  let allowMin = 15;
  let settingsCache = null;
  let settingsDirty = false;

  /* ---------- API 연결 ---------- */
  function connect() {
    return new Promise((resolve) => {
      let done = false;
      const finish = (real) => {
        if (done) return; done = true;
        if (real && window.pywebview && window.pywebview.api) { api = window.pywebview.api; }
        else { api = window.createMockApi(); isMock = true; }
        resolve();
      };
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_state === 'function') return finish(true);
      window.addEventListener('pywebviewready', () => finish(true));
      setTimeout(() => finish(!!(window.pywebview && window.pywebview.api && window.pywebview.api.get_state)), 1500);
    });
  }

  async function call(name, ...args) {
    try {
      const fn = api[name];
      if (typeof fn !== 'function') throw new Error(`${name} 기능을 찾을 수 없습니다.`);
      const res = await fn.apply(api, args);
      if (res && typeof res === 'object' && res.ok === false) {
        toast(res.error || '요청을 처리하지 못했습니다.', true);
      }
      return res;
    } catch (e) {
      toast((e && e.message) || String(e), true);
      return null;
    }
  }

  /* ---------- 유틸 ---------- */
  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const p = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
  }
  function clock(epoch) {
    const d = new Date(epoch * 1000);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  function relative(sec) {
    if (sec < 60) return '곧';
    const m = Math.round(sec / 60);
    if (m < 60) return `${m}분 뒤`;
    const h = Math.floor(m / 60), r = m % 60;
    if (h < 24) return r ? `${h}시간 ${r}분 뒤` : `${h}시간 뒤`;
    return `${Math.floor(h / 24)}일 뒤`;
  }
  function minutesText(min) {
    if (min < 60) return `${min}분`;
    const h = Math.floor(min / 60), m = min % 60;
    return m ? `${h}시간 ${m}분` : `${h}시간`;
  }
  function setText(el, t) { if (el && el.textContent !== t) el.textContent = t; }
  function setHtml(el, h) { if (el && el.dataset.h !== h) { el.dataset.h = h; el.innerHTML = h; } }
  // "29분", "1시간 5분"처럼 글자가 섞인 타이머는 숫자만 크게, 단위는 작게
  function timerHtml(t) { return esc(t).replace(/([^\d:\s]+)/g, '<span class="cd-unit">$1</span>'); }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

  function toast(msg, isError) {
    const el = document.createElement('div');
    el.className = 'toast' + (isError ? ' is-error' : '');
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(() => el.remove(), isError ? 4200 : 2600);
  }

  /* ---------- 내비게이션 ---------- */
  function show(view) {
    $$('.nav-item').forEach((b) => b.classList.toggle('is-current', b.dataset.view === view));
    $$('.view').forEach((v) => v.classList.toggle('is-current', v.id === 'view-' + view));
    $('.main').scrollTop = 0;
    if (view === 'schedule') loadSchedules();
    if (view === 'history') loadHistory();
    if (view === 'settings' && !settingsDirty) loadSettings();
  }

  /* ---------- 홈 ---------- */
  function buildTargets() {
    const wrap = $('#targets');
    wrap.innerHTML = TARGET_KEYS.map((k) => `
      <div class="target" data-key="${k}" data-s="idle">
        <span class="target-name">${TARGET_LABEL[k]}</span>
        <span class="target-state"><span class="target-label">대기</span><span class="target-time"></span></span>
        <span class="target-reason" hidden></span>
        <div class="target-action"></div>
      </div>`).join('');
  }

  function renderTarget(k, t, st) {
    const el = $(`.target[data-key="${k}"]`);
    if (!el || !t) return;
    setText($('.target-name', el), t.label || TARGET_LABEL[k]);
    const openLeft = t.allow_until ? t.allow_until - st.now : 0;
    let s, label, time = '', action = '';
    if (!t.enabled) { s = 'off'; label = '꺼짐'; }
    else if (openLeft > 0) { s = 'open'; label = '잠깐 열림'; time = `${fmt(openLeft)} 남음`; action = 'revoke'; }
    else if (st.active && t.blocked) { s = 'blocked'; label = '차단 중'; if (t.allowable) action = 'allow'; }
    else if (st.active) { s = 'idle'; label = '열려 있음'; }
    else { s = 'idle'; label = '대기'; }
    if (el.dataset.s !== s) el.dataset.s = s;
    setText($('.target-label', el), label);
    setText($('.target-time', el), time);
    const reason = $('.target-reason', el);
    const r = s === 'open' && t.allow_reason ? t.allow_reason : '';
    reason.hidden = !r; setText(reason, r); reason.title = r;
    const act = $('.target-action', el);
    if (act.dataset.a !== action) {
      act.dataset.a = action;
      act.innerHTML = action === 'allow' ? '<button class="btn btn-sm" data-allow>공부용으로 잠깐 열기</button>'
        : action === 'revoke' ? '<button class="btn btn-sm" data-revoke>다시 막기</button>' : '';
    }
  }

  function renderHome(st) {
    document.body.classList.toggle('is-locked', !!st.active);
    $('#adminBanner').hidden = st.is_admin !== false;

    setText($('#statusText'), st.active ? '집중 중' : '대기 중');
    setText($('#sourceText'), st.active && st.source ? SOURCE_LABEL[st.source] || '' : '');

    const cd = $('#countdown'), sub = $('#countdownSub');
    const prog = $('#progress');
    let frac = null;
    if (st.active) {
      if (st.ends_at) {
        cd.classList.remove('is-text');
        setHtml(cd, fmt(st.ends_at - st.now));
        setText(sub, `${clock(st.ends_at)}에 끝납니다`);
        if (st.started_at && st.ends_at > st.started_at) {
          frac = Math.min(1, Math.max(0, (st.ends_at - st.now) / (st.ends_at - st.started_at)));
        }
      } else if (st.source === 'focustodo') {
        const timer = st.focustodo && st.focustodo.timer;
        cd.classList.toggle('is-text', !timer);
        setHtml(cd, timer ? timerHtml(String(timer)) : '포모도로 진행 중');
        setText(sub, '포모도로가 멈추면 자동으로 풀립니다');
      } else {
        cd.classList.add('is-text');
        setHtml(cd, '차단 중');
        setText(sub, st.started_at ? `${clock(st.started_at)}부터` : '');
      }
      $('#btnExtend').hidden = !st.ends_at || st.source !== 'manual';
    }
    prog.hidden = frac === null;
    if (frac !== null) $('#progressFill').style.transform = `scaleX(${frac.toFixed(4)})`;

    // 대기 화면 정보
    const f = st.focustodo || {};
    let ftd = '연동 꺼짐';
    if (f.enabled) ftd = (FTD_STATUS[f.status] || f.status || '—') + (f.timer ? ` · ${f.timer}` : '');
    setText($('#ftdText'), ftd);
    const ns = st.next_schedule;
    setText($('#nextText'), ns ? `${ns.label} · ${relative(ns.starts_at - st.now)}` : '없음');

    const tg = st.targets || {};
    TARGET_KEYS.forEach((k) => renderTarget(k, tg[k], st));
  }

  function updateStartLabel() {
    setText($('#btnStart'), `${minutesText(selectedMin)} 집중 시작`);
  }

  async function poll() {
    if (polling || !api) return;
    polling = true;
    try {
      const st = await api.get_state();
      if (st) {
        S = st;
        renderHome(st);
        if ($('#view-history').classList.contains('is-current')) renderToday(st);
      }
    } catch (e) { /* 다음 주기에 다시 시도 */ }
    polling = false;
  }

  /* ---------- 잠깐 열기 시트 ---------- */
  function openAllow(k) {
    allowTarget = k;
    setText($('#allowTitle'), `${TARGET_LABEL[k]} 잠깐 열기`);
    $('#allowReason').value = '';
    const def = (settingsCache && settingsCache.allow_default_minutes) || 15;
    setAllowMin([10, 15, 30, 60].includes(def) ? def : 15);
    $('#allowDialog').showModal();
    $('#allowReason').focus();
  }
  function setAllowMin(m) {
    allowMin = m;
    $$('#allowMinutes button').forEach((b) => b.setAttribute('aria-checked', String(+b.dataset.min === m)));
  }

  /* ---------- 그만하기 시트 ---------- */
  function openStop() {
    const strict = S && S.strict;
    $('#stopStrict').hidden = !strict;
    $('#stopPlain').hidden = !!strict;
    setText($('#stopPhrase'), (S && S.strict_phrase) || '');
    $('#stopInput').value = '';
    $('#stopSubmit').disabled = !!strict;
    $('#stopDialog').showModal();
    if (strict) $('#stopInput').focus();
  }

  /* ---------- 일정 ---------- */
  function renderSchedules(list) {
    const ul = $('#schedList');
    if (!Array.isArray(list)) return;
    if (!list.length) { ul.innerHTML = '<li class="sched-empty">아직 일정이 없습니다. 아래에서 요일과 시간을 골라 추가하세요.</li>'; return; }
    ul.innerHTML = list.map((s) => `
      <li class="sched-item${s.enabled ? '' : ' is-off'}" data-id="${esc(s.id)}">
        <span class="sched-days" aria-label="요일">${[...DAYS].map((d, i) => `<span class="${s.days.includes(i) ? 'on' : ''}">${d}</span>`).join('')}</span>
        <span class="sched-time">${esc(s.start)} – ${esc(s.end)}</span>
        <input type="checkbox" class="switch" data-toggle ${s.enabled ? 'checked' : ''} aria-label="일정 켜기">
        <button class="btn btn-quiet btn-sm" data-remove>삭제</button>
      </li>`).join('');
  }
  async function loadSchedules() { renderSchedules(await call('get_schedules')); }

  function buildDayToggles() {
    $('#dayToggles').innerHTML = [...DAYS].map((d, i) => `<button type="button" data-day="${i}" aria-pressed="${i < 5}">${d}</button>`).join('');
  }

  /* ---------- 기록 ---------- */
  function renderToday(st) {
    const t = st.stats_today || {};
    const fm = t.focus_minutes || 0;
    const h = Math.floor(fm / 60), m = fm % 60;
    const focusEl = $('#statFocus');
    const html = h ? `${h}<small>시간</small> ${m}<small>분</small>` : `${m}<small>분</small>`;
    if (focusEl.innerHTML !== html) focusEl.innerHTML = html;
    const hitsHtml = `${t.blocked_hits || 0}<small>회</small>`;
    if ($('#statHits').innerHTML !== hitsHtml) $('#statHits').innerHTML = hitsHtml;

    const allows = (t.allows || []).slice().sort((a, b) => b.at - a.at);
    const sig = JSON.stringify(allows);
    const log = $('#allowLog');
    if (log.dataset.sig === sig) return;
    log.dataset.sig = sig;
    log.innerHTML = allows.length ? allows.map((a) => `
      <li><span class="t">${clock(a.at)}</span><span>${esc(TARGET_LABEL[a.target] || a.target)}</span><span class="m">${a.minutes}분</span><span>${esc(a.reason || '')}</span></li>`).join('')
      : '<li class="empty">오늘은 잠깐 연 적이 없습니다.</li>';
  }

  async function loadHistory() {
    if (S) renderToday(S);
    const hist = await call('get_history', 7);
    if (!Array.isArray(hist)) return;
    const max = Math.max(60, ...hist.map((d) => d.focus_minutes || 0));
    const todayStr = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; })();
    $('#bars').innerHTML = hist.map((d) => {
      const [y, mo, da] = d.date.split('-').map(Number);
      const wd = (new Date(y, mo - 1, da).getDay() + 6) % 7;
      const pct = Math.round(((d.focus_minutes || 0) / max) * 100);
      const isToday = d.date === todayStr;
      return `<div class="bar${isToday ? ' is-today' : ''}" title="${d.date} · 집중 ${minutesText(d.focus_minutes || 0)} · 막힌 시도 ${d.blocked_hits || 0}회">
        <span class="bar-val">${d.focus_minutes ? minutesText(d.focus_minutes) : '–'}</span>
        <span class="bar-track"><span class="bar-fill" style="height:${pct}%"></span></span>
        <span class="bar-day">${isToday ? '오늘' : DAYS[wd]}</span>
      </div>`;
    }).join('');
  }

  /* ---------- 설정 ---------- */
  function buildSettingTargets() {
    $('#setTargets').innerHTML = TARGET_KEYS.map((k) => `
      <label class="set-row">
        <span class="set-text"><b>${TARGET_LABEL[k]}</b><small>${k === 'kakaotalk' ? '차단 중에는 카카오톡 프로그램을 닫습니다.' : '사이트 접속을 막습니다.'}</small></span>
        <input type="checkbox" class="switch" name="t_${k}">
      </label>`).join('');
  }

  async function loadSettings() {
    const s = await call('get_settings');
    if (!s) return;
    settingsCache = s;
    const f = $('#settingsForm');
    TARGET_KEYS.forEach((k) => { f[`t_${k}`].checked = !!(s.targets_enabled || {})[k]; });
    ['instagram', 'youtube', 'webtoon'].forEach((k) => { f[`dom_${k}`].value = ((s.extra_domains || {})[k] || []).join('\n'); });
    ['strict', 'block_during_break', 'autostart', 'focustodo_enabled', 'tab_guard', 'browser_policy', 'hosts_block', 'ai_warning'].forEach((n) => { f[n].checked = !!s[n]; });
    f.strict_phrase.value = s.strict_phrase || '';
    f.allow_default_minutes.value = String(s.allow_default_minutes || 15);
    f.allow_daily_limit.value = String(s.allow_daily_limit == null ? 3 : s.allow_daily_limit);
    f.ai_interval_min.value = String(s.ai_interval_min || 5);
    f.work_description.value = s.work_description || '';
    syncStrictPhrase();
    settingsDirty = false;
    setText($('#saveState'), '');
  }

  function collectSettings() {
    const f = $('#settingsForm');
    const lines = (v) => v.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
    const base = settingsCache ? JSON.parse(JSON.stringify(settingsCache)) : {};
    base.targets_enabled = Object.fromEntries(TARGET_KEYS.map((k) => [k, f[`t_${k}`].checked]));
    base.extra_domains = Object.assign({}, base.extra_domains, {
      instagram: lines(f.dom_instagram.value), youtube: lines(f.dom_youtube.value), webtoon: lines(f.dom_webtoon.value),
    });
    ['strict', 'block_during_break', 'autostart', 'focustodo_enabled', 'tab_guard', 'browser_policy', 'hosts_block', 'ai_warning'].forEach((n) => { base[n] = f[n].checked; });
    base.strict_phrase = f.strict_phrase.value.trim();
    base.allow_default_minutes = parseInt(f.allow_default_minutes.value, 10) || 15;
    base.allow_daily_limit = parseInt(f.allow_daily_limit.value, 10);
    if (isNaN(base.allow_daily_limit)) base.allow_daily_limit = 3;
    base.ai_interval_min = parseInt(f.ai_interval_min.value, 10) || 5;
    base.work_description = f.work_description.value.trim();
    return base;
  }

  function syncStrictPhrase() {
    const f = $('#settingsForm');
    f.strict_phrase.disabled = !f.strict.checked;
  }

  /* ---------- 이벤트 ---------- */
  function bind() {
    $$('.nav-item').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));

    $('#btnHide').addEventListener('click', async () => {
      await call('hide_window');
      if (isMock) toast('브라우저 미리보기에서는 창을 숨길 수 없습니다.');
    });

    // 프리셋
    $$('.preset[data-min]').forEach((b) => b.addEventListener('click', () => {
      selectedMin = +b.dataset.min;
      $$('.preset').forEach((p) => p.classList.toggle('is-selected', p === b));
      $('#customMin').value = '';
      updateStartLabel();
    }));
    const custom = $('#customMin');
    custom.addEventListener('input', () => {
      const v = parseInt(custom.value, 10);
      if (v > 0) {
        selectedMin = Math.min(v, 720);
        $$('.preset').forEach((p) => p.classList.toggle('is-selected', p.classList.contains('preset-custom')));
        updateStartLabel();
      }
    });
    custom.addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#btnStart').click(); });

    $('#btnStart').addEventListener('click', async () => {
      const st = await call('start_session', selectedMin);
      if (st && st.now) { S = st; renderHome(st); }
    });
    $('#btnExtend').addEventListener('click', async () => {
      const st = await call('extend_session', 15);
      if (st && st.now) { S = st; renderHome(st); toast('15분 연장했습니다.'); }
    });
    $('#btnStop').addEventListener('click', openStop);

    // 대상 카드
    $('#targets').addEventListener('click', async (e) => {
      const card = e.target.closest('.target'); if (!card) return;
      const k = card.dataset.key;
      if (e.target.closest('[data-allow]')) openAllow(k);
      if (e.target.closest('[data-revoke]')) {
        const st = await call('revoke_allow', k);
        if (st && st.now) { S = st; renderHome(st); }
        toast(`${OBJ[k]} 다시 막았습니다.`);
      }
    });

    // 시트 공통 닫기
    $$('dialog [data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
    $$('dialog').forEach((d) => d.addEventListener('click', (e) => { if (e.target === d) d.close(); }));

    // 잠깐 열기
    $$('#allowMinutes button').forEach((b) => b.addEventListener('click', () => setAllowMin(+b.dataset.min)));
    $('#allowForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const reason = $('#allowReason').value.trim();
      if (!reason) { $('#allowReason').focus(); toast('여는 이유를 적어 주세요.', true); return; }
      const res = await call('allow_temporarily', allowTarget, allowMin, reason);
      if (res && res.ok !== false) {
        $('#allowDialog').close();
        toast(`${OBJ[allowTarget]} ${allowMin}분 동안 열었습니다.`);
        poll();
      }
    });

    // 그만하기
    $('#stopInput').addEventListener('input', () => {
      $('#stopSubmit').disabled = $('#stopInput').value !== ((S && S.strict_phrase) || '');
    });
    $('#stopInput').addEventListener('paste', (e) => e.preventDefault());
    $('#stopForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const phrase = S && S.strict ? $('#stopInput').value : '';
      const res = await call('stop_session', phrase);
      if (res && res.ok !== false) {
        $('#stopDialog').close();
        toast('집중을 끝냈습니다.');
        poll();
      }
    });

    // 일정
    $('#dayToggles').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-day]'); if (!b) return;
      b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true'));
    });
    $('#schedForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const days = $$('#dayToggles button[aria-pressed="true"]').map((b) => +b.dataset.day);
      const start = $('#schedStart').value, end = $('#schedEnd').value;
      if (!days.length) { toast('요일을 하나 이상 고르세요.', true); return; }
      if (!start || !end || start >= end) { toast('끝 시각은 시작 시각보다 늦어야 합니다.', true); return; }
      const list = await call('add_schedule', days, start, end);
      if (Array.isArray(list)) { renderSchedules(list); toast('일정을 추가했습니다.'); }
    });
    $('#schedList').addEventListener('click', async (e) => {
      const li = e.target.closest('.sched-item'); if (!li) return;
      if (e.target.closest('[data-remove]')) {
        const list = await call('remove_schedule', li.dataset.id);
        if (Array.isArray(list)) { renderSchedules(list); toast('일정을 삭제했습니다.'); }
      }
    });
    $('#schedList').addEventListener('change', async (e) => {
      const li = e.target.closest('.sched-item');
      if (!li || !e.target.matches('[data-toggle]')) return;
      const list = await call('toggle_schedule', li.dataset.id, e.target.checked);
      if (Array.isArray(list)) renderSchedules(list);
    });

    // 설정
    const form = $('#settingsForm');
    form.addEventListener('input', () => { settingsDirty = true; setText($('#saveState'), '저장하지 않은 변경 사항이 있습니다.'); });
    form.addEventListener('change', (e) => {
      settingsDirty = true; setText($('#saveState'), '저장하지 않은 변경 사항이 있습니다.');
      if (e.target.name === 'strict') syncStrictPhrase();
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const obj = collectSettings();
      if (obj.strict && !obj.strict_phrase) { toast('엄격 모드에는 해제 문장이 필요합니다.', true); return; }
      const res = await call('save_settings', obj);
      if (res && res.ok !== false) {
        settingsCache = obj; settingsDirty = false;
        setText($('#saveState'), '');
        toast('설정을 저장했습니다.');
        poll();
      }
    });
    $('#btnDiagnose').addEventListener('click', async () => {
      const out = $('#diagOut');
      out.hidden = false; out.textContent = '읽는 중…';
      const r = await call('focustodo_diagnose');
      if (!r) { out.textContent = '진단에 실패했습니다.'; return; }
      out.textContent = [
        `창 찾음: ${r.found_window ? '예' : '아니요 — Focus To-Do를 실행해 두세요'}`,
        `타이머: ${r.timer || '—'}`,
        `상태: ${FTD_STATUS[r.status] || r.status || '—'}`,
        ...(r.hidden ? ['Focus To-Do 창이 최소화돼 있어 화면을 못 읽는 중 — 마지막 카운트다운이 끝날 때까지 집중 상태 유지'] : []),
        ...(r.error ? [`오류: ${r.error}`] : []),
        `읽은 글자 (${(r.texts || []).length}개)`,
        ...(r.texts || []).map((t, i) => `  ${String(i + 1).padStart(2, ' ')}. ${t}`),
      ].join('\n');
    });
    $('#btnAiTest').addEventListener('click', async () => {
      const out = $('#aiOut');
      const btn = $('#btnAiTest');
      out.hidden = false; out.textContent = '판정 중… (10초쯤)';
      btn.disabled = true;
      // 업무 설명을 먼저 저장해야 판정에 반영된다
      if (settingsDirty) await call('save_settings', collectSettings());
      const r = await call('ai_check_now');
      btn.disabled = false;
      if (!r) { out.textContent = '판정에 실패했습니다.'; return; }
      if (r.error) { out.textContent = `실패: ${r.error}`; return; }
      if (r.skipped) { out.textContent = '맨 앞 창이 이 앱이라 건너뜀 — 3초 안에 다른 창을 눌러 두고 다시 시험하세요.'; return; }
      out.textContent = [
        `창: ${r.title} (${r.exe})`,
        `판정: ${r.related ? '업무 관련' : '업무와 무관 → 경고'}`,
        `이유: ${r.reason || '—'}`,
      ].join('\n');
    });
  }

  /* ---------- 시작 ---------- */
  async function init() {
    buildTargets();
    buildDayToggles();
    buildSettingTargets();
    updateStartLabel();
    bind();
    await connect();
    $('#apiMode').hidden = !isMock;
    call('get_settings').then((s) => { if (s) settingsCache = s; });
    await poll();
    setInterval(poll, 1000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
