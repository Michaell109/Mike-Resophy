// 全局变量
let categories = {};
let currentCategoryId = null;
let currentPaperId = null;
let papers = [];
let expandedCategories = new Set(); // 记录展开的分类
let draggedPaper = null; // 当前拖拽的论文
let dragExpandTimer = null; // 拖拽展开定时器

// DOM 元素
const categoryTree = document.getElementById('category-tree');
const papersList = document.getElementById('papers-list');
const paperInfo = document.getElementById('paper-info');
const currentCategoryTitle = document.getElementById('current-category');
const modal = document.getElementById('modal');
const contextMenu = document.getElementById('context-menu');
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const loading = document.getElementById('loading');

// 初始化应用
document.addEventListener('DOMContentLoaded', function() {
    loadCategories();
    setupEventListeners();
});

// 设置事件监听器
function setupEventListeners() {
    // 添加分类按钮 - 根据是否有选中的分类来决定添加位置
    document.getElementById('add-root-category').addEventListener('click', () => {
        if (currentCategoryId && currentCategoryId !== 'root') {
            // 如果有选中的分类，在该分类下添加子分类
            showAddCategoryModal(currentCategoryId);
        } else {
            // 如果没有选中分类，添加根分类
            showAddCategoryModal('root');
        }
    });

    // 上传按钮
    document.getElementById('upload-btn').addEventListener('click', () => {
        if (currentCategoryId) {
            fileInput.click();
        } else {
            showMessage('请先选择一个分类', 'warning');
        }
    });

    // 刷新按钮
    document.getElementById('refresh-papers').addEventListener('click', () => {
        if (currentCategoryId) {
            loadPapers(currentCategoryId);
        }
    });

// 文件输入
fileInput.addEventListener('change', handleFileSelect);
    
    // 排序选择器
    document.getElementById('sort-by').addEventListener('change', () => {
        if (papers.length > 0) {
            renderPapersList();
        }
    });

    // 全局搜索
    setupGlobalSearch();

    // 拖拽上传
    setupDragAndDrop();

    // 模态框
    setupModal();

    // 右键菜单
    setupContextMenu();

    // 点击空白处关闭菜单
    document.addEventListener('click', () => {
        contextMenu.style.display = 'none';
    });

    // 点击分类树空白区域，清空选中
    categoryTree.addEventListener('click', (e) => {
        if (e.target === categoryTree) {
            document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
            currentCategoryId = null;
            currentCategoryTitle.textContent = '选择一个分类查看 PDF';
        }
    });
}

// 加载分类数据
async function loadCategories() {
    try {
        showLoading(true);
        const response = await fetch('/api/categories');
        categories = await response.json();
        renderCategoryTree();
    } catch (error) {
        console.error('加载分类失败:', error);
        showMessage('加载分类失败', 'error');
    } finally {
        showLoading(false);
    }
}

// 渲染分类树
function renderCategoryTree() {
    categoryTree.innerHTML = '';
    if (categories.children) {
        // 顶层分类按名称排序
        const sorted = [...categories.children].sort((a,b)=> (a.name||'').localeCompare(b.name||''));
        sorted.forEach(category => {
            const element = createCategoryElement(category);
            categoryTree.appendChild(element);
        });
    }
}

// 更新分类数据（不重新渲染）
async function updateCategoriesData() {
    try {
        const response = await fetch('/api/categories');
        categories = await response.json();
    } catch (error) {
        console.error('更新分类数据失败:', error);
    }
}

// 保持状态的渲染分类树
async function renderCategoryTreeWithState() {
    // 保存当前展开状态
    saveExpandedState();
    
    // 重新渲染
    renderCategoryTree();
    
    // 恢复展开状态
    restoreExpandedState();
    
    // 恢复选中状态
    if (currentCategoryId) {
        const categoryElement = document.querySelector(`[data-category-id="${currentCategoryId}"]`);
        if (categoryElement) {
            categoryElement.classList.add('selected');
        }
    }
}

// 保存展开状态
function saveExpandedState() {
    expandedCategories.clear();
    document.querySelectorAll('.category-toggle.expanded').forEach(toggle => {
        const categoryItem = toggle.closest('.category-container').querySelector('.category-item');
        if (categoryItem) {
            expandedCategories.add(categoryItem.dataset.categoryId);
        }
    });
}

// 恢复展开状态
function restoreExpandedState() {
    expandedCategories.forEach(categoryId => {
        const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
        if (categoryElement) {
            const container = categoryElement.closest('.category-container');
            const toggle = container.querySelector('.category-toggle');
            const children = container.querySelector('.category-children');
            
            if (toggle && children) {
                toggle.classList.add('expanded');
                children.classList.remove('collapsed');
            }
        }
    });
}

