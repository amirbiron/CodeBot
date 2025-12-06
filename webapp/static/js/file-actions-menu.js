/**
 * File actions responsive toolbar with overflow menu + share/history/trash helpers.
 */
(function () {
    'use strict';

    const MOBILE_QUERY = window.matchMedia('(max-width: 640px)');
    const ACTIVE_BARS = new Set();

    const debounce = (fn, wait = 120) => {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(null, args), wait);
        };
    };

    const notify = (message, type = 'info', options = {}) => {
        try {
            if (window.bulkActions && typeof window.bulkActions.showNotification === 'function') {
                window.bulkActions.showNotification(message, type, options);
                return;
            }
        } catch (err) {
            console.warn('notification failed', err);
        }
        try {
            window.alert(message);
        } catch (_) {}
    };

    const closeModal = (overlay) => {
        if (overlay && overlay.parentNode) {
            overlay.parentNode.removeChild(overlay);
        }
    };

    const createModal = (title, contentHtml) => {
        const overlay = document.createElement('div');
        overlay.className = 'file-action-modal';
        overlay.innerHTML = `
            <div class="file-action-modal__content">
                <button type="button" class="file-action-modal__close" data-modal-close aria-label="סגור">✕</button>
                <h3 style="margin-top:0;">${title}</h3>
                <div class="file-action-modal__body">${contentHtml || ''}</div>
            </div>
        `;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', (ev) => {
            if (ev.target === overlay) {
                closeModal(overlay);
            }
        });
        const closeBtn = overlay.querySelector('[data-modal-close]');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => closeModal(overlay));
        }
        return overlay;
    };

    const shareFile = async (fileId, permanent) => {
        const body = JSON.stringify({
            type: permanent ? 'permanent' : 'temporary',
            permanent: !!permanent,
        });
        const resp = await fetch(`/api/share/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok || !data.url) {
            throw new Error(data.error || 'share_failed');
        }
        try {
            await navigator.clipboard.writeText(data.url);
            notify(permanent ? 'הקישור הקבוע הועתק' : 'קישור זמני הועתק', 'success');
        } catch (err) {
            console.warn('clipboard error', err);
            notify(data.url, 'info');
        }
        return data;
    };

    const openShareModal = (bar) => {
        const overlay = createModal(
            `📤 שיתוף "${bar.fileName}"`,
            `
            <p>בחרו סוג קישור לשיתוף הקובץ.</p>
            <div class="file-action-modal__actions">
                <button type="button" class="btn btn-primary" data-share-variant="temporary">
                    <i class="fas fa-clock"></i>
                    קישור זמני (24h)
                </button>
                <button type="button" class="btn btn-secondary" data-share-variant="permanent">
                    <i class="fas fa-infinity"></i>
                    קישור קבוע
                </button>
            </div>
            `
        );
        overlay.querySelectorAll('[data-share-variant]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const variant = btn.getAttribute('data-share-variant');
                btn.disabled = true;
                try {
                    const data = await shareFile(bar.fileId, variant === 'permanent');
                    if (data.url) {
                        overlay.querySelector('.file-action-modal__body').innerHTML = `
                            <p>הקישור הועתק ללוח:</p>
                            <div style="background: rgba(255,255,255,0.08); padding:0.5rem 0.75rem; border-radius:8px; direction:ltr; text-align:left;">
                                ${data.url}
                            </div>
                        `;
                        setTimeout(() => closeModal(overlay), 1800);
                    }
                } catch (err) {
                    console.error('share failed', err);
                    notify('שגיאה ביצירת קישור', 'error');
                    btn.disabled = false;
                }
            });
        });
    };

    const fetchHistory = async (bar) => {
        const resp = await fetch(`/api/file/${bar.fileId}/history`);
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
            throw new Error(data.error || 'history_failed');
        }
        return data;
    };

    const restoreVersion = async (bar, versionId, trigger) => {
        const confirmMsg = `להחזיר את "${bar.fileName}" לגרסה שנבחרה?`;
        if (!window.confirm(confirmMsg)) {
            return null;
        }
        if (trigger) {
            trigger.disabled = true;
        }
        try {
            const resp = await fetch(`/api/file/${bar.fileId}/history/${versionId}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'restore_failed');
            }
            notify('הגרסה שוחזרה בהצלחה', 'success');
            return data;
        } finally {
            if (trigger) {
                trigger.disabled = false;
            }
        }
    };

    const renderHistoryModal = (bar) => {
        const overlay = createModal(`🕐 היסטוריית גרסאות - ${bar.fileName}`, `
            <p style="margin-bottom:0;">טוען היסטוריה...</p>
        `);
        const body = overlay.querySelector('.file-action-modal__body');

        fetchHistory(bar)
            .then((data) => {
                const history = Array.isArray(data.history) ? data.history : [];
                if (!history.length) {
                    body.innerHTML = `<div class="file-history__empty">אין גרסאות קודמות.</div>`;
                    return;
                }
                const list = document.createElement('div');
                list.className = 'file-history__list';
                history.forEach((item) => {
                    const row = document.createElement('div');
                    row.className = 'file-history__item';
                    row.innerHTML = `
                        <div class="file-history__meta">
                            <strong>גרסה ${item.version}</strong>
                            <small>${item.updated_at || item.created_at || ''}</small>
                            <small>${item.size || ''} · ${item.lines || 0} שורות</small>
                        </div>
                        <div class="file-history__actions">
                            <a class="btn btn-secondary btn-icon btn-sm" data-history-view target="_blank" rel="noopener noreferrer" href="/file/${item.id}">
                                <i class="fas fa-eye"></i>
                                צפה
                            </a>
                            <button class="btn btn-primary btn-icon btn-sm" type="button" data-history-restore="${item.id}">
                                <i class="fas fa-undo"></i>
                                שחזר
                            </button>
                        </div>
                    `;
                    list.appendChild(row);
                });
                body.innerHTML = '';
                body.appendChild(list);
                body.querySelectorAll('[data-history-restore]').forEach((btn) => {
                    btn.addEventListener('click', async () => {
                        const versionId = btn.getAttribute('data-history-restore');
                        try {
                            const data = await restoreVersion(bar, versionId, btn);
                            if (data && data.file_id) {
                                const viewLink = btn.closest('.file-history__item')?.querySelector('[data-history-view]');
                                if (viewLink) {
                                    viewLink.href = `/file/${data.file_id}`;
                                }
                            }
                        } catch (err) {
                            console.error('restore error', err);
                            notify('שגיאה בשחזור הגרסה', 'error');
                        }
                    });
                });
            })
            .catch((err) => {
                console.error('history fetch failed', err);
                body.innerHTML = `<div class="file-history__empty">לא הצלחנו לטעון את ההיסטוריה.</div>`;
            });
    };

    const moveFileToTrash = async (bar) => {
        const msg = `להעביר את "${bar.fileName}" לסל המיחזור?`;
        if (!window.confirm(msg)) {
            return;
        }
        const resp = await fetch('/api/files/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: [bar.fileId] }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data.error || 'delete_failed');
        }
        const card = bar.root.closest('.file-card');
        if (card) {
            card.classList.add('is-trashed');
        }
        notify('הקובץ הועבר לסל המיחזור', 'success');
    };

    const handleGlobalClick = (event) => {
        ACTIVE_BARS.forEach((bar) => {
            if (!bar.root.contains(event.target)) {
                bar.closeMenu();
            }
        });
    };

    document.addEventListener('click', handleGlobalClick);

    class FileActionBar {
        constructor(root) {
            this.root = root;
            this.primary = root.querySelector('.file-actions__primary');
            this.menu = root.querySelector('.file-actions__menu');
            this.toggle = root.querySelector('.file-actions__menu-toggle');
            this.fileId = root.dataset.fileId;
            this.fileName = root.dataset.fileName || 'הקובץ';
            this.sourceUrl = root.dataset.sourceUrl || '';
            this.sourceHost = root.dataset.sourceHost || '';
            this.hasSource = root.dataset.hasSource === 'true' && !!this.sourceUrl;
            this.actions = this.collectActions();
            this.customItems = this.buildCustomItems();
            this.menuOpen = false;

            this.toggle?.addEventListener('click', (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                this.toggleMenu();
            });

            this.handleResize = debounce(() => this.reflow());
            window.addEventListener('resize', this.handleResize);
            try {
                MOBILE_QUERY.addEventListener('change', this.handleResize);
            } catch (_) {
                try {
                    MOBILE_QUERY.addListener(this.handleResize);
                } catch (err) {
                    console.warn('matchMedia listener unsupported', err);
                }
            }

            ACTIVE_BARS.add(this);
            this.reflow();
        }

        collectActions() {
            if (!this.primary) {
                return [];
            }
            return Array.from(this.primary.querySelectorAll('[data-action-id]')).map((el) => ({
                id: el.getAttribute('data-action-id'),
                element: el,
                label: el.getAttribute('data-action-label') || el.textContent.trim(),
                icon: el.getAttribute('data-action-icon') || '',
                priority: Number(el.getAttribute('data-action-priority') || '50'),
                fixed: el.getAttribute('data-action-fixed') === 'true',
            }));
        }

        buildCustomItems() {
            if (!this.fileId) {
                return [];
            }
            const items = [
                {
                    id: 'share',
                    label: 'שתף קובץ',
                    icon: '📤',
                    handler: () => openShareModal(this),
                },
                {
                    id: 'history',
                    label: 'היסטוריה',
                    icon: '🕐',
                    handler: () => renderHistoryModal(this),
                },
                {
                    id: 'trash',
                    label: 'העבר לסל',
                    icon: '🗑️',
                    handler: async () => {
                        try {
                            await moveFileToTrash(this);
                        } catch (err) {
                            console.error('trash failed', err);
                            notify('שגיאה בהעברת הקובץ לסל', 'error');
                        }
                    },
                    danger: true,
                },
            ];
            if (this.hasSource) {
                items.splice(1, 0, {
                    id: 'source',
                    label: this.sourceHost ? `למקור (${this.sourceHost})` : 'למקור',
                    icon: '🔗',
                    href: this.sourceUrl,
                });
            }
            return items;
        }

        toggleMenu(forceState) {
            const nextState = typeof forceState === 'boolean' ? forceState : !this.menuOpen;
            this.menuOpen = nextState;
            if (!this.menu) {
                return;
            }
            this.menu.setAttribute('aria-hidden', nextState ? 'false' : 'true');
            this.toggle?.setAttribute('aria-expanded', nextState ? 'true' : 'false');
        }

        closeMenu() {
            if (this.menuOpen) {
                this.toggleMenu(false);
            }
        }

        reflow() {
            if (!this.primary) {
                return;
            }
            this.actions.forEach((action) => {
                if (action.element) {
                    action.element.classList.remove('is-hidden');
                    action.element.removeAttribute('aria-hidden');
                    action.hidden = false;
                }
            });

            const hideable = this.actions
                .filter((action) => !action.fixed)
                .sort((a, b) => b.priority - a.priority);

            const needsOverflow = () => {
                if (!this.primary) return false;
                return this.primary.scrollWidth - this.primary.clientWidth > 4;
            };

            let guard = 0;
            while (needsOverflow() && guard < hideable.length) {
                const action = hideable[guard];
                if (action && action.element) {
                    action.hidden = true;
                    action.element.classList.add('is-hidden');
                    action.element.setAttribute('aria-hidden', 'true');
                }
                guard += 1;
            }

            this.renderMenu();
        }

        renderMenu() {
            if (!this.menu || !this.toggle) {
                return;
            }
            const items = [];

            this.customItems.forEach((item) => {
                if (item.id === 'source' && !this.hasSource) {
                    return;
                }
                items.push(item);
            });

            this.actions
                .filter((action) => action.hidden)
                .sort((a, b) => a.priority - b.priority)
                .forEach((action) => {
                    items.push({
                        id: `overflow-${action.id}`,
                        label: action.label,
                        icon: action.icon,
                        handler: () => {
                            this.closeMenu();
                            window.requestAnimationFrame(() => {
                                action.element?.click();
                            });
                        },
                    });
                });

            this.menu.innerHTML = '';
            if (!items.length) {
                this.toggle.classList.add('is-hidden');
                this.menu.setAttribute('aria-hidden', 'true');
                this.menuOpen = false;
                return;
            }

            this.toggle.classList.remove('is-hidden');
            items.forEach((item) => {
                const element = document.createElement(item.href ? 'a' : 'button');
                if (item.href) {
                    element.href = item.href;
                    element.target = '_blank';
                    element.rel = 'noopener noreferrer';
                } else {
                    element.type = 'button';
                    element.addEventListener('click', () => {
                        this.closeMenu();
                        try {
                            item.handler?.();
                        } catch (err) {
                            console.error('menu handler failed', err);
                        }
                    });
                }
                element.setAttribute('role', 'menuitem');
                element.className = 'file-actions__menu-item';
                if (item.danger) {
                    element.classList.add('file-actions__menu-item--danger');
                }
                const icon = item.icon ? `<span aria-hidden="true">${item.icon}</span>` : '';
                element.innerHTML = `${icon}<span>${item.label}</span>`;
                this.menu.appendChild(element);
            });
            this.menu.setAttribute('aria-hidden', 'true');
            this.toggle.setAttribute('aria-expanded', 'false');
            this.menuOpen = false;
        }
    }

    const init = () => {
        const roots = document.querySelectorAll('.file-actions[data-file-id]');
        roots.forEach((root) => {
            try {
                if (!root._fileActionBar) {
                    root._fileActionBar = new FileActionBar(root);
                }
            } catch (err) {
                console.error('failed to init file action bar', err);
            }
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
