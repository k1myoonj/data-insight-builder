/**
 * AI Data Insight Builder - Frontend Logic (Pure Vanilla JavaScript)
 * 규칙: 엄격한 프론트엔드 콘솔 로깅, Chart.js 라이프사이클 관리, 5단계 분석 파이프라인
 */

(function () {
  'use strict';

  // 상태 관리 객체
  let currentFile = null;
  let currentInspectData = null;
  let currentRunData = null;
  let currentChartInstance = null;

  // 12개 도구 카탈로그 목록 (수동 선택용)
  const TOOL_CATALOG = [
    { name: "top_bottom_n", title: "기준연도 상위·하위 랭킹 비교" },
    { name: "trend_line", title: "주요 항목 연도별 시계열 추이 비교" },
    { name: "compare_one_vs_all", title: "특정 항목 vs 전체 평균 벤치마크 비교" },
    { name: "change_rate", title: "두 시점 간 성장량 및 변화율 분석" },
    { name: "distribution", title: "구간별 수치 분포 (히스토그램)" },
    { name: "correlation_scatter", title: "두 시점/변수 간 상관관계 분석 (산점도)" },
    { name: "group_summary", title: "대륙/그룹별 평균 및 통계 비교" },
    { name: "describe_numeric", title: "기술통계치 요약 (평균/중앙값/분포)" },
    { name: "year_coverage", title: "연도별 데이터 수집 완성도" },
    { name: "detect_aggregates", title: "집계/그룹 묶음 행 감지" },
    { name: "quality_report", title: "데이터 품질 종합 진단" },
    { name: "reshape_wide_to_long", title: "연도 열을 행으로 접기 (롱 포맷)" }
  ];

  // DOM 요소 참조
  const healthBadge = document.getElementById('healthBadge');
  const healthText = document.getElementById('healthText');
  const errorBanner = document.getElementById('errorBanner');
  const errorMessage = document.getElementById('errorMessage');
  const closeErrorBtn = document.getElementById('closeErrorBtn');

  // Step 1: 업로드
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const selectedFileInfo = document.getElementById('selectedFileInfo');
  const selectedFileName = document.getElementById('selectedFileName');
  const selectedFileSize = document.getElementById('selectedFileSize');
  const inspectBtn = document.getElementById('inspectBtn');
  const inspectSpinner = document.getElementById('inspectSpinner');

  // Step 2: 진단 결과
  const inspectSection = document.getElementById('inspectSection');
  const statDimensions = document.getElementById('statDimensions');
  const statEncoding = document.getElementById('statEncoding');
  const statSkiprows = document.getElementById('statSkiprows');
  const statRecYear = document.getElementById('statRecYear');
  const warningsBox = document.getElementById('warningsBox');
  const warningsList = document.getElementById('warningsList');
  const previewThead = document.getElementById('previewThead');
  const previewTbody = document.getElementById('previewTbody');
  const suggestBtn = document.getElementById('suggestBtn');
  const suggestSpinner = document.getElementById('suggestSpinner');

  // Step 3: 추천 제안
  const suggestSection = document.getElementById('suggestSection');
  const suggestionsList = document.getElementById('suggestionsList');
  const manualToolSelect = document.getElementById('manualToolSelect');
  const manualRefPeriod = document.getElementById('manualRefPeriod');
  const manualExcludeAgg = document.getElementById('manualExcludeAgg');
  const manualRunBtn = document.getElementById('manualRunBtn');

  // Step 4: 계산 및 차트
  const runSection = document.getElementById('runSection');
  const runToolName = document.getElementById('runToolName');
  const runRefPeriod = document.getElementById('runRefPeriod');
  const runUsedRows = document.getElementById('runUsedRows');
  const runExcludedRows = document.getElementById('runExcludedRows');
  const runExcludedReasons = document.getElementById('runExcludedReasons');
  const runCaution = document.getElementById('runCaution');
  const chartCanvas = document.getElementById('analysisChart');
  const calcResultDisplay = document.getElementById('calcResultDisplay');
  const explainModeBBtn = document.getElementById('explainModeBBtn');
  const explainModeABtn = document.getElementById('explainModeABtn');
  const explainSpinnerB = document.getElementById('explainSpinnerB');
  const explainSpinnerA = document.getElementById('explainSpinnerA');

  // Step 5: 리포트
  const explainSection = document.getElementById('explainSection');
  const explainTitle = document.getElementById('explainTitle');
  const explainModeBadge = document.getElementById('explainModeBadge');
  const modeComparisonNotice = document.getElementById('modeComparisonNotice');
  const reportMarkdownContainer = document.getElementById('reportMarkdownContainer');

  // Step 2-1: 자연어 자유 질문
  const nlQuestionSection = document.getElementById('nlQuestionSection');
  const nlChipsContainer = document.getElementById('nlChipsContainer');
  const nlQuestionForm = document.getElementById('nlQuestionForm');
  const nlInput = document.getElementById('nlInput');
  const nlSubmitBtn = document.getElementById('nlSubmitBtn');
  const nlSpinner = document.getElementById('nlSpinner');
  const nlAnswerBox = document.getElementById('nlAnswerBox');
  const nlAnswerMarkdown = document.getElementById('nlAnswerMarkdown');
  const nlGoToVizBtn = document.getElementById('nlGoToVizBtn');
  let lastNLRunResult = null;

  // Step 6: 후속 질문 (Q&A 대화창)
  const chatSection = document.getElementById('chatSection');
  const promptChipsContainer = document.getElementById('promptChipsContainer');
  const chatMessagesBox = document.getElementById('chatMessagesBox');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const sendChatBtn = document.getElementById('sendChatBtn');
  const chatSpinner = document.getElementById('chatSpinner');

  // ----------------------------------------------------------------------------
  // 유틸리티 함수
  // ----------------------------------------------------------------------------
  function showError(msg) {
    console.error(`[ERROR] ${msg}`);
    errorMessage.textContent = msg;
    errorBanner.classList.remove('hidden');
    errorBanner.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function hideError() {
    errorBanner.classList.add('hidden');
    errorMessage.textContent = '';
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }

  function simpleMarkdownToHtml(md) {
    if (!md) return '';
    let html = md
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^## (.*$)/gim, '<h2>$1</h2>')
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/gim, '<em>$1</em>')
      .replace(/^> (.*$)/gim, '<blockquote>$1</blockquote>');

    // 리스트 및 단락 처리
    const lines = html.split('\n');
    let inList = false;
    let result = [];

    for (let line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        if (!inList) {
          result.push('<ul>');
          inList = true;
        }
        result.push(`<li>${trimmed.substring(2)}</li>`);
      } else {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        if (trimmed.length > 0 && !trimmed.startsWith('<h') && !trimmed.startsWith('<block')) {
          result.push(`<p>${trimmed}</p>`);
        } else if (trimmed.length > 0) {
          result.push(trimmed);
        }
      }
    }
    if (inList) result.push('</ul>');
    return result.join('\n');
  }

  // ----------------------------------------------------------------------------
  // 초기화 및 서버 헬스체크
  // ----------------------------------------------------------------------------
  async function checkHealth() {
    try {
      const res = await fetch('/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.status === 'healthy') {
        healthBadge.className = 'status-badge online';
        healthText.textContent = `정상 동작 (모델: ${data.gemini_model})`;
      } else {
        throw new Error('Unhealthy status');
      }
    } catch (err) {
      healthBadge.className = 'status-badge offline';
      healthText.textContent = '서버 연결 안 됨';
      console.warn('[HEALTH] 서버 헬스체크 실패:', err.message);
    }
  }

  function initManualToolDropdown() {
    manualToolSelect.innerHTML = '';
    TOOL_CATALOG.forEach(tool => {
      const opt = document.createElement('option');
      opt.value = tool.name;
      opt.textContent = `${tool.title} (${tool.name})`;
      manualToolSelect.appendChild(opt);
    });
  }

  // ----------------------------------------------------------------------------
  // Step 1: 파일 선택 및 드래그 앤 드롭
  // ----------------------------------------------------------------------------
  function handleFileSelect(file) {
    hideError();
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.csv')) {
      showError('CSV 형식(.csv)의 파일만 업로드할 수 있습니다.');
      return;
    }

    currentFile = file;
    console.log(`[UPLOAD] 파일 선택 완료: ${file.name} (${formatBytes(file.size)})`);

    selectedFileName.textContent = file.name;
    selectedFileSize.textContent = formatBytes(file.size);
    selectedFileInfo.classList.remove('hidden');

    // 이전 분석 결과 초기화
    inspectSection.classList.add('hidden');
    nlQuestionSection.classList.add('hidden');
    nlAnswerBox.classList.add('hidden');
    suggestSection.classList.add('hidden');
    runSection.classList.add('hidden');
    explainSection.classList.add('hidden');
    lastNLRunResult = null;

    // 파일 선택 즉시 자동으로 데이터 진단 및 내용 열기 실행!
    startInspect();
  }

  // 브라우저 기본 드래그 앤 드롭 파일 열기 방지
  window.addEventListener('dragover', (e) => e.preventDefault(), false);
  window.addEventListener('drop', (e) => e.preventDefault(), false);

  // 드롭존 시각 효과 및 파일 수신 이벤트
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('dragover');
    });
  });

  ['dragleave', 'dragend'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('dragover');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  });

  // input[type=file] 변경 이벤트 (label 클릭 시 브라우저가 자동 트리거)
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelect(e.target.files[0]);
    }
    // 동일 파일 재선택 가능하도록 초기화
    fileInput.value = '';
  });

  closeErrorBtn.addEventListener('click', hideError);

  // ----------------------------------------------------------------------------
  // Step 2: /inspect 진단 요청
  // ----------------------------------------------------------------------------
  async function startInspect() {
    if (!currentFile) {
      showError('먼저 CSV 파일을 선택해 주세요.');
      return;
    }

    hideError();
    inspectBtn.disabled = true;
    inspectSpinner.classList.remove('hidden');
    console.log('[INSPECT] 진단 요청 시작');

    const formData = new FormData();
    formData.append('file', currentFile);

    try {
      const res = await fetch('/inspect', { method: 'POST', body: formData });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || '진단 중 오류가 발생했습니다.');
      }

      currentInspectData = data;
      console.log(`[INSPECT] 응답 수신: ${data.dimensions.rows}행 x ${data.dimensions.columns}열, 경고: ${data.warnings.length}개`);

      // 스탯 채우기
      statDimensions.textContent = `${data.dimensions.rows.toLocaleString()}행 × ${data.dimensions.columns}열`;
      statEncoding.textContent = data.file_info.encoding;
      statSkiprows.textContent = data.file_info.skiprows > 0 ? `${data.file_info.skiprows}줄 스킵` : '첫 줄(스킵 없음)';
      statRecYear.textContent = data.recommended_reference_year ? `${data.recommended_reference_year}년` : '미감지';

      if (data.recommended_reference_year) {
        manualRefPeriod.value = data.recommended_reference_year;
      }

      // 경고 채우기
      warningsList.innerHTML = '';
      if (data.warnings && data.warnings.length > 0) {
        data.warnings.forEach(w => {
          const li = document.createElement('li');
          li.textContent = w;
          warningsList.appendChild(li);
        });
        warningsBox.classList.remove('hidden');
      } else {
        warningsBox.classList.add('hidden');
      }

      // 10행 미리보기 표 렌더링
      renderPreviewTable(data.columns, data.preview);

      inspectSection.classList.remove('hidden');
      nlQuestionSection.classList.remove('hidden');
      inspectSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
      showError(err.message);
    } finally {
      inspectBtn.disabled = false;
      inspectSpinner.classList.remove('hidden');
      inspectSpinner.classList.add('hidden');
    }
  }

  inspectBtn.addEventListener('click', startInspect);

  function renderPreviewTable(columns, previewRows) {
    previewThead.innerHTML = '';
    previewTbody.innerHTML = '';

    if (!columns || !previewRows || previewRows.length === 0) return;

    // 헤더 생성
    const trHead = document.createElement('tr');
    columns.forEach(col => {
      const th = document.createElement('th');
      th.textContent = col;
      trHead.appendChild(th);
    });
    previewThead.appendChild(trHead);

    // 데이터 행 생성 (상위 10행)
    previewRows.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        const val = row[col];
        td.textContent = (val !== null && val !== undefined) ? val : '';
        tr.appendChild(td);
      });
      previewTbody.appendChild(tr);
    });
  }

  // ----------------------------------------------------------------------------
  // Step 3: /suggest 제안 요청 및 렌더링
  // ----------------------------------------------------------------------------
  suggestBtn.addEventListener('click', async () => {
    hideError();
    suggestBtn.disabled = true;
    suggestSpinner.classList.remove('hidden');
    console.log('[SUGGEST] 제안 요청 시작');

    try {
      const res = await fetch('/suggest', { method: 'POST' });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || '분석 제안 수신 실패');
      }

      const suggestions = data.suggestions || [];
      console.log(`[SUGGEST] 응답 수신 (제안 개수: ${suggestions.length}개)`);

      renderSuggestions(suggestions);
      suggestSection.classList.remove('hidden');
      suggestSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
      showError(err.message);
    } finally {
      suggestBtn.disabled = false;
      suggestSpinner.classList.add('hidden');
    }
  });

  function renderSuggestions(suggestions) {
    suggestionsList.innerHTML = '';

    if (suggestions.length === 0) {
      suggestionsList.innerHTML = '<p class="text-muted">제안 가능한 분석 도구가 없습니다.</p>';
      return;
    }

    suggestions.forEach((sug, idx) => {
      const card = document.createElement('div');
      card.className = 'suggest-card-item';

      card.innerHTML = `
        <div>
          <div class="suggest-card-header">
            <h3 class="suggest-title">${sug.title || sug.tool}</h3>
            <span class="suggest-tool-tag">${sug.tool}</span>
          </div>
          <p class="suggest-why"><strong>🎯 분석 이유:</strong> ${sug.why || '데이터에서 유의미한 패턴을 탐색합니다.'}</p>
          <div class="suggest-caution"><strong>⚠️ 주의사항:</strong> ${sug.caution || '결측치와 표본 크기에 유의하세요.'}</div>
        </div>
        <div class="suggest-card-footer">
          <button class="btn btn-primary btn-run-suggest" data-index="${idx}" style="width: 100%;">
            ▶️ 이 분석 실행하기
          </button>
        </div>
      `;

      card.querySelector('.btn-run-suggest').addEventListener('click', () => {
        executeTool(sug.tool, sug.params || {});
      });

      suggestionsList.appendChild(card);
    });
  }

  // 수동 실행 버튼
  manualRunBtn.addEventListener('click', () => {
    const toolName = manualToolSelect.value;
    const refPeriod = manualRefPeriod.value.trim();
    const excludeAgg = manualExcludeAgg.checked;

    const params = {
      reference_period: refPeriod,
      exclude_aggregates: excludeAgg
    };

    executeTool(toolName, params);
  });

  // ----------------------------------------------------------------------------
  // Step 4: /run 도구 실행 및 Chart.js 렌더링
  // ----------------------------------------------------------------------------
  function displayRunResult(data) {
    if (!data) return;
    currentRunData = data;
    console.log(`[RUN] 결과 표시: 도구=${data.tool}, 사용 행=${data.used_rows}, 제외 행=${data.excluded_rows}`);

    // 메타 정보 표시
    runToolName.textContent = data.tool;
    runRefPeriod.textContent = data.reference_period || '지정 안 됨';
    runUsedRows.textContent = `${data.used_rows}개`;
    runExcludedRows.textContent = `${data.excluded_rows}개`;

    runExcludedReasons.textContent = data.excluded_reasons && data.excluded_reasons.length > 0
      ? `• 제외 사유: ${data.excluded_reasons.join(' | ')}`
      : '• 제외된 행 없음 (전체 행 사용)';

    runCaution.textContent = data.caution ? `• 주의사항: ${data.caution}` : '';

    // Chart.js 차트 렌더링
    renderChart(data.chart_data);

    // 계산 결과 수치 테이블/요약 렌더링
    renderResultDisplay(data.result);

    runSection.classList.remove('hidden');
    explainSection.classList.add('hidden'); // 새로운 실행 시 이전 해석 리포트 숨김
    runSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function executeTool(toolName, params) {
    hideError();
    console.log(`[RUN] 도구 실행 시작 (도구명: ${toolName}, 기준시점: ${params.reference_period || 'N/A'})`);

    try {
      const res = await fetch('/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: toolName, params: params })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || '도구 실행 중 오류가 발생했습니다.');
      }

      displayRunResult(data);
    } catch (err) {
      showError(err.message);
    }
  }

  function renderChart(chartData) {
    // 기존 차트 인스턴스 파괴 (메모리 누수 방지)
    if (currentChartInstance) {
      currentChartInstance.destroy();
      currentChartInstance = null;
    }

    if (!chartData || !chartData.data) {
      chartCanvas.style.display = 'none';
      return;
    }

    chartCanvas.style.display = 'block';
    const ctx = chartCanvas.getContext('2d');

    // Chart.js 인스턴스 생성
    currentChartInstance = new Chart(ctx, {
      type: chartData.type || 'bar',
      data: chartData.data,
      options: chartData.options || { responsive: true }
    });

    console.log(`[CHART] 차트 렌더 완료 (차트 종류: ${chartData.type || 'bar'})`);
  }

  function renderResultDisplay(result) {
    calcResultDisplay.innerHTML = '';
    if (!result) return;

    // 만약 top_n 목록이 있으면 표로 렌더링
    if (result.top_n && Array.isArray(result.top_n)) {
      let tableHtml = `
        <h4 style="margin-bottom: 8px;">🏆 상위 순위 데이터 표</h4>
        <table class="data-table">
          <thead>
            <tr><th>순위</th><th>국가 / 항목명</th><th>수치 (${currentRunData.unit || '값'})</th></tr>
          </thead>
          <tbody>
      `;
      result.top_n.forEach(item => {
        tableHtml += `<tr><td>${item.rank}위</td><td><strong>${item.label}</strong></td><td>${item.value}</td></tr>`;
      });
      tableHtml += '</tbody></table>';
      calcResultDisplay.innerHTML = tableHtml;
    } else if (result.statistics) {
      // 기술통계 요약 표
      const s = result.statistics;
      calcResultDisplay.innerHTML = `
        <h4 style="margin-bottom: 8px;">📐 ${result.column} 기술통계치 계산표</h4>
        <div class="stats-grid">
          <div class="stat-box"><span class="stat-label">표본 개수</span><span class="stat-value">${s.count}</span></div>
          <div class="stat-box"><span class="stat-label">평균 (Mean)</span><span class="stat-value">${s.mean}</span></div>
          <div class="stat-box"><span class="stat-label">중앙값 (Median)</span><span class="stat-value">${s.median}</span></div>
          <div class="stat-box"><span class="stat-label">표준편차 (Std)</span><span class="stat-value">${s.std}</span></div>
          <div class="stat-box"><span class="stat-label">최솟값</span><span class="stat-value">${s.min}</span></div>
          <div class="stat-box"><span class="stat-label">최댓값</span><span class="stat-value">${s.max}</span></div>
        </div>
      `;
    } else if (result.target_item) {
      // compare_one_vs_all 벤치마크 표
      calcResultDisplay.innerHTML = `
        <h4 style="margin-bottom: 8px;">🎯 ${result.target_item} 벤치마크 계산표</h4>
        <div class="stats-grid">
          <div class="stat-box highlight"><span class="stat-label">${result.target_item}</span><span class="stat-value">${result.target_value}</span></div>
          <div class="stat-box"><span class="stat-label">전체 평균</span><span class="stat-value">${result.overall_mean}</span></div>
          <div class="stat-box"><span class="stat-label">전체 중앙값</span><span class="stat-value">${result.overall_median}</span></div>
          <div class="stat-box"><span class="stat-label">세계 순위</span><span class="stat-value">${result.rank}위 / ${result.total_items}개국</span></div>
        </div>
      `;
    }
  }

  // ----------------------------------------------------------------------------
  // Step 5: /explain 해석 리포트 생성 (모드 A / 모드 B)
  // ----------------------------------------------------------------------------
  explainModeBBtn.addEventListener('click', () => requestExplain('B'));
  explainModeABtn.addEventListener('click', () => requestExplain('A'));

  async function requestExplain(mode) {
    hideError();
    console.log(`[EXPLAIN] 해석 요청 시작 (모드: ${mode})`);

    const spinner = mode === 'B' ? explainSpinnerB : explainSpinnerA;
    const btn = mode === 'B' ? explainModeBBtn : explainModeABtn;

    btn.disabled = true;
    spinner.classList.remove('hidden');

    try {
      const res = await fetch('/explain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode })
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || '해석 보고서 생성 실패');
      }

      console.log(`[EXPLAIN] 응답 수신 (모드: ${mode})`);

      explainTitle.textContent = mode === 'B'
        ? '5. AI 데이터 인사이트 리포트 (정식 분석)'
        : '5. AI 데이터 인사이트 리포트 (비교용 모드 A)';

      explainModeBadge.textContent = mode === 'B' ? '정식 (모드 B: Pandas 계산 기반)' : '비교용 (모드 A: AI 상상 보고서)';
      explainModeBadge.style.backgroundColor = mode === 'B' ? '#eff6ff' : '#fef2f2';
      explainModeBadge.style.color = mode === 'B' ? '#1d4ed8' : '#991b1b';

      if (mode === 'A') {
        modeComparisonNotice.textContent = '⚠️ [비교용 모드 A]: 이 보고서는 Pandas 계산 결과를 주지 않고 작성된 보고서입니다. 모드 B와 비교해 보세요!';
        modeComparisonNotice.className = 'mode-notice mode-a';
        modeComparisonNotice.classList.remove('hidden');
      } else {
        modeComparisonNotice.textContent = '';
        modeComparisonNotice.className = 'mode-notice hidden';
      }

      // 마크다운 파싱 렌더링
      reportMarkdownContainer.innerHTML = simpleMarkdownToHtml(data.report_markdown);

      explainSection.classList.remove('hidden');
      explainSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
      showError(err.message);
    } finally {
      btn.disabled = false;
      spinner.classList.add('hidden');
    }
  }

  // ----------------------------------------------------------------------------
  // 후속 질문 (Q&A) 대화창 로직
  // ----------------------------------------------------------------------------
  function appendChatMessage(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${role === 'user' ? 'user-msg' : 'bot-msg'}`;

    const avatarDiv = document.createElement('div');
    avatarDiv.className = 'msg-avatar';
    avatarDiv.textContent = role === 'user' ? '👤' : '🤖';

    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'msg-bubble';

    if (role === 'user') {
      const p = document.createElement('p');
      p.textContent = text;
      bubbleDiv.appendChild(p);
    } else {
      bubbleDiv.innerHTML = simpleMarkdownToHtml(text);
    }

    msgDiv.appendChild(avatarDiv);
    msgDiv.appendChild(bubbleDiv);
    chatMessagesBox.appendChild(msgDiv);

    // 스크롤을 항상 최하단으로 부드럽게 이동
    chatMessagesBox.scrollTo({
      top: chatMessagesBox.scrollHeight,
      behavior: 'smooth'
    });
  }

  async function handleSendChat(questionText) {
    const question = (questionText || chatInput.value || '').trim();
    if (!question) return;

    console.log(`[CHAT] 후속 질문 전송: "${question}"`);

    // 사용자 메시지 추가 및 입력창 비우기
    appendChatMessage('user', question);
    chatInput.value = '';

    // 상태 변경 (로딩)
    sendChatBtn.disabled = true;
    chatInput.disabled = true;
    chatSpinner.classList.remove('hidden');

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || '답변 생성 중 오류가 발생했습니다.');
      }

      console.log('[CHAT] 후속 질문 답변 수신 완료');
      appendChatMessage('bot', data.answer_markdown);

    } catch (err) {
      console.error('[ERROR] 후속 질문 오류:', err);
      appendChatMessage('bot', `⚠️ **답변 생성 실패**: ${err.message}`);
      showError(err.message);
    } finally {
      sendChatBtn.disabled = false;
      chatInput.disabled = false;
      chatSpinner.classList.add('hidden');
      chatInput.focus();
    }
  }

  // 말풍선 추천 칩 클릭 이벤트 바인딩
  if (promptChipsContainer) {
    promptChipsContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.chip-btn');
      if (!btn) return;
      const question = btn.getAttribute('data-question');
      if (question) {
        handleSendChat(question);
      }
    });
  }

  // 폼 전송 이벤트 바인딩
  if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleSendChat();
    });
  }

  // ----------------------------------------------------------------------------
  // Step 2-1: 자연어 자유 질문 처리 로직
  // ----------------------------------------------------------------------------
  async function handleSendNLQuestion(questionText) {
    const question = (questionText || nlInput.value || '').trim();
    if (!question) {
      showError('질문 내용을 입력해 주세요.');
      return;
    }

    hideError();
    console.log(`[NL_QUERY] 자연어 질문 전송: "${question}"`);

    nlInput.value = question;
    nlSubmitBtn.disabled = true;
    nlInput.disabled = true;
    nlSpinner.classList.remove('hidden');

    try {
      const res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question })
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || '자연어 질문 분석 중 오류가 발생했습니다.');
      }

      console.log(`[NL_QUERY] 답변 수신 완료 (도구: ${data.tool})`);
      nlAnswerMarkdown.innerHTML = simpleMarkdownToHtml(data.answer_markdown);
      lastNLRunResult = data.run_result;

      nlAnswerBox.classList.remove('hidden');
      nlAnswerBox.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
      console.error('[ERROR] 자연어 질문 오류:', err);
      showError(err.message);
    } finally {
      nlSubmitBtn.disabled = false;
      nlInput.disabled = false;
      nlSpinner.classList.add('hidden');
    }
  }

  // 추천 질문 칩 클릭
  if (nlChipsContainer) {
    nlChipsContainer.addEventListener('click', (e) => {
      const btn = e.target.closest('.chip-btn');
      if (!btn) return;
      const q = btn.getAttribute('data-question');
      if (q) {
        handleSendNLQuestion(q);
      }
    });
  }

  // 질문 폼 전송
  if (nlQuestionForm) {
    nlQuestionForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleSendNLQuestion();
    });
  }

  // 시각화 차트 및 심층 분석으로 이동 버튼
  if (nlGoToVizBtn) {
    nlGoToVizBtn.addEventListener('click', () => {
      if (!lastNLRunResult) {
        showError('시각화할 계산 결과가 없습니다. 다시 질문해 주세요.');
        return;
      }
      console.log('[NL_QUERY] 시각화 차트 보기 클릭 -> Step 4로 연결');
      displayRunResult(lastNLRunResult);
    });
  }

  // ----------------------------------------------------------------------------
  // 페이지 로드 완료 초기화
  // ----------------------------------------------------------------------------
  window.addEventListener('DOMContentLoaded', () => {
    checkHealth();
    initManualToolDropdown();
    console.log('[PAGE] 페이지 로드 완료');
  });

})();