// 创建分类元素
function createCategoryElement(category, level = 0) {
    // 创建主容器
    const container = document.createElement('div');
    container.className = 'category-container';
    
    // 创建分类项
    const div = document.createElement('div');
    div.className = 'category-item';
    div.dataset.categoryId = category.id;
    div.style.paddingLeft = `${level * 20 + 12}px`;

    const hasChildren = category.children && category.children.length > 0;
    
    div.innerHTML = `
        ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span style="width: 16px; margin-right: 5px;"></span>'}
        <i class="fas fa-folder" style="margin-right: 8px; color: #ffc107;"></i>
        <span class="category-name">${category.name}</span>
        <span class="pdf-count">(${category.pdf_count || 0})</span>
    `;

    // 点击事件
    div.addEventListener('click', (e) => {
        e.stopPropagation();
        // 若重复点击已选中的分类，则取消选中
        if (div.classList.contains('selected')) {
            div.classList.remove('selected');
            currentCategoryId = null;
            currentCategoryTitle.textContent = '选择一个分类查看 PDF';
            // 清空中间列表与右侧信息
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-file-pdf"></i>
                    <p>选择左侧分类查看 PDF 文件</p>
                </div>
            `;
            paperInfo.innerHTML = `
                <div class="empty-state">
                    <i class=\"fas fa-file-alt\"></i>
                    <p>选择一篇论文查看详细信息</p>
                </div>
            `;
            return;
        }
        selectCategory(category.id, category.name);
    });

    // 右键菜单
    div.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e, category.id);
    });

    // 添加拖拽目标功能
    setupCategoryDropTarget(div, category);

    // 切换展开/折叠
    const toggle = div.querySelector('.category-toggle');
    if (toggle) {
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCategoryChildren(container, category);
        });
    }

    // 将分类项添加到容器
    container.appendChild(div);

    // 添加子分类
    if (hasChildren) {
        const childrenDiv = document.createElement('div');
        childrenDiv.className = 'category-children collapsed';
        // 子分类按名称排序
        const sortedChildren = [...category.children].sort((a,b)=> (a.name||'').localeCompare(b.name||''));
        sortedChildren.forEach(child => {
            const childElement = createCategoryElement(child, level + 1);
            childrenDiv.appendChild(childElement);
        });
        container.appendChild(childrenDiv);
    }

    return container;
}

// 切换分类子项显示/隐藏
function toggleCategoryChildren(element, category) {
    const toggle = element.querySelector('.category-toggle');
    const children = element.querySelector('.category-children');
    
    if (children) {
        const isCollapsed = children.classList.contains('collapsed');
        children.classList.toggle('collapsed');
        toggle.classList.toggle('expanded', !isCollapsed);
    }
}

// 选择分类
function selectCategory(categoryId, categoryName) {
    // 移除之前的选中状态
    document.querySelectorAll('.category-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // 添加选中状态
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        categoryElement.classList.add('selected');
    }

    currentCategoryId = categoryId;
    currentCategoryTitle.textContent = categoryName;
    
    // 加载该分类下的论文
    loadPapers(categoryId);
    
    // 清空右侧信息面板
    clearPaperInfo();
}

// 加载论文列表
async function loadPapers(categoryId) {
    try {
        // 使用局部占位，避免全局遮罩导致闪烁
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>加载中...</p>
            </div>
        `;
        const response = await fetch(`/api/papers/${categoryId}`);
        papers = await response.json();
        renderPapersList();
    } catch (error) {
        console.error('加载论文失败:', error);
        showMessage('加载论文失败', 'error');
    }
}

// 渲染论文列表
function renderPapersList() {
    const sortControls = document.getElementById('sort-controls');
    
    if (papers.length === 0) {
        papersList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-file-pdf"></i>
                <p>此分类下暂无 PDF 文件</p>
                <p style="font-size: 12px; margin-top: 10px;">拖拽文件到左侧上传区域或点击上传按钮</p>
            </div>
        `;
        sortControls.style.display = 'none';
        return;
    }

    // 显示排序控件
    sortControls.style.display = 'flex';
    
    // 获取当前排序方式
    const sortBy = document.getElementById('sort-by').value;
    
    // 排序论文
    const sortedPapers = sortPapers([...papers], sortBy);

    papersList.innerHTML = '';
    sortedPapers.forEach(paper => {
        const div = document.createElement('div');
        div.className = 'paper-item';
        div.dataset.paperId = paper.id;
        
    div.innerHTML = `
            <div class="paper-icon">
                <i class="fas fa-file-pdf"></i>
            </div>
            <div class="paper-details">
                <div class="paper-title">${paper.title || paper.filename}</div>
                <div class="paper-meta">
                    ${paper.authors ? `作者: ${paper.authors} | ` : ''}
                    ${paper.year ? `年份: ${paper.year} | ` : ''}
                    上传时间: ${new Date(paper.upload_date).toLocaleDateString()}
                </div>
            </div>
            <div class="paper-actions">
                <button class="paper-action-btn edit" title="编辑信息" onclick="editPaper('${paper.id}', event)">
                    <i class="fas fa-edit"></i>
                </button>
            <button class="paper-action-btn move" title="移动到其他目录" onclick="openMovePaperPicker('${paper.id}', event)">
                <i class="fas fa-arrow-right"></i>
            </button>
                <button class="paper-action-btn" title="删除论文" onclick="deletePaper('${paper.id}', event)">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;

        div.addEventListener('click', (e) => {
            // 如果正在拖拽，不处理点击事件
            if (draggedPaper) {
                e.preventDefault();
                return;
            }
            selectPaper(paper.id);
        });

        // 双击打开 PDF 阅读器
        div.addEventListener('dblclick', (e) => {
            e.preventDefault();
            openPDFViewer(paper.id);
        });

        // 添加拖拽功能
        setupPaperDrag(div, paper);

        papersList.appendChild(div);
    });
}

// 选择论文
function selectPaper(paperId) {
    // 移除之前的选中状态
    document.querySelectorAll('.paper-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // 添加选中状态
    const paperElement = document.querySelector(`[data-paper-id="${paperId}"]`);
    if (paperElement) {
        paperElement.classList.add('selected');
    }

    currentPaperId = paperId;
    loadPaperInfo(paperId);
}

// 加载论文信息
async function loadPaperInfo(paperId) {
    try {
        const response = await fetch(`/api/paper/${paperId}`);
        const paper = await response.json();
        renderPaperInfo(paper);
    } catch (error) {
        console.error('加载论文信息失败:', error);
        showMessage('加载论文信息失败', 'error');
    }
}

// 渲染论文信息
function renderPaperInfo(paper) {
    paperInfo.innerHTML = `
        <div class="info-section">
            <div class="info-label">标题</div>
            <div class="info-value editable" data-field="title" contenteditable="true">${paper.title || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">作者</div>
            <div class="info-value editable" data-field="authors" contenteditable="true">${paper.authors || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">单位/机构</div>
            <div class="info-value editable" data-field="affiliation" contenteditable="true">${paper.affiliation || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">年份</div>
            <div class="info-value editable" data-field="year" contenteditable="true">${paper.year || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">期刊/会议</div>
            <div class="info-value editable" data-field="journal" contenteditable="true">${paper.journal || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">关键词</div>
            <div class="info-value editable" data-field="keywords" contenteditable="true">${paper.keywords || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">摘要</div>
            <div class="info-value editable" data-field="abstract" contenteditable="true" style="min-height: 100px;">${paper.abstract || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">笔记</div>
            <div class="info-value editable" data-field="notes" contenteditable="true" style="min-height: 80px;">${paper.notes || ''}</div>
        </div>
        <div class="info-section">
            <div class="info-label">文件信息</div>
            <div class="info-value">
                <strong>文件名:</strong> ${paper.filename}<br>
                <strong>上传时间:</strong> ${new Date(paper.upload_date).toLocaleString()}
            </div>
        </div>
    `;

    // 添加编辑事件监听器
    paperInfo.querySelectorAll('.editable').forEach(element => {
        element.addEventListener('blur', () => {
            savePaperField(paper.id, element.dataset.field, element.textContent);
        });
        
        element.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && element.dataset.field !== 'abstract' && element.dataset.field !== 'notes') {
                e.preventDefault();
                element.blur();
            }
        });
    });
}

