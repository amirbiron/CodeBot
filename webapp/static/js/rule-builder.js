/**
 * Visual Rule Builder
 * ממשק Drag & Drop לבניית כללים ויזואליים
 *
 * מקור: GUIDES/VISUAL_RULE_ENGINE_GUIDE.md
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
        if (!this.container) {
            return;
        }
        
        this.container.innerHTML = `
            <div class="rule-builder">
                <div class="rule-builder__toolbar">
                    <button class="btn btn-sm" data-add="condition">+ תנאי</button>
                    <button class="btn btn-sm" data-add="group-and">+ קבוצת AND</button>
                    <button class="btn btn-sm" data-add="group-or">+ קבוצת OR</button>
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
    
    _ensureSortable(container, groupName) {
        if (!container) return;
        if (typeof Sortable === 'undefined') return;
        
        // הימנעות מיצירה כפולה על אותו אלמנט
        if (container.__rbSortableInstance) {
            return;
        }
        
        container.__rbSortableInstance = new Sortable(container, {
            group: groupName,
            animation: 150,
            ghostClass: 'sortable-ghost',
            draggable: '.block',
            filter: '.empty-hint',
            onEnd: () => this.syncFromDOM()
        });
    }
    
    setupDragAndDrop() {
        // הגדרת Sortable.js או ספריית D&D אחרת
        const conditionsContainer = this.container.querySelector('.conditions-container');
        const actionsContainer = this.container.querySelector('.actions-container');
        
        // root containers
        this._ensureSortable(conditionsContainer, 'conditions');
        this._ensureSortable(actionsContainer, 'actions');
        
        // nested group drop zones (לקינון קבוצות)
        this.container.querySelectorAll('.block__children[data-drop-zone="group"]').forEach((el) => {
            this._ensureSortable(el, 'conditions');
        });
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
    
    createAction() {
        return {
            type: 'send_alert',
            severity: 'warning',
            channel: 'default'
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
        
        // ודא ש-drop zones מקוננים עובדים אחרי רינדור
        this.setupDragAndDrop();
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
        const operators = [
            { value: 'eq', label: '=' },
            { value: 'ne', label: '≠' },
            { value: 'gt', label: '>' },
            { value: 'gte', label: '≥' },
            { value: 'lt', label: '<' },
            { value: 'lte', label: '≤' },
            { value: 'contains', label: 'מכיל' },
            { value: 'regex', label: 'RegEx' }
        ];
        
        return `
            <div class="block condition-block" draggable="true" data-type="condition">
                <div class="block__header">
                    <span class="block__icon">📊</span>
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
    
    renderGroupBlock(group, depth) {
        const isAnd = group.operator === 'AND';
        const className = isAnd ? 'group-and' : 'group-or';
        const label = isAnd ? 'וגם (AND)' : 'או (OR)';
        
        const childrenHtml = group.children
            .map(child => this.renderConditions(child, depth + 1))
            .join('');
        
        return `
            <div class="block group-block ${className}" data-type="group" data-operator="${group.operator}">
                <div class="block__header">
                    <span class="block__icon">${isAnd ? '🔗' : '🔀'}</span>
                    <span class="block__title">${label}</span>
                    <button class="block__add-child" data-action="add-condition">+ תנאי</button>
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__children" data-drop-zone="group">
                    ${childrenHtml || '<p class="empty-hint">גרור תנאים לכאן</p>'}
                </div>
            </div>
        `;
    }
    
    renderActions(actions) {
        return actions.map((action, index) => `
            <div class="block action-block" data-type="action" data-index="${index}">
                <div class="block__header">
                    <span class="block__icon">⚡</span>
                    <span class="block__title">פעולה</span>
                    <button class="block__delete" data-action="delete">×</button>
                </div>
                <div class="block__content">
                    <select class="action-type-select" data-bind="type">
                        <option value="send_alert" ${action.type === 'send_alert' ? 'selected' : ''}>
                            📢 שלח התראה
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
                </div>
            </div>
        `).join('');
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
    
    _castValue(raw, fieldType) {
        const text = (raw === null || raw === undefined) ? '' : String(raw);
        const trimmed = text.trim();
        if (trimmed === '') return '';
        
        const t = (fieldType || '').toLowerCase();
        if (t === 'int') {
            const n = parseInt(trimmed, 10);
            return Number.isFinite(n) ? n : trimmed;
        }
        if (t === 'float') {
            const n = parseFloat(trimmed);
            return Number.isFinite(n) ? n : trimmed;
        }
        if (t === 'boolean') {
            const v = trimmed.toLowerCase();
            if (v === 'true' || v === '1' || v === 'yes') return true;
            if (v === 'false' || v === '0' || v === 'no') return false;
            return trimmed;
        }
        return trimmed;
    }
    
    _lookupFieldType(fieldName) {
        const name = String(fieldName || '').trim();
        if (!name) return '';
        const fields = Array.isArray(this.options.availableFields) ? this.options.availableFields : [];
        const meta = fields.find(f => (f && String(f.name || '').trim() === name)) || null;
        return meta && meta.type ? String(meta.type) : '';
    }
    
    /**
     * פונקציית עזר רקורסיבית: DOM -> JSON Node
     * @param {HTMLElement} element
     * @returns {Object|null}
     */
    _parseNode(element) {
        if (!element || !(element instanceof HTMLElement)) return null;
        
        const nodeType = element.getAttribute('data-type') || '';
        
        if (nodeType === 'condition') {
            const fieldEl = element.querySelector('[data-bind="field"]');
            const opEl = element.querySelector('[data-bind="operator"]');
            const valueEl = element.querySelector('[data-bind="value"]');
            
            const field = fieldEl ? String(fieldEl.value || '') : '';
            const operator = opEl ? String(opEl.value || '') : '';
            const rawValue = valueEl ? valueEl.value : '';
            
            const fieldType = this._lookupFieldType(field);
            const value = this._castValue(rawValue, fieldType);
            
            return { type: 'condition', field, operator, value };
        }
        
        if (nodeType === 'group') {
            const operator = (element.getAttribute('data-operator') || 'AND').toUpperCase();
            const childrenContainer = element.querySelector('.block__children') || element.querySelector('[data-drop-zone="group"]');
            
            const children = [];
            if (childrenContainer) {
                Array.from(childrenContainer.children || []).forEach((childEl) => {
                    if (!(childEl instanceof HTMLElement)) return;
                    if (!childEl.classList.contains('block')) return;
                    const parsed = this._parseNode(childEl);
                    if (parsed) {
                        children.push(parsed);
                    }
                });
            }
            
            return { type: 'group', operator, children };
        }
        
        return null;
    }
    
    syncFromDOM() {
        // סנכרון מצב ה-DOM חזרה ל-rule object (ה-DOM הוא מקור האמת)
        
        // --- תנאים ---
        const conditionsContainer = this.container.querySelector('.conditions-container');
        const topLevelChildren = [];
        
        if (conditionsContainer) {
            Array.from(conditionsContainer.children || []).forEach((childEl) => {
                if (!(childEl instanceof HTMLElement)) return;
                if (!childEl.classList.contains('block')) return;
                const parsed = this._parseNode(childEl);
                if (parsed) {
                    topLevelChildren.push(parsed);
                }
            });
        }
        
        // ודא שמבנה התנאים הראשי הוא Group (כמו במדריך)
        if (!this.rule.conditions || this.rule.conditions.type !== 'group') {
            this.rule.conditions = { type: 'group', operator: 'AND', children: [] };
        }
        this.rule.conditions.children = topLevelChildren;
        
        // --- פעולות ---
        const actionsContainer = this.container.querySelector('.actions-container');
        const actions = [];
        
        if (actionsContainer) {
            actionsContainer.querySelectorAll('.action-block[data-type="action"]').forEach((actionEl) => {
                const action = {};
                actionEl.querySelectorAll('[data-bind]').forEach((bindEl) => {
                    const key = bindEl.getAttribute('data-bind') || '';
                    if (!key) return;
                    
                    let value = '';
                    if (bindEl.type === 'checkbox') {
                        value = !!bindEl.checked;
                    } else {
                        value = bindEl.value;
                    }
                    action[key] = value;
                });
                if (!action.type) {
                    action.type = 'send_alert';
                }
                actions.push(action);
            });
        }
        
        this.rule.actions = actions;
        
        // עדכון תצוגה מקדימה
        const preview = this.container.querySelector('.json-preview');
        if (preview) {
            preview.textContent = JSON.stringify(this.rule, null, 2);
        }
        
        this.notifyChange();
    }
    
    deleteBlock(blockElement) {
        // מחיקת בלוק מה-DOM ואז סנכרון מחדש (מקור אמת יחיד)
        if (!blockElement) return;
        
        const parent = blockElement.parentElement;
        try {
            blockElement.remove();
        } catch (_err) {
            try {
                if (parent) parent.removeChild(blockElement);
            } catch (_err2) {}
        }
        
        // אם מחקנו את הבלוק האחרון בתוך קבוצה, החזר empty-hint
        if (parent && parent.classList && parent.classList.contains('block__children')) {
            const hasBlocks = parent.querySelector('.block');
            if (!hasBlocks && !parent.querySelector('.empty-hint')) {
                parent.insertAdjacentHTML('beforeend', '<p class="empty-hint">גרור תנאים לכאן</p>');
            }
        }
        
        // שלב 3 במדריך: סנכרון מיד אחרי מחיקה
        this.syncFromDOM();
    }
    
    addConditionToGroup(groupElement) {
        if (!groupElement) return;
        const childrenContainer = groupElement.querySelector('.block__children[data-drop-zone="group"]');
        if (!childrenContainer) return;
        
        // ניקוי empty-hint אם קיים
        const hint = childrenContainer.querySelector('.empty-hint');
        if (hint) {
            try { hint.remove(); } catch (_err) {}
        }
        
        const condition = this.createCondition();
        const html = this.renderConditionBlock(condition);
        childrenContainer.insertAdjacentHTML('beforeend', html);
        
        // attach events + enable D&D for the newly created drop zone
        this.attachBlockEvents();
        this.setupDragAndDrop();
        
        // שמור עקביות ב-JSON
        this.syncFromDOM();
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
