document.addEventListener('DOMContentLoaded', function() {
    const suiteDataNode = document.getElementById('suite-data');
    const suiteData = suiteDataNode ? JSON.parse(suiteDataNode.textContent || '[]') : [];
    const defaultBaseUrlNode = document.getElementById('default-base-url');
    const defaultBaseUrl = defaultBaseUrlNode ? JSON.parse(defaultBaseUrlNode.textContent || '"http://localhost:5004/"') : 'http://localhost:5004/';
    const selectedBranchNode = document.getElementById('selected-branch');
    const selectedBranch = selectedBranchNode ? JSON.parse(selectedBranchNode.textContent || '""') : '';
    const freshnessCheckIntervalNode = document.getElementById('freshness-check-interval');
    const freshnessCheckIntervalSeconds = freshnessCheckIntervalNode ? Number(JSON.parse(freshnessCheckIntervalNode.textContent || '1800')) : 1800;
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

    function formatRelativeTime(timestamp) {
        if (!timestamp) {
            return '';
        }
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) {
            return '';
        }
        const diffMs = Date.now() - date.getTime();
        const diffMins = Math.max(0, Math.floor(diffMs / 60000));
        if (diffMins < 1) {
            return 'just now';
        }
        if (diffMins < 60) {
            return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
        }
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) {
            return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
        }
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;
    }

    function showToast(message) {
        if (!toastContainer) {
            return;
        }
        const toast = document.createElement('div');
        toast.className = 'toast toast-warning';
        toast.textContent = message;
        toastContainer.appendChild(toast);
        window.setTimeout(() => {
            toast.classList.add('is-hiding');
            window.setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 200);
        }, 4500);
    }

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
                freshnessStatusLabel.textContent = relative
                    ? `Status: Out of date (GitHub changed ${relative})`
                    : 'Status: Out of date';
            } else {
                freshnessStatusLabel.classList.add('is-up-to-date');
                freshnessStatusLabel.textContent = 'Status: Up to date';
            }
        }

        if (syncButton) {
            if (data && data.is_stale) {
                syncButton.classList.add('is-stale');
                syncButton.title = 'Tests changed in GitHub since last sync';
            } else {
                syncButton.classList.remove('is-stale');
                syncButton.removeAttribute('title');
            }
        }

        if (hasStaleFlag) {
            if (previousIsStale === false && data.is_stale) {
                showToast('Tests changed in GitHub. Refresh to sync the latest updates.');
            }
            previousIsStale = data.is_stale;
        }
    }

    function checkBranchFreshness() {
        if (!selectedBranch) {
            return;
        }
        fetch(`/api/branch-freshness?branch=${encodeURIComponent(selectedBranch)}`)
            .then(response => response.ok ? response.json() : null)
            .then(data => {
                if (data) {
                    updateFreshnessUi(data);
                }
            })
            .catch(() => {
                // Non-blocking: stale checks should not break page interactions.
            });
    }

    function getStoredBaseUrl() {
        return window.localStorage.getItem('testbook_base_url');
    }

    function setStoredBaseUrl(url) {
        window.localStorage.setItem('testbook_base_url', url);
    }

    function getCurrentBaseUrl() {
        const stored = getStoredBaseUrl();
        return stored || defaultBaseUrl;
    }

    function updateBaseUrlInput() {
        if (baseUrlInput) {
            baseUrlInput.value = getCurrentBaseUrl();
        }
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const testsetById = new Map();
    const testById = new Map();
    suiteData.forEach(suite => {
        (suite.testsets || []).forEach(testset => {
            testsetById.set(String(testset.id), { suite: suite, testset: testset });
            (testset.tests || []).forEach(test => {
                testById.set(String(test.id), { suite: suite, testset: testset, test: test });
            });
        });
    });

    function renderTestset(testsetWrap) {
        const testset = testsetWrap.testset;
        const suite = testsetWrap.suite;
        if (!contentRoot) {
            return;
        }

        const currentBaseUrl = getCurrentBaseUrl();

        const testsHtml = (testset.tests || []).map((test, testIdx) => {
            const contextEntries = Object.entries(test.context || {});
            const contextHtml = contextEntries.length
                ? `<div class="test-context"><h4>Context</h4><ul>${contextEntries.map(([k, v]) => `<li><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</li>`).join('')}</ul></div>`
                : '';
            const setupHtml = (test.setup || []).length
                ? `<div class="test-setup"><h4>Setup</h4><ul>${test.setup.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>`
                : '';
            const stepsHtml = (test.steps || []).map((step, stepIdx) => {
                const resultsHtml = (step.results || []).length
                    ? `<div class="step-results"><h5>Expected results</h5><ul>${step.results.map(result => `<li>${escapeHtml(result)}</li>`).join('')}</ul></div>`
                    : '';

                let pathHtml = '';
                if (step.path) {
                    const pathUrl = currentBaseUrl.replace(/\/$/, '') + '/' + step.path.replace(/^\//, '');
                    pathHtml = `<div class="step-link"><strong>Path:</strong> <a href="${escapeHtml(pathUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.path)}</a></div>`;
                }

                const linksHtml = [
                    pathHtml,
                    step.resource
                        ? `<div class="step-link"><strong>Resource:</strong> ${step.resource_url ? `<a href="${escapeHtml(step.resource_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(step.resource)}</a>` : escapeHtml(step.resource)}</div>`
                        : ''
                ].join('');
                return `<li class="step-item"><div class="step-instruction">${escapeHtml(step.text || '')}</div>${linksHtml}${resultsHtml}</li>`;
            }).join('');

            return `
                <article class="test-card" id="test-${escapeHtml(test.id)}">
                    <div class="test-card-header">
                        <h3>${testIdx + 1}. ${escapeHtml(test.title)}</h3>
                        ${test.github_edit_url ? `<a class="github-edit-link" href="${escapeHtml(test.github_edit_url)}" target="_blank" rel="noopener noreferrer">Edit on GitHub</a>` : ''}
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

        contentRoot.innerHTML = `
            <header class="testset-header-main">
                <h2>${escapeHtml(suite.name)}: ${escapeHtml(testset.name)}</h2>
                <p class="muted">${(testset.tests || []).length} test${(testset.tests || []).length === 1 ? '' : 's'}</p>
            </header>
            ${testsHtml || '<p class="muted">No tests in this testset.</p>'}
        `;
    }

    function setActiveTarget(target) {
        document.querySelectorAll('.nav-target.is-active').forEach(node => node.classList.remove('is-active'));
        const directTarget = document.querySelector(`.nav-target[data-target="${target}"]`);
        if (directTarget) {
            directTarget.classList.add('is-active');
        }
    }

    function loadTarget(target, pushHash) {
        if (!target) {
            return;
        }

        let selectedWrap = null;
        let selectedTestId = null;
        if (target.startsWith('set/')) {
            const testsetId = target.split('/')[1];
            selectedWrap = testsetById.get(String(testsetId)) || null;
        } else if (target.startsWith('test/')) {
            const testId = target.split('/')[1];
            const testWrap = testById.get(String(testId)) || null;
            if (testWrap) {
                selectedWrap = { suite: testWrap.suite, testset: testWrap.testset };
                selectedTestId = String(testWrap.test.id);
            }
        }

        if (!selectedWrap) {
            return;
        }

        renderTestset(selectedWrap);
        setActiveTarget(target);

        if (selectedTestId) {
            const testElement = document.getElementById(`test-${selectedTestId}`);
            if (testElement) {
                testElement.scrollIntoView({ block: 'start', behavior: 'smooth' });
            }
        } else if (appMain) {
            appMain.scrollTop = 0;
        }

        if (pushHash) {
            history.pushState(null, '', `#${target}`);
        }
    }

    function refreshCurrentTarget() {
        const hash = window.location.hash ? window.location.hash.substring(1) : '';
        if (hash) {
            loadTarget(hash, false);
        }
    }

    document.querySelectorAll('.nav-target').forEach(node => {
        node.addEventListener('click', function(event) {
            event.preventDefault();
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
        if (hash) {
            loadTarget(hash, false);
        }
    });

    const expandAllBtn = document.querySelector('.btn-expand-all');
    if (expandAllBtn) {
        expandAllBtn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.suite-content').forEach(content => {
                content.classList.remove('collapsed');
                const btn = content.closest('.suite-item').querySelector('.suite-header .toggle-btn');
                if (btn) {
                    const icon = btn.querySelector('.toggle-icon');
                    icon.textContent = '▼';
                    btn.setAttribute('aria-expanded', 'true');
                }
            });
            document.querySelectorAll('.test-list').forEach(content => {
                content.classList.remove('collapsed');
                const btn = content.closest('.testset-item').querySelector('.testset-header .toggle-btn');
                if (btn) {
                    const icon = btn.querySelector('.toggle-icon');
                    icon.textContent = '▼';
                    btn.setAttribute('aria-expanded', 'true');
                }
            });
        });
    }

    const collapseAllBtn = document.querySelector('.btn-collapse-all');
    if (collapseAllBtn) {
        collapseAllBtn.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.suite-content').forEach(content => {
                content.classList.add('collapsed');
                const btn = content.closest('.suite-item').querySelector('.suite-header .toggle-btn');
                if (btn) {
                    const icon = btn.querySelector('.toggle-icon');
                    icon.textContent = '▶';
                    btn.setAttribute('aria-expanded', 'false');
                }
            });
            document.querySelectorAll('.test-list').forEach(content => {
                content.classList.add('collapsed');
                const btn = content.closest('.testset-item').querySelector('.testset-header .toggle-btn');
                if (btn) {
                    const icon = btn.querySelector('.toggle-icon');
                    icon.textContent = '▶';
                    btn.setAttribute('aria-expanded', 'false');
                }
            });
        });
    }

    document.querySelectorAll('.suite-header .toggle-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const suiteItem = this.closest('.suite-item');
            const content = suiteItem.querySelector('.suite-content');
            const icon = this.querySelector('.toggle-icon');
            if (content) {
                content.classList.toggle('collapsed');
                const isCollapsed = content.classList.contains('collapsed');
                this.setAttribute('aria-expanded', String(!isCollapsed));
                icon.textContent = isCollapsed ? '▶' : '▼';
            }
        });
    });

    document.querySelectorAll('.testset-header .toggle-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const testsetItem = this.closest('.testset-item');
            const content = testsetItem.querySelector('.test-list');
            const icon = this.querySelector('.toggle-icon');
            if (content) {
                content.classList.toggle('collapsed');
                const isCollapsed = content.classList.contains('collapsed');
                this.setAttribute('aria-expanded', String(!isCollapsed));
                icon.textContent = isCollapsed ? '▶' : '▼';
            }
        });
    });

    if (baseUrlSaveBtn) {
        baseUrlSaveBtn.addEventListener('click', function() {
            if (!baseUrlInput) {
                return;
            }
            const newUrl = baseUrlInput.value.trim();
            if (newUrl) {
                setStoredBaseUrl(newUrl);
                refreshCurrentTarget();
            }
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
        baseUrlInput.addEventListener('keypress', function(event) {
            if (event.key === 'Enter' && baseUrlSaveBtn) {
                baseUrlSaveBtn.click();
            }
        });
    }

    updateBaseUrlInput();
    checkBranchFreshness();
    if (Number.isFinite(freshnessCheckIntervalSeconds) && freshnessCheckIntervalSeconds > 0) {
        window.setInterval(checkBranchFreshness, freshnessCheckIntervalSeconds * 1000);
    }
});