// 保存论文字段
async function savePaperField(paperId, field, value) {
    try {
        const response = await fetch(`/api/paper/${paperId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                [field]: value
            })
        });

        if (response.ok) {
            // 更新本地数据
            const paper = papers.find(p => p.id === paperId);
            if (paper) {
                paper[field] = value;
                // 如果更新的是标题，重新渲染论文列表
                if (field === 'title') {
                    renderPapersList();
                    selectPaper(paperId); // 重新选中
                }
            }
        } else {
            showMessage('保存失败', 'error');
        }
    } catch (error) {
        console.error('保存论文信息失败:', error);
        showMessage('保存失败', 'error');
    }
}

// 清空论文信息
function clearPaperInfo() {
    paperInfo.innerHTML = `
        <div class="empty-state">
            <i class="fas fa-file-alt"></i>
            <p>选择一篇论文查看详细信息</p>
        </div>
    `;
    currentPaperId = null;
}

// 设置拖拽上传
function setupDragAndDrop() {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadZone.addEventListener(eventName, unhighlight, false);
    });

    function highlight() {
        uploadZone.classList.add('dragover');
    }

    function unhighlight() {
        uploadZone.classList.remove('dragover');
    }

    uploadZone.addEventListener('drop', handleDrop, false);
    uploadZone.addEventListener('click', () => {
        if (currentCategoryId) {
            fileInput.click();
        } else {
            showMessage('请先选择一个分类', 'warning');
        }
    });
}

// 处理拖拽放置
function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    handleFiles(files);
}

// 处理文件选择
function handleFileSelect(e) {
    const files = e.target.files;
    handleFiles(files);
}

// 处理文件上传
function handleFiles(files) {
    if (!currentCategoryId) {
        showMessage('请先选择一个分类', 'warning');
        return;
    }

    Array.from(files).forEach(file => {
        if (file.type === 'application/pdf') {
            uploadFile(file);
        } else {
            showMessage(`文件 ${file.name} 不是 PDF 格式`, 'warning');
        }
    });
}

// 使用 PDF.js 解析元数据并上传
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category_id', currentCategoryId);

    // 前端用 PDF.js 解析元数据
    try {
        const meta = await parsePdfWithPdfjs(file, { maxPages: 8 });
        // 从文件名自动识别 arXiv ID（例如 2510.09608v1.pdf 或 2510.09608.pdf）
        const arxivId = extractArxivIdFromName(file.name);
        if (arxivId) {
            meta.arxiv_id = arxivId;
        }
        if (meta) {
            formData.append('metadata', JSON.stringify(meta));
        }
    } catch (err) {
        console.warn('解析PDF元数据失败（忽略继续上传）:', err);
    }

    try {
        showLoading(true);
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        if (result.success) {
            showMessage(`文件 ${file.name} 上传成功`, 'success');
            loadPapers(currentCategoryId);
        } else {
            showMessage(`上传失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('上传文件失败:', error);
        showMessage('上传失败', 'error');
    } finally {
        showLoading(false);
    }
}

// 用 PDF.js 解析文件元数据
async function parsePdfWithPdfjs(file, { maxPages = 5 } = {}) {
    if (!window['pdfjsLib']) return null;
    const blobUrl = URL.createObjectURL(file);
    try {
        const loadingTask = pdfjsLib.getDocument({ url: blobUrl });
        const pdf = await loadingTask.promise;
        const pages = Math.min(maxPages, pdf.numPages);
        let text = '';
        for (let i = 1; i <= pages; i++) {
            const page = await pdf.getPage(i);
            const content = await page.getTextContent();
            const strings = content.items.map(it => it.str);
            text += strings.join(' ') + '\n';
        }
        URL.revokeObjectURL(blobUrl);
        const normalized = normalizePdfText(text);
        const meta = extractMetadataFromText(normalized);
        return meta;
    } catch (e) {
        URL.revokeObjectURL(blobUrl);
        throw e;
    }
}

function normalizePdfText(text) {
    let t = text || '';
    t = t.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    t = t.replace(/[\t\f]+/g, ' ');
    t = t.replace(/\u00A0/g, ' ');
    t = t.replace(/\n{3,}/g, '\n\n');
    t = t.split('\n').map(l => l.trim()).join('\n');
    return t;
}

function extractMetadataFromText(text) {
    const title = extractTitle(text);
    const authors = extractAuthors(text);
    const affiliation = extractAffiliation(text);
    // 摘要改为由后端通过 arXiv API 获取，这里不再解析
    return { title, authors, affiliation };
}

function extractTitle(text) {
    const lines = text.split('\n');
    for (let i = 0; i < Math.min(10, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length > 10 && line.length < 300 && /[A-Za-z一-龥]/.test(line)) {
            if (!/^page|vol|volume|issue|doi|arxiv/i.test(line) && !/@|\.com|\.org/.test(line)) {
                return line;
            }
        }
    }
    return '';
}

function extractAuthors(text) {
    const lines = text.split('\n');
    const patterns = [
        /^([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)/, // John Smith, Jane Doe
        /^([A-Z]\.?\s*[A-Z][a-z]+(?:,\s*[A-Z]\.?\s*[A-Z][a-z]+)*)/
    ];
    for (let i = 0; i < Math.min(15, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length < 5 || line.length > 200) continue;
        for (const p of patterns) {
            const m = line.match(p);
            if (m) return m[1];
        }
    }
    return '';
}

function extractAffiliation(text) {
    const lines = text.split('\n');
    const keys = /(university|college|institute|laboratory|lab|department|school|center|centre|research|academy|corporation|company|inc\.|ltd\.|google|microsoft|openai|anthropic|meta|stanford|mit|harvard|berkeley|cambridge|大学|学院|研究所|实验室|研究院)/i;
    const results = [];
    for (let i = 0; i < Math.min(25, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length > 6 && line.length < 300 && keys.test(line)) {
            if (!/^(abstract|摘要|introduction|引言|keywords|关键词)/i.test(line)) {
                if (!results.includes(line)) results.push(line);
            }
        }
    }
    return results.slice(0, 3).join('; ');
}

function extractAbstract(text) {
    const stop = /(keywords|index\s*terms|subjects?|introduction|background|materials\s+and\s+methods|methods|results|conclusions|references|acknowledg(e)?ments|关键词|引言|方法|结果|结论|参考文献)/i;
    const start = /(abstract|summary|摘要|概要)/i;
    const lines = text.split('\n');
    let started = false;
    const buf = [];
    for (const raw of lines) {
        const line = raw.trim();
        if (!started) {
            if (start.test(line)) {
                const after = line.replace(start, '').replace(/^[:\-\.]\s*/, '').trim();
                if (after) buf.push(after);
                started = true;
            }
            continue;
        }
        if (stop.test(line)) break;
        buf.push(line);
    }
    const candidate = buf.join(' ').replace(/\s+/g, ' ').trim();
    if (candidate.length >= 50) return candidate;
    // fallback: longest paragraph
    const paragraphs = text.split(/\n\s*\n/).map(p => p.replace(/\s+/g, ' ').trim());
    const cand2 = paragraphs.filter(p => p.length >= 120).sort((a,b)=>b.length-a.length)[0] || '';
    return cand2;
}

// 从文件名中提取 arXiv ID
function extractArxivIdFromName(name) {
    const base = (name || '').replace(/\.pdf$/i, '');
    // 新样式 arXiv: YYMM.number vN 可选，例如 2510.09608v1 或 2510.09608
    const m = base.match(/\b(\d{4}\.\d{4,5})(v\d+)?\b/i);
    if (m) return m[1] + (m[2] || '');
    // 兼容带前缀的写法 arXiv:2510.09608v1
    const m2 = base.match(/arxiv[:\-\s]?(\d{4}\.\d{4,5})(v\d+)?/i);
    if (m2) return m2[1] + (m2[2] || '');
    return '';
}

// 设置模态框
function setupModal() {
    const closeBtn = modal.querySelector('.close');
    const cancelBtn = document.getElementById('modal-cancel');
    
    closeBtn.addEventListener('click', hideModal);
    cancelBtn.addEventListener('click', hideModal);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            hideModal();
        }
    });
}

