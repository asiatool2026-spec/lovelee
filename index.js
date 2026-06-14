// ── 인증 토큰 관리 ──────────────────────────────
let _authToken = sessionStorage.getItem('lbox_token') || '';

function authHeaders() {
  return _authToken ? { 'Authorization': 'Bearer ' + _authToken } : {};
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value.trim();
  const errEl    = document.getElementById('login-error');
  const btn      = document.getElementById('login-btn');

  if (!username || !password) { errEl.style.display = 'block'; return; }

  btn.disabled = true;
  btn.textContent = '확인 중...';
  errEl.style.display = 'none';

  try {
    const res  = await fetch('/api/login', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();

    if (res.ok && data.token !== undefined) {
      _authToken = data.token;
      sessionStorage.setItem('lbox_token', _authToken);
      document.getElementById('login-overlay').style.display = 'none';
      document.getElementById('app-container').style.display = '';
      initDashboard();
    } else {
      errEl.style.display = 'block';
    }
  } catch (e) {
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = '로그인';
  }
}

// Enter 키 로그인
document.addEventListener('DOMContentLoaded', () => {
  ['login-username', 'login-password'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  });

  // 이미 토큰이 있으면 바로 대시보드
  if (_authToken) {
    fetch('/api/config', { headers: authHeaders() }).then(r => {
      if (r.ok) {
        document.getElementById('login-overlay').style.display = 'none';
        document.getElementById('app-container').style.display = '';
        initDashboard();
      } else {
        sessionStorage.removeItem('lbox_token');
        _authToken = '';
      }
    }).catch(() => {});
  }
});

// API 및 DOM 바인딩 정의
const API_URL = ''; // 동일 출처에서 서빙되므로 상대경로 사용

// DOM Elements — Scraper
const statusBadge    = document.getElementById('status-badge');
const cookieInput    = document.getElementById('cookie-input');
const saveConfigBtn  = document.getElementById('save-config-btn');
const keywordInput   = document.getElementById('keyword-input');
const limitInput     = document.getElementById('limit-input');
const delayInput     = document.getElementById('delay-input');
const runScraperBtn  = document.getElementById('run-scraper-btn');
const clearLogBtn    = document.getElementById('clear-log-btn');
const consoleLog     = document.getElementById('console-log');
const caseCountText  = document.getElementById('case-count');
const searchFilterInput = document.getElementById('search-filter');
const casesTbody     = document.getElementById('cases-tbody');

// DOM Elements — Diagnose
const diagnoseBtn    = document.getElementById('diagnose-btn');
const diagnoseOutput = document.getElementById('diagnose-output');

// DOM Elements — RAG

// Modal Elements
const caseModal = document.getElementById('case-modal');
const closeModalBtn = document.getElementById('close-modal-btn');
const closeModalFooterBtn = document.getElementById('close-modal-footer-btn');
const modalCourt = document.getElementById('modal-court');
const modalCaseNumber = document.getElementById('modal-case-number');
const modalCaseName = document.getElementById('modal-case-name');
const modalDate = document.getElementById('modal-date');
const modalId = document.getElementById('modal-id');
const modalBodyText = document.getElementById('modal-body-text');
const downloadJsonBtn = document.getElementById('download-json-btn');

let activeCaseData = null;
let logPollingInterval = null;

// 초기 로드
document.addEventListener('DOMContentLoaded', () => {
  fetchConfig();
  fetchCases();
  setupEventListeners();
  checkAndRestoreLogPolling();
});

// 이벤트 리스너 등록
function setupEventListeners() {
  saveConfigBtn.addEventListener('click', saveConfig);
  runScraperBtn.addEventListener('click', runCrawler);
  clearLogBtn.addEventListener('click', () => {
    consoleLog.textContent = '대기 중... 콘솔 로그가 비워졌습니다.';
  });
  searchFilterInput.addEventListener('input', filterCasesTable);
  closeModalBtn.addEventListener('click', closeModal);
  closeModalFooterBtn.addEventListener('click', closeModal);
  caseModal.addEventListener('click', (e) => { if (e.target === caseModal) closeModal(); });
  downloadJsonBtn.addEventListener('click', downloadActiveCaseJSON);
  diagnoseBtn.addEventListener('click', runDiagnose);
  document.getElementById('research-gen-btn').addEventListener('click', generateResearch);
  document.getElementById('research-download-btn').addEventListener('click', downloadResearch);
}

