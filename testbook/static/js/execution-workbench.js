/**
 * Execution Workbench
 *
 * Renders interactive test execution panels with:
 * - Pass/Fail buttons for each result
 * - Comment fields for steps and results
 * - Test-wide pass/fail buttons with smart state management
 * - Real-time AJAX saving
 */

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

    const contentRoot = document.getElementById('test-content-root');
    const appMain = document.querySelector('.app-main');

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

    // -----------------------------------------------------------------------
    // Execution state management
    // -----------------------------------------------------------------------
    const executionStateMap = new Map(); // resultId -> {status: 'pass'|'fail'|'pending', comment: string}
    const executionStepComments = new Map(); // stepId -> comment string
    const executionTestState = new Map(); // testId -> {status: 'pass'|'fail'|'pending'|'skipped', manualStatus: ''|'pass'|'fail'|'skipped', comment: string}

    function normalizeTestStatus(status) {
        return ['pending', 'pass', 'fail', 'skipped'].includes(status) ? status : 'pending';
    }

    function normalizeManualTestStatus(status) {
        return ['pass', 'fail', 'skipped'].includes(status) ? status : '';
    }

    function getResultState(resultId) {
        return executionStateMap.get(String(resultId)) || { status: 'pending', comment: '' };
    }

    function setResultState(resultId, status, comment) {
        const rId = String(resultId);
        executionStateMap.set(rId, { status, comment });
    }

    function getStepComment(stepId) {
        return executionStepComments.get(String(stepId)) || '';
    }

    function setStepComment(stepId, comment) {
        executionStepComments.set(String(stepId), comment);
    }

    function getTestState(testId) {
        const state = executionTestState.get(String(testId)) || { status: 'pending', manualStatus: '', comment: '' };
        return {
            status: normalizeTestStatus(state.status),
            manualStatus: normalizeManualTestStatus(state.manualStatus),
            comment: state.comment || ''
        };
    }

    function setTestState(testId, status, comment, manualStatus) {
        const current = getTestState(testId);
        executionTestState.set(String(testId), {
            status: normalizeTestStatus(status),
            manualStatus: manualStatus === undefined
                ? current.manualStatus
                : normalizeManualTestStatus(manualStatus),
            comment: comment === undefined ? current.comment : (comment || '')
        });
    }

    function deriveTestStatusFromResultIds(resultIds) {
        const statuses = (resultIds || []).map(resultId => getResultState(resultId).status || 'pending');
        const hasFail = statuses.some(status => status === 'fail');
        const allPass = statuses.length > 0 && statuses.every(status => status === 'pass');
        return {
            hasFail,
            allPass,
            status: hasFail ? 'fail' : (allPass ? 'pass' : 'pending')
        };
    }

    function updateExecutionNavStatusIndicator(testId, status) {
        const indicator = document.querySelector(`.exec-nav-status[data-test-id="${testId}"]`);
        if (!indicator) return;
        const navStatus = status === 'pending' ? 'todo' : normalizeTestStatus(status);
        indicator.dataset.status = navStatus;
        indicator.textContent = navStatus;
        indicator.classList.remove(
            'exec-nav-status--todo',
            'exec-nav-status--pass',
            'exec-nav-status--fail',
            'exec-nav-status--skipped'
        );
        indicator.classList.add(`exec-nav-status--${navStatus}`);
    }

    function applyDerivedTestStatusForCard(testCard, persist) {
        if (!testCard) return;
        const testId = String(testCard.dataset.testId || '');
        if (!testId) return;

        const resultIds = Array.from(testCard.querySelectorAll('.exec-result-row[data-result-id]'))
            .map(row => String(row.dataset.resultId || ''))
            .filter(Boolean);
        const derived = deriveTestStatusFromResultIds(resultIds);

        const existingState = getTestState(testId);
        const previousStatus = existingState.status;
        const effectiveStatus = derived.hasFail
            ? 'fail'
            : (existingState.manualStatus || (derived.allPass ? 'pass' : 'pending'));
        const nextState = {
            status: effectiveStatus,
            manualStatus: existingState.manualStatus,
            comment: existingState.comment || ''
        };
        executionTestState.set(testId, nextState);

        const passBtn = testCard.querySelector(`.btn-test-pass[data-test-id="${testId}"]`);
        const failBtn = testCard.querySelector(`.btn-test-fail[data-test-id="${testId}"]`);
        const skippedBtn = testCard.querySelector(`.btn-test-skipped[data-test-id="${testId}"]`);
        if (passBtn) {
            passBtn.disabled = derived.hasFail;
            passBtn.classList.toggle('is-disabled', derived.hasFail);
            passBtn.classList.toggle('is-active', effectiveStatus === 'pass' && !derived.hasFail);
        }
        if (failBtn) {
            failBtn.classList.toggle('is-active', effectiveStatus === 'fail');
        }
        if (skippedBtn) {
            skippedBtn.classList.toggle('is-active', effectiveStatus === 'skipped');
        }

        updateExecutionNavStatusIndicator(testId, effectiveStatus);
        testCard.dataset.persistedStatus = effectiveStatus;

        if (persist && previousStatus !== effectiveStatus) {
            saveTestStatus(testId, effectiveStatus, nextState.comment);
        }

        return nextState;
    }

    // -----------------------------------------------------------------------
    // API calls
    // -----------------------------------------------------------------------
    function saveResultStatus(resultId, status, comment) {
        const payload = {
            status: status,
            comment: comment || ''
        };
        return fetch(`/api/execution-result/${encodeURIComponent(resultId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) return Promise.reject(r);
            return r.json();
        }).catch(err => {
            console.error('Failed to save result status:', err);
            return null;
        });
    }

    function saveStepComment(stepId, comment) {
        const payload = { comment: comment || '' };
        return fetch(`/api/execution-step/${encodeURIComponent(stepId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) return Promise.reject(r);
            return r.json();
        }).catch(err => {
            console.error('Failed to save step comment:', err);
            return null;
        });
    }

    function saveTestStatus(testId, status, comment) {
        const payload = {
            status: status,
            comment: comment || ''
        };
        return fetch(`/api/execution-test/${encodeURIComponent(testId)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(r => {
            if (!r.ok) return Promise.reject(r);
            return r.json();
        }).catch(err => {
            console.error('Failed to save test status:', err);
            return null;
        });
    }

    // -----------------------------------------------------------------------
    // Test rendering
    // -----------------------------------------------------------------------
    function renderTestset(testsetWrap) {
        const testset = testsetWrap.testset;
        const suite = testsetWrap.suite;
        if (!contentRoot) return;

        const currentBaseUrl = getCurrentBaseUrl();

        // Load initial state from payload
        executionStateMap.clear();
        executionStepComments.clear();
        executionTestState.clear();

        (testset.tests || []).forEach(test => {
            if (test.id) {
                executionTestState.set(String(test.id), {
                    status: normalizeTestStatus(test.status || 'pending'),
                    manualStatus: normalizeManualTestStatus(test.status || ''),
                    comment: test.comment || ''
                });
            }
            (test.steps || []).forEach(step => {
                if (step.id) {
                    executionStepComments.set(String(step.id), step.comment || '');
                }
                (step.results || []).forEach(result => {
                    if (result.id) {
                        executionStateMap.set(String(result.id), {
                            status: result.status || 'pending',
                            comment: result.comment || ''
                        });
                    }
                });
            });
        });

        const testsHtml = (testset.tests || []).map((test, testIdx) => {
            const testId = String(test.id);
            const contextEntries = Object.entries(test.context || {});

            // Context section
            const contextHtml = contextEntries.length
                ? `<div class="exec-test-context">
                    <h4>Context</h4>
                    <ul>${contextEntries.map(([k, v]) => `<li><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</li>`).join('')}</ul>
                   </div>`
                : '';

            // Setup section
            const setupHtml = (test.setup || []).length
                ? `<div class="exec-test-setup">
                    <h4>Setup</h4>
                    <ul>${test.setup.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
                   </div>`
                : '';

            // Steps and results in tabular form
            const stepsHtml = (test.steps || []).map((step, stepIdx) => {
                const stepId = String(step.id);
                const results = (step.results || []);

                // Step header with path/resource links
                let pathHtml = '';
                if (step.path) {
                    const pathUrl = currentBaseUrl.replace(/\/$/, '') + '/' + step.path.replace(/^\//, '');
                    pathHtml = `<div class="exec-step-link"><strong>Path:</strong> <a href="${escapeHtml(pathUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.path)}</a></div>`;
                }
                const resourceHtml = step.resource ? `<div class="exec-step-link"><strong>Resource:</strong> ${step.resource_url ? `<a href="${escapeHtml(step.resource_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.resource)}</a>` : escapeHtml(step.resource)}</div>` : '';

                const linksHtml = [pathHtml, resourceHtml].join('');

                // Results table
                const resultsTableHtml = (results && results.length > 0)
                    ? `<div class="exec-results-section">
                        <h5>Expected Results</h5>
                        <table class="exec-results-table">
                            <tbody>
                                ${results.map((result, resultIdx) => {
                                    const resultId = String(result.id);
                                    const resultText = typeof result === 'string' ? result : String(result.text || '');
                                    const state = getResultState(resultId);
                                    const commentOpen = state.comment ? 'comment-open' : '';
                                    return `
                                        <tr class="exec-result-row ${commentOpen}" data-result-id="${escapeHtml(resultId)}">
                                            <td class="exec-result-text">${escapeHtml(resultText)}</td>
                                            <td class="exec-result-actions">
                                                <button type="button" class="btn-result btn-result-pass ${state.status === 'pass' ? 'is-active' : ''}" 
                                                        data-result-id="${escapeHtml(resultId)}" title="Mark as Pass">✓</button>
                                                <button type="button" class="btn-result btn-result-fail ${state.status === 'fail' ? 'is-active' : ''}" 
                                                        data-result-id="${escapeHtml(resultId)}" title="Mark as Fail">✗</button>
                                                <button type="button" class="btn-result-comment ${state.comment ? 'has-comment' : ''}" 
                                                        data-result-id="${escapeHtml(resultId)}" data-step-id="${escapeHtml(stepId)}" title="Comment">💬</button>
                                            </td>
                                        </tr>
                                        <tr class="exec-result-comment-row ${state.comment ? 'is-visible' : ''}" data-result-id="${escapeHtml(resultId)}">
                                            <td colspan="2">
                                                <textarea class="exec-result-comment-box" placeholder="Any issues with this result..." data-result-id="${escapeHtml(resultId)}">${escapeHtml(state.comment)}</textarea>
                                            </td>
                                        </tr>
                                    `;
                                }).join('')}
                            </tbody>
                        </table>
                    </div>`
                    : '';

                // Step comment section
                const stepComment = getStepComment(stepId);
                const stepCommentHtml = `
                    <textarea class="exec-step-comment-box ${stepComment ? '' : 'is-collapsed'}" placeholder="Any issues with this step..." data-step-id="${escapeHtml(stepId)}">${escapeHtml(stepComment)}</textarea>
                `;

                return `
                    <div class="exec-step-block" data-step-id="${escapeHtml(stepId)}">
                        <div class="exec-step-header">
                            <span class="exec-step-number">Step ${stepIdx + 1}</span>
                            <span class="exec-step-text">${escapeHtml(step.text || '')}</span>
                            <button type="button" class="btn-result-comment btn-step-comment-toggle ${stepComment ? 'has-comment is-open' : ''}" data-step-id="${escapeHtml(stepId)}" title="Step comment" aria-label="Toggle step comment">💬</button>
                        </div>
                        ${linksHtml}
                        ${stepCommentHtml}
                        ${resultsTableHtml}
                    </div>
                `;
            }).join('');

            // Test-wide pass/fail buttons
            // Determine if any result is fail
            const testResults = (test.steps || []).flatMap(step => step.results || []);
            const hasFailResult = testResults.some(r => getResultState(String(r.id)).status === 'fail');
            const allPassResults = testResults.length > 0 && testResults.every(r => getResultState(String(r.id)).status === 'pass');
            const testStateData = getTestState(String(testId));
            const effectiveTestStatus = hasFailResult
                ? 'fail'
                : (testStateData.manualStatus || (allPassResults ? 'pass' : 'pending'));

            const testStatusBtnsHtml = `
                <div class="exec-test-status-section">
                    <div class="exec-test-status-label">Test Result:</div>
                    <button type="button" class="btn-test-status btn-test-pass ${hasFailResult ? 'is-disabled' : ''} ${effectiveTestStatus === 'pass' && !hasFailResult ? 'is-active' : ''}" 
                            data-test-id="${escapeHtml(testId)}" 
                            title="${hasFailResult ? 'Disable because test has failing results' : 'Mark entire test as Pass'}"
                            ${hasFailResult ? 'disabled' : ''}>
                        Pass
                    </button>
                    <button type="button" class="btn-test-status btn-test-fail ${effectiveTestStatus === 'fail' ? 'is-active' : ''}" 
                            data-test-id="${escapeHtml(testId)}"
                            title="Mark entire test as Fail">
                        Fail
                    </button>
                    <button type="button" class="btn-test-status btn-test-skipped ${effectiveTestStatus === 'skipped' ? 'is-active' : ''}" 
                            data-test-id="${escapeHtml(testId)}"
                            title="Mark entire test as Skipped">
                        Skipped
                    </button>
                </div>
            `;

            // Test comment section
            const testCommentHtml = `
                <div class="exec-test-comment-section">
                    <h4>Test Comment</h4>
                    <textarea class="exec-test-comment-box" placeholder="General comments on this test ..." data-test-id="${escapeHtml(testId)}">${escapeHtml(testStateData.comment)}</textarea>
                </div>
            `;

            return `
                <article class="exec-test-card" id="exec-test-${escapeHtml(testId)}" data-test-id="${escapeHtml(testId)}" data-persisted-status="${escapeHtml(effectiveTestStatus)}">
                    <div class="exec-test-card-header">
                        <h3>${testIdx + 1}. ${escapeHtml(test.title)}</h3>
                    </div>
                    ${contextHtml}
                    ${setupHtml}
                    <div class="exec-test-steps">
                        ${stepsHtml}
                    </div>
                    ${testStatusBtnsHtml}
                    ${testCommentHtml}
                </article>
            `;
        }).join('');

        contentRoot.innerHTML = `
            <header class="exec-testset-header-main">
                <div class="exec-testset-header-content">
                    <div class="exec-testset-info">
                        <h2>${escapeHtml(suite.name)}: ${escapeHtml(testset.name)}</h2>
                        <p class="muted">${(testset.tests || []).length} test${(testset.tests || []).length === 1 ? '' : 's'}</p>
                    </div>
                </div>
            </header>
            ${testsHtml || '<p class="muted">No tests in this testset.</p>'}
        `;

        // Wire up event handlers
        attachExecutionEventHandlers();
    }

    // -----------------------------------------------------------------------
    // Event handlers
    // -----------------------------------------------------------------------
    function attachExecutionEventHandlers() {
        if (!contentRoot) return;

        // Result pass/fail buttons
        contentRoot.querySelectorAll('.btn-result-pass').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const resultId = this.dataset.resultId;
                const state = getResultState(resultId);
                const newStatus = state.status === 'pass' ? 'pending' : 'pass';
                setResultState(resultId, newStatus, state.comment);
                updateResultButtonDisplay(resultId);
                const testCard = this.closest('.exec-test-card');
                if (testCard) {
                    const testId = String(testCard.dataset.testId || '');
                    const testState = getTestState(testId);
                    if (testState.manualStatus === 'skipped') {
                        setTestState(testId, testState.status, testState.comment, '');
                    }
                }
                applyDerivedTestStatusForCard(testCard, true);
                saveResultStatus(resultId, newStatus, state.comment);
            });
        });

        contentRoot.querySelectorAll('.btn-result-fail').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const resultId = this.dataset.resultId;
                const state = getResultState(resultId);
                const newStatus = state.status === 'fail' ? 'pending' : 'fail';
                setResultState(resultId, newStatus, state.comment);
                updateResultButtonDisplay(resultId);
                const testCard = this.closest('.exec-test-card');
                if (testCard) {
                    const testId = String(testCard.dataset.testId || '');
                    const testState = getTestState(testId);
                    if (testState.manualStatus === 'skipped') {
                        setTestState(testId, testState.status, testState.comment, '');
                    }
                }
                if (newStatus === 'fail') {
                    // Auto-open comment box
                    const commentRow = contentRoot.querySelector(`.exec-result-comment-row[data-result-id="${resultId}"]`);
                    if (commentRow) {
                        commentRow.classList.add('is-visible');
                        const commentBox = commentRow.querySelector('.exec-result-comment-box');
                        if (commentBox) {
                            commentBox.focus();
                        }
                    }
                }
                applyDerivedTestStatusForCard(testCard, true);
                saveResultStatus(resultId, newStatus, state.comment);
            });
        });

        // Result comment toggle buttons
        contentRoot.querySelectorAll('.btn-result-comment').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const resultId = this.dataset.resultId;
                if (!resultId) return;
                const commentRow = contentRoot.querySelector(`.exec-result-comment-row[data-result-id="${resultId}"]`);
                if (commentRow) {
                    commentRow.classList.toggle('is-visible');
                    if (commentRow.classList.contains('is-visible')) {
                        const commentBox = commentRow.querySelector('.exec-result-comment-box');
                        if (commentBox) {
                            commentBox.focus();
                        }
                    }
                }
            });
        });

        // Result comment text areas
        contentRoot.querySelectorAll('.exec-result-comment-box').forEach(textarea => {
            textarea.addEventListener('change', function() {
                const resultId = this.dataset.resultId;
                const state = getResultState(resultId);
                const comment = this.value;
                setResultState(resultId, state.status, comment);
                updateResultCommentButton(resultId);
                saveResultStatus(resultId, state.status, comment);
            });
        });

        // Step comment toggle buttons
        contentRoot.querySelectorAll('.btn-step-comment-toggle').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const stepId = this.dataset.stepId;
                const stepBlock = contentRoot.querySelector(`.exec-step-block[data-step-id="${stepId}"]`);
                if (stepBlock) {
                    const commentBox = stepBlock.querySelector('.exec-step-comment-box');
                    if (commentBox) {
                        commentBox.classList.toggle('is-collapsed');
                        this.classList.toggle('is-open', !commentBox.classList.contains('is-collapsed'));
                        if (!commentBox.classList.contains('is-collapsed')) {
                            commentBox.focus();
                        }
                    }
                }
            });
        });

        // Step comment text areas
        contentRoot.querySelectorAll('.exec-step-comment-box').forEach(textarea => {
            textarea.addEventListener('change', function() {
                const stepId = this.dataset.stepId;
                const comment = this.value;
                setStepComment(stepId, comment);
                const toggleBtn = contentRoot.querySelector(`.btn-step-comment-toggle[data-step-id="${stepId}"]`);
                if (toggleBtn) {
                    toggleBtn.classList.toggle('has-comment', !!comment.trim());
                }
                saveStepComment(stepId, comment);
            });
        });

        // Test pass/fail/skipped buttons
        contentRoot.querySelectorAll('.btn-test-status').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                if (this.disabled) return;
                const testId = this.dataset.testId;
                const currentState = getTestState(testId);
                let selectedStatus = 'pass';
                if (this.classList.contains('btn-test-fail')) {
                    selectedStatus = 'fail';
                } else if (this.classList.contains('btn-test-skipped')) {
                    selectedStatus = 'skipped';
                }
                const nextManualStatus = currentState.manualStatus === selectedStatus ? '' : selectedStatus;
                setTestState(testId, nextManualStatus || 'pending', currentState.comment, nextManualStatus);
                const testCard = this.closest('.exec-test-card');
                const effectiveState = applyDerivedTestStatusForCard(testCard, false) || getTestState(testId);
                saveTestStatus(testId, effectiveState.status, effectiveState.comment);
            });
        });

        // Test comment text areas
        contentRoot.querySelectorAll('.exec-test-comment-box').forEach(textarea => {
            textarea.addEventListener('change', function() {
                const testId = this.dataset.testId;
                const comment = this.value;
                const currentState = getTestState(testId);
                setTestState(testId, currentState.status, comment, currentState.manualStatus);
                saveTestStatus(testId, currentState.status, comment);
            });
        });

        // Ensure test status buttons always reflect current result states.
        contentRoot.querySelectorAll('.exec-test-card').forEach(card => {
            applyDerivedTestStatusForCard(card, false);
        });
    }

    function updateResultButtonDisplay(resultId) {
        const state = getResultState(resultId);
        const passBtn = contentRoot.querySelector(`.btn-result-pass[data-result-id="${resultId}"]`);
        const failBtn = contentRoot.querySelector(`.btn-result-fail[data-result-id="${resultId}"]`);

        if (passBtn) {
            passBtn.classList.toggle('is-active', state.status === 'pass');
        }
        if (failBtn) {
            failBtn.classList.toggle('is-active', state.status === 'fail');
        }
    }

    function updateResultCommentButton(resultId) {
        const state = getResultState(resultId);
        const commentBtn = contentRoot.querySelector(`.btn-result-comment[data-result-id="${resultId}"]`);
        if (commentBtn) {
            commentBtn.classList.toggle('has-comment', !!state.comment);
        }
    }

    // -----------------------------------------------------------------------
    // Base URL management
    // -----------------------------------------------------------------------
    function getStoredBaseUrl() { return window.localStorage.getItem('testbook_base_url'); }
    function setStoredBaseUrl(url) { window.localStorage.setItem('testbook_base_url', url); }
    function getCurrentBaseUrl() { return getStoredBaseUrl() || defaultBaseUrl; }

    // -----------------------------------------------------------------------
    // Navigation
    // -----------------------------------------------------------------------
    const testsetById = new Map();
    const testById = new Map();

    suiteData.forEach(suite => {
        (suite.testsets || []).forEach(testset => {
            const tsIdStr = String(testset.id);
            testsetById.set(tsIdStr, { suite, testset });
            (testset.tests || []).forEach(test => {
                const tIdStr = String(test.id);
                testById.set(tIdStr, { suite, testset, test });
            });
        });
    });

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
        renderTestset(selectedWrap);
        setActiveTarget(target);
        if (selectedTestId) {
            const el = document.getElementById(`exec-test-${selectedTestId}`);
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
    // Init
    // -----------------------------------------------------------------------
    // Initial render happens via hash navigation above
});