// 显示添加分类模态框
function showAddCategoryModal(parentId) {
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const confirmBtn = document.getElementById('modal-confirm');

    modalTitle.textContent = '添加分类';
    modalBody.innerHTML = `
        <div class="form-group">
            <label for="category-name">分类名称</label>
            <input type="text" id="category-name" placeholder="请输入分类名称">
        </div>
    `;

    confirmBtn.onclick = () => {
        const name = document.getElementById('category-name').value.trim();
        if (name) {
            addCategory(parentId, name);
            hideModal();
        } else {
            showMessage('请输入分类名称', 'warning');
        }
    };

    showModal();
    document.getElementById('category-name').focus();
}

// 显示重命名分类模态框
function showRenameCategoryModal(categoryId) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;

    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const confirmBtn = document.getElementById('modal-confirm');

    modalTitle.textContent = '重命名分类';
    modalBody.innerHTML = `
        <div class="form-group">
            <label for="category-name">分类名称</label>
            <input type="text" id="category-name" value="${category.name}">
        </div>
    `;

    confirmBtn.onclick = () => {
        const name = document.getElementById('category-name').value.trim();
        if (name && name !== category.name) {
            renameCategory(categoryId, name);
            hideModal();
        } else if (!name) {
            showMessage('请输入分类名称', 'warning');
        } else {
            hideModal();
        }
    };

    showModal();
    const input = document.getElementById('category-name');
    input.focus();
    input.select();
}

