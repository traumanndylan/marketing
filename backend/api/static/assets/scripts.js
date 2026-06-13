function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.add('toast-out'); }, 3000);
    setTimeout(() => { toast.remove(); }, 3250);
}

let _confirmCb = null;
function showConfirm(message) {
    return new Promise(resolve => {
        document.getElementById('confirmMessage').textContent = message;
        document.getElementById('confirmOverlay').classList.add('open');
        _confirmCb = resolve;
    });
}
function confirmResolve(val) {
    document.getElementById('confirmOverlay').classList.remove('open');
    if (_confirmCb) { _confirmCb(val); _confirmCb = null; }
}
document.getElementById('confirmOverlay').addEventListener('click', function (e) {
    if (e.target === this) confirmResolve(false);
});

async function fetchOverview() {
    try {
        const d = await fetch('/api/overview').then(r => r.json());
        document.getElementById('overviewStats').innerHTML = `
            <div class="stat"><div class="stat-val" style="color:var(--green)">${d.sent}</div><div class="stat-label">Sent</div></div>
            <div class="stat"><div class="stat-val" style="color:var(--yellow)">${d.queued}</div><div class="stat-label">Queued</div></div>
            <div class="stat"><div class="stat-val" style="color:var(--red)">${d.failed}</div><div class="stat-label">Failed</div></div>
            <div class="stat"><div class="stat-val" style="color:var(--muted)">${d.skipped}</div><div class="stat-label">Skipped</div></div>`;

        document.getElementById('leadsStats').innerHTML = `
            <div class="stat" style="grid-column: span 4;">
                <div class="stat-val" style="font-size: 1.2rem; color:var(--accent)">${d.total_leads || 0}</div>
                <div class="stat-label">Total Contacts</div>
            </div>`;

        if (d.country_stats) {
            const countries = Object.entries(d.country_stats).map(([c, count]) =>
                `<span style="background:var(--surface2); padding:2px 8px; border-radius:12px; margin:2px 4px; display:inline-block; border:1px solid var(--border);">${c}: <b style="color:var(--text)">${count}</b></span>`
            );
            document.getElementById('countryStats').innerHTML = countries.join('');
        }
    } catch (e) { }
}

async function fetchStatus() {
    try {
        const d = await fetch('/api/status').then(r => r.json());
        const badge = document.getElementById('schedulerStatus');
        const btn = document.getElementById('pauseBtn');
        if (d.paused) {
            badge.className = 'badge badge-yellow'; badge.textContent = 'Paused';
            btn.innerHTML = '<i class="fa-solid fa-play"></i> Resume';
        } else {
            badge.className = 'badge badge-green'; badge.textContent = 'Active';
            btn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause';
        }
    } catch (e) { }
}

async function fetchSessions() {
    try {
        const d = await fetch('/api/sessions').then(r => r.json());
        const list = document.getElementById('sessionsList');
        const select = document.getElementById('messageCountrySelect');
        const prev = select.value;
        select.innerHTML = '<option value="default">Default Message</option>';
        list.innerHTML = '';

        if (!d.sessions || d.sessions.length === 0) {
            list.innerHTML = '<div style="color:var(--muted);font-size:.85rem;padding:.5rem 0;">No sessions yet.</div>';
            return;
        }

        d.sessions.forEach(s => {
            const status = s.status || 'UNKNOWN';
            const statusUpper = status.toUpperCase();
            const statusLabel = statusUpper === 'READY' ? 'Active' : status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
            let bclass = 'badge-yellow';
            if (statusLabel === 'Active') bclass = 'badge-green';
            if (['SUSPENDED', 'BANNED', 'OFFLINE', 'DISCONNECTED'].includes(statusUpper)) bclass = 'badge-red';

            const displayName = s.name || s.country;

            list.innerHTML += `
            <div class="session-item">
                <div class="session-header">
                    <div class="session-name">${displayName} <span style="color:var(--muted);font-weight:400;">(${s.country_code})</span></div>
                    <div class="session-actions">
                        <span class="badge ${bclass}">${statusLabel}</span>
                        <button class="btn btn-icon" onclick="requestOtp('${s.session_id}')" title="Link via OTP" style="color:var(--accent);"><i class="fa-solid fa-link"></i></button>
                        <button class="btn btn-icon" onclick="openEditModal('${s.session_id}','${(s.name || '').replace(/'/g, "\\'")}','${s.country.replace(/'/g, "\\'")}','${s.country_code}',${s.active})" title="Edit"><i class="fa-solid fa-pen"></i></button>
                        <button class="btn btn-icon btn-danger" onclick="deleteSession('${s.session_id}')" title="Delete"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </div>
                <div class="session-meta">${s.session_id}</div>
            </div>`;
            select.innerHTML += `<option value="${s.country_code}">${displayName}</option>`;
        });
        if (prev) select.value = prev;
    } catch (e) { }
}

