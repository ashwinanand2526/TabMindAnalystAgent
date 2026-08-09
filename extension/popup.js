// ── Constants & Configuration ────────────────────────────────────────────────
const BRIDGE_URL = 'http://localhost:7861';

// State variables
let activeTabs = [];
let selectedTabIds = [];
let currentSessionId = null;
let eventSource = null;

// UI Elements
const serverStatus = document.getElementById('server-status');
const tabsList = document.getElementById('tabs-list');
const selectedCount = document.getElementById('selected-count');
const analyzeBtn = document.getElementById('analyze-btn');
const focusSelect = document.getElementById('focus-select');

const tabSelectionSection = document.getElementById('tab-selection-section');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');

const progressBarFill = document.getElementById('progress-bar-fill');
const progressPercentage = document.getElementById('progress-percentage');
const currentStepLabel = document.getElementById('current-step-label');
const consoleLogs = document.getElementById('console-logs');

const verdictCard = document.getElementById('verdict-card');
const verdictWinner = document.getElementById('verdict-winner');
const verdictReason = document.getElementById('verdict-reason');
const caveatsList = document.getElementById('caveats-list');
const comparisonTable = document.getElementById('comparison-table');
const analysisSummaryText = document.getElementById('analysis-summary-text');
const resetBtn = document.getElementById('reset-btn');

// ── Initialization & Event Listeners ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkServerHealth();
  scanTabs();

  // Handle analyze button click
  analyzeBtn.addEventListener('click', startAnalysis);

  // Handle reset button click
  resetBtn.addEventListener('click', () => {
    switchPanel(tabSelectionSection);
    scanTabs();
  });
});

// ── Switch Panels ────────────────────────────────────────────────────────────
function switchPanel(targetPanel) {
  [tabSelectionSection, progressSection, resultsSection].forEach(panel => {
    panel.classList.remove('active');
  });
  targetPanel.classList.add('active');
}

// ── Check Server Health ───────────────────────────────────────────────────────
async function checkServerHealth() {
  const indicator = serverStatus.querySelector('.status-indicator');
  const text = serverStatus.querySelector('.status-text');

  try {
    const res = await fetch(`${BRIDGE_URL}/health`);
    if (res.ok) {
      indicator.className = 'status-indicator online';
      text.textContent = 'Bridge Online';
      analyzeBtn.disabled = selectedTabIds.length === 0;
    } else {
      throw new Error('Not OK');
    }
  } catch (err) {
    indicator.className = 'status-indicator offline';
    text.textContent = 'Offline (Auto-starting...)';
    
    // Send a message to background.js to attempt an auto-start via Native Messaging
    chrome.runtime.sendMessage({ action: 'ensure_bridge' }, (response) => {
      setTimeout(checkServerHealth, 3000); // Retry in 3s
    });
  }
}