// 显示模态框
function showModal() {
    modal.style.display = 'block';
}

// 隐藏模态框
function hideModal() {
    modal.style.display = 'none';
}

// 添加分类
async function addCategory(parentId, name) {
    try {
        const response = await fetch('/api/categories', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                parent_id: parentId,
                name: name
            })
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('分类添加成功', 'success');
            // 更新本地数据而不是重新加载整个树
            await updateCategoriesData();
            // 保持展开状态和选中状态
            await renderCategoryTreeWithState();
        } else {
            showMessage(`添加失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('添加分类失败:', error);
        showMessage('添加分类失败', 'error');
    }
}

// 重命名分类
async function renameCategory(categoryId, newName) {
    try {
        const response = await fetch(`/api/categories/${categoryId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: newName
            })
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('分类重命名成功', 'success');
            // 更新本地数据而不是重新加载整个树
            await updateCategoriesData();
            // 保持展开状态和选中状态
            await renderCategoryTreeWithState();
        } else {
            showMessage(`重命名失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('重命名分类失败:', error);
        showMessage('重命名分类失败', 'error');
    }
}

// 删除分类
async function deleteCategory(categoryId) {
    try {
        const response = await fetch(`/api/categories/${categoryId}`, {
            method: 'DELETE'
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('分类删除成功', 'success');
            
            // 如果删除的是当前选中的分类，清空选中状态
            if (currentCategoryId === categoryId) {
                currentCategoryId = null;
                currentCategoryTitle.textContent = '选择一个分类查看 PDF';
                papersList.innerHTML = `
                    <div class="empty-state">
                        <i class="fas fa-file-pdf"></i>
                        <p>选择左侧分类查看 PDF 文件</p>
                    </div>
                `;
                clearPaperInfo();
            }
            
            // 更新本地数据而不是重新加载整个树
            await updateCategoriesData();
            // 保持展开状态和选中状态
            await renderCategoryTreeWithState();
        } else {
            showMessage(`删除失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('删除分类失败:', error);
        showMessage('删除分类失败', 'error');
    }
}

// 设置右键菜单
function setupContextMenu() {
    document.getElementById('rename-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        showRenameCategoryModal(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('add-subcategory').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        showAddCategoryModal(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('delete-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        const category = findCategoryById(categories, categoryId);
        const categoryName = category ? category.name : '未知分类';
        
        if (confirm(`确定要删除分类"${categoryName}"吗？\n\n注意：这将删除该分类及其所有子分类，以及其中的所有PDF文件。此操作无法恢复！`)) {
            deleteCategory(categoryId);
        }
        contextMenu.style.display = 'none';
    });
}

// 显示右键菜单
function showContextMenu(e, categoryId) {
    contextMenu.dataset.categoryId = categoryId;
    contextMenu.style.display = 'block';
    contextMenu.style.left = e.pageX + 'px';
    contextMenu.style.top = e.pageY + 'px';
}

// 查找分类
function findCategoryById(node, id) {
    if (node.id === id) {
        return node;
    }
    
    if (node.children) {
        for (let child of node.children) {
            const result = findCategoryById(child, id);
            if (result) return result;
        }
    }
    
    return null;
}

// 显示加载状态
function showLoading(show) {
    loading.style.display = show ? 'flex' : 'none';
}

