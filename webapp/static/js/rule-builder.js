/**
 * Visual Rule Builder
 * ממשק Drag & Drop לבניית כללים ויזואליים
 */

class RuleBuilder {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            onRuleChange: () => {},
            availableFields: [],
            availableActions: [],
            ...options
        };

        this.rule = {
            conditions: { type: 'group', operator: 'AND', children: [] },
            actions: []
        };

        this.init();
    }

    /**
     * 🔧 תיקון באג #3: פונקציית Escape למניעת XSS
     * מקודדת תווים מיוחדים ב-HTML כדי למנוע הזרקת סקריפטים
     */
    htmlEscape(str) {
        if (str === null || str === undefined) return '';
        if (typeof str !== 'string') str = String(str);

        const escapeMap = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
            '/': '&#x2F;',
            '`': '&#x60;',
            '=': '&#x3D;'
        };

        return str.replace(/[&<>"'`=\/]/g, char => escapeMap[char]);
    }

    init() {
        // 🔧 תיקון: הוספת כפתור NOT לממשק
        this.container.innerHTML = `
            <div class="rule-builder">
                <div class="rule-builder__toolbar">
                    <button class="btn btn-sm" data-add="condition">+ תנאי</button>
                    <button class="btn btn-sm" data-add="group-and">+ קבוצת AND</button>
                    <button class="btn btn-sm" data-add="group-or">+ קבוצת OR</button>
                    <button class="btn btn-sm" data-add="group-not">🚫 קבוצת NOT</button>
                    <button class="btn btn-sm" data-add="action">+ פעולה</button>
                </div>
                <div class="rule-builder__canvas" data-drop-zone="root">
                    <div class="conditions-area">
                        <h4>תנאים (IF)</h4>
                        <div class="conditions-container" data-drop-zone="conditions"></div>
                    </div>
                    <div class="actions-area">
                        <h4>פעולות (THEN)</h4>
                        <div class="actions-container" data-drop-zone="actions"></div>
                    </div>
                </div>
                <div class="rule-builder__preview">
                    <h4>תצוגה מקדימה</h4>
                    <pre class="json-preview"></pre>
                </div>
            </div>
        `;

        this.setupEventListeners();
        this.setupDragAndDrop();
        this.render();
    }

    setupEventListeners() {
        // כפתורי הוספה
        this.container.querySelectorAll('[data-add]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const type = e.target.dataset.add;
                this.addBlock(type);
            });
        });
    }

    setupDragAndDrop() {
        // הגדרת Sortable.js או ספריית D&D אחרת
        const conditionsContainer = this.container.querySelector('.conditions-container');
        const actionsContainer = this.container.querySelector('.actions-container');

        if (typeof Sortable !== 'undefined') {
            new Sortable(conditionsContainer, {
                group: 'conditions',
                animation: 150,
                ghostClass: 'sortable-ghost',
                handle: '.drag-handle',  // רק האייקון משמש לגרירה
                filter: 'input, textarea, select, button', // ליתר ביטחון
                preventOnFilter: false,
                onEnd: () => this.syncFromDOM()
            });

            new Sortable(actionsContainer, {
                group: 'actions',
                animation: 150,
                ghostClass: 'sortable-ghost',
                handle: '.drag-handle',  // רק האייקון משמש לגרירה
                filter: 'input, textarea, select, button', // ליתר ביטחון
                preventOnFilter: false,
                onEnd: () => this.syncFromDOM()
            });
        }
    }

    addBlock(type) {
        switch (type) {
            case 'condition':
                this.rule.conditions.children.push(this.createCondition());
                break;
            case 'group-and':
                this.rule.conditions.children.push(this.createGroup('AND'));
                break;
            case 'group-or':
                this.rule.conditions.children.push(this.createGroup('OR'));
                break;
            // 🔧 תיקון: הוספת תמיכה ב-NOT operator
            case 'group-not':
                this.rule.conditions.children.push(this.createGroup('NOT'));
                break;
            case 'action':
                this.rule.actions.push(this.createAction());
                break;
        }
        this.render();
        this.notifyChange();
    }

    createCondition() {
        return {
            type: 'condition',
            field: '',
            operator: 'eq',
            value: ''
        };
    }

    createGroup(operator) {
        return {
            type: 'group',
            operator: operator,
            children: []
        };
    }

    /**
     * 🔧 תיקון: שדות Action מלאים בהתאם לסכמה
     *
     * שדות נדרשים:
     * - type: סוג הפעולה (send_alert, create_ticket, webhook, suppress, create_github_issue)
     * - severity: רמת חומרה (info, warning, critical)
     *
     * שדות אופציונליים (לפי סוג):
     * - channel: ערוץ יעד (telegram, slack, email)
     * - message_template: תבנית הודעה עם placeholders כמו {{rule_name}}, {{triggered_conditions}}
     * - labels: תגיות (למשל עבור GitHub Issues)
     * - assignees: רשימת assignees (עבור GitHub Issues)
     * - webhook_url: כתובת ה-webhook (עבור type=webhook)
     */
    createAction() {
        return {
            type: 'send_alert',
            severity: 'warning',
            channel: 'default',
            message_template: '🔔 {{rule_name}}: {{triggered_conditions}}'
        };
    }

    render() {
        // רינדור תנאים
        const conditionsHtml = this.renderConditions(this.rule.conditions);
        this.container.querySelector('.conditions-container').innerHTML = conditionsHtml;

        // רינדור פעולות
        const actionsHtml = this.renderActions(this.rule.actions);
        this.container.querySelector('.actions-container').innerHTML = actionsHtml;

        // עדכון תצוגה מקדימה
        this.container.querySelector('.json-preview').textContent =
            JSON.stringify(this.rule, null, 2);

        // הוספת event listeners לאלמנטים חדשים
        this.attachBlockEvents();
    }

    renderConditions(node, depth = 0) {
        if (node.type === 'condition') {
            return this.renderConditionBlock(node);
        } else if (node.type === 'group') {
            return this.renderGroupBlock(node, depth);
        }
        return '';
    }

    renderConditionBlock(condition) {
        const fields = this.options.availableFields;
        // 🔧 תיקון: רשימה מלאה של כל האופרטורים הנתמכים ב-Backend
        const operators = [
            { value: 'eq', label: '= שווה' },
            { value: 'ne', label: '≠ שונה' },
            { value: 'gt', label: '> גדול מ' },
            { value: 'gte', label: '≥ גדול או שווה' },
            { value: 'lt', label: '< קטן מ' },
            { value: 'lte', label: '≤ קטן או שווה' },
            { value: 'contains', label: 'מכיל' },
            { value: 'not_contains', label: 'לא מכיל' },
            { value: 'starts_with', label: 'מתחיל ב' },
            { value: 'ends_with', label: 'מסתיים ב' },
            { value: 'regex', label: 'RegEx' },
            { value: 'in', label: 'נמצא ברשימה' },
            { value: 'not_in', label: 'לא נמצא ברשימה' }
        ];

        return `
            <div class="block condition-block" data-type="condition">
                <div class="block__header">
                    <span class="block__icon drag-handle">📊</span>
                    <span class="block__title">תנאי</span>
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__content">
                    <select class="field-select" data-bind="field">
                        <option value="">בחר שדה...</option>
                        ${fields.map(f => `
                            <option value="${f.name}" ${condition.field === f.name ? 'selected' : ''}>
                                ${f.label}
                            </option>
                        `).join('')}
                    </select>
                    <select class="operator-select" data-bind="operator">
                        ${operators.map(op => `
                            <option value="${op.value}" ${condition.operator === op.value ? 'selected' : ''}>
                                ${op.label}
                            </option>
                        `).join('')}
                    </select>
                    <input type="text" class="value-input" data-bind="value"
                           value="${this.htmlEscape(condition.value)}" placeholder="ערך">
                </div>
            </div>
        `;
    }

    /**
     * 🔧 תיקון: תמיכה מלאה ב-NOT operator
     * - NOT מקבל רק ילד אחד
     * - עיצוב ייחודי לקבוצת NOT
     */
    renderGroupBlock(group, depth) {
        const operator = group.operator;
        let className, label, icon;

        switch (operator) {
            case 'AND':
                className = 'group-and';
                label = 'וגם (AND)';
                icon = '🔗';
                break;
            case 'OR':
                className = 'group-or';
                label = 'או (OR)';
                icon = '🔀';
                break;
            case 'NOT':
                className = 'group-not';
                label = 'היפוך (NOT)';
                icon = '🚫';
                break;
            default:
                className = 'group-and';
                label = operator;
                icon = '❓';
        }

        const childrenHtml = group.children
            .map(child => this.renderConditions(child, depth + 1))
            .join('');

        // NOT מקבל רק ילד אחד
        const showAddButton = operator !== 'NOT' || group.children.length === 0;
        const hint = operator === 'NOT'
            ? '<p class="empty-hint">גרור תנאי אחד לכאן (NOT הופך את התוצאה)</p>'
            : '<p class="empty-hint">גרור תנאים לכאן</p>';

        return `
            <div class="block group-block ${className}" data-type="group" data-operator="${operator}">
                <div class="block__header">
                    <span class="block__icon drag-handle">${icon}</span>
                    <span class="block__title">${label}</span>
                    ${showAddButton ? '<button class="block__add-child" data-action="add-condition">+ תנאי</button>' : ''}
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__children" data-drop-zone="group">
                    ${childrenHtml || hint}
                </div>
            </div>
        `;
    }

    /**
     * 🔧 תיקון: רינדור Action עם כל השדות הנדרשים
     *
     * שדות UI מלאים:
     * - type: סוג הפעולה (חובה)
     * - severity: רמת חומרה (חובה)
     * - channel: ערוץ יעד (אופציונלי, מוצג עבור send_alert)
     * - message_template: תבנית הודעה (אופציונלי, מוצג עבור send_alert)
     */
    renderActions(actions) {
        return actions.map((action, index) => {
            const showChannelAndTemplate = action.type === 'send_alert';

            return `
                <div class="block action-block" data-type="action" data-index="${index}">
                    <div class="block__header">
                        <span class="block__icon drag-handle">⚡</span>
                        <span class="block__title">פעולה</span>
                        <button class="block__delete" data-action="delete">×</button>
                    </div>
                    <div class="block__content">
                        <select class="action-type-select" data-bind="type">
                            <option value="send_alert" ${action.type === 'send_alert' ? 'selected' : ''}>
                                📢 שלח התראה
                            </option>
                            <option value="create_github_issue" ${action.type === 'create_github_issue' ? 'selected' : ''}>
                                🐛 צור GitHub Issue
                            </option>
                            <option value="create_ticket" ${action.type === 'create_ticket' ? 'selected' : ''}>
                                🎫 צור טיקט
                            </option>
                            <option value="webhook" ${action.type === 'webhook' ? 'selected' : ''}>
                                🔗 קרא ל-Webhook
                            </option>
                            <option value="suppress" ${action.type === 'suppress' ? 'selected' : ''}>
                                🔇 השתק התראות
                            </option>
                        </select>
                        <select class="severity-select" data-bind="severity">
                            <option value="info" ${action.severity === 'info' ? 'selected' : ''}>ℹ️ Info</option>
                            <option value="warning" ${action.severity === 'warning' ? 'selected' : ''}>⚠️ Warning</option>
                            <option value="critical" ${action.severity === 'critical' ? 'selected' : ''}>🔴 Critical</option>
                        </select>
                        ${showChannelAndTemplate ? `
                            <select class="channel-select" data-bind="channel">
                                <option value="default" ${action.channel === 'default' ? 'selected' : ''}>ברירת מחדל</option>
                                <option value="telegram" ${action.channel === 'telegram' ? 'selected' : ''}>📱 Telegram</option>
                                <option value="slack" ${action.channel === 'slack' ? 'selected' : ''}>💬 Slack</option>
                                <option value="email" ${action.channel === 'email' ? 'selected' : ''}>📧 Email</option>
                            </select>
                            <input type="text" class="message-template-input" data-bind="message_template"
                                   value="${this.htmlEscape(action.message_template || '')}"
                                   placeholder="תבנית הודעה: {{rule_name}}, {{triggered_conditions}}">
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }

    attachBlockEvents() {
        // מחיקת בלוקים
        this.container.querySelectorAll('[data-action="delete"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const block = e.target.closest('.block');
                this.deleteBlock(block);
            });
        });

        // שינויים בשדות
        this.container.querySelectorAll('[data-bind]').forEach(input => {
            input.addEventListener('change', () => this.syncFromDOM());
        });

        // הוספת תנאי לקבוצה
        this.container.querySelectorAll('[data-action="add-condition"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const block = e.target.closest('.group-block');
                this.addConditionToGroup(block);
            });
        });
    }

    /**
     * שלב 1 (לפי המדריך): פונקציית עזר רקורסיבית שממפה DOM -> JSON
     * @param {HTMLElement} element
     * @returns {object|null}
     */
    _parseNode(element) {
        if (!element || !element.dataset) return null;

        const type = element.dataset.type;

        if (type === 'condition') {
            const fieldEl = element.querySelector('[data-bind="field"]');
            const operatorEl = element.querySelector('[data-bind="operator"]');
            const valueEl = element.querySelector('[data-bind="value"]');

            return {
                type: 'condition',
                field: fieldEl ? fieldEl.value : '',
                operator: operatorEl ? operatorEl.value : 'eq',
                value: valueEl ? valueEl.value : ''
            };
        }

        if (type === 'group') {
            const operator = element.dataset.operator || element.getAttribute('data-operator') || 'AND';
            const childrenContainer =
                element.querySelector('.block__children') ||
                element.querySelector('[data-drop-zone="group"]');

            let children = [];
            if (childrenContainer) {
                children = Array.from(childrenContainer.children)
                    .filter(child => child && child.classList && child.classList.contains('block'))
                    .map(child => this._parseNode(child))
                    .filter(Boolean);
            }

            // NOT אמור לקבל רק ילד אחד (תואם למה שמוצג ב-UI)
            if (operator === 'NOT' && children.length > 1) {
                children = [children[0]];
            }

            return {
                type: 'group',
                operator: operator,
                children: children
            };
        }

        return null;
    }

    syncFromDOM() {
        // סנכרון מצב ה-DOM חזרה ל-rule object

        // 1) תנאים (Conditions)
        const conditionsContainer = this.container.querySelector('.conditions-container');
        if (conditionsContainer) {
            // תמיכה בשתי צורות DOM:
            // א) ילדים ברמה העליונה בתוך .conditions-container
            // ב) עטיפה של "root group" יחיד (כלומר: יש בלוק אחד בלבד ברמה העליונה והוא group)
            let topLevelContainer = conditionsContainer;
            const directBlocks = Array.from(conditionsContainer.children)
                .filter(child => child && child.classList && child.classList.contains('block'));

            if (directBlocks.length === 1 && directBlocks[0].dataset && directBlocks[0].dataset.type === 'group') {
                const rootGroup = directBlocks[0];
                const rootChildren =
                    rootGroup.querySelector('.block__children') ||
                    rootGroup.querySelector('[data-drop-zone="group"]');
                if (rootChildren) topLevelContainer = rootChildren;
            }

            const newChildren = Array.from(topLevelContainer.children)
                .filter(child => child && child.classList && child.classList.contains('block'))
                .map(child => this._parseNode(child))
                .filter(Boolean);

            this.rule.conditions.children = newChildren;
        }

        // 2) פעולות (Actions)
        const actionsContainer = this.container.querySelector('.actions-container');
        if (actionsContainer) {
            const actionBlocks = Array.from(actionsContainer.children)
                .filter(child => child && child.classList && child.classList.contains('action-block'));

            const newActions = actionBlocks.map(block => {
                const typeEl = block.querySelector('[data-bind="type"]');
                const severityEl = block.querySelector('[data-bind="severity"]');

                const type = typeEl ? typeEl.value : 'send_alert';
                const severity = severityEl ? severityEl.value : 'warning';

                const action = { type, severity };

                // עבור send_alert: ודא שאוספים גם channel ו-message_template
                if (type === 'send_alert') {
                    const channelEl = block.querySelector('[data-bind="channel"]');
                    const templateEl = block.querySelector('[data-bind="message_template"]');
                    action.channel = channelEl ? channelEl.value : 'default';
                    action.message_template = templateEl ? templateEl.value : '';
                }

                return action;
            });

            this.rule.actions = newActions;
        }

        // עדכון תצוגה מקדימה
        const previewEl = this.container.querySelector('.json-preview');
        if (previewEl) {
            previewEl.textContent = JSON.stringify(this.rule, null, 2);
        }

        // בסיום: notifyChange
        this.notifyChange();
    }

    deleteBlock(blockElement) {
        // מחיקת בלוק מה-DOM ואז סנכרון חזרה ל-rule
        if (!blockElement) return;
        if (!blockElement.classList || !blockElement.classList.contains('block')) return;

        blockElement.remove();

        // שלב 3 (לפי המדריך): לאחר מחיקה - סנכרון מיידי כדי לשמור עקביות
        this.syncFromDOM();

        // רינדור מחדש כדי להחזיר hints/אינדקסים/אירועים
        this.render();
    }

    addConditionToGroup(groupElement) {
        // הוספת תנאי לקבוצה דרך ה-DOM ואז סנכרון
        if (!groupElement) return;

        const childrenContainer =
            groupElement.querySelector('.block__children') ||
            groupElement.querySelector('[data-drop-zone="group"]');

        if (!childrenContainer) return;

        // אם יש hint ריק - הסר אותו לפני הוספה
        childrenContainer.querySelectorAll('.empty-hint').forEach(h => h.remove());

        const newCondition = this.createCondition();
        childrenContainer.insertAdjacentHTML('beforeend', this.renderConditionBlock(newCondition));

        this.syncFromDOM();
        this.render();
    }

    notifyChange() {
        this.options.onRuleChange(this.rule);
    }

    // API ציבורי

    getRule() {
        return JSON.parse(JSON.stringify(this.rule));
    }

    setRule(rule) {
        this.rule = JSON.parse(JSON.stringify(rule));
        this.render();
    }

    validate() {
        const errors = [];
        const conditions = this.rule.conditions;

        // 🔧 תיקון באג #4: תמיכה בתנאי בודד (לא רק קבוצה)
        // בדיקת מבנה התנאים - יכול להיות group או condition בודד
        if (!conditions || !conditions.type) {
            errors.push('מבנה התנאים אינו תקין');
        } else if (conditions.type === 'group') {
            // אם זו קבוצה, בדוק שיש לפחות תנאי אחד
            if (!conditions.children || conditions.children.length === 0) {
                errors.push('חובה להוסיף לפחות תנאי אחד לקבוצה');
            }
        } else if (conditions.type === 'condition') {
            // תנאי בודד תקין - ממשיך לבדיקת השדות
        } else {
            errors.push(`סוג תנאי לא מוכר: ${conditions.type}`);
        }

        // בדיקת פעולות
        if (this.rule.actions.length === 0) {
            errors.push('חובה להוסיף לפחות פעולה אחת');
        }

        // בדיקת שדות חסרים (רקורסיבית)
        if (conditions && conditions.type) {
            this.validateNode(conditions, errors);
        }

        return errors;
    }

    validateNode(node, errors) {
        if (!node || !node.type) return;

        if (node.type === 'condition') {
            if (!node.field) errors.push('תנאי חסר שדה');
            if (node.value === '' || node.value === undefined || node.value === null) {
                errors.push('תנאי חסר ערך');
            }
        } else if (node.type === 'group') {
            // 🔧 בדיקה שיש children לפני הגישה אליהם
            if (node.children && Array.isArray(node.children)) {
                node.children.forEach(child => this.validateNode(child, errors));
            }
        }
    }
}

// ייצוא
if (typeof module !== 'undefined' && module.exports) {
    module.exports = RuleBuilder;
}