// ── Scan Open Browser Tabs ───────────────────────────────────────────────────
function scanTabs() {
  tabsList.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Scanning browser tabs...</p>
    </div>
  `;

  // Query tabs in the current window
  chrome.tabs.query({ currentWindow: true }, (tabs) => {
    // Filter out internal chrome:// pages and the extension popup itself
    activeTabs = tabs.filter(tab => {
      return tab.url && 
             !tab.url.startsWith('chrome://') && 
             !tab.url.startsWith('chrome-extension://') &&
             !tab.url.startsWith('edge://');
    });

    if (activeTabs.length === 0) {
      tabsList.innerHTML = `
        <div class="loading-state">
          <p>No open tabs available to analyze.</p>
        </div>
      `;
      selectedCount.textContent = '0 selected';
      analyzeBtn.disabled = true;
      return;
    }

    tabsList.innerHTML = '';
    selectedTabIds = [];

    activeTabs.forEach(tab => {
      const tabCard = document.createElement('div');
      tabCard.className = 'tab-item';
      tabCard.dataset.tabId = tab.id;

      tabCard.innerHTML = `
        <input type="checkbox" class="tab-checkbox" id="check-${tab.id}">
        <div class="tab-info">
          <span class="tab-title" title="${escapeHtml(tab.title)}">${escapeHtml(tab.title)}</span>
          <span class="tab-url">${escapeHtml(tab.url)}</span>
        </div>
      `;

      // Card click event
      tabCard.addEventListener('click', (e) => {
        const checkbox = tabCard.querySelector('.tab-checkbox');
        if (e.target !== checkbox) {
          checkbox.checked = !checkbox.checked;
        }
        toggleTabSelection(tab.id, checkbox.checked, tabCard);
      });

      // Checkbox click directly
      tabCard.querySelector('.tab-checkbox').addEventListener('change', (e) => {
        toggleTabSelection(tab.id, e.target.checked, tabCard);
      });

      tabsList.appendChild(tabCard);
    });

    selectedCount.textContent = '0 selected';
  });
}

function toggleTabSelection(tabId, isChecked, cardEl) {
  if (isChecked) {
    cardEl.classList.add('selected');
    if (!selectedTabIds.includes(tabId)) {
      selectedTabIds.push(tabId);
    }
  } else {
    cardEl.classList.remove('selected');
    selectedTabIds = selectedTabIds.filter(id => id !== tabId);
  }

  selectedCount.textContent = `${selectedTabIds.length} selected`;
  
  // Only enable analyze button if we are online and have selected tabs
  const isOnline = serverStatus.querySelector('.status-indicator').classList.contains('online');
  analyzeBtn.disabled = selectedTabIds.length === 0 || !isOnline;
}

// ── Scrape & Start Analysis ──────────────────────────────────────────────────
async function startAnalysis() {
  if (selectedTabIds.length === 0) return;

  switchPanel(progressSection);
  consoleLogs.innerHTML = '';
  updateProgress(0, 'Scraping tab contents...');

  addLog('started', 'Scraping page contents of selected tabs...');

  const payloads = [];

  for (const tabId of selectedTabIds) {
    const tabObj = activeTabs.find(t => t.id === tabId);
    if (!tabObj) continue;

    addLog('started', `Scraping: ${tabObj.title}`);

    try {
      const pageHtml = await scrapeTabContent(tabId);
      payloads.push({
        url: tabObj.url,
        title: tabObj.title,
        html: pageHtml
      });
      addLog('complete', `Scraped: ${tabObj.title} (${Math.round(pageHtml.length / 1024)} KB)`);
    } catch (err) {
      addLog('failed', `Failed to scrape tab ${tabId}: ${err.message}. Using fallback description.`);
      payloads.push({
        url: tabObj.url,
        title: tabObj.title,
        html: `<h1>${tabObj.title}</h1><p>Failed to retrieve full HTML page. Scrape fallback.</p>`
      });
    }
  }

  updateProgress(10, 'Sending payload to agent bridge...');
  
  try {
    const focus = focusSelect.value;
    const response = await fetch(`${BRIDGE_URL}/analyze-tabs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tabs: payloads, focus: focus })
    });

    if (!response.ok) {
      const errDetails = await response.json();
      throw new Error(errDetails.detail || 'Failed to submit query to bridge');
    }

    const initData = await response.json();
    currentSessionId = initData.session_id;
    addLog('started', `Session initialized: ${currentSessionId}. Spawning agent Executor loop.`);
    
    // Connect to SSE stream
    connectSse(currentSessionId, payloads.length);
  } catch (err) {
    addLog('failed', `Error connecting to bridge: ${err.message}`);
    updateProgress(0, 'Error occurred');
    setTimeout(() => {
      const errorBtn = document.createElement('button');
      errorBtn.className = 'btn secondary sm';
      errorBtn.style.marginTop = '10px';
      errorBtn.textContent = 'Return to Tab Selection';
      errorBtn.onclick = () => switchPanel(tabSelectionSection);
      consoleLogs.appendChild(errorBtn);
    }, 1000);
  }
}

// Scrape tab HTML by executing scripting in context
function scrapeTabContent(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript({
      target: { tabId: tabId },
      func: () => {
        // Strip heavy tags to keep prompt payload optimal
        const docClone = document.documentElement.cloneNode(true);
        const tagsToStrip = ['script', 'style', 'svg', 'iframe', 'noscript', 'link', 'head', 'img', 'video', 'audio'];
        tagsToStrip.forEach(tag => {
          docClone.querySelectorAll(tag).forEach(el => el.remove());
        });
        
        // Return innerHTML of the stripped document
        return docClone.innerHTML || document.body.innerText;
      }
    }, (results) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (results && results[0]) {
        resolve(results[0].result);
      } else {
        reject(new Error('No results from script execution'));
      }
    });
  });
}

// ── Connect EventSource SSE ──────────────────────────────────────────────────
function connectSse(sessionId, tabCount) {
  const url = `${BRIDGE_URL}/stream/${sessionId}`;
  
  if (eventSource) {
    eventSource.close();
  }

  // Calculate expected node counts for progress calculation
  // Typical execution: 1 planner, tabCount tab_readers, tabCount distillers, 1 comparator, 1 verdict, 1 formatter
  const totalExpectedSteps = 4 + (2 * tabCount);
  let completedSteps = 0;

  eventSource = new EventSource(url);

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'node_started') {
      const label = `Node ${data.node_id}: running ${data.skill}...`;
      updateProgress(
        Math.min(90, Math.round((completedSteps / totalExpectedSteps) * 100)), 
        label
      );
      addLog('started', `Step ${data.node_id} [${data.skill}] started.`);
    } 
    else if (data.type === 'node_complete') {
      completedSteps++;
      const pct = Math.min(90, Math.round((completedSteps / totalExpectedSteps) * 100));
      updateProgress(pct, `Completed ${data.skill}.`);
      addLog('complete', `Step ${data.node_id} [${data.skill}] complete in ${data.elapsed_s.toFixed(1)}s.`);
    } 
    else if (data.type === 'node_failed') {
      completedSteps++;
      addLog('failed', `Step ${data.node_id} [${data.skill}] failed! error: ${data.error || 'unknown'}`);
    } 
    else if (data.type === 'critic_fail_recovery') {
      addLog('recovery', `Critic FAIL on previous distiller! Splicing in recovery Planner with rationale: "${data.rationale}"`);
    } 
    else if (data.type === 'done') {
      eventSource.close();
      updateProgress(100, 'Analysis complete! Fetching results...');
      addLog('complete', 'Graph processing complete. Finalizing output.');
      setTimeout(() => {
        fetchResults(sessionId);
      }, 1000);
    } 
    else if (data.type === 'error') {
      eventSource.close();
      addLog('failed', `Server error: ${data.message}`);
      updateProgress(0, 'Failed');
    }
  };

  eventSource.onerror = (err) => {
    console.error('SSE Error:', err);
    eventSource.close();
    addLog('failed', 'Lost SSE connection to bridge server.');
  };
}