// 显示消息
function showMessage(message, type = 'info') {
    // 创建消息元素
    const messageDiv = document.createElement('div');
    messageDiv.className = `message message-${type}`;
    messageDiv.textContent = message;
    
    // 添加样式
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 4px;
        color: white;
        font-size: 14px;
        z-index: 3000;
        max-width: 300px;
        word-wrap: break-word;
        animation: slideIn 0.3s ease-out;
    `;
    
    // 根据类型设置颜色
    const colors = {
        success: '#28a745',
        error: '#dc3545',
        warning: '#ffc107',
        info: '#17a2b8'
    };
    
    messageDiv.style.backgroundColor = colors[type] || colors.info;
    
    // 添加到页面
    document.body.appendChild(messageDiv);
    
    // 3秒后自动移除
    setTimeout(() => {
        messageDiv.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.parentNode.removeChild(messageDiv);
            }
        }, 300);
    }, 3000);
}

// 设置论文拖拽功能
function setupPaperDrag(paperElement, paper) {
    paperElement.draggable = true;
    
    paperElement.addEventListener('dragstart', (e) => {
        console.log('开始拖拽论文:', paper.title || paper.filename);
        draggedPaper = paper;
        paperElement.classList.add('dragging');
        
        // 设置拖拽数据
        e.dataTransfer.setData('text/plain', paper.id);
        e.dataTransfer.effectAllowed = 'move';
        
        // 设置拖拽图像
        e.dataTransfer.setDragImage(paperElement, 0, 0);
    });
    
    paperElement.addEventListener('dragend', (e) => {
        console.log('结束拖拽论文');
        paperElement.classList.remove('dragging');
        draggedPaper = null;
        
        // 清理所有拖拽状态
        document.querySelectorAll('.category-item.drag-over, .category-item.drag-target').forEach(el => {
            el.classList.remove('drag-over', 'drag-target');
        });
        
        // 清理定时器
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
    });
}

// 设置分类拖拽目标功能
function setupCategoryDropTarget(categoryElement, category) {
    const container = categoryElement.closest('.category-container') || categoryElement;

    function onDragOver(e) {
        if (!draggedPaper) return;
        
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        
        // 添加拖拽悬停样式
        categoryElement.classList.add('drag-over');
        
        // 如果有子分类且未展开，设置自动展开
        const children = container.querySelector('.category-children');
        const toggle = container.querySelector('.category-toggle');
        
        if (children && children.classList.contains('collapsed') && toggle) {
            // 清除之前的定时器
            if (dragExpandTimer) {
                clearTimeout(dragExpandTimer);
            }
            
            // 设置新的展开定时器
            dragExpandTimer = setTimeout(() => {
                console.log('自动展开分类:', category.name);
                toggle.classList.add('expanded');
                children.classList.remove('collapsed');
                expandedCategories.add(category.id);
            }, 800); // 800ms 后自动展开
        }
    }

    categoryElement.addEventListener('dragenter', onDragOver);
    categoryElement.addEventListener('dragover', onDragOver);
    
    categoryElement.addEventListener('dragleave', (e) => {
        if (!draggedPaper) return;
        
        // 检查是否真的离开了元素（而不是进入子元素）
        const rect = categoryElement.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;
        
        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
            categoryElement.classList.remove('drag-over');
            
            // 清除展开定时器
            if (dragExpandTimer) {
                clearTimeout(dragExpandTimer);
                dragExpandTimer = null;
            }
        }
    });
    
    categoryElement.addEventListener('drop', (e) => {
        if (!draggedPaper) return;
        
        console.log('放置论文到分类:', category.name);
        e.preventDefault();
        categoryElement.classList.remove('drag-over');
        categoryElement.classList.add('drag-target');
        
        // 清除定时器
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
        
        // 移动论文
        movePaper(draggedPaper.id, category.id);
        
        // 短暂显示目标状态后清除
        setTimeout(() => {
            categoryElement.classList.remove('drag-target');
        }, 1000);
    });
}

// 移动论文到新分类
async function movePaper(paperId, targetCategoryId) {
    try {
        const response = await fetch(`/api/paper/${paperId}/move`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                target_category_id: targetCategoryId
            })
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('论文移动成功', 'success');
            
            // 更新本地数据
            await updateCategoriesData();
            await renderCategoryTreeWithState();
            
            // 如果当前显示的是源分类，重新加载论文列表
            if (currentCategoryId === result.source_category || currentCategoryId === result.target_category) {
                loadPapers(currentCategoryId);
            }
        } else {
            showMessage(`移动失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('移动论文失败:', error);
        showMessage('移动论文失败', 'error');
    }
}

// 打开 PDF 阅读器
function openPDFViewer(paperId) {
    console.log('打开 PDF 阅读器:', paperId);
    const viewerUrl = `/viewer/${paperId}`;
    window.open(viewerUrl, '_blank');
}

// 全局搜索（实时）
function setupGlobalSearch() {
    const input = document.getElementById('global-search');
    const panel = document.getElementById('search-results');
    if (!input || !panel) return;

    let timer = null;
    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(timer);
        if (!q) { panel.style.display = 'none'; panel.innerHTML=''; return; }
        timer = setTimeout(async () => {
            try {
                const params = new URLSearchParams();
                params.set('q', q);
                if (currentCategoryId) {
                    params.set('category_id', currentCategoryId);
                }
                const resp = await fetch(`/api/search?${params.toString()}`);
                const data = await resp.json();
                renderSearchResults(panel, q, data.results || []);
            } catch (e) {
                console.error('搜索失败', e);
            }
        }, 250);
    });

    document.addEventListener('click', (e) => {
        if (!panel.contains(e.target) && e.target !== input) {
            panel.style.display = 'none';
        }
    });
}