async function addSession() {
    const name = document.getElementById('newName').value.trim();
    const country = document.getElementById('newCountry').value.trim();
    const country_code = document.getElementById('newCountryCode').value.trim();
    const session_id = document.getElementById('newSessionId').value.trim();
    if (!country || !country_code || !session_id) { showToast('Missing required fields.', 'error'); return; }
    await fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, country, country_code, session_id, active: true }) });
    ['newName', 'newCountry', 'newCountryCode', 'newSessionId'].forEach(id => document.getElementById(id).value = '');
    fetchSessions();
}

async function deleteSession(id) {
    if (!(await showConfirm('Delete this session?'))) return;
    await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
    fetchSessions();
}

function openEditModal(sessionId, name, country, countryCode, active) {
    document.getElementById('editOldSessionId').value = sessionId;
    document.getElementById('editName').value = name;
    document.getElementById('editCountry').value = country;
    document.getElementById('editCountryCode').value = countryCode;
    document.getElementById('editSessionId').value = sessionId;
    document.getElementById('editActive').value = active ? 'true' : 'false';
    document.getElementById('editModal').classList.add('open');
}

function closeEditModal() { document.getElementById('editModal').classList.remove('open'); }

async function saveEdit() {
    const oldId = document.getElementById('editOldSessionId').value;
    const name = document.getElementById('editName').value.trim();
    const country = document.getElementById('editCountry').value.trim();
    const country_code = document.getElementById('editCountryCode').value.trim();
    const session_id = document.getElementById('editSessionId').value.trim();
    const active = document.getElementById('editActive').value === 'true';
    await fetch(`/api/sessions/${oldId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, country, country_code, session_id, active }) });
    closeEditModal(); fetchSessions();
}

function requestOtp(sessionId) {
    document.getElementById('otpSessionId').value = sessionId;
    document.getElementById('otpPhone').value = '';
    document.getElementById('otpResult').innerText = '';
    document.getElementById('otpModal').classList.add('open');
}

function closeOtpModal() { document.getElementById('otpModal').classList.remove('open'); }

async function submitOtp() {
    const session_id = document.getElementById('otpSessionId').value;
    const phone = document.getElementById('otpPhone').value.trim();
    if (!phone) { showToast('Enter a phone number', 'error'); return; }
    document.getElementById('otpResult').innerText = 'Requesting...';
    try {
        const res = await fetch('/api/openwa/otp', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id, phone })
        }).then(r => r.json());
        if (res.code) {
            document.getElementById('otpResult').innerText = res.code;
        } else {
            document.getElementById('otpResult').innerText = 'Error';
            showToast(res.error || 'Failed to get code', 'error');
        }
    } catch (e) {
        document.getElementById('otpResult').innerText = 'Error';
    }
}

async function loadMessage() {
    const cc = document.getElementById('messageCountrySelect').value;
    const cat = document.getElementById('messageCategorySelect').value;
    const d = await fetch(`/api/messages/${cc}/${cat}`).then(r => r.json());
    document.getElementById('messageEditor').value = d.text;
}

async function saveMessage() {
    const cc = document.getElementById('messageCountrySelect').value;
    const cat = document.getElementById('messageCategorySelect').value;
    const text = document.getElementById('messageEditor').value;
    await fetch(`/api/messages/${cc}/${cat}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    showToast('Message saved.', 'success');
}

function syncMapWithConfig(text) {
    if (!text || !map) return;
    const lines = text.split('\n');
    const countryNames = [];
    lines.forEach(line => {
        if (line.trim().startsWith('#')) {
            countryNames.push(line.substring(1).trim().toLowerCase());
        }
    });

    const codesToSelect = [];
    for (const code in map.regions) {
        if (map.regions[code] && map.regions[code].config) {
            const regionName = map.regions[code].config.name.toLowerCase();
            if (countryNames.includes(regionName)) {
                codesToSelect.push(code);
            }
        }
    }

    if (codesToSelect.length > 0) {
        map.clearSelectedRegions();
        map.setSelectedRegions(codesToSelect);
        selectedCountries = codesToSelect;
        updateSelectedDisplay();
    }
}

async function loadConfigFile() {
    const filename = document.getElementById('configFileSelect').value;
    const d = await fetch(`/api/config/${filename}`).then(r => r.json());
    document.getElementById('configEditor').value = d.text;

    if (filename === 'cities.txt') {
        syncMapWithConfig(d.text);
    }
}

async function saveConfigFile() {
    const filename = document.getElementById('configFileSelect').value;
    const text = document.getElementById('configEditor').value;
    await fetch(`/api/config/${filename}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    showToast('File saved.', 'success');

    if (filename === 'cities.txt') {
        syncMapWithConfig(text);
    }
}

let selectedCountries = [];

function updateSelectedDisplay() {
    const listEl = document.getElementById('selectedCountriesList');
    if (!listEl) return;
    if (!map) { listEl.innerText = 'None'; return; }
    const names = selectedCountries.map(code => map.regions[code]?.config?.name || code);
    listEl.innerText = names.length ? names.join(', ') : 'None';
}

let lastMapClickTime = 0;
let lastMapClickCode = '';

function createMap(mapName = 'world') {
    const container = document.getElementById('worldMap');
    if (!container) return null;
    container.innerHTML = '';
    return new jsVectorMap({
        selector: '#worldMap',
        map: mapName,
        theme: 'dark',
        regionsSelectable: true,
        regionStyle: {
            initial: { fill: '#2e3347', stroke: 'none', strokeWidth: 0 },
            selected: { fill: '#2d8a56' },
            selectedHover: { fill: '#247a4a' },
            hover: { fill: '#247a4a', fillOpacity: 1 }
        },
        showTooltip: true,
        onRegionSelected: function (code, isSelected, selectedRegions) {
            selectedCountries = selectedRegions;
            updateSelectedDisplay();
        },
        onRegionClick: function (event, code) {
            if (mapName === 'world' && code === 'US') {
                const now = Date.now();
                if (now - lastMapClickTime < 500 && lastMapClickCode === 'US') {
                    try {
                        map.setFocus({ region: 'US', animate: true });
                    } catch (e) {
                        console.error('Zoom animation error:', e);
                    }

                    const container = document.getElementById('worldMap');
                    container.style.transition = 'opacity 0.4s ease';
                    container.style.opacity = '0';

                    setTimeout(() => {
                        const currentScroll = window.scrollY;
                        changeMapRegion('us_aea_en');
                        window.scroll(0, currentScroll);
                        container.style.opacity = '1';
                    }, 450);
                }
                lastMapClickTime = now;
                lastMapClickCode = code;
            }
        }
    });
}

let map = createMap();

function changeMapRegion(region) {
    selectedCountries = [];
    updateSelectedDisplay();
    if (map) {
        map.destroy();
        map = createMap(region);
    }
    const btn = document.getElementById('backToWorldBtn');
    if (btn) btn.style.display = region === 'world' ? 'none' : 'inline-flex';
}

async function generateCities() {
    if (!selectedCountries.length) {
        showToast('List cleared (No countries selected).', 'info');
        return;
    }

    const pop = document.getElementById('popSlider').value;
    const btn = document.getElementById('genCitiesBtn');
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';

    try {
        const res = await fetch('/api/generate-cities', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ countries: selectedCountries, population: pop })
        });
        const data = await res.json();

        if (res.ok) {
            await fetch('/api/config/cities.txt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: data.text })
            });

            updateSelectedDisplay();
            showToast(`Generated and saved ${data.count} cities to cities.txt.`, 'success');
        } else {
            showToast('Error: ' + data.error, 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('JS Error: ' + e.message, 'error');
    }
    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate List';
}

async function triggerRun() {
    await fetch('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'run' }) });
    showToast('Run triggered.', 'success');
}

async function togglePause() {
    const paused = document.getElementById('schedulerStatus').textContent.includes('Paused');
    await fetch('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: paused ? 'resume' : 'pause' }) });
    fetchStatus();
}

async function fetchMessageLimit() {
    try {
        const d = await fetch('/api/limit').then(r => r.json());
        if (d.limit) document.getElementById('globalMessageLimit').value = d.limit;
    } catch (e) { }
}

async function saveMessageLimit() {
    const val = document.getElementById('globalMessageLimit').value;
    await fetch('/api/limit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: val }) });
    showToast('Message limit saved.', 'success');
}

async function fetchLogs() {
    try {
        const d = await fetch('/api/logs').then(r => r.json());
        const box = document.getElementById('logsContainer');
        if (!d.logs || d.logs.length === 0) { box.textContent = 'No logs yet.'; return; }
        const isAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;
        box.innerHTML = d.logs.map(line => {
            let cls = '';
            if (line.includes('Sent message')) cls = 'log-sent';
            else if (line.includes('Failed')) cls = 'log-failed';
            else if (line.includes('Queued')) cls = 'log-queued';
            else if (line.includes('Alert:') || line.includes('CRITICAL')) cls = 'log-alert';
            return `<div class="${cls}">${line}</div>`;
        }).join('');
        if (isAtBottom) box.scrollTop = box.scrollHeight;
    } catch (e) { }
}

const scraperMachineSelect = document.getElementById('scraperMachineSelect');
if (scraperMachineSelect) {
    scraperMachineSelect.addEventListener('change', function () {
        document.getElementById('cloudServerIpGroup').style.display = this.value === 'cloud' ? 'block' : 'none';
    });
}

async function saveServerIp() {
    const ip = document.getElementById('cloudServerIp').value;
    await fetch('/api/scraper/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ server_ip: ip }) });
    showToast('Server IP saved.', 'success');
}

async function runScraper() {
    const machine = document.getElementById('scraperMachineSelect').value;
    await fetch('/api/scraper/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target: machine }) });
    showToast('Scraper started on ' + machine, 'success');
}

async function clearLogs(target) {
    if (!(await showConfirm('Clear ' + target + ' logs?'))) return;
    await fetch('/api/logs/clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target }) });
    if (target === 'main') fetchLogs();
    if (target === 'scraper') fetchScraperLogs();
}

async function stopScraper() {
    try {
        const res = await fetch('/api/scraper/stop', { method: 'POST' }).then(r => r.json());
        if (res.success) {
            showToast('Sent stop signal. Scraper will exit safely.', 'success');
        } else {
            showToast('Scraper is not running.', 'alert');
        }
    } catch (e) {
        showToast('Error stopping scraper.', 'error');
    }
}

let localEtaSeconds = 0;
let localEtaInterval = null;

function updateEtaDisplay() {
    const el = document.getElementById('scraperEta');
    if (!el) return;

    if (localEtaSeconds <= 0) {
        el.innerText = "Finishing...";
        return;
    }

    const m = Math.floor(localEtaSeconds / 60);
    const s = localEtaSeconds % 60;
    el.innerText = `${m}m ${s}s`;
}

async function fetchScraperEta() {
    try {
        const d = await fetch('/api/scraper/eta').then(r => r.json());
        if (d.status === 'running') {
            if (localEtaSeconds === 0) {
                localEtaSeconds = d.eta;
            } else if (d.eta < localEtaSeconds) {
                localEtaSeconds = d.eta;
            } else if (d.eta > localEtaSeconds + 120) {
                localEtaSeconds = d.eta;
            }
            updateEtaDisplay();

            if (!localEtaInterval) {
                localEtaInterval = setInterval(() => {
                    if (localEtaSeconds > 0) {
                        localEtaSeconds--;
                        updateEtaDisplay();
                    }
                }, 1000);
            }

            const pct = d.total > 0 ? Math.round((d.progress / d.total) * 100) : 0;
            const txt = document.getElementById('scraperProgressText');
            const bar = document.getElementById('scraperProgressBar');
            if (txt) txt.innerText = `${pct}% (${d.progress}/${d.total})`;
            if (bar) {
                bar.style.width = `${pct}%`;
                bar.style.background = 'var(--green)';
            }
        } else if (d.status === 'calculating') {
            if (localEtaInterval) { clearInterval(localEtaInterval); localEtaInterval = null; }
            localEtaSeconds = 0;
            const el = document.getElementById('scraperEta');
            if (el) el.innerText = "Calc...";
            const bar = document.getElementById('scraperProgressBar');
            if (bar) bar.style.background = 'var(--green)';
        } else {
            if (localEtaInterval) { clearInterval(localEtaInterval); localEtaInterval = null; }
            localEtaSeconds = 0;

            const el = document.getElementById('scraperEta');
            if (el) el.innerText = "--:--";

            const txt = document.getElementById('scraperProgressText');
            const bar = document.getElementById('scraperProgressBar');
            if (txt) txt.innerText = `0% (0/0)`;
            if (bar) {
                bar.style.width = `0%`;
                bar.style.background = 'transparent';
            }
        }
    } catch (e) { }
}

async function fetchCategories() {
    try {
        const d = await fetch('/api/categories').then(r => r.json());
        const select = document.getElementById('messageCategorySelect');
        const prev = select.value;
        select.innerHTML = '<option value="default">Default</option>';
        if (d.categories) {
            d.categories.forEach(cat => {
                select.innerHTML += `<option value="${cat.name}">${cat.name}</option>`;
            });
        }
        if (prev) select.value = prev;
    } catch (e) { }
}

async function fetchScraperLogs() {
    try {
        const d = await fetch('/api/scraper/logs').then(r => r.json());
        const box = document.getElementById('scraperLogsContainer');
        if (d.logs && d.logs.length > 0) {
            const isAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 50;
            box.innerHTML = d.logs.map(line => `<div>${line}</div>`).join('');
            if (isAtBottom) box.scrollTop = box.scrollHeight;
        } else {
            box.innerHTML = 'Waiting for scraper to start...';
        }
    } catch (e) { }
}

if (document.getElementById('overviewStats')) {
    fetchOverview();
    setInterval(fetchOverview, 5000);
}
if (document.getElementById('schedulerStatus')) {
    fetchStatus();
    setInterval(fetchStatus, 5000);
}
if (document.getElementById('sessionsList')) {
    fetchSessions();
    setInterval(fetchSessions, 10000);
}
if (document.getElementById('messageCategorySelect')) {
    fetchCategories();
    setInterval(fetchCategories, 10000);
    loadMessage();
}
if (document.getElementById('configFileSelect')) {
    loadConfigFile();
}
if (document.getElementById('logsContainer')) {
    fetchLogs();
    setInterval(fetchLogs, 5000);
}
if (document.getElementById('scraperEta')) {
    fetchScraperEta();
    setInterval(fetchScraperEta, 5000);
}
if (document.getElementById('scraperLogsContainer')) {
    fetchScraperLogs();
    setInterval(fetchScraperLogs, 3000);
}
if (document.getElementById('globalMessageLimit')) {
    fetchMessageLimit();
}