// 1. 인증 및 상태 조회
async function fetchConfig() {
  try {
    const res = await fetch('/api/config', { headers: authHeaders() });
    const data = await res.json();
    
    if (data.cookie_exists) {
      statusBadge.textContent = '🔑 로그인 세션 등록 완료';
      statusBadge.className = 'badge badge-success';
      if (data.cookie_preview) {
        cookieInput.placeholder = `현재 쿠키가 저장되어 있습니다 (${data.cookie_preview})`;
      }
    } else {
      statusBadge.textContent = '⚠️ 로그인 세션 없음 (크롤링 제한됨)';
      statusBadge.className = 'badge badge-warning';
    }
  } catch (err) {
    console.error('Config fetch failed:', err);
    statusBadge.textContent = '🔌 백엔드 연결 오류';
    statusBadge.className = 'badge badge-warning';
  }
}

// 2. 쿠키 정보 저장
async function saveConfig() {
  const cookieVal = cookieInput.value.trim();
  if (!cookieVal) {
    alert('쿠키 값을 입력한 뒤 저장을 시도하세요.');
    return;
  }
  
  saveConfigBtn.disabled = true;
  saveConfigBtn.textContent = '저장 중...';
  
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie: cookieVal })
    });
    const data = await res.json();
    
    if (data.status === 'success') {
      alert('세션 정보가 .env에 성공적으로 저장되었습니다!');
      cookieInput.value = '';
      fetchConfig();
    } else {
      alert(`저장 실패: ${data.message}`);
    }
  } catch (err) {
    alert(`서버 통신 에러: ${err.message}`);
  } finally {
    saveConfigBtn.disabled = false;
    saveConfigBtn.textContent = '설정 저장';
  }
}

// 3. 판례 리스트 로드
async function fetchCases() {
  try {
    const res = await fetch('/api/cases', { headers: authHeaders() });
    const data = await res.json();
    renderCasesTable(data.cases || []);
  } catch (err) {
    console.error('Failed to load cases:', err);
    casesTbody.innerHTML = `<tr><td colspan="6" class="td-empty" style="color: #ef4444;">판례 목록을 불러오지 못했습니다. app.py가 실행 중인지 확인하세요.</td></tr>`;
  }
}

// 4. 판례 테이블 렌더링
function renderCasesTable(cases) {
  caseCountText.textContent = cases.length;
  
  if (cases.length === 0) {
    casesTbody.innerHTML = `<tr><td colspan="6" class="td-empty">로컬에 저장된 판례가 없습니다. 크롤링을 구동하여 수집을 시작해 보세요!</td></tr>`;
    return;
  }
  
  casesTbody.innerHTML = '';
  cases.forEach(c => {
    const tr = document.createElement('tr');
    tr.dataset.caseId = c.case_id;
    tr.dataset.searchTarget = `${c.case_number} ${c.court} ${c.case_name}`.toLowerCase();
    tr.addEventListener('click', () => showCaseDetail(c.case_id));
    tr.innerHTML = `
      <td style="font-weight: 600; color: var(--text-title);">${c.case_number}</td>
      <td>${c.court || '<span class="text-muted">-</span>'}</td>
      <td>${c.judgment_date || '<span class="text-muted">-</span>'}</td>
      <td>${c.case_name || '<span class="text-muted">-</span>'}</td>
      <td class="snippet-cell">${c.snippet}</td>
      <td>
        <button class="row-action-btn" onclick="event.stopPropagation(); showCaseDetail('${c.case_id}')">열기</button>
      </td>
    `;
    casesTbody.appendChild(tr);
  });
}

// 5. 판례 검색 필터링
function filterCasesTable() {
  const query = searchFilterInput.value.toLowerCase().trim();
  const rows = casesTbody.querySelectorAll('tr');
  rows.forEach(row => {
    const target = row.dataset.searchTarget;
    if (!target) return;
    row.style.display = target.includes(query) ? '' : 'none';
  });
}

// 6. 크롤러 실행
async function runCrawler() {
  const keyword = keywordInput.value.trim();
  const limit = parseInt(limitInput.value);
  const delay = 0;
  
  if (!keyword) {
    alert('수집할 키워드를 입력해 주세요.');
    return;
  }
  
  runScraperBtn.disabled = true;
  runScraperBtn.textContent = '크롤러 구동 중...';
  consoleLog.textContent = '[INFO] 크롤링 구동 요청을 보냈습니다...\n';
  
  try {
    const res = await fetch('/api/crawl', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ keyword, limit, delay })
    });
    const data = await res.json();
    
    if (res.status === 200 && data.status === 'started') {
      // 로컬 서버: 백그라운드 실행 → 폴링 시작
      startLogPolling();
    } else if (res.status === 200 && data.status === 'done') {
      // 서버리스: 동기 완료 → 자동 인덱싱
      if (data.log) consoleLog.textContent = data.log;
      fetchCases();
      runScraperBtn.disabled = false;
      runScraperBtn.textContent = '크롤링 실행';
    } else {
      alert(`구동 실패: ${data.message || JSON.stringify(data)}`);
      runScraperBtn.disabled = false;
      runScraperBtn.textContent = '크롤링 실행';
    }
  } catch (err) {
    consoleLog.textContent = `[ERROR] 서버 통신 실패: ${err.message}`;
    runScraperBtn.disabled = false;
    runScraperBtn.textContent = '크롤링 실행';
  }
}