function renderSearchResults(panel, q, results) {
    if (!results.length) { panel.style.display = 'none'; panel.innerHTML=''; return; }
    const esc = (s) => (s||'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
    const hi = (text) => esc(text).replace(new RegExp(`(${escapeRegExp(q)})`,'ig'), '<mark>$1</mark>');
    panel.innerHTML = results.map(r => {
        const fields = (r.matched_fields||[]).map(f=>`<span class="search-field-tag">${f}</span>`).join('');
        const authors = r.authors ? `<div class="search-meta">${hi(r.authors)}</div>` : '';
        const abs = r.abstract ? `<div class="search-meta">${hi(r.abstract.slice(0,200))}...</div>` : '';
        return `<div class="search-item" data-paper-id="${r.id}">
            <div class="search-title">${hi(r.title || r.filename || '')} ${fields}</div>
            ${authors}
            ${abs}
        </div>`;
    }).join('');
    panel.style.display = 'block';
    panel.querySelectorAll('.search-item').forEach(item => {
        item.addEventListener('click', () => {
            const pid = item.getAttribute('data-paper-id');
            openPDFViewer(pid);
            panel.style.display = 'none';
        });
    });
}

function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 删除论文
async function deletePaper(paperId, event) {
    event.stopPropagation();
    
    // 获取论文信息用于确认
    let paperTitle = '该论文';
    try {
        const response = await fetch(`/api/paper/${paperId}`);
        if (response.ok) {
            const paper = await response.json();
            paperTitle = paper.title || paper.filename || '该论文';
        }
    } catch (error) {
        console.error('获取论文信息失败:', error);
    }
    
    if (!confirm(`确定要删除 "${paperTitle}" 吗？\n\n此操作将永久删除论文文件，无法恢复。`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/paper/${paperId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            const result = await response.json();
            showMessage('论文删除成功', 'success');
            
            // 刷新当前分类的论文列表
            if (currentCategoryId) {
                loadPapers(currentCategoryId);
            }
            
            // 更新分类树（更新PDF计数）
            await updateCategoriesData();
            renderCategoryTreeWithState();
            
        } else {
            const error = await response.json();
            showMessage(`删除失败: ${error.error}`, 'error');
        }
    } catch (error) {
        console.error('删除论文失败:', error);
        showMessage('删除失败，请稍后重试', 'error');
    }
}

// 编辑论文信息
async function editPaper(paperId, event) {
    event.stopPropagation();
    
    try {
        // 获取论文信息
        const response = await fetch(`/api/paper/${paperId}`);
        if (!response.ok) {
            showMessage('获取论文信息失败', 'error');
            return;
        }
        
        const paper = await response.json();
        
        // 显示编辑模态框
        const modalTitle = document.querySelector('#modal-title');
        const modalBody = document.querySelector('#modal-body');
        const confirmBtn = document.querySelector('#modal-confirm');
        
        modalTitle.textContent = '编辑论文信息';
        modalBody.innerHTML = `
            <div class="form-group">
                <label for="paper-title">论文标题</label>
                <input type="text" id="paper-title" value="${paper.title || ''}" placeholder="论文标题">
            </div>
            <div class="form-group">
                <label for="paper-authors">作者</label>
                <input type="text" id="paper-authors" value="${paper.authors || ''}" placeholder="作者姓名，多个作者用逗号分隔">
            </div>
            <div class="form-group">
                <label for="paper-affiliation">单位/机构</label>
                <input type="text" id="paper-affiliation" value="${paper.affiliation || ''}" placeholder="作者单位或机构">
            </div>
            <div class="form-group">
                <label for="paper-year">发表年份</label>
                <input type="number" id="paper-year" value="${paper.year || ''}" placeholder="发表年份" min="1900" max="2030">
            </div>
            <div class="form-group">
                <label for="paper-journal">期刊/会议</label>
                <input type="text" id="paper-journal" value="${paper.journal || ''}" placeholder="期刊或会议名称">
            </div>
            <div class="form-group">
                <label for="paper-abstract">摘要</label>
                <textarea id="paper-abstract" rows="4" placeholder="论文摘要">${paper.abstract || ''}</textarea>
            </div>
        `;
        
        confirmBtn.onclick = async () => {
            const updatedPaper = {
                title: document.getElementById('paper-title').value.trim(),
                authors: document.getElementById('paper-authors').value.trim(),
                affiliation: document.getElementById('paper-affiliation').value.trim(),
                year: document.getElementById('paper-year').value.trim(),
                journal: document.getElementById('paper-journal').value.trim(),
                abstract: document.getElementById('paper-abstract').value.trim()
            };
            
            // 移除空值
            Object.keys(updatedPaper).forEach(key => {
                if (!updatedPaper[key]) {
                    delete updatedPaper[key];
                }
            });
            
            try {
                const updateResponse = await fetch(`/api/paper/${paperId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(updatedPaper)
                });
                
                if (updateResponse.ok) {
                    showMessage('论文信息更新成功', 'success');
                    hideModal();
                    
                    // 刷新当前分类的论文列表
                    if (currentCategoryId) {
                        loadPapers(currentCategoryId);
                    }
                } else {
                    const error = await updateResponse.json();
                    showMessage(`更新失败: ${error.error}`, 'error');
                }
            } catch (error) {
                console.error('更新论文信息失败:', error);
                showMessage('更新失败，请稍后重试', 'error');
            }
        };
        
        showModal();
        document.getElementById('paper-title').focus();
        
    } catch (error) {
        console.error('编辑论文失败:', error);
        showMessage('编辑失败，请稍后重试', 'error');
    }
}

// 打开移动论文目录选择器
async function openMovePaperPicker(paperId, event) {
    event.stopPropagation();
    try {
        // 确保拿到最新分类
        await updateCategoriesData();
        const modalTitle = document.querySelector('#modal-title');
        const modalBody = document.querySelector('#modal-body');
        const confirmBtn = document.querySelector('#modal-confirm');
        const cancelBtn = document.querySelector('#modal-cancel');

        modalTitle.textContent = '移动到目录';
        modalBody.innerHTML = `
            <div class="form-group">
                <div id="move-category-tree" style="max-height:50vh; overflow:auto; padding:8px; border:1px solid #eee; border-radius:6px;"></div>
            </div>
        `;

        // 渲染可选择的分类树（radio）
        const treeContainer = modalBody.querySelector('#move-category-tree');
        renderCategorySelectTree(categories, treeContainer);

        confirmBtn.onclick = async () => {
            const selected = treeContainer.querySelector('input[name="target-category"]:checked');
            if (!selected) { showMessage('请选择目标目录', 'warning'); return; }
            const targetId = selected.value;
            try {
                await movePaper(paperId, targetId);
                hideModal();
            } catch (e) {
                console.error(e);
            }
        };
        showModal();
    } catch (e) {
        console.error('打开移动选择器失败', e);
        showMessage('打开移动选择器失败', 'error');
    }
}

function renderCategorySelectTree(root, container) {
    container.innerHTML = '';

    function createSelectableNode(node, level = 0) {
        const wrapper = document.createElement('div');
        wrapper.className = 'category-container';

        const item = document.createElement('div');
        item.className = 'category-item';
        item.dataset.categoryId = node.id || 'root';
        item.style.paddingLeft = `${level * 20 + 12}px`;

        const hasChildren = node.children && node.children.length > 0;
        item.innerHTML = `
            ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span style="width: 16px; margin-right: 5px;"></span>'}
            <i class="fas fa-folder" style="margin-right: 8px; color: #ffc107;"></i>
            <span class="category-name">${node.name || 'Root'}</span>
            ${node.id ? `<input type="radio" name="target-category" value="${node.id}" style="margin-left:auto; margin-right:10px;">` : ''}
        `;

        // 展开/折叠
        const toggle = item.querySelector('.category-toggle');
        let childrenDiv = null;
        if (hasChildren) {
            childrenDiv = document.createElement('div');
            childrenDiv.className = 'category-children collapsed';
        }

        if (toggle && childrenDiv) {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isCollapsed = childrenDiv.classList.contains('collapsed');
                childrenDiv.classList.toggle('collapsed');
                toggle.classList.toggle('expanded', isCollapsed);
            });
        }

        // 点击名称也选中 radio
        const label = item.querySelector('.category-name');
        const radio = item.querySelector('input[type="radio"]');
        if (radio) {
            label.addEventListener('click', (e) => {
                e.stopPropagation();
                radio.checked = true;
            });
            item.addEventListener('click', (e) => {
                // 避免点击 toggle 重复触发
                if (!e.target.classList.contains('category-toggle') && !e.target.closest('.category-toggle')) {
                    radio.checked = true;
                }
            });
        }

        wrapper.appendChild(item);

        if (hasChildren) {
            const sortedChildren = [...node.children].sort((a,b)=> (a.name||'').localeCompare(b.name||''));
            sortedChildren.forEach(child => {
                const childEl = createSelectableNode(child, level + 1);
                childrenDiv.appendChild(childEl);
            });
            wrapper.appendChild(childrenDiv);
        }

        return wrapper;
    }

    // 渲染 Root 的子节点作为可选项
    if (root && root.children) {
        const sortedTop = [...root.children].sort((a,b)=> (a.name||'').localeCompare(b.name||''));
        sortedTop.forEach(child => container.appendChild(createSelectableNode(child, 0)));
    }
}

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 论文排序函数
function sortPapers(papers, sortBy) {
    return papers.sort((a, b) => {
        switch (sortBy) {
            case 'upload_date_desc':
                return new Date(b.upload_date) - new Date(a.upload_date);
            case 'upload_date_asc':
                return new Date(a.upload_date) - new Date(b.upload_date);
            case 'title_asc':
                const titleA = (a.title || a.filename || '').toLowerCase();
                const titleB = (b.title || b.filename || '').toLowerCase();
                return titleA.localeCompare(titleB);
            case 'title_desc':
                const titleA2 = (a.title || a.filename || '').toLowerCase();
                const titleB2 = (b.title || b.filename || '').toLowerCase();
                return titleB2.localeCompare(titleA2);
            case 'year_desc':
                const yearA = parseInt(a.year) || 0;
                const yearB = parseInt(b.year) || 0;
                return yearB - yearA;
            case 'year_asc':
                const yearA2 = parseInt(a.year) || 0;
                const yearB2 = parseInt(b.year) || 0;
                return yearA2 - yearB2;
            case 'authors_asc':
                const authorsA = (a.authors || '').toLowerCase();
                const authorsB = (b.authors || '').toLowerCase();
                return authorsA.localeCompare(authorsB);
            case 'authors_desc':
                const authorsA2 = (a.authors || '').toLowerCase();
                const authorsB2 = (b.authors || '').toLowerCase();
                return authorsB2.localeCompare(authorsA2);
            default:
                return new Date(b.upload_date) - new Date(a.upload_date);
        }
    });
}