// ── Fetch and Render Final Results ───────────────────────────────────────────
async function fetchResults(sessionId) {
  try {
    const res = await fetch(`${BRIDGE_URL}/result/${sessionId}`);
    if (!res.ok) throw new Error('Failed to retrieve session results');

    const result = await res.json();
    renderResults(result);
    switchPanel(resultsSection);
  } catch (err) {
    addLog('failed', `Error loading results: ${err.message}`);
  }
}

function renderResults(resData) {
  // 1. Render Verdict Card
  const verdict = resData.verdict || {};
  if (verdict.winner) {
    verdictWinner.textContent = verdict.winner;
    verdictReason.textContent = verdict.reason || '';
    
    // Render caveats
    caveatsList.innerHTML = '';
    const caveats = verdict.caveats || [];
    if (caveats.length > 0) {
      document.getElementById('caveats-box').style.display = 'block';
      caveats.forEach(cav => {
        const li = document.createElement('li');
        li.textContent = cav;
        caveatsList.appendChild(li);
      });
    } else {
      document.getElementById('caveats-box').style.display = 'none';
    }
  } else {
    // Fallback if structured verdict is missing
    verdictWinner.textContent = 'Recommendation Ready';
    verdictReason.textContent = 'Analysis complete. See details below.';
    document.getElementById('caveats-box').style.display = 'none';
  }

  // 2. Render Comparison Table Matrix
  const comp = resData.comparison || {};
  const dimensions = comp.dimensions || [];
  const matrix = comp.matrix || {};
  const scores = comp.scores || {};
  
  if (dimensions.length > 0 && Object.keys(matrix).length > 0) {
    // Render headers (first column is dimension, rest are product names)
    const products = Object.keys(matrix);
    let theadHtml = `<tr><th>Dimension</th>`;
    products.forEach(p => {
      theadHtml += `<th title="${escapeHtml(p)}">${escapeHtml(p)}</th>`;
    });
    theadHtml += `</tr>`;
    comparisonTable.querySelector('thead').innerHTML = theadHtml;

    // Render body
    let tbodyHtml = '';
    
    // First render normal dimension rows
    dimensions.forEach(dim => {
      tbodyHtml += `<tr><td><strong>${escapeHtml(dim.replace(/_/g, ' '))}</strong></td>`;
      products.forEach(p => {
        const val = matrix[p][dim] !== undefined ? matrix[p][dim] : 'N/A';
        tbodyHtml += `<td>${escapeHtml(val)}</td>`;
      });
      tbodyHtml += `</tr>`;
    });

    // Then render scores row if available
    if (Object.keys(scores).length > 0) {
      tbodyHtml += `<tr class="score-row" style="background: rgba(0,210,255,0.06); border-top: 2px solid rgba(0,210,255,0.2)">
        <td><strong style="color: var(--accent-blue)">AI Score</strong></td>`;
      products.forEach(p => {
        const score = scores[p] && scores[p].total !== undefined ? scores[p].total : 'N/A';
        tbodyHtml += `<td class="score-bold">${score}</td>`;
      });
      tbodyHtml += `</tr>`;
    }

    comparisonTable.querySelector('tbody').innerHTML = tbodyHtml;
  } else {
    comparisonTable.innerHTML = '<tr><td style="text-align: center; color: var(--text-muted);">No comparison matrix generated.</td></tr>';
  }

  // 3. Render Analytical Summary Paragraphs
  const summaryMarkdown = resData.answer || resData.final_answer || '';
  // Simple markdown-to-html conversion for paragraph tags & bolding
  let formattedHtml = summaryMarkdown
    .replace(/\n\n/g, '</p><p>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
  
  if (!formattedHtml.startsWith('<p>')) {
    formattedHtml = `<p>${formattedHtml}</p>`;
  }
  analysisSummaryText.innerHTML = formattedHtml;
}

// ── UI Helper Methods ────────────────────────────────────────────────────────
function updateProgress(percentage, text) {
  progressBarFill.style.width = `${percentage}%`;
  progressPercentage.textContent = `${percentage}%`;
  currentStepLabel.textContent = text;
}

function addLog(type, message) {
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  consoleLogs.appendChild(entry);
  
  // Auto-scroll console
  consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

function escapeHtml(unsafe) {
  if (typeof unsafe !== 'string') return String(unsafe);
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