// 7. 실시간 로그 폴링
function startLogPolling() {
  if (logPollingInterval) clearInterval(logPollingInterval);
  
  runScraperBtn.disabled = true;
  runScraperBtn.textContent = '수집 진행 중...';
  
  logPollingInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/logs', { headers: authHeaders() });
      const data = await res.json();
      
      consoleLog.textContent = data.logs;
      consoleLog.scrollTop = consoleLog.scrollHeight;
      
      if (data.status === 'idle') {
        clearInterval(logPollingInterval);
        logPollingInterval = null;
        
        fetchCases();

        runScraperBtn.disabled = false;
        runScraperBtn.textContent = '크롤링 실행';
      }
    } catch (err) {
      console.error('Log polling failed:', err);
    }
  }, 1000);
}

// 8. 페이지 로드 시 백그라운드 크롤링 상태 복구
async function checkAndRestoreLogPolling() {
  try {
    const res = await fetch('/api/logs', { headers: authHeaders() });
    const data = await res.json();
    
    if (data.logs && data.logs !== '대기 중...') {
      consoleLog.textContent = data.logs;
      consoleLog.scrollTop = consoleLog.scrollHeight;
    }
    if (data.status === 'running') {
      startLogPolling();
    }
  } catch (err) {
    console.error('Failed to check background status:', err);
  }
}

// 9. 상세 모달 열기
async function showCaseDetail(caseId) {
  try {
    const res = await fetch(`/api/cases/${caseId}`, { headers: authHeaders() });
    if (!res.ok) throw new Error('판례 상세를 가져오지 못했습니다.');
    
    const data = await res.json();
    activeCaseData = data;
    
    modalCourt.textContent = data.court || '법원 미상';
    modalCaseNumber.textContent = data.case_number || '사건번호 미상';
    modalCaseName.textContent = data.case_name || '사건명 미상';
    modalDate.textContent = data.judgment_date || '선고일 미상';
    modalId.textContent = data.case_id;
    modalBodyText.textContent = data.content || '본문 텍스트 정보가 없습니다.';
    caseModal.classList.add('open');
  } catch (err) {
    alert(err.message);
  }
}

// 10. 모달 닫기
function closeModal() {
  caseModal.classList.remove('open');
  activeCaseData = null;
}

// 11. JSON 다운로드
function downloadActiveCaseJSON() {
  if (!activeCaseData) return;
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(activeCaseData, null, 2));
  const a = document.createElement('a');
  a.setAttribute("href", dataStr);
  a.setAttribute("download", `lbox_${activeCaseData.case_id}.json`);
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// 12. API 진단
async function runDiagnose() {
  diagnoseBtn.disabled = true;
  diagnoseBtn.textContent = '진단 중...';
  diagnoseOutput.style.display = 'block';
  diagnoseOutput.textContent = '[INFO] 엔드포인트 진단 실행 중... (최대 30초 소요)';

  try {
    const res = await fetch('/api/diagnose', { headers: authHeaders() });
    const data = await res.json();
    diagnoseOutput.textContent = data.output || data.message || JSON.stringify(data, null, 2);
  } catch (err) {
    diagnoseOutput.textContent = `[ERROR] 진단 실패: ${err.message}`;
  } finally {
    diagnoseBtn.disabled = false;
    diagnoseBtn.textContent = '엔드포인트 진단 실행';
  }
}

// 16. 리서치 결과 문서 생성
let _researchText = '';

async function generateResearch() {
  const genBtn = document.getElementById('research-gen-btn');
  const dlBtn  = document.getElementById('research-download-btn');
  const body   = document.getElementById('research-body');
  const output = document.getElementById('research-output');

  genBtn.disabled = true;
  genBtn.textContent = '생성 중...';

  try {
    const res  = await fetch('/api/research', { headers: authHeaders() });
    const data = await res.json();

    if (!data.document) {
      alert(data.message || '수집된 판례가 없습니다. 크롤링을 먼저 실행해 주세요.');
      return;
    }

    _researchText = data.document;
    output.textContent = _researchText;
    body.style.display = 'block';
    dlBtn.style.display = '';
    output.scrollTop = 0;
  } catch (err) {
    alert('문서 생성 실패: ' + err.message);
  } finally {
    genBtn.disabled = false;
    genBtn.textContent = '문서 생성';
  }
}

function downloadResearch() {
  if (!_researchText) return;
  const blob = new Blob([_researchText], { type: 'text/plain;charset=utf-8' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `lbox_research_${new Date().toISOString().slice(0,10)}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
