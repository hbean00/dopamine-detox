/* 브라우저 미리보기용 가짜 API — pywebview가 없을 때만 쓰인다.
   URL 옵션: ?admin=0 (관리자 경고 표시), ?ftd=1 (Focus To-Do 포모도로 진행 중), ?ftd=min (타이머가 "24분"처럼 분만 올 때), ?strict=0,
            ?level=1~4 (그 단계로 집중 중인 상태로 시작), ?whale=0 (웨일이 꺼져 있음) */
(function () {
  const q = new URLSearchParams(location.search);
  const now = () => Date.now() / 1000;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const wait = (v) => new Promise((r) => setTimeout(() => r(clone(v)), 40));

  const LEVELS = [
    { id: 1, name: '가벼운 집중', short: '딴짓 사이트만 차단',
      rules: ['Instagram·YouTube·웹툰과 추가한 주소 차단', '카카오톡 종료', '공부용 잠깐 열기 하루 3회'] },
    { id: 2, name: '깊은 집중', short: 'SNS·뉴스·쇼핑까지 차단',
      rules: ['1단계 차단 전부', 'SNS·뉴스·쇼핑·OTT·커뮤니티 차단', '카카오톡·디스코드 등 메신저 종료', '잠깐 열기 없음'] },
    { id: 3, name: 'Claude만', short: 'Claude와 허용 사이트만',
      rules: ['Claude·localhost와 허용 사이트만 열림', '허용 앱 밖의 창은 닫음', '잠깐 열기 없음'] },
    { id: 4, name: '오프라인', short: '외부 웹·Claude 차단',
      rules: ['외부 웹사이트 모두 차단 (localhost는 열림)', 'Claude 웹·앱 차단', '허용 앱 밖의 창은 닫음'] },
  ];
  // 1·2단계에서 막는 주소 — 허용 사이트에 넣을 수 없다
  const BLOCKED_12 = ['instagram.com', 'youtube.com', 'youtu.be', 'comic.naver.com', 'webtoons.com', 'facebook.com', 'x.com', 'twitter.com',
    'tiktok.com', 'netflix.com', 'coupang.com', 'news.naver.com', 'dcinside.com', 'reddit.com'];

  const settings = {
    targets_enabled: { instagram: true, youtube: true, kakaotalk: true, webtoon: true },
    extra_domains: { instagram: [], youtube: [], webtoon: ['newtoki.example'] },
    strict: q.get('strict') !== '0',
    strict_phrase: '나는 지금 집중을 포기합니다',
    block_during_break: false,
    autostart: false,
    focustodo_enabled: true,
    tab_guard: true,
    browser_policy: true,
    hosts_block: false,
    allow_default_minutes: 15,
    allow_daily_limit: 3,
    ai_warning: false,
    ai_interval_min: 5,
    work_description: '',
    last_level: 2,
    focustodo_level: 2,
    allowed_sites: ['lms.school.ac.kr', 'scholar.google.com'],
    allowed_apps: ['code.exe', 'winword.exe', 'hwp.exe', 'acrord32.exe', 'notion.exe'],
  };

  let schedules = [
    { id: 's1', days: [0, 1, 2, 3, 4], start: '09:00', end: '12:00', enabled: true, level: 3 },
    { id: 's2', days: [1, 3], start: '19:30', end: '22:00', enabled: false, level: 1 },
  ];

  const sess = { active: false, source: null, started_at: null, ends_at: null, level: null };
  const allow = { youtube: null, kakaotalk: null };
  const today = { focusSec: 47 * 60, hits: 3, allows: [{ target: 'youtube', reason: '선형대수 강의 영상', minutes: 15, at: now() - 3 * 3600 }] };
  let ftdEnd = null;
  if (q.get('ftd') === '1' || q.get('ftd') === 'min') ftdEnd = now() + 24 * 60 + 12;
  const demoLevel = parseInt(q.get('level'), 10);
  if (demoLevel >= 1 && demoLevel <= 4) Object.assign(sess, { active: true, source: 'manual', started_at: now() - 12 * 60, ends_at: now() + 48 * 60, level: demoLevel });
  let whale = q.get('whale') !== '0';
  let last = now();

  const labels = { instagram: 'Instagram', youtube: 'YouTube', kakaotalk: '카카오톡', webtoon: '웹툰' };
  const allowable = { youtube: true, kakaotalk: true };
  const endSess = () => Object.assign(sess, { active: false, source: null, started_at: null, ends_at: null, level: null });

  function tick() {
    const t = now();
    const dt = t - last; last = t;
    if (sess.active && sess.ends_at && t >= sess.ends_at) endSess();
    if (ftdEnd && t >= ftdEnd) ftdEnd = null;
    for (const k of Object.keys(allow)) if (allow[k] && allow[k].until <= t) allow[k] = null;
    const on = sess.active || !!ftdEnd;
    if (on) { today.focusSec += dt; if (Math.random() < dt / 25) today.hits++; }
  }

  function nextSchedule() {
    const d = new Date();
    for (let add = 0; add < 8; add++) {
      const day = new Date(d.getFullYear(), d.getMonth(), d.getDate() + add);
      const wd = (day.getDay() + 6) % 7;
      for (const s of schedules.filter((s) => s.enabled && s.days.includes(wd)).sort((a, b) => a.start.localeCompare(b.start))) {
        const [h, m] = s.start.split(':').map(Number);
        const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m).getTime() / 1000;
        if (at > now()) return { label: `${'월화수목금토일'[wd]} ${s.start}–${s.end}`, starts_at: at };
      }
    }
    return null;
  }

  function state() {
    tick();
    const t = now();
    const ftdOn = !!ftdEnd && settings.focustodo_enabled;
    const active = sess.active || ftdOn;
    const source = sess.active ? sess.source : ftdOn ? 'focustodo' : null;
    const level = sess.active ? sess.level : ftdOn ? settings.focustodo_level : null;
    const lv = LEVELS.find((l) => l.id === level) || null;
    const targets = {};
    for (const k of Object.keys(labels)) {
      const a = allow[k];
      const en = settings.targets_enabled[k] || (active && level >= 3);
      const can = !!allowable[k] && (!active || level === 1);
      targets[k] = {
        label: labels[k], enabled: en, blocked: active && en && !a,
        allowable: can, allow_until: a ? a.until : null,
      };
      if (allowable[k]) targets[k].allow_reason = a ? a.reason : null;
    }
    let ftdTimer = null;
    if (ftdEnd) { const r = Math.max(0, Math.round(ftdEnd - t)); ftdTimer = q.get('ftd') === 'min' ? `${Math.ceil(r / 60)}분` : `${String(Math.floor(r / 60)).padStart(2, '0')}:${String(r % 60).padStart(2, '0')}`; }
    return {
      now: t, active, source,
      started_at: sess.active ? sess.started_at : null,
      ends_at: sess.active ? sess.ends_at : null,
      level: active ? level : null,
      level_name: active && lv ? lv.name : null,
      levels: LEVELS,
      rules_now: active && lv ? lv.rules : [],
      whale_running: whale,
      targets,
      focustodo: { enabled: settings.focustodo_enabled, status: ftdEnd ? 'focus' : 'idle', timer: ftdTimer },
      next_schedule: nextSchedule(),
      strict: settings.strict, strict_phrase: settings.strict_phrase,
      stats_today: { focus_minutes: Math.floor(today.focusSec / 60), blocked_hits: today.hits, allows: today.allows },
      is_admin: q.get('admin') !== '0',
    };
  }

  window.createMockApi = function () {
    return {
      get_state: () => wait(state()),
      get_levels: () => wait(LEVELS),
      start_session: (minutes, level) => {
        minutes = Math.max(1, parseInt(minutes, 10) || 30);
        level = parseInt(level, 10) || 1;
        if (level < 1 || level > 4) return wait({ ok: false, error: '알 수 없는 집중 단계입니다.' });
        if (sess.active && settings.strict && level < (sess.level || 1)) {
          return wait({ ok: false, error: '엄격 모드에서는 집중 중에 단계를 낮출 수 없어요.' });
        }
        Object.assign(sess, { active: true, source: 'manual', started_at: now(), ends_at: now() + minutes * 60, level });
        if (level >= 3) whale = true;   // 다시 시작된 웨일
        for (const k of Object.keys(allow)) if (level >= 2) allow[k] = null;
        settings.last_level = level;
        return wait(state());
      },
      stop_session: (phrase) => {
        if (settings.strict && phrase !== settings.strict_phrase) return wait({ ok: false, error: '문장이 정확히 일치하지 않습니다.' });
        endSess();
        ftdEnd = null;
        return wait({ ok: true });
      },
      extend_session: (minutes) => { if (sess.active && sess.ends_at) sess.ends_at += minutes * 60; return wait(state()); },
      allow_temporarily: (target, minutes, reason) => {
        const st = state();
        if (!st.targets[target] || !st.targets[target].allowable) return wait({ ok: false, error: '이 단계에서는 잠깐 열 수 없습니다.' });
        if (!reason || !reason.trim()) return wait({ ok: false, error: '여는 이유를 적어 주세요.' });
        allow[target] = { until: now() + minutes * 60, reason: reason.trim() };
        today.allows.push({ target, reason: reason.trim(), minutes, at: now() });
        return wait({ ok: true });
      },
      revoke_allow: (target) => { allow[target] = null; return wait(state()); },
      get_schedules: () => wait(schedules),
      add_schedule: (days, start, end, level) => {
        schedules.push({ id: 's' + Date.now(), days: days.slice().sort(), start, end, enabled: true, level: parseInt(level, 10) || 1 });
        return wait(schedules);
      },
      remove_schedule: (id) => { schedules = schedules.filter((s) => s.id !== id); return wait(schedules); },
      toggle_schedule: (id, enabled) => { const s = schedules.find((x) => x.id === id); if (s) s.enabled = enabled; return wait(schedules); },
      get_settings: () => wait(settings),
      save_settings: (obj) => {
        if (obj.strict && !String(obj.strict_phrase || '').trim()) return wait({ ok: false, error: '엄격 모드에는 해제 문장이 필요합니다.' });
        for (const d of obj.allowed_sites || []) {
          const host = String(d).toLowerCase().replace(/^www\./, '');
          const hit = BLOCKED_12.find((b) => host === b || host.endsWith('.' + b));
          if (hit) return wait({ ok: false, error: `${hit}은 1·2단계 차단 대상이라 허용 사이트에 넣을 수 없어요` });
        }
        Object.assign(settings, clone(obj));
        return wait({ ok: true });
      },
      list_running_apps: () => wait([
        { exe: 'code.exe', title: 'main.py - dopamine-detox - Visual Studio Code' },
        { exe: 'hwp.exe', title: 'ASIC설계_LAB3_보고서.hwp - 한글' },
        { exe: 'obsidian.exe', title: '강의 노트 - Obsidian' },
        { exe: 'kakaotalk.exe', title: '카카오톡' },
        { exe: 'spotify.exe', title: 'Spotify Premium' },
        { exe: 'acrord32.exe', title: '회로이론_7장.pdf - Adobe Acrobat Reader' },
      ]),
      ai_check_now: () => wait({ at: Date.now() / 1000, title: '침착맨 레전드 모음 - YouTube', exe: 'whale.exe', related: false, reason: '유튜브 영상은 업무와 무관' }),
      focustodo_diagnose: () => wait({
        found_window: true,
        timer: ftdEnd ? state().focustodo.timer : '25:00',
        status: ftdEnd ? 'focus' : 'idle',
        texts: ['Focus To-Do', '오늘', '내일', '이번 주', '계획됨', '완료', '보고서 초안', ftdEnd ? state().focustodo.timer : '25:00', '포모도로', '시작'],
      }),
      get_history: (days) => {
        const out = [];
        const seed = [62, 115, 38, 0, 142, 88];
        for (let i = days - 1; i >= 0; i--) {
          const d = new Date(); d.setDate(d.getDate() - i);
          const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          if (i === 0) out.push({ date: ds, focus_minutes: Math.floor(today.focusSec / 60), blocked_hits: today.hits });
          else out.push({ date: ds, focus_minutes: seed[i % seed.length], blocked_hits: (seed[i % seed.length] / 11) | 0 });
        }
        return wait(out);
      },
      hide_window: () => wait(null),
    };
  };
})();
