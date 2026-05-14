document.addEventListener('DOMContentLoaded', function() {
    // -----------------------------------------------------------------------
    // Page data
    // -----------------------------------------------------------------------
    const suiteDataNode = document.getElementById('suite-data');
    const suiteData = suiteDataNode ? JSON.parse(suiteDataNode.textContent || '[]') : [];
    const defaultBaseUrlNode = document.getElementById('default-base-url');
    const defaultBaseUrl = defaultBaseUrlNode ? JSON.parse(defaultBaseUrlNode.textContent || '"http://localhost:5004/"') : 'http://localhost:5004/';
    const selectedBranchNode = document.getElementById('selected-branch');
    const selectedBranch = selectedBranchNode ? JSON.parse(selectedBranchNode.textContent || '""') : '';
    const freshnessCheckIntervalNode = document.getElementById('freshness-check-interval');
    const freshnessCheckIntervalSeconds = freshnessCheckIntervalNode ? Number(JSON.parse(freshnessCheckIntervalNode.textContent || '1800')) : 1800;
    const activePlanIdNode = document.getElementById('active-plan-id');
    const activePlanId = activePlanIdNode ? String(JSON.parse(activePlanIdNode.textContent || '""') || '') : '';
    const planTestIdsNode = document.getElementById('plan-test-ids');
    let planTestIds = new Set(planTestIdsNode ? JSON.parse(planTestIdsNode.textContent || '[]').map(String) : []);

    // Track currently displayed content for refreshing
    let currentlyDisplayedTarget = null;

    const contentRoot = document.getElementById('test-content-root');
    const appMain = document.querySelector('.app-main');
    const syncButton = document.getElementById('sync-button');
    const lastSyncedLabel = document.getElementById('last-synced-label');
    const freshnessStatusLabel = document.getElementById('freshness-status-label');
    const toastContainer = document.getElementById('toast-container');
    const baseUrlInput = document.getElementById('base-url-input');
    const baseUrlSaveBtn = document.getElementById('base-url-save-btn');
    const baseUrlResetBtn = document.getElementById('base-url-reset-btn');
    let previousIsStale = null;

    // -----------------------------------------------------------------------
    // Lookup maps built from suiteData
    // -----------------------------------------------------------------------
    const testsetById = new Map();   // testsetId -> { suite, testset }
    const testById = new Map();      // testId -> { suite, testset, test }
    const testsetTestIds = new Map(); // testsetId -> Set<testId>
    const suiteTestIds = new Map();   // suiteId -> Set<testId>

    suiteData.forEach(suite => {
        const sIdStr = String(suite.id);
        if (!suiteTestIds.has(sIdStr)) suiteTestIds.set(sIdStr, new Set());
        (suite.testsets || []).forEach(testset => {
            const tsIdStr = String(testset.id);
            const tsTestIds = new Set();
            testsetById.set(tsIdStr, { suite, testset });
            (testset.tests || []).forEach(test => {
                const tIdStr = String(test.id);
                testById.set(tIdStr, { suite, testset, test });
                tsTestIds.add(tIdStr);
                suiteTestIds.get(sIdStr).add(tIdStr);
            });
            testsetTestIds.set(tsIdStr, tsTestIds);
        });
    });

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------
    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatRelativeTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return '';
        const diffMs = Date.now() - date.getTime();
        const diffMins = Math.max(0, Math.floor(diffMs / 60000));
        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
    }

    function showToast(message) {
        if (!toastContainer) return;
        const toast = document.createElement('div');
        toast.className = 'toast toast-warning';
        toast.textContent = message;
        toastContainer.appendChild(toast);
        window.setTimeout(() => {
            toast.classList.add('is-hiding');
            window.setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 200);
        }, 4500);
    }

    // -----------------------------------------------------------------------
    // Base URL management
    // -----------------------------------------------------------------------
    function getStoredBaseUrl() { return window.localStorage.getItem('testbook_base_url'); }
    function setStoredBaseUrl(url) { window.localStorage.setItem('testbook_base_url', url); }
    function getCurrentBaseUrl() { return getStoredBaseUrl() || defaultBaseUrl; }
    function updateBaseUrlInput() { if (baseUrlInput) baseUrlInput.value = getCurrentBaseUrl(); }

    // -----------------------------------------------------------------------
    // Freshness
    // -----------------------------------------------------------------------
    function updateFreshnessUi(data) {
        if (lastSyncedLabel) {
            const display = data && data.last_synced_display ? data.last_synced_display : 'Never';
            lastSyncedLabel.textContent = `Last synced: ${display}`;
        }
        const hasStaleFlag = !!(data && typeof data.is_stale === 'boolean');
        if (freshnessStatusLabel) {
            freshnessStatusLabel.classList.remove('is-checking', 'is-up-to-date', 'is-stale');
            if (!hasStaleFlag) {
                freshnessStatusLabel.classList.add('is-checking');
                freshnessStatusLabel.textContent = 'Status: Unable to check freshness';
            } else if (data.is_stale) {
                const relative = formatRelativeTime(data.remote_updated_at);
                freshnessStatusLabel.classList.add('is-stale');
                freshnessStatusLabel.textContent = relative ? `Status: Out of date (GitHub changed ${relative})` : 'Status: Out of date';
            } else {
                freshnessStatusLabel.classList.add('is-up-to-date');
                freshnessStatusLabel.textContent = 'Status: Up to date';
            }
        }
        if (syncButton) {
            if (data && data.is_stale) { syncButton.classList.add('is-stale'); syncButton.title = 'Tests changed in GitHub since last sync'; }
            else { syncButton.classList.remove('is-stale'); syncButton.removeAttribute('title'); }
        }
        if (hasStaleFlag) {
            if (previousIsStale === false && data.is_stale) showToast('Tests changed in GitHub. Refresh to sync the latest updates.');
            previousIsStale = data.is_stale;
        }
    }

    function checkBranchFreshness() {
        if (!selectedBranch) return;
        fetch(`/api/branch-freshness?branch=${encodeURIComponent(selectedBranch)}`)
            .then(r => r.ok ? r.json() : null)
            .then(data => { if (data) updateFreshnessUi(data); })
            .catch(() => {});
    }

    // -----------------------------------------------------------------------
    // Plan button logic
    // -----------------------------------------------------------------------

    /**
     * Get all test IDs that would be affected by an action on a given item.
     * For a test: just that test
     * For a testset: all tests in that testset
     * For a suite: all tests in all testsets in that suite
     */
    function getAffectedTestIds(itemId, itemType) {
        if (itemType === 'test') {
            return new Set([String(itemId)]);
        } else if (itemType === 'testset') {
            return testsetTestIds.get(String(itemId)) || new Set();
        } else if (itemType === 'suite') {
            return suiteTestIds.get(String(itemId)) || new Set();
        }
        return new Set();
    }

    function makePlanBtn(label, action, testIds, cssClass, title) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = label;
        btn.title = title || '';
        btn.className = `btn-plan btn-plan-${cssClass}`;
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            callPlanApi(action, testIds);
        });
        return btn;
    }

    /**
     * Given a set of all test IDs for an item and the current plan membership,
     * returns an array of {label, action, ids, cssClass} descriptors.
     */
    function planBtnDescriptors(allIds) {
        if (!activePlanId || !allIds || allIds.size === 0) return [];
        const allArr = Array.from(allIds);
        const inCount = allArr.filter(id => planTestIds.has(id)).length;
        if (inCount === 0) {
            return [{ label: '+', title: 'Add to plan', action: 'add', ids: allArr, cssClass: 'add' }];
        } else if (inCount === allArr.length) {
            return [{ label: '−', title: 'Remove from plan', action: 'remove', ids: allArr, cssClass: 'remove' }];
        } else {
            return [
                { label: '+', title: 'Add remaining to plan', action: 'add', ids: allArr.filter(id => !planTestIds.has(id)), cssClass: 'add' },
                { label: '−', title: 'Remove from plan', action: 'remove', ids: allArr.filter(id => planTestIds.has(id)), cssClass: 'remove' },
            ];
        }
    }

    function renderPlanButtons() {
        if (!activePlanId) return;

        // Suite slots
        document.querySelectorAll('.plan-btn-slot[data-for-suite]').forEach(slot => {
            const suiteId = String(slot.dataset.forSuite);
            const allIds = suiteTestIds.get(suiteId) || new Set();
            slot.innerHTML = '';
            planBtnDescriptors(allIds).forEach(d => slot.appendChild(makePlanBtn(d.label, d.action, d.ids, d.cssClass, d.title)));
        });

        // Testset slots
        document.querySelectorAll('.plan-btn-slot[data-for-testset]').forEach(slot => {
            const tsId = String(slot.dataset.forTestset);
            const allIds = testsetTestIds.get(tsId) || new Set();
            slot.innerHTML = '';
            planBtnDescriptors(allIds).forEach(d => slot.appendChild(makePlanBtn(d.label, d.action, d.ids, d.cssClass, d.title)));
        });

        // Individual test slots
        document.querySelectorAll('.plan-btn-slot[data-for-test]').forEach(slot => {
            const tId = String(slot.dataset.forTest);
            const allIds = new Set([tId]);
            slot.innerHTML = '';
            planBtnDescriptors(allIds).forEach(d => slot.appendChild(makePlanBtn(d.label, d.action, d.ids, d.cssClass, d.title)));
        });
    }

    function callPlanApi(action, testIds) {
        if (!activePlanId) return;
        fetch(`/api/plan/${encodeURIComponent(activePlanId)}/tests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, test_ids: testIds }),
        })
            .then(r => r.ok ? r.json() : Promise.reject(r))
            .then(data => {
                // Update plan membership from API response
                planTestIds = new Set((data.test_ids || []).map(String));

                // Re-render all navigation buttons to reflect new state
                renderPlanButtons();

                // Re-render main content if anything is currently displayed
                // Always try to refresh the currently displayed target to update buttons
                if (currentlyDisplayedTarget) {
                    loadTarget(currentlyDisplayedTarget, false);
                } else {
                    // Fallback to using hash if we don't have tracking
                    const hash = window.location.hash ? window.location.hash.substring(1) : '';
                    if (hash) {
                        loadTarget(hash, false);
                    }
                }
            })
            .catch(() => showToast('Could not update the plan. Please try again.'));
    }

    // -----------------------------------------------------------------------
    // Test content rendering
    // -----------------------------------------------------------------------
    function renderPlanBtnsForTest(testId) {
        if (!activePlanId) return '';
        const tIdStr = String(testId);
        const descriptors = planBtnDescriptors(new Set([tIdStr]));
        return descriptors.map(d =>
            `<button type="button" title="${escapeHtml(d.title || '')}" class="btn-plan btn-plan-${escapeHtml(d.cssClass)}" data-plan-action="${escapeHtml(d.action)}" data-plan-test-ids="${escapeHtml(JSON.stringify(d.ids))}">${escapeHtml(d.label)}</button>`
        ).join('');
    }

    function renderPlanBtnsForTestset(testsetId) {
        if (!activePlanId) return '';
        const tsIdStr = String(testsetId);
        const allIds = testsetTestIds.get(tsIdStr) || new Set();
        const descriptors = planBtnDescriptors(allIds);
        return descriptors.map(d =>
            `<button type="button" title="${escapeHtml(d.title || '')}" class="btn-plan btn-plan-${escapeHtml(d.cssClass)}" data-plan-action="${escapeHtml(d.action)}" data-plan-test-ids="${escapeHtml(JSON.stringify(d.ids))}">${escapeHtml(d.label)}</button>`
        ).join('');
    }

    function renderTestset(testsetWrap) {
        const testset = testsetWrap.testset;
        const suite = testsetWrap.suite;
        if (!contentRoot) return;

        const currentBaseUrl = getCurrentBaseUrl();

        const testsHtml = (testset.tests || []).map((test, testIdx) => {
            const contextEntries = Object.entries(test.context || {});
            const contextHtml = contextEntries.length
                ? `<div class="test-context"><h4>Context</h4><ul>${contextEntries.map(([k, v]) => `<li><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</li>`).join('')}</ul></div>`
                : '';
            const setupHtml = (test.setup || []).length
                ? `<div class="test-setup"><h4>Setup</h4><ul>${test.setup.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`
                : '';
            const stepsHtml = (test.steps || []).map(step => {
                const resultsHtml = (step.results || []).length
                    ? `<div class="step-results"><h5>Expected results</h5><ul>${step.results.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul></div>`
                    : '';
                let pathHtml = '';
                if (step.path) {
                    const pathUrl = currentBaseUrl.replace(/\/$/, '') + '/' + step.path.replace(/^\//, '');
                    pathHtml = `<div class="step-link"><strong>Path:</strong> <a href="${escapeHtml(pathUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.path)}</a></div>`;
                }
                const linksHtml = [
                    pathHtml,
                    step.resource ? `<div class="step-link"><strong>Resource:</strong> ${step.resource_url ? `<a href="${escapeHtml(step.resource_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.resource)}</a>` : escapeHtml(step.resource)}</div>` : ''
                ].join('');
                return `<li class="step-item"><div class="step-instruction">${escapeHtml(step.text || '')}</div>${linksHtml}${resultsHtml}</li>`;
            }).join('');

            const planBtnsHtml = renderPlanBtnsForTest(test.id);

            return `
                <article class="test-card" id="test-${escapeHtml(test.id)}">
                    <div class="test-card-header">
                        <h3>${testIdx + 1}. ${escapeHtml(test.title)}</h3>
                        <div class="test-card-actions">
                            ${planBtnsHtml ? `<span class="plan-btns-inline">${planBtnsHtml}</span>` : ''}
                            ${test.github_edit_url ? `<a class="github-edit-link" href="${escapeHtml(test.github_edit_url)}" target="_blank" rel="noopener noreferrer">Edit on GitHub</a>` : ''}
                        </div>
                    </div>
                    ${contextHtml}
                    ${setupHtml}
                    <div class="test-steps">
                        <h4>Steps</h4>
                        <ol>${stepsHtml}</ol>
                    </div>
                </article>
            `;
        }).join('');

        const planBtnsHtml = renderPlanBtnsForTestset(testset.id);

        contentRoot.innerHTML = `
            <header class="testset-header-main">
                <div class="testset-header-content">
                    <div class="testset-info">
                        <h2>${escapeHtml(suite.name)}: ${escapeHtml(testset.name)}</h2>
                        <p class="muted">${(testset.tests || []).length} test${(testset.tests || []).length === 1 ? '' : 's'}</p>
                    </div>
                    ${planBtnsHtml ? `<div class="plan-btns-inline">${planBtnsHtml}</div>` : ''}
                </div>
            </header>
            ${testsHtml || '<p class="muted">No tests in this testset.</p>'}
        `;

        // Wire up plan buttons rendered into card HTML strings (they are in innerHTML so
        // the makePlanBtn event listeners won't work; use event delegation on contentRoot)
    }

     // Event delegation for plan buttons inside rendered test cards
    // This handles both testset header buttons and individual test buttons
    if (contentRoot) {
        contentRoot.addEventListener('click', function(e) {
            const btn = e.target.closest('.btn-plan[data-plan-action]');
            if (!btn) return;
            e.stopPropagation();
            e.preventDefault();
            try {
                const action = btn.dataset.planAction;
                const ids = JSON.parse(btn.dataset.planTestIds || '[]');
                callPlanApi(action, ids);
            } catch (_) {}
        });
    }

    // -----------------------------------------------------------------------
    // Navigation
    // -----------------------------------------------------------------------
    function setActiveTarget(target) {
        document.querySelectorAll('.nav-target.is-active').forEach(n => n.classList.remove('is-active'));
        const direct = document.querySelector(`.nav-target[data-target="${target}"]`);
        if (direct) direct.classList.add('is-active');
    }

    function loadTarget(target, pushHash) {
        if (!target) return;
        let selectedWrap = null;
        let selectedTestId = null;
        if (target.startsWith('set/')) {
            selectedWrap = testsetById.get(String(target.split('/')[1])) || null;
        } else if (target.startsWith('test/')) {
            const testId = target.split('/')[1];
            const testWrap = testById.get(String(testId)) || null;
            if (testWrap) { selectedWrap = { suite: testWrap.suite, testset: testWrap.testset }; selectedTestId = String(testWrap.test.id); }
        }
        if (!selectedWrap) return;
        currentlyDisplayedTarget = target;  // Track what's being displayed
        renderTestset(selectedWrap);
        setActiveTarget(target);
        if (selectedTestId) {
            const el = document.getElementById(`test-${selectedTestId}`);
            if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
        } else if (appMain) appMain.scrollTop = 0;
        if (pushHash) history.pushState(null, '', `#${target}`);
    }

    document.querySelectorAll('.nav-target').forEach(node => {
        node.addEventListener('click', function(e) {
            e.preventDefault();
            loadTarget(this.getAttribute('data-target'), true);
        });
    });

    const initialHash = window.location.hash ? window.location.hash.substring(1) : '';
    if (initialHash) {
        loadTarget(initialHash, false);
    } else if (suiteData.length > 0 && suiteData[0].testsets && suiteData[0].testsets.length > 0) {
        loadTarget(`set/${suiteData[0].testsets[0].id}`, false);
    }

    window.addEventListener('hashchange', function() {
        const hash = window.location.hash ? window.location.hash.substring(1) : '';
        if (hash) loadTarget(hash, false);
    });

    // -----------------------------------------------------------------------
    // Expand / Collapse
    // -----------------------------------------------------------------------
    const expandAllBtn = document.querySelector('.btn-expand-all');
    if (expandAllBtn) {
        expandAllBtn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.suite-content').forEach(c => {
                c.classList.remove('collapsed');
                const btn = c.closest('.suite-item').querySelector('.suite-header .toggle-btn');
                if (btn) { btn.querySelector('.toggle-icon').textContent = '▼'; btn.setAttribute('aria-expanded', 'true'); }
            });
            document.querySelectorAll('.test-list').forEach(c => {
                c.classList.remove('collapsed');
                const btn = c.closest('.testset-item').querySelector('.testset-header .toggle-btn');
                if (btn) { btn.querySelector('.toggle-icon').textContent = '▼'; btn.setAttribute('aria-expanded', 'true'); }
            });
        });
    }

    const collapseAllBtn = document.querySelector('.btn-collapse-all');
    if (collapseAllBtn) {
        collapseAllBtn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.suite-content').forEach(c => {
                c.classList.add('collapsed');
                const btn = c.closest('.suite-item').querySelector('.suite-header .toggle-btn');
                if (btn) { btn.querySelector('.toggle-icon').textContent = '▶'; btn.setAttribute('aria-expanded', 'false'); }
            });
            document.querySelectorAll('.test-list').forEach(c => {
                c.classList.add('collapsed');
                const btn = c.closest('.testset-item').querySelector('.testset-header .toggle-btn');
                if (btn) { btn.querySelector('.toggle-icon').textContent = '▶'; btn.setAttribute('aria-expanded', 'false'); }
            });
        });
    }

    document.querySelectorAll('.suite-header .toggle-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault(); e.stopPropagation();
            const content = this.closest('.suite-item').querySelector('.suite-content');
            const icon = this.querySelector('.toggle-icon');
            if (content) {
                content.classList.toggle('collapsed');
                const collapsed = content.classList.contains('collapsed');
                this.setAttribute('aria-expanded', String(!collapsed));
                icon.textContent = collapsed ? '▶' : '▼';
            }
        });
    });

    document.querySelectorAll('.testset-header .toggle-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault(); e.stopPropagation();
            const content = this.closest('.testset-item').querySelector('.test-list');
            const icon = this.querySelector('.toggle-icon');
            if (content) {
                content.classList.toggle('collapsed');
                const collapsed = content.classList.contains('collapsed');
                this.setAttribute('aria-expanded', String(!collapsed));
                icon.textContent = collapsed ? '▶' : '▼';
            }
        });
    });

    // -----------------------------------------------------------------------
    // Base URL event wiring
    // -----------------------------------------------------------------------
    function refreshCurrentTarget() {
        const hash = window.location.hash ? window.location.hash.substring(1) : '';
        if (hash) loadTarget(hash, false);
    }

    if (baseUrlSaveBtn) {
        baseUrlSaveBtn.addEventListener('click', function() {
            if (!baseUrlInput) return;
            const newUrl = baseUrlInput.value.trim();
            if (newUrl) { setStoredBaseUrl(newUrl); refreshCurrentTarget(); }
        });
    }
    if (baseUrlResetBtn) {
        baseUrlResetBtn.addEventListener('click', function() {
            window.localStorage.removeItem('testbook_base_url');
            updateBaseUrlInput();
            refreshCurrentTarget();
        });
    }
    if (baseUrlInput) {
        baseUrlInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && baseUrlSaveBtn) baseUrlSaveBtn.click();
        });
    }

    // -----------------------------------------------------------------------
    // Init
    // -----------------------------------------------------------------------
    updateBaseUrlInput();
    renderPlanButtons();
    checkBranchFreshness();
    if (Number.isFinite(freshnessCheckIntervalSeconds) && freshnessCheckIntervalSeconds > 0) {
        window.setInterval(checkBranchFreshness, freshnessCheckIntervalSeconds * 1000);
    }
});
