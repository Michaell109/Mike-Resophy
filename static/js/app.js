// 全局变量
let categories = {};
let currentCategoryId = null;
let currentPaperId = null;
let papers = [];
let expandedCategories = new Set(); // 记录展开的分类
let draggedPaper = null; // 当前拖拽的论文
let dragExpandTimer = null; // 拖拽展开定时器
let currentViewMode = 'category'; // 'category' | 'translating' | 'analyzing' | 'reading-list' - 当前视图模式
let readingListCount = 0; // 待读列表数量
let readingListPaperIds = new Set(); // 待读列表中的论文ID集合

// 翻译相关
let translationQueue = []; // 翻译队列
let isTranslating = false; // 是否正在翻译
let translationStatus = {}; // 翻译状态 {paperId: 'translating' | 'queued' | 'completed' | 'error', queuePosition: number, taskId: string}
let translationLogInterval = {}; // 日志轮询定时器 {taskId: intervalId}

// AI解读相关
let analysisQueue = []; // 解读队列
let isAnalyzing = false; // 是否正在解读
let analysisStatus = {}; // 解读状态 {paperId: 'analyzing' | 'queued' | 'completed' | 'error', queuePosition: number, taskId: string, step: string}
let analysisLogInterval = {}; // 日志轮询定时器 {taskId: intervalId}

// 保存队列到 localStorage
function saveQueuesToStorage() {
    try {
        localStorage.setItem('translationQueue', JSON.stringify(translationQueue));
        localStorage.setItem('analysisQueue', JSON.stringify(analysisQueue));
        localStorage.setItem('translationStatus', JSON.stringify(translationStatus));
        localStorage.setItem('analysisStatus', JSON.stringify(analysisStatus));
    } catch (e) {
        console.error('保存队列状态失败:', e);
    }
}

// 从 localStorage 恢复队列
function restoreQueuesFromStorage() {
    try {
        const savedTQueue = localStorage.getItem('translationQueue');
        const savedAQueue = localStorage.getItem('analysisQueue');
        const savedTStatus = localStorage.getItem('translationStatus');
        const savedAStatus = localStorage.getItem('analysisStatus');
        
        if (savedTQueue) {
            translationQueue = JSON.parse(savedTQueue);
        }
        if (savedAQueue) {
            analysisQueue = JSON.parse(savedAQueue);
        }
        if (savedTStatus) {
            translationStatus = JSON.parse(savedTStatus);
        }
        if (savedAStatus) {
            analysisStatus = JSON.parse(savedAStatus);
        }
    } catch (e) {
        console.error('恢复队列状态失败:', e);
        translationQueue = [];
        analysisQueue = [];
        translationStatus = {};
        analysisStatus = {};
    }
}

// 清理已完成的队列项
function cleanupCompletedQueues() {
    // 清理翻译队列中已完成或失败的项目
    translationQueue = translationQueue.filter(pid => {
        const status = translationStatus[pid];
        return status && (status.status === 'queued' || status.status === 'translating');
    });
    
    // 清理解读队列中已完成或失败的项目
    analysisQueue = analysisQueue.filter(pid => {
        const status = analysisStatus[pid];
        return status && (status.status === 'queued' || status.status === 'analyzing');
    });
    
    // 清理状态中已完成或失败的项目
    Object.keys(translationStatus).forEach(pid => {
        const status = translationStatus[pid];
        if (status.status === 'completed' || status.status === 'error') {
            delete translationStatus[pid];
        }
    });
    
    Object.keys(analysisStatus).forEach(pid => {
        const status = analysisStatus[pid];
        if (status.status === 'completed' || status.status === 'error') {
            delete analysisStatus[pid];
        }
    });
    
    saveQueuesToStorage();
}

// 多选相关
let isMultiSelectMode = false;
let selectedPaperIds = new Set();
let lastSelectedIndex = null; // 用于 shift 选择

// DOM 元素
const categoryTree = document.getElementById('category-tree');
const papersList = document.getElementById('papers-list');
const paperInfo = document.getElementById('paper-info');
const currentCategoryTitle = document.getElementById('current-category');
const modal = document.getElementById('modal');
const contextMenu = document.getElementById('context-menu');
const paperContextMenu = document.getElementById('paper-context-menu');
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const loading = document.getElementById('loading');

// 保存当前视图状态
function saveCurrentViewState() {
    const state = {
        viewMode: currentViewMode,
        categoryId: currentCategoryId,
        tabName: document.querySelector('.nav-tab.active')?.dataset.tab || 'paper'
    };
    try {
        sessionStorage.setItem('currentViewState', JSON.stringify(state));
    } catch (e) {
        console.error('保存当前视图状态失败:', e);
    }
}

// 恢复上次视图状态
async function restoreViewState() {
    try {
        const saved = sessionStorage.getItem('currentViewState');
        if (saved) {
            const state = JSON.parse(saved);

            if (state.tabName === 'setting') {
                switchTab('setting');
                return;
            }

            switchTab('paper');

            if (state.viewMode === 'translating') {
                await showTranslatingPapers();
                return;
            }
            if (state.viewMode === 'analyzing') {
                await showAnalyzingPapers();
                return;
            }
            if (state.viewMode === 'reading-list') {
                await showReadingList();
                return;
            }
            if (state.viewMode === 'category' && state.categoryId) {
                const categoryItem = document.querySelector(`.category-item[data-category-id="${state.categoryId}"]`);
                if (categoryItem) {
                    categoryItem.click();
                    return;
                }
            }

            await renderRecentIfNoCategory();
            return;
        }

        switchTab('paper');
        await renderRecentIfNoCategory();
    } catch (e) {
        console.error('恢复视图状态失败:', e);
        switchTab('paper');
        await renderRecentIfNoCategory();
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', async function() {
    await loadCategories();
    setupEventListeners();
    setupNavigation();
    loadTranslationSettings();
    loadAnalysisSettings();
    loadHabitSettings();
    loadGeneralSettings();
    // 先恢复队列状态，再恢复运行中的任务
    restoreQueuesFromStorage();
    cleanupCompletedQueues();
    await restoreActiveTasks();
    // 恢复队列后，继续处理队列
    if (translationQueue.length > 0 && !isTranslating) {
        processTranslationQueue();
    }
    if (analysisQueue.length > 0 && !isAnalyzing) {
        processAnalysisQueue();
    }
    // 恢复上次视图状态
    await restoreViewState();
    updateTaskIndicator();
    updateReadingListCount();
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

    // arXiv 导入按钮
    document.getElementById('upload-arxiv-btn').addEventListener('click', () => {
        if (currentCategoryId) {
            showArxivUploadModal();
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

    // 多选开关按钮
    document.getElementById('toggle-multiselect').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMultiSelectMode();
    });

// 文件输入
fileInput.addEventListener('change', handleFileSelect);
    
    // 排序选择器
    document.getElementById('sort-by').addEventListener('change', () => {
        if (papers.length > 0) {
            renderPapersList();
        }
    });

    // 批量工具栏动作
    const batchAnalyze = document.getElementById('batch-analyze');
    const batchTranslate = document.getElementById('batch-translate');
    const batchMove = document.getElementById('batch-move');
    const batchDelete = document.getElementById('batch-delete');
    const batchCancel = document.getElementById('batch-cancel');
    if (batchAnalyze) batchAnalyze.addEventListener('click', onBatchAnalyze);
    if (batchTranslate) batchTranslate.addEventListener('click', onBatchTranslate);
    if (batchMove) batchMove.addEventListener('click', onBatchMove);
    if (batchDelete) batchDelete.addEventListener('click', onBatchDelete);
    if (batchCancel) batchCancel.addEventListener('click', (e)=>{ e.stopPropagation(); exitMultiSelectMode(); });

    // 全局搜索
    setupGlobalSearch();

    // 拖拽上传
    setupDragAndDrop();

    // 模态框
    setupModal();

    // 右键菜单
    setupContextMenu();
    setupPaperContextMenu();
    
    // 面板调整
    setupSidebarResizing();
    setupInfoPanelResizing();

    // 点击空白处关闭菜单
    document.addEventListener('click', (e) => {
        contextMenu.style.display = 'none';
        paperContextMenu.style.display = 'none';
        // 多选状态下，点击主要区域空白退出
        if (isMultiSelectMode) {
            const main = document.querySelector('.main-content');
            const isInsideMain = main && main.contains(e.target);
            const isPaperItem = e.target.closest && e.target.closest('.paper-item');
            const isToolbar = e.target.closest && e.target.closest('#batch-toolbar');
            const isToggleBtn = e.target.closest && e.target.closest('#toggle-multiselect');
            if (isInsideMain && !isPaperItem && !isToolbar && !isToggleBtn) {
                exitMultiSelectMode();
            }
        }
    });

    // 点击分类树空白区域，清空选中并展示最近阅读
    categoryTree.addEventListener('click', (e) => {
        if (e.target === categoryTree) {
            document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
            currentCategoryId = null;
            currentCategoryTitle.textContent = '选择一个分类查看 PDF';
            renderRecentIfNoCategory();
            clearPaperInfo();
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
        ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span class="category-toggle-placeholder"></span>'}
        <i class="fas fa-folder" style="margin-right: 6px; color: #ffc107; font-size: 12px;"></i>
        <span class="category-name">${category.name}</span>
        <span class="pdf-count">${category.pdf_count || 0}</span>
    `;

    // 点击事件
    div.addEventListener('click', (e) => {
        e.stopPropagation();
        // 无论点击分类项的哪个位置，都先展开其子目录（若存在）
        const children = container.querySelector('.category-children');
        const toggle = div.querySelector('.category-toggle');
        if (children && children.classList.contains('collapsed')) {
            children.classList.remove('collapsed');
            if (toggle) toggle.classList.add('expanded');
        }
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
        children.classList.toggle('collapsed');
        const isExpanded = !children.classList.contains('collapsed');
        if (toggle) {
            toggle.classList.toggle('expanded', isExpanded);
        }
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
        currentViewMode = 'category';
        currentCategoryId = categoryId;
        saveCurrentViewState();
        // 清除分类树中的选中状态
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // 如果点击了分类，选中它
        if (categoryId && categoryId !== 'root') {
            const categoryItem = document.querySelector(`.category-item[data-category-id="${categoryId}"]`);
            if (categoryItem) {
                categoryItem.classList.add('selected');
            }
        }
        // 使用局部占位，避免全局遮罩导致闪烁
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>加载中...</p>
            </div>
        `;
        const response = await fetch(`/api/papers/${categoryId}`);
        papers = await response.json();
        // 确保待读列表ID集合已更新
        await updateReadingListCount();
        renderPapersList();
    } catch (error) {
        console.error('加载论文失败:', error);
        showMessage('加载论文失败', 'error');
    }
}

// 显示翻译中的论文列表
async function showTranslatingPapers() {
    try {
        currentViewMode = 'translating';
        currentCategoryId = null; // 清除分类选中
        saveCurrentViewState();
        // 清除分类树中的选中状态
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // 更新标题
        const currentCategoryTitle = document.getElementById('current-category');
        if (currentCategoryTitle) {
            const tCount = translationQueue.length + Object.values(translationStatus).filter(s => s.status === 'translating').length;
            currentCategoryTitle.textContent = `翻译中 (${tCount} 篇)`;
        }
        // 收集所有翻译中的论文ID（队列中 + 正在翻译的）
        const paperIds = new Set();
        translationQueue.forEach(pid => paperIds.add(pid));
        Object.keys(translationStatus).forEach(pid => {
            const status = translationStatus[pid];
            if (status && (status.status === 'translating' || status.status === 'queued')) {
                paperIds.add(pid);
            }
        });
        // 如果没有论文，显示空状态
        if (paperIds.size === 0) {
            papers = [];
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-language"></i>
                    <p>当前没有翻译中的论文</p>
                </div>
            `;
            document.getElementById('sort-controls').style.display = 'none';
            return;
        }
        // 从后端获取这些论文的详细信息
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>加载中...</p>
            </div>
        `;
        const paperDetails = await Promise.all(
            Array.from(paperIds).map(async (paperId) => {
                try {
                    const response = await fetch(`/api/paper/${paperId}`);
                    if (response.ok) {
                        return await response.json();
                    }
                    return null;
                } catch (e) {
                    console.error(`加载论文 ${paperId} 失败:`, e);
                    return null;
                }
            })
        );
        papers = paperDetails.filter(p => p !== null);
        // 确保待读列表ID集合已更新
        await updateReadingListCount();
        renderPapersList();
    } catch (error) {
        console.error('加载翻译中论文失败:', error);
        showMessage('加载翻译中论文失败', 'error');
    }
}

// 显示待读列表
async function showReadingList() {
    try {
        currentViewMode = 'reading-list';
        currentCategoryId = null; // 清除分类选中
        saveCurrentViewState();
        // 清除分类树中的选中状态
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // 更新标题
        const currentCategoryTitle = document.getElementById('current-category');
        if (currentCategoryTitle) {
            currentCategoryTitle.textContent = `待读列表 (${readingListCount} 篇)`;
        }
        // 从后端获取待读列表
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>加载中...</p>
            </div>
        `;
        const response = await fetch('/api/reading-list');
        papers = await response.json();
        // 更新计数
        readingListCount = papers.length;
        updateReadingListCount();
        // 如果没有论文，显示空状态
        if (papers.length === 0) {
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-book-open"></i>
                    <p>待读列表为空</p>
                </div>
            `;
            document.getElementById('sort-controls').style.display = 'none';
            return;
        }
        renderPapersList();
    } catch (error) {
        console.error('加载待读列表失败:', error);
        showMessage('加载待读列表失败', 'error');
    }
}

// 更新待读列表计数和ID集合
async function updateReadingListCount() {
    try {
        const response = await fetch('/api/reading-list');
        const papers = await response.json();
        readingListCount = papers.length;
        // 更新ID集合
        readingListPaperIds.clear();
        papers.forEach(p => readingListPaperIds.add(p.id));
        
        const tiReadingCount = document.getElementById('ti-reading-count');
        if (tiReadingCount) {
            tiReadingCount.textContent = readingListCount;
        }
        const btnReading = document.getElementById('btn-show-reading-list');
        if (btnReading) {
            if (readingListCount > 0) {
                btnReading.classList.add('has-tasks');
            } else {
                btnReading.classList.remove('has-tasks');
            }
        }
    } catch (e) {
        console.error('更新待读列表计数失败:', e);
    }
}

// 添加到待读列表
async function addToReadingList(paperId, event) {
    if (event) event.stopPropagation();
    try {
        const response = await fetch(`/api/reading-list/${paperId}/add`, {
            method: 'POST'
        });
        if (response.ok) {
            showMessage('已添加到待读列表', 'success');
            // 更新ID集合和计数
            readingListPaperIds.add(paperId);
            await updateReadingListCount();
            // 如果当前正在查看分类列表，更新显示
            if (currentViewMode === 'category' && currentCategoryId) {
                renderPapersList();
            }
        } else {
            showMessage('添加失败', 'error');
        }
    } catch (error) {
        console.error('添加失败:', error);
        showMessage('添加失败', 'error');
    }
}

// 从待读列表移除论文
async function removeFromReadingList(paperId, event) {
    if (event) event.stopPropagation();
    try {
        const response = await fetch(`/api/reading-list/${paperId}/remove`, {
            method: 'POST'
        });
        if (response.ok) {
            showMessage('已从待读列表移除', 'success');
            // 更新ID集合和计数
            readingListPaperIds.delete(paperId);
            await updateReadingListCount();
            // 如果当前正在查看待读列表，刷新列表
            if (currentViewMode === 'reading-list') {
                showReadingList();
            } else if (currentViewMode === 'category' && currentCategoryId) {
                // 如果在分类列表中，更新显示
                renderPapersList();
            }
        } else {
            showMessage('移除失败', 'error');
        }
    } catch (error) {
        console.error('移除失败:', error);
        showMessage('移除失败', 'error');
    }
}

// 显示解读中的论文列表
async function showAnalyzingPapers() {
    try {
        currentViewMode = 'analyzing';
        currentCategoryId = null; // 清除分类选中
        saveCurrentViewState();
        // 清除分类树中的选中状态
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // 更新标题
        const currentCategoryTitle = document.getElementById('current-category');
        if (currentCategoryTitle) {
            const aCount = analysisQueue.length + Object.values(analysisStatus).filter(s => s.status === 'analyzing').length;
            currentCategoryTitle.textContent = `解读中 (${aCount} 篇)`;
        }
        // 收集所有解读中的论文ID（队列中 + 正在解读的）
        const paperIds = new Set();
        analysisQueue.forEach(pid => paperIds.add(pid));
        Object.keys(analysisStatus).forEach(pid => {
            const status = analysisStatus[pid];
            if (status && (status.status === 'analyzing' || status.status === 'queued')) {
                paperIds.add(pid);
            }
        });
        // 如果没有论文，显示空状态
        if (paperIds.size === 0) {
            papers = [];
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-brain"></i>
                    <p>当前没有解读中的论文</p>
                </div>
            `;
            document.getElementById('sort-controls').style.display = 'none';
            return;
        }
        // 从后端获取这些论文的详细信息
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>加载中...</p>
            </div>
        `;
        const paperDetails = await Promise.all(
            Array.from(paperIds).map(async (paperId) => {
                try {
                    const response = await fetch(`/api/paper/${paperId}`);
                    if (response.ok) {
                        return await response.json();
                    }
                    return null;
                } catch (e) {
                    console.error(`加载论文 ${paperId} 失败:`, e);
                    return null;
                }
            })
        );
        papers = paperDetails.filter(p => p !== null);
        // 确保待读列表ID集合已更新
        await updateReadingListCount();
        renderPapersList();
    } catch (error) {
        console.error('加载解读中论文失败:', error);
        showMessage('加载解读中论文失败', 'error');
    }
}

// 生成论文项的HTML（表格布局）
function generatePaperItemHTML(paper, showCheckbox = false) {
    const isSelected = selectedPaperIds.has(paper.id);
    
    // 图标列
    const iconCol = `
        <div class="paper-col-icon">
            ${showCheckbox && isMultiSelectMode ? `<input type="checkbox" ${isSelected ? 'checked' : ''} data-check="1" style="margin-right: 6px;" />` : ''}
            <i class="fas fa-file-pdf" style="color: #dc3545; font-size: 16px;"></i>
        </div>
    `;
    
    // 标题列
    const titleCol = `
        <div class="paper-col-title" title="${paper.title || paper.filename}">
            ${paper.title || paper.filename}
        </div>
    `;
    
    // 日期列
    const uploadDate = new Date(paper.upload_date).toLocaleDateString();
    const arxivDate = paper.arxiv_published_date ? new Date(paper.arxiv_published_date).toLocaleDateString() : null;
    const dateCol = `
        <div class="paper-col-date">
            ${uploadDate}${arxivDate ? '<br>arXiv: ' + arxivDate : ''}
        </div>
    `;
    
    // AI翻译列
    const tStatus = translationStatus[paper.id];
    let translateCol = '';
    if (tStatus && tStatus.status === 'translating') {
        translateCol = `<div class="paper-col-action"><span class="paper-action-status processing"><i class="fas fa-spinner fa-spin"></i> 翻译中...<button class="paper-action-stop" onclick="cancelTranslation('${paper.id}', event)" title="停止翻译"><i class="fas fa-times"></i></button></span></div>`;
    } else if (tStatus && tStatus.status === 'queued') {
        translateCol = `<div class="paper-col-action"><span class="paper-action-status processing"><i class="fas fa-clock"></i> 队列中<button class="paper-action-stop" onclick="cancelTranslation('${paper.id}', event)" title="取消队列"><i class="fas fa-times"></i></button></span></div>`;
    } else if (paper.has_chinese_version) {
        translateCol = `<div class="paper-col-action"><button class="paper-col-btn view chinese" onclick="openChineseVersion('${paper.id}', event)"><i class="fas fa-language"></i> 中文版</button></div>`;
    } else {
        translateCol = `<div class="paper-col-action"><button class="paper-col-btn translate icon-only" onclick="requestTranslation('${paper.id}', event)" title="AI翻译"><i class="fas fa-language"></i></button></div>`;
    }
    
    // AI解读列
    const aStatus = analysisStatus[paper.id];
    let analyzeCol = '';
    if (aStatus && aStatus.status === 'analyzing') {
        const step = aStatus.step === 'pdf2md' ? 'PDF解析中...' : 'LLM解读中...';
        analyzeCol = `<div class="paper-col-action"><span class="paper-action-status processing"><i class="fas fa-spinner fa-spin"></i> ${step}<button class="paper-action-stop" onclick="cancelAnalysis('${paper.id}', event)" title="停止解读"><i class="fas fa-times"></i></button></span></div>`;
    } else if (aStatus && aStatus.status === 'queued') {
        analyzeCol = `<div class="paper-col-action"><span class="paper-action-status processing"><i class="fas fa-clock"></i> 队列中<button class="paper-action-stop" onclick="cancelAnalysis('${paper.id}', event)" title="取消队列"><i class="fas fa-times"></i></button></span></div>`;
    } else if (paper.has_analysis_result) {
        analyzeCol = `<div class="paper-col-action"><button class="paper-col-btn view analysis" onclick="viewAnalysisResult('${paper.id}', event)"><i class="fas fa-brain"></i> AI解读</button></div>`;
    } else {
        analyzeCol = `<div class="paper-col-action"><button class="paper-col-btn analyze icon-only" onclick="requestAnalysis('${paper.id}', event)" title="AI解读"><i class="fas fa-brain"></i></button></div>`;
    }
    
    return iconCol + titleCol + dateCol + translateCol + analyzeCol;
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
    // 将当前排序保存，便于 shift 选择
    window.__currentSortedPapers = sortedPapers.map(p=>p.id);

    // 添加表头
    papersList.innerHTML = `
        <div class="paper-header">
            <div class="paper-header-col"></div>
            <div class="paper-header-col">标题<div class="paper-header-resizer" data-col="1"></div></div>
            <div class="paper-header-col">日期<div class="paper-header-resizer" data-col="2"></div></div>
            <div class="paper-header-col">AI 翻译<div class="paper-header-resizer" data-col="3"></div></div>
            <div class="paper-header-col">AI 解读</div>
        </div>
    `;
    
    // 添加列宽调整功能
    setupColumnResizing();
    
    sortedPapers.forEach(paper => {
        const div = document.createElement('div');
        const isSelected = selectedPaperIds.has(paper.id);
        div.className = `paper-item${isSelected ? ' multi-selected' : ''}`;
        div.dataset.paperId = paper.id;
        div.innerHTML = generatePaperItemHTML(paper, true);

        div.addEventListener('click', (e) => {
            if (draggedPaper) { e.preventDefault(); return; }
            if (isMultiSelectMode) {
                handleMultiSelectClick(e, paper.id);
            } else {
                selectPaper(paper.id);
            }
        });

        // 添加右键菜单
        div.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showPaperContextMenu(e, paper.id);
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
    markPaperViewed(paperId);
}

// 加载论文信息
async function loadPaperInfo(paperId) {
    try {
        const panel = document.querySelector('.info-panel');
        if (panel) panel.classList.remove('wide');
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
                ${paper.arxiv_published_date ? `<br><strong>arXiv 发布时间:</strong> ${new Date(paper.arxiv_published_date).toLocaleString()}` : ''}
            </div>
        </div>
        ${paper.has_chinese_version ? `
        <div class="info-section">
            <div class="info-label">中文版本</div>
            <div class="info-value">
                <button class="btn btn-primary" onclick="openChineseVersion('${paper.id}')">
                    <i class="fas fa-language"></i> 打开中文版本 PDF
                </button>
            </div>
        </div>
        ` : ''}
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
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // 为分类树添加拖拽支持
    categoryTree.addEventListener('dragover', (e) => {
        preventDefaults(e);
        e.dataTransfer.dropEffect = 'copy';
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.add('drag-over');
        }
    });

    categoryTree.addEventListener('dragleave', (e) => {
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.remove('drag-over');
        }
    });

    categoryTree.addEventListener('drop', (e) => {
        preventDefaults(e);
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.remove('drag-over');
            const categoryId = categoryItem.dataset.categoryId;
            if (categoryId) {
                handleFilesWithCategory(e.dataTransfer.files, categoryId);
            }
        }
    });

    // 为论文列表区域添加拖拽支持
    papersList.addEventListener('dragover', (e) => {
        preventDefaults(e);
        e.dataTransfer.dropEffect = 'copy';
        if (currentCategoryId) {
            papersList.classList.add('drag-over');
        }
    });

    papersList.addEventListener('dragleave', (e) => {
        papersList.classList.remove('drag-over');
    });

    papersList.addEventListener('drop', (e) => {
        preventDefaults(e);
        papersList.classList.remove('drag-over');
        if (currentCategoryId) {
            handleFilesWithCategory(e.dataTransfer.files, currentCategoryId);
        } else {
            showMessage('请先选择一个分类', 'warning');
        }
    });

    // 左下角上传区域已移除：仅在存在时绑定（兼容旧DOM）
    if (uploadZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadZone.addEventListener(eventName, preventDefaults, false);
        });
        ['dragenter', 'dragover'].forEach(eventName => {
            uploadZone.addEventListener(eventName, () => {
                uploadZone.classList.add('dragover');
            }, false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            uploadZone.addEventListener(eventName, () => {
                uploadZone.classList.remove('dragover');
            }, false);
        });
        uploadZone.addEventListener('drop', (e) => {
            if (currentCategoryId) {
                handleFilesWithCategory(e.dataTransfer.files, currentCategoryId);
            } else {
                showMessage('请先选择一个分类', 'warning');
            }
        }, false);
        uploadZone.addEventListener('click', () => {
            if (currentCategoryId) {
                fileInput.click();
            } else {
                showMessage('请先选择一个分类', 'warning');
            }
        });
    }
}

// 处理文件选择
function handleFileSelect(e) {
    const files = e.target.files;
    if (currentCategoryId) {
        handleFilesWithCategory(files, currentCategoryId);
    } else {
        showMessage('请先选择一个分类', 'warning');
    }
}

// 处理文件上传（带分类ID）
function handleFilesWithCategory(files, categoryId) {
    Array.from(files).forEach(file => {
        if (file.type === 'application/pdf') {
            uploadFile(file, categoryId);
        } else {
            showMessage(`文件 ${file.name} 不是 PDF 格式`, 'warning');
        }
    });
}

// 使用 PDF.js 解析元数据并上传
async function uploadFile(file, categoryId) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category_id', categoryId);

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
            // 如果上传到当前选中的分类，刷新列表
            if (currentCategoryId === categoryId) {
                loadPapers(currentCategoryId);
            }
            // 同步更新分类计数和待读列表计数
            await updateCategoriesData();
            renderCategoryTreeWithState();
            updateReadingListCount();
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
    let confirmBtn = document.getElementById('modal-confirm');
    let cancelBtn = document.getElementById('modal-cancel');

    modalTitle.textContent = '添加分类';
    modalBody.innerHTML = `
        <div class="form-group">
            <label for="category-name">分类名称</label>
            <input type="text" id="category-name" placeholder="请输入分类名称">
        </div>
    `;

    // 重置按钮监听，避免与其他弹窗冲突
    const confirmClone = confirmBtn.cloneNode(true);
    const cancelClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelClone, cancelBtn);
    confirmBtn = document.getElementById('modal-confirm');
    cancelBtn = document.getElementById('modal-cancel');
    confirmBtn.style.display = 'inline-block';
    confirmBtn.textContent = '确认';
    cancelBtn.textContent = '取消';

    confirmBtn.onclick = () => {
        const name = document.getElementById('category-name').value.trim();
        if (name) {
            addCategory(parentId, name);
            hideModal();
        } else {
            showMessage('请输入分类名称', 'warning');
        }
    };
    cancelBtn.onclick = () => hideModal();

    showModal();
    document.getElementById('category-name').focus();
    // 绑定回车键提交
    const input = document.getElementById('category-name');
    input.addEventListener('keydown', (e) => {
        // 避免输入法候选上屏时的 Enter 被当作提交
        if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            confirmBtn.click();
        }
    });
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

// 设置论文右键菜单
function setupPaperContextMenu() {
    document.getElementById('paper-translate').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        requestTranslation(paperId);
        paperContextMenu.style.display = 'none';
    });
    
    document.getElementById('paper-analyze').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        requestAnalysis(paperId);
        paperContextMenu.style.display = 'none';
    });
    
    document.getElementById('paper-move').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        openMovePaperPicker(paperId);
        paperContextMenu.style.display = 'none';
    });
    
    document.getElementById('paper-delete').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        deletePaper(paperId);
        paperContextMenu.style.display = 'none';
    });
}

// 显示论文右键菜单
function showPaperContextMenu(e, paperId) {
    paperContextMenu.dataset.paperId = paperId;
    paperContextMenu.style.display = 'block';
    paperContextMenu.style.left = e.pageX + 'px';
    paperContextMenu.style.top = e.pageY + 'px';
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

// 打开中文版PDF
function openChineseVersion(paperId) {
    const paper = papers.find(p => p.id === paperId);
    if (!paper || !paper.has_chinese_version) {
        showMessage('中文版本不存在', 'error');
        return;
    }
    const viewerUrl = `/viewer/${paperId}?chinese=true`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// 打开 PDF 阅读器（打开原版）
function openPDFViewer(paperId) {
    console.log('打开 PDF 阅读器:', paperId);
    const viewerUrl = `/viewer/${paperId}`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// 显示 arXiv 上传模态框
function showArxivUploadModal() {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');
    
    modalTitle.textContent = '从 arXiv 导入论文';
    modalBody.innerHTML = `
        <div style="margin-bottom: 15px;">
            <label for="arxiv-url" style="display: block; margin-bottom: 5px; font-weight: 500;">arXiv URL 或 ID:</label>
            <input type="text" id="arxiv-url" placeholder="例如: https://arxiv.org/pdf/2511.03725 或 2511.03725" 
                   style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;">
            <p style="margin-top: 5px; font-size: 12px; color: #666;">
                支持格式：https://arxiv.org/pdf/2511.03725、https://arxiv.org/abs/2511.03725 或直接输入 arXiv ID
            </p>
        </div>
        <div id="arxiv-upload-status" style="display: none; margin-top: 10px;">
            <div class="loading-small" style="display: flex; align-items: center; gap: 10px;">
                <div class="spinner-small"></div>
                <span>正在下载并导入...</span>
            </div>
        </div>
    `;
    
    confirmBtn.style.display = 'inline-block';
    confirmBtn.textContent = '导入';
    cancelBtn.textContent = '取消';
    
    // 清除之前的所有事件监听器（通过移除并重新添加）
    const confirmBtnClone = confirmBtn.cloneNode(true);
    const cancelBtnClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmBtnClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelBtnClone, cancelBtn);
    
    // 重新获取按钮引用
    const newConfirmBtn = document.getElementById('modal-confirm');
    const newCancelBtn = document.getElementById('modal-cancel');
    
    newConfirmBtn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const arxivUrl = document.getElementById('arxiv-url').value.trim();
        if (!arxivUrl) {
            showMessage('请输入 arXiv URL 或 ID', 'warning');
            return;
        }
        // 非阻塞导入：立即关闭弹窗并在后台导入
        hideModal();
        showMessage('开始后台导入…', 'success');
        
        // 后台下载并在完成后刷新分类计数/当前列表
        (async () => {
            try {
                const response = await fetch('/api/upload/arxiv', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        arxiv_url: arxivUrl,
                        category_id: currentCategoryId
                    })
                });
                const result = await response.json();
                if (response.ok && result.success) {
                    showMessage('论文导入成功', 'success');
                    if (currentCategoryId) {
                        loadPapers(currentCategoryId);
                    }
                    await updateCategoriesData();
                    renderCategoryTreeWithState();
                    updateReadingListCount();
                } else {
                    showMessage(result.error || '导入失败', 'error');
                }
            } catch (err) {
                console.error('导入 arXiv 论文失败:', err);
                showMessage('导入失败，请稍后重试', 'error');
            }
        })();
    };
    
    // 设置取消按钮 - 直接覆盖 onclick
    newCancelBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideModal();
    };
    
    // 支持回车键提交
    const arxivUrlInput = document.getElementById('arxiv-url');
    if (arxivUrlInput) {
        arxivUrlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                newConfirmBtn.click();
            }
        });
        
        // 自动聚焦输入框
        setTimeout(() => {
            arxivUrlInput.focus();
        }, 100);
    }
    
    showModal();
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
async function deletePaper(paperId, event = null) {
    if (event) {
        event.stopPropagation();
    }
    
    try {
        // 乐观更新：先从列表移除
        papers = papers.filter(p => p.id !== paperId);
        renderPapersList();

        const response = await fetch(`/api/paper/${paperId}`, { method: 'DELETE' });
        if (response.ok) {
            showMessage('论文删除成功', 'success');
            await updateCategoriesData();
            renderCategoryTreeWithState();
            updateReadingListCount();
        } else {
            const error = await response.json();
            showMessage(`删除失败: ${error.error}`, 'error');
            // 回滚：重新加载列表
            if (currentCategoryId) loadPapers(currentCategoryId);
        }
    } catch (error) {
        console.error('删除论文失败:', error);
        showMessage('删除失败，请稍后重试', 'error');
        if (currentCategoryId) loadPapers(currentCategoryId);
    }
}

// 切换点赞状态
async function toggleStar(paperId, event) {
    event.stopPropagation();
    
    try {
        const paper = papers.find(p => p.id === paperId);
        if (!paper) {
            showMessage('论文未找到', 'error');
            return;
        }
        
        const newStarred = !paper.starred;
        
        const response = await fetch(`/api/paper/${paperId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                starred: newStarred
            })
        });
        
        if (response.ok) {
            // 更新本地数据
            paper.starred = newStarred;
            
            // 重新渲染论文列表以更新显示
            renderPapersList();
            
            // 如果当前选中了这篇论文，重新选中以保持选中状态
            if (currentPaperId === paperId) {
                selectPaper(paperId);
            }
            
            showMessage(newStarred ? '已点赞' : '已取消点赞', 'success');
        } else {
            showMessage('操作失败', 'error');
        }
    } catch (error) {
        console.error('切换点赞状态失败:', error);
        showMessage('操作失败，请稍后重试', 'error');
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

// ========== 多选逻辑 ==========
function toggleMultiSelectMode() {
    isMultiSelectMode = !isMultiSelectMode;
    if (!isMultiSelectMode) {
        selectedPaperIds.clear();
        lastSelectedIndex = null;
    }
    updateBatchUI();
    renderPapersList();
}

function exitMultiSelectMode() {
    if (!isMultiSelectMode) return;
    isMultiSelectMode = false;
    selectedPaperIds.clear();
    lastSelectedIndex = null;
    updateBatchUI();
    renderPapersList();
}

function updateBatchUI() {
    const toolbar = document.getElementById('batch-toolbar');
    const btn = document.getElementById('toggle-multiselect');
    const count = document.getElementById('batch-count');
    if (toolbar) toolbar.style.display = isMultiSelectMode ? 'flex' : 'none';
    if (btn) btn.classList.toggle('active', isMultiSelectMode);
    if (count) count.textContent = `已选中 ${selectedPaperIds.size} 项`;
}

function handleMultiSelectClick(e, paperId) {
    const ids = window.__currentSortedPapers || papers.map(p=>p.id);
    const index = ids.indexOf(paperId);
    const checkbox = e.target && (e.target.matches('input[type="checkbox"]') || (e.target.closest && e.target.closest('.paper-checkbox')));
    const withShift = e.shiftKey;
    if (withShift && lastSelectedIndex !== null) {
        // 选择区间
        const [start, end] = index > lastSelectedIndex ? [lastSelectedIndex, index] : [index, lastSelectedIndex];
        for (let i = start; i <= end; i++) selectedPaperIds.add(ids[i]);
    } else {
        // 切换当前项
        if (selectedPaperIds.has(paperId) && !checkbox) {
            selectedPaperIds.delete(paperId);
        } else {
            selectedPaperIds.add(paperId);
        }
        lastSelectedIndex = index;
    }
    updateBatchUI();
    renderPapersList();
}

async function onBatchAnalyze() {
    if (selectedPaperIds.size === 0) { showMessage('请先选择论文', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    for (const id of ids) {
        await requestAnalysis(id);
    }
    showMessage(`已提交 ${ids.length} 篇解读`, 'success');
}

async function onBatchTranslate() {
    if (selectedPaperIds.size === 0) { showMessage('请先选择论文', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    for (const id of ids) {
        await requestTranslation(id);
    }
    showMessage(`已提交 ${ids.length} 篇翻译`, 'success');
    updateTaskIndicator();
}

async function onBatchMove() {
    if (selectedPaperIds.size === 0) { showMessage('请先选择论文', 'warning'); return; }
    // 复用单个移动的目录选择器，但不传 paperId，在确认时对所有选中执行
    try {
        await updateCategoriesData();
        const modalTitle = document.querySelector('#modal-title');
        const modalBody = document.querySelector('#modal-body');
        const confirmBtn = document.querySelector('#modal-confirm');
        const cancelBtn = document.querySelector('#modal-cancel');

        modalTitle.textContent = `移动所选 (${selectedPaperIds.size}) 篇 到目录`;
        modalBody.innerHTML = `
            <div class="form-group">
                <div id="move-category-tree" style="max-height:50vh; overflow:auto; padding:8px; border:1px solid #eee; border-radius:6px;"></div>
            </div>
        `;
        const treeContainer = modalBody.querySelector('#move-category-tree');
        renderCategorySelectTree(categories, treeContainer);

        // 解绑旧事件
        const confirmClone = confirmBtn.cloneNode(true);
        const cancelClone = cancelBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(confirmClone, confirmBtn);
        cancelBtn.parentNode.replaceChild(cancelClone, cancelBtn);
        const newConfirm = document.getElementById('modal-confirm');
        const newCancel = document.getElementById('modal-cancel');

        newConfirm.onclick = async () => {
            const selected = treeContainer.querySelector('input[name="target-category"]:checked');
            if (!selected) { showMessage('请选择目标目录', 'warning'); return; }
            const targetId = selected.value;
            const ids = Array.from(selectedPaperIds);
            for (const id of ids) {
                await movePaper(id, targetId);
            }
            hideModal();
            exitMultiSelectMode();
        };
        newCancel.onclick = () => hideModal();
        showModal();
    } catch (e) {
        console.error(e);
        showMessage('打开移动选择器失败', 'error');
    }
}

async function onBatchDelete() {
    if (selectedPaperIds.size === 0) { showMessage('请先选择论文', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    // 乐观更新：先从前端移除
    papers = papers.filter(p => !selectedPaperIds.has(p.id));
    renderPapersList();
    // 依次调用后端删除
    for (const id of ids) {
        try { await fetch(`/api/paper/${id}`, { method: 'DELETE' }); } catch (e) { console.error(e); }
    }
    showMessage('批量删除完成', 'success');
    await updateCategoriesData();
    renderCategoryTreeWithState();
    exitMultiSelectMode();
}

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

// ==================== 导航和设置功能 ====================

// 设置导航
function setupNavigation() {
    const navTabs = document.querySelectorAll('.nav-tab');
    navTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;
            switchTab(targetTab);
        });
    });

    // 设置页左侧导航
    document.addEventListener('click', (e) => {
        const item = e.target.closest && e.target.closest('.setting-nav-item');
        if (!item) return;
        document.querySelectorAll('.setting-nav-item').forEach(b=>b.classList.remove('active'));
        item.classList.add('active');
        const key = item.getAttribute('data-setting');
        document.querySelectorAll('.setting-panel').forEach(p=>p.style.display='none');
        const panel = document.getElementById(`setting-panel-${key}`);
        if (panel) panel.style.display = 'block';
    });

    // 翻译任务按钮
    const btnShowTranslating = document.getElementById('btn-show-translating');
    if (btnShowTranslating) {
        btnShowTranslating.addEventListener('click', () => {
            switchTab('paper');
            showTranslatingPapers();
        });
    }

    // 解读任务按钮
    const btnShowAnalyzing = document.getElementById('btn-show-analyzing');
    if (btnShowAnalyzing) {
        btnShowAnalyzing.addEventListener('click', () => {
            switchTab('paper');
            showAnalyzingPapers();
        });
    }

    // 待读列表按钮
    const btnShowReadingList = document.getElementById('btn-show-reading-list');
    if (btnShowReadingList) {
        btnShowReadingList.addEventListener('click', () => {
            switchTab('paper');
            showReadingList();
        });
    }
}

// 切换标签页
function switchTab(tabName) {
    const paperView = document.getElementById('paper-view');
    const settingView = document.getElementById('setting-view');
    const navTabs = document.querySelectorAll('.nav-tab');
    
    navTabs.forEach(tab => {
        if (tab.dataset.tab === tabName) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    
    if (tabName === 'paper') {
        paperView.style.display = 'flex';
        settingView.style.display = 'none';
        // 不调用 renderRecentIfNoCategory，让调用者决定显示什么
    } else if (tabName === 'setting') {
        paperView.style.display = 'none';
        settingView.style.display = 'block';
    }
    saveCurrentViewState();
}

// 保存翻译设置
function saveTranslationSettings() {
    const settings = {
        openaiModel: document.getElementById('openai-model').value.trim(),
        openaiBaseUrl: document.getElementById('openai-base-url').value.trim(),
        openaiApiKey: document.getElementById('openai-api-key').value.trim()
    };
    
    localStorage.setItem('translationSettings', JSON.stringify(settings));
    showMessage('设置已保存', 'success');
}

// 加载翻译设置
function loadTranslationSettings() {
    const saved = localStorage.getItem('translationSettings');
    if (saved) {
        try {
            const settings = JSON.parse(saved);
            document.getElementById('openai-model').value = settings.openaiModel || '';
            document.getElementById('openai-base-url').value = settings.openaiBaseUrl || '';
            document.getElementById('openai-api-key').value = settings.openaiApiKey || '';
        } catch (e) {
            console.error('加载设置失败:', e);
        }
    }
}

// 获取翻译设置
function getTranslationSettings() {
    const saved = localStorage.getItem('translationSettings');
    if (saved) {
        try {
            return JSON.parse(saved);
        } catch (e) {
            console.error('解析设置失败:', e);
        }
    }
    return null;
}

// ==================== 翻译功能 ====================

// ========== General 设置 ==========
async function saveGeneralSettings() {
    const maxItemsInput = document.getElementById('reading-list-max-items');
    const maxItems = parseInt(maxItemsInput?.value ?? '', 10);

    if (isNaN(maxItems) || maxItems < 1) {
        showMessage('请输入有效的待读列表显示数量（≥1）', 'error');
        maxItemsInput?.focus();
        return;
    }
    
    try {
        const response = await fetch('/api/settings/general', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                reading_list_max_items: maxItems
            })
        });
        
        const result = await response.json();
        if (response.ok && result.success) {
            showMessage('General 设置已保存', 'success');
        } else {
            showMessage(result.error || '保存失败', 'error');
        }
    } catch (error) {
        console.error('保存General设置失败:', error);
        showMessage('保存失败', 'error');
    }
}

async function loadGeneralSettings() {
    try {
        const response = await fetch('/api/settings/general');
        if (response.ok) {
            const settings = await response.json();
            const maxItemsInput = document.getElementById('reading-list-max-items');
            if (maxItemsInput) {
                maxItemsInput.value = settings.reading_list_max_items ?? 100;
            }
        }
    } catch (error) {
        console.error('加载General设置失败:', error);
    }
}

// ========== Habit 设置 ==========
function saveHabitSettings() {
    const count = parseInt(document.getElementById('habit-recent-count').value, 10);
    const settings = {
        recentCount: (!isNaN(count) && count > 0) ? count : 10
    };
    localStorage.setItem('habitSettings', JSON.stringify(settings));
    showMessage('Habit 设置已保存', 'success');
    // 立即应用
    renderRecentIfNoCategory();
}

function loadHabitSettings() {
    const saved = localStorage.getItem('habitSettings');
    let settings = { recentCount: 10 };
    if (saved) {
        try { settings = Object.assign(settings, JSON.parse(saved)); } catch {}
    }
    const input = document.getElementById('habit-recent-count');
    if (input) input.value = settings.recentCount;
}

function getHabitSettings() {
    const saved = localStorage.getItem('habitSettings');
    if (saved) {
        try { return JSON.parse(saved); } catch {}
    }
    return { recentCount: 10 };
}

// ========== 最近阅读 ==========
function markPaperViewed(paperId) {
    try {
        const key = 'recentPapers';
        const now = Date.now();
        let items = [];
        const saved = localStorage.getItem(key);
        if (saved) { items = JSON.parse(saved) || []; }
        // 去重保留最新
        items = items.filter(it => it.paperId !== paperId);
        items.unshift({ paperId, viewedAt: now });
        // 限制最大长度（为避免无限增长，取 200）
        if (items.length > 200) items = items.slice(0, 200);
        localStorage.setItem(key, JSON.stringify(items));
    } catch (e) { console.error('标记最近阅读失败', e); }
}

// 顶部任务指示器
function updateTaskIndicator() {
    const tiTCount = document.getElementById('ti-translate-count');
    const tiACount = document.getElementById('ti-analyze-count');
    if (!tiTCount || !tiACount) return;
    // 统计队列中+运行中的数量
    const transQueued = translationQueue.length;
    const transRunning = Object.values(translationStatus).filter(s => s.status === 'translating').length;
    const analyzeQueued = analysisQueue.length;
    const analyzeRunning = Object.values(analysisStatus).filter(s => s.status === 'analyzing').length;
    const tCount = transQueued + transRunning;
    const aCount = analyzeQueued + analyzeRunning;
    tiTCount.textContent = tCount;
    tiACount.textContent = aCount;
    
    // 更新按钮样式（如果有任务则高亮）
    const btnT = document.getElementById('btn-show-translating');
    const btnA = document.getElementById('btn-show-analyzing');
    if (btnT) {
        if (tCount > 0) {
            btnT.classList.add('has-tasks');
        } else {
            btnT.classList.remove('has-tasks');
        }
    }
    if (btnA) {
        if (aCount > 0) {
            btnA.classList.add('has-tasks');
        } else {
            btnA.classList.remove('has-tasks');
        }
    }
}

function renderTaskTooltip() {
    const tooltip = document.getElementById('task-tooltip');
    if (!tooltip) return;
    const parts = [];
    // 翻译
    const tBlock = [];
    translationQueue.forEach(pid => {
        const p = (papers || []).find(x=>x.id===pid) || {};
        tBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(队列)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
    });
    Object.entries(translationStatus).forEach(([pid, s]) => {
        if (s.status === 'translating') {
            const p = (papers || []).find(x=>x.id===pid) || {};
            tBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(执行)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
        }
    });
    if (tBlock.length) {
        parts.push('<div class="tt-title">翻 译</div>');
        parts.push(`<div class=\"tt-group\">${tBlock.join('')}</div>`);
    }
    // 解读
    const aBlock = [];
    analysisQueue.forEach(pid => {
        const p = (papers || []).find(x=>x.id===pid) || {};
        aBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(队列)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
    });
    Object.entries(analysisStatus).forEach(([pid, s]) => {
        if (s.status === 'analyzing') {
            const p = (papers || []).find(x=>x.id===pid) || {};
            aBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(执行)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
        }
    });
    if (aBlock.length) {
        parts.push('<div class="tt-title">解 读</div>');
        parts.push(`<div class=\"tt-group\">${aBlock.join('')}</div>`);
    }
    tooltip.innerHTML = parts.length ? parts.join('') : '<div class="tt-item" style="color:#888;">暂无进行中的任务</div>';
}

async function renderAllPapers() {
    if (currentCategoryId) return;
    try {
        // 从后端获取所有论文
        const response = await fetch('/api/papers/all');
        if (!response.ok) {
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-file-pdf"></i>
                    <p>加载论文失败</p>
                </div>`;
            return;
        }
        
        papers = await response.json();
        
        if (!papers.length) {
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-file-pdf"></i>
                    <p>暂无论文</p>
                    <p style="font-size:12px; margin-top:6px; color:#666;">请上传或导入论文</p>
                </div>`;
            document.getElementById('sort-controls').style.display = 'none';
            return;
        }
        
        // 更新标题
        currentCategoryTitle.textContent = `所有论文 (${papers.length} 篇)`;
        
        // 确保待读列表ID集合已更新
        await updateReadingListCount();
        
        // 使用标准的渲染函数，支持排序
        renderPapersList();
    } catch (e) {
        console.error('渲染所有论文失败', e);
        papersList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-file-pdf"></i>
                <p>加载论文失败</p>
            </div>`;
    }
}

// 保留旧函数名作为别名，以便不破坏现有调用
async function renderRecentIfNoCategory() {
    await renderAllPapers();
}

// 请求翻译
async function requestTranslation(paperId, event) {
    if (event) {
        event.stopPropagation();
    }
    const paper = papers.find(p => p.id === paperId);
    if (!paper) {
        showMessage('论文未找到', 'error');
        return;
    }
    
    // 检查是否已有中文版本
    if (paper.has_chinese_version) {
        if (confirm('该论文已有中文版本，是否重新翻译？')) {
            // 可以在这里添加重新翻译的逻辑
        } else {
            return;
        }
    }
    
    // 检查设置
    const settings = getTranslationSettings();
    if (!settings || !settings.openaiModel || !settings.openaiBaseUrl || !settings.openaiApiKey) {
        showMessage('请先在设置中配置翻译参数', 'warning');
        switchTab('setting');
        return;
    }
    
    // 添加到队列
    if (translationStatus[paperId]) {
        showMessage('该论文已在翻译队列中', 'warning');
        return;
    }
    
    translationQueue.push(paperId);
    // 更新队列位置（包括当前这一个）
    const queuePosition = translationQueue.length;
    updateTranslationStatus(paperId, 'queued', queuePosition);
    saveQueuesToStorage(); // 保存队列状态
    renderPapersList(); // 立即更新显示
    updateTaskIndicator();
    
    // 开始处理队列
    processTranslationQueue();
}

// 处理翻译队列（全局唯一队列，确保同一时间只有一个任务执行）
async function processTranslationQueue() {
    // 严格检查：如果正在翻译或队列为空，直接返回
    if (isTranslating) {
        return; // 已有任务在执行，不启动新任务
    }
    if (translationQueue.length === 0) {
        return; // 队列为空
    }
    
    // 原子性设置：先设置标志，再取任务
    isTranslating = true;
    const paperId = translationQueue.shift();
    saveQueuesToStorage();
    
    try {
        updateTranslationStatus(paperId, 'translating', 0);
        renderPapersList(); // 更新显示
        
        const settings = getTranslationSettings();
        const response = await fetch('/api/paper/translate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                openai_model: settings.openaiModel,
                openai_base_url: settings.openaiBaseUrl,
                openai_api_key: settings.openaiApiKey
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            const taskId = result.task_id;
            
            // 开始轮询日志
            startLogPolling(taskId, paperId);
            
            // 更新状态为正在翻译，并保存taskId
            updateTranslationStatus(paperId, 'translating', 0, taskId);
            renderPapersList(); // 更新显示
            
            // 显示日志查看按钮的提示
            showMessage('翻译任务已启动，点击日志按钮查看进度', 'success');
        } else {
            updateTranslationStatus(paperId, 'error', 0);
            saveQueuesToStorage();
            showMessage(result.error || '翻译失败', 'error');
            isTranslating = false;
            renderPapersList(); // 更新显示
            processTranslationQueue(); // 继续处理队列
        }
    } catch (error) {
        console.error('翻译失败:', error);
        updateTranslationStatus(paperId, 'error', 0);
        saveQueuesToStorage();
        showMessage('翻译失败，请稍后重试', 'error');
        isTranslating = false;
        renderPapersList(); // 更新显示
        processTranslationQueue(); // 继续处理队列
    }
}

// 开始轮询翻译日志
function startLogPolling(taskId, paperId) {
    // 停止之前的轮询（如果有）
    if (translationLogInterval[taskId]) {
        clearInterval(translationLogInterval[taskId]);
    }
    
    // 每2秒轮询一次
    translationLogInterval[taskId] = setInterval(async () => {
        try {
            const response = await fetch(`/api/paper/translate/${taskId}/logs`);
            const result = await response.json();
            
            if (response.ok && result.success) {
                const status = result.status;
                
                // 如果任务完成或失败，停止轮询
                if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                    clearInterval(translationLogInterval[taskId]);
                    delete translationLogInterval[taskId];
                    
                    // 更新状态（保留taskId）
                    const currentTaskId = translationStatus[paperId]?.taskId;
                    if (status === 'completed') {
                        updateTranslationStatus(paperId, 'completed', 0, currentTaskId);
                        const paper = papers.find(p => p.id === paperId);
                        if (paper && result.result && result.result.success) {
                            paper.has_chinese_version = true;
                            paper.chinese_version_path = result.result.chinese_version_path;
                        }
                        showMessage('翻译完成', 'success');
                    } else {
                        updateTranslationStatus(paperId, 'error', 0, currentTaskId);
                        showMessage(result.result?.error || '翻译失败', 'error');
                    }
                    
                    // 继续处理队列
                    isTranslating = false;
                    renderPapersList();
                    renderRecentIfNoCategory(); // 同时更新最近阅读列表
                    processTranslationQueue();
                }
            } else {
                // 如果任务不存在（可能被外部删除或服务器重启），停止轮询并清理状态
                if (response.status === 404) {
                    clearInterval(translationLogInterval[taskId]);
                    delete translationLogInterval[taskId];
                    // 从队列中移除
                    const queueIndex = translationQueue.indexOf(paperId);
                    if (queueIndex !== -1) {
                        translationQueue.splice(queueIndex, 1);
                    }
                    // 删除状态
                    delete translationStatus[paperId];
                    // 重置标志
                    isTranslating = false;
                    saveQueuesToStorage();
                    updateTaskIndicator();
                    renderPapersList();
                    renderRecentIfNoCategory();
                    processTranslationQueue();
                }
            }
        } catch (error) {
            console.error('获取翻译日志失败:', error);
        }
    }, 2000); // 每2秒轮询一次
}

// 停止日志轮询
function stopLogPolling(taskId) {
    if (translationLogInterval[taskId]) {
        clearInterval(translationLogInterval[taskId]);
        delete translationLogInterval[taskId];
    }
}

// 查看翻译日志
async function showTranslationLogs(paperId, event) {
    if (event) {
        event.stopPropagation();
    }
    const status = translationStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('未找到翻译任务', 'warning');
        return;
    }
    
    const taskId = status.taskId;
    
    // 获取日志
    try {
        const response = await fetch(`/api/paper/translate/${taskId}/logs`);
        const result = await response.json();
        
        if (response.ok && result.success) {
            // 显示日志模态框
            showLogModal(taskId, result.logs, result.status, paperId);
        } else {
            showMessage('获取日志失败', 'error');
        }
    } catch (error) {
        console.error('获取日志失败:', error);
        showMessage('获取日志失败', 'error');
    }
}

// 显示日志模态框
function showLogModal(taskId, logs, status, paperId) {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');
    
    modalTitle.textContent = '翻译日志';
    
    const logContent = logs.length > 0 ? logs.join('\n') : '暂无日志';
    const canCancel = status === 'running' || status === 'queued';
    
    modalBody.innerHTML = `
        <div style="margin-bottom: 15px;">
            <strong>状态:</strong> 
            <span id="log-status">${getStatusText(status)}</span>
        </div>
        <div style="margin-bottom: 15px;">
            <button class="btn btn-secondary" onclick="refreshLogs('${taskId}', '${paperId}')" style="margin-right: 10px;">
                <i class="fas fa-refresh"></i> 刷新日志
            </button>
            ${canCancel ? `
            <button class="btn btn-danger" onclick="cancelTranslation('${taskId}', '${paperId}')">
                <i class="fas fa-stop"></i> 终止翻译
            </button>
            ` : ''}
        </div>
        <div style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 4px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word;">
            ${escapeHtml(logContent)}
        </div>
    `;
    
    confirmBtn.style.display = 'none';
    cancelBtn.textContent = '关闭';
    cancelBtn.onclick = () => hideModal();
    
    showModal();
    
    // 如果正在运行，自动刷新
    if (status === 'running' || status === 'queued') {
        const autoRefresh = setInterval(async () => {
            try {
                const response = await fetch(`/api/paper/translate/${taskId}/logs`);
                const result = await response.json();
                if (response.ok && result.success) {
                    const statusEl = document.getElementById('log-status');
                    if (statusEl) {
                        statusEl.textContent = getStatusText(result.status);
                    }
                    const logEl = modalBody.querySelector('div[style*="background: #1e1e1e"]');
                    if (logEl) {
                        logEl.textContent = result.logs.join('\n');
                    }
                    
                    // 如果完成，停止自动刷新
                    if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') {
                        clearInterval(autoRefresh);
                        // 更新状态（保留taskId）
                        const currentTaskId = translationStatus[paperId]?.taskId;
                        if (result.status === 'completed') {
                            updateTranslationStatus(paperId, 'completed', 0, currentTaskId);
                            const paper = papers.find(p => p.id === paperId);
                            if (paper && result.result && result.result.success) {
                                paper.has_chinese_version = true;
                                paper.chinese_version_path = result.result.chinese_version_path;
                            }
                        } else {
                            updateTranslationStatus(paperId, 'error', 0, currentTaskId);
                        }
                        renderPapersList();
                    }
                }
            } catch (error) {
                console.error('刷新日志失败:', error);
            }
        }, 2000);
        
        // 模态框关闭时停止自动刷新
        const closeBtn = document.querySelector('.close');
        const originalClose = closeBtn.onclick;
        closeBtn.onclick = () => {
            clearInterval(autoRefresh);
            hideModal();
        };
    }
}

// 刷新日志
async function refreshLogs(taskId, paperId) {
    showTranslationLogs(paperId);
}

// 取消翻译（从状态中取消，需要taskId）
async function cancelTranslation(taskId, paperId) {
    if (!confirm('确定要终止翻译吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/paper/translate/${taskId}/cancel`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (response.ok && result.success) {
            showMessage('翻译已取消', 'success');
            stopLogPolling(taskId);
            updateTranslationStatus(paperId, 'error', 0, taskId);
            isTranslating = false;
            renderPapersList();
            renderRecentIfNoCategory();
            hideModal();
            processTranslationQueue(); // 继续处理队列
        } else {
            // 如果任务不存在（服务器重启等情况），清理前端状态
            if (response.status === 404 || (result.error && result.error.includes('任务不存在'))) {
                showMessage('任务不存在，已清理状态', 'warning');
                // 检查是否正在翻译（在删除状态前检查）
                const wasTranslating = isTranslating && translationStatus[paperId] && translationStatus[paperId].taskId === taskId;
                // 清理前端状态
                stopLogPolling(taskId);
                // 从队列中移除
                const queueIndex = translationQueue.indexOf(paperId);
                if (queueIndex !== -1) {
                    translationQueue.splice(queueIndex, 1);
                }
                // 删除状态
                delete translationStatus[paperId];
                // 如果正在翻译，重置标志
                if (wasTranslating) {
                    isTranslating = false;
                }
                saveQueuesToStorage();
                updateTaskIndicator();
                renderPapersList();
                renderRecentIfNoCategory();
                hideModal();
                // 继续处理队列
                processTranslationQueue();
            } else {
                showMessage(result.error || '取消翻译失败', 'error');
            }
        }
    } catch (error) {
        console.error('取消翻译失败:', error);
        showMessage('取消翻译失败', 'error');
    }
}

// 从状态中取消翻译（通过paperId查找taskId）
async function cancelTranslationFromStatus(paperId, event) {
    if (event) event.stopPropagation();
    const status = translationStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('未找到翻译任务', 'warning');
        return;
    }
    await cancelTranslation(status.taskId, paperId);
}

// 从队列中取消翻译
async function cancelTranslationFromQueue(paperId, event) {
    if (event) event.stopPropagation();
    const index = translationQueue.indexOf(paperId);
    if (index === -1) {
        showMessage('论文不在队列中', 'warning');
        return;
    }
    translationQueue.splice(index, 1);
    saveQueuesToStorage();
    delete translationStatus[paperId];
    updateTranslationStatus(paperId, 'error', 0);
    showMessage('已从队列中移除', 'success');
}

// 获取状态文本
function getStatusText(status) {
    const statusMap = {
        'queued': '队列中',
        'running': '正在翻译',
        'completed': '已完成',
        'failed': '失败',
        'cancelled': '已取消'
    };
    return statusMap[status] || status;
}

// HTML转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 更新翻译状态
function updateTranslationStatus(paperId, status, queuePosition, taskId) {
    // 保留已有的taskId
    const existingTaskId = translationStatus[paperId]?.taskId;
    translationStatus[paperId] = {
        status: status,
        queuePosition: queuePosition,
        taskId: taskId || existingTaskId  // 保留已有的taskId，或使用新的
    };
    
    // 如果完成或出错，从状态中移除
    if (status === 'completed' || status === 'error') {
        delete translationStatus[paperId];
    }
    
    // 更新显示（根据当前视图模式）
    if (currentViewMode === 'translating') {
        // 如果正在查看翻译列表，刷新列表
        showTranslatingPapers();
    } else if (currentViewMode === 'reading-list') {
        // 如果正在查看待读列表，只更新单个论文状态，不重新加载整个列表
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderRecentIfNoCategory();
    }
    updateTaskIndicator();
    saveQueuesToStorage();
}

// 获取总阅读时长显示文本
function getTotalReadTimeText(paper) {
    const readTime = paper.read_time || 0; // 阅读PDF时间（秒）
    const analysisViewTime = paper.analysis_view_time || 0; // 阅读AI解读时间（秒）
    const totalTime = readTime + analysisViewTime;
    
    if (totalTime === 0) {
        return '';
    }
    
    // 转换为分钟和秒
    const minutes = Math.floor(totalTime / 60);
    const seconds = totalTime % 60;
    
    let timeText = '';
    if (minutes > 0) {
        timeText = `${minutes}分`;
        if (seconds > 0) {
            timeText += `${seconds}秒`;
        }
    } else {
        timeText = `${seconds}秒`;
    }
    
    return `<span style="color: #666; margin-left: 8px;">| 已读: ${timeText}</span>`;
}

// 获取翻译状态显示文本
function getTranslationStatusText(paperId) {
    const status = translationStatus[paperId];
    if (!status) return '';
    
    if (status.status === 'translating') {
        return `<span class="translation-status translating">
            <i class="fas fa-spinner fa-spin"></i> 正在翻译...
            <button class="status-cancel-btn" onclick="cancelTranslationFromStatus('${paperId}', event)" title="取消翻译">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'queued') {
        // 计算当前在队列中的位置
        const currentIndex = translationQueue.indexOf(paperId) + 1;
        return `<span class="translation-status queued">
            <i class="fas fa-clock"></i> 队列中 (${currentIndex}/${translationQueue.length})
            <button class="status-cancel-btn" onclick="cancelTranslationFromQueue('${paperId}', event)" title="取消队列">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    }
    return '';
}

// 打开中文版本PDF
function openChineseVersion(paperId) {
    const paper = papers.find(p => p.id === paperId);
    if (!paper || !paper.has_chinese_version) {
        showMessage('中文版本不存在', 'error');
        return;
    }
    const viewerUrl = `/viewer/${paperId}?chinese=true`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// ========== AI解读相关函数 ==========

// 保存解读设置
function saveAnalysisSettings() {
    const settings = {
        mineruServerUrl: document.getElementById('mineru-server-url').value.trim(),
        openaiBaseUrl: document.getElementById('analysis-openai-base-url').value.trim(),
        openaiApiKey: document.getElementById('analysis-openai-api-key').value.trim(),
        systemPrompt: document.getElementById('analysis-system-prompt').value.trim()
    };
    
    localStorage.setItem('analysisSettings', JSON.stringify(settings));
    showMessage('设置已保存', 'success');
}

// 加载解读设置
function loadAnalysisSettings() {
    const saved = localStorage.getItem('analysisSettings');
    if (saved) {
        try {
            const settings = JSON.parse(saved);
            document.getElementById('mineru-server-url').value = settings.mineruServerUrl || '';
            document.getElementById('analysis-openai-base-url').value = settings.openaiBaseUrl || '';
            document.getElementById('analysis-openai-api-key').value = settings.openaiApiKey || '';
            document.getElementById('analysis-system-prompt').value = settings.systemPrompt || '';
        } catch (e) {
            console.error('加载设置失败:', e);
        }
    } else {
        // 设置默认的 SYSTEM_PROMPT
        const defaultPrompt = `请以中文 markdown 的形式为这篇文章写一个公众号风格的包含有详细内容的长推文，内容要详细且丰富，
实验内容也要充分，比如包括消融实验。注意你一定要使用原始markdown 中的图片和表格来让你的公众号文章更加清晰，
图片,比如模型结构，teaser，或者一些结果图，阐释图直接插入到正文对应位置之中，不要放到最后。图片对于一个公众号文章来说很重要

INPUT: <MARKDOWN>`;
        document.getElementById('analysis-system-prompt').value = defaultPrompt;
    }
}

// 获取解读设置
function getAnalysisSettings() {
    const saved = localStorage.getItem('analysisSettings');
    if (saved) {
        try {
            return JSON.parse(saved);
        } catch (e) {
            console.error('读取设置失败:', e);
            return null;
        }
    }
    return null;
}

// 恢复进行中的任务状态（页面刷新/重新打开后）
async function restoreActiveTasks() {
    try {
        // 先从本地队列恢复排队状态（这些队列在刷新前可能尚未提交到后端）
        const queuedTranslateIds = Array.isArray(translationQueue) ? [...translationQueue] : [];
        const queuedAnalyzeIds = Array.isArray(analysisQueue) ? [...analysisQueue] : [];

        translationStatus = {};
        analysisStatus = {};

        queuedTranslateIds.forEach((pid) => {
            translationStatus[pid] = { status: 'queued', taskId: translationStatus[pid]?.taskId || null };
        });
        queuedAnalyzeIds.forEach((pid) => {
            analysisStatus[pid] = { status: 'queued', taskId: analysisStatus[pid]?.taskId || null };
        });

        // 翻译任务（从后端合并活跃任务）
        const tRes = await fetch('/api/paper/translate/active');
        const tJson = await tRes.json();
        if (tRes.ok && tJson.success && Array.isArray(tJson.tasks)) {
            let hasRunningTranslation = false;
            for (const t of tJson.tasks) {
                const paperId = t.paper_id;
                try {
                    const logRes = await fetch(`/api/paper/translate/${t.task_id}/logs`);
                    if (logRes.ok) {
                        const logData = await logRes.json();
                        if (logData.success && (logData.status === 'running' || logData.status === 'queued')) {
                            translationStatus[paperId] = {
                                status: t.status === 'running' ? 'translating' : 'queued',
                                taskId: t.task_id,
                            };
                            if (t.status === 'queued' && !translationQueue.includes(paperId)) {
                                translationQueue.push(paperId);
                            }
                            if (t.status === 'running') {
                                hasRunningTranslation = true;
                                startLogPolling(t.task_id, paperId);
                            }
                        }
                    }
                } catch (e) {
                    console.error(`验证翻译任务 ${t.task_id} 失败:`, e);
                }
            }
            isTranslating = hasRunningTranslation;
        }

        // 解读任务（从后端合并活跃任务）
        const aRes = await fetch('/api/paper/analyze/active');
        const aJson = await aRes.json();
        if (aRes.ok && aJson.success && Array.isArray(aJson.tasks)) {
            let hasRunningAnalysis = false;
            for (const a of aJson.tasks) {
                const paperId = a.paper_id;
                try {
                    const logRes = await fetch(`/api/paper/analyze/${a.task_id}/logs`);
                    if (logRes.ok) {
                        const logData = await logRes.json();
                        if (logData.success && (logData.status === 'running' || logData.status === 'queued')) {
                            analysisStatus[paperId] = {
                                status: a.status === 'running' ? 'analyzing' : 'queued',
                                taskId: a.task_id,
                                step: a.step || null,
                            };
                            if (a.status === 'queued' && !analysisQueue.includes(paperId)) {
                                analysisQueue.push(paperId);
                            }
                            if (a.status === 'running') {
                                hasRunningAnalysis = true;
                                startAnalysisLogPolling(a.task_id, paperId);
                            }
                        }
                    }
                } catch (e) {
                    console.error(`验证解读任务 ${a.task_id} 失败:`, e);
                }
            }
            isAnalyzing = hasRunningAnalysis;
        }

        // 持久化并更新指示器
        saveQueuesToStorage();
        updateTaskIndicator();

        // 刷新当前视图
        if (currentCategoryId) {
            loadPapers(currentCategoryId);
        } else {
            renderRecentIfNoCategory();
        }
    } catch (e) {
        console.error('恢复任务状态失败:', e);
    }
}

// 请求AI解读
async function requestAnalysis(paperId, event) {
    if (event) {
        event.stopPropagation();
    }

    const paper = papers.find(p => p.id === paperId);
    if (!paper) {
        showMessage('论文未找到', 'error');
        return;
    }

    // 检查是否已有解读结果
    const hasResult = paper.has_analysis_result;
    if (hasResult) {
        if (!confirm('该论文已有AI解读结果，是否重新解读？')) {
            return;
        }
    }

    // 检查设置
    const settings = getAnalysisSettings();
    if (!settings || !settings.mineruServerUrl || !settings.openaiBaseUrl || !settings.openaiApiKey || !settings.systemPrompt) {
        showMessage('请先在设置中配置AI解读参数', 'warning');
        // 切换到设置页面
        document.querySelector('.nav-tab[data-tab="setting"]').click();
        return;
    }

    // 检查是否已在队列中或正在解读
    if (analysisStatus[paperId]) {
        const status = analysisStatus[paperId].status;
        if (status === 'analyzing' || status === 'queued') {
            showMessage('该论文已在解读队列中', 'info');
            return;
        }
    }

    // 添加到队列
    analysisQueue.push(paperId);
    
    // 更新状态
    const queuePosition = analysisQueue.length;
    updateAnalysisStatus(paperId, 'queued', queuePosition);
    saveQueuesToStorage();
    
    // 处理队列
    processAnalysisQueue();
    updateTaskIndicator();
}

// 处理解读队列（全局唯一队列，确保同一时间只有一个任务执行）
async function processAnalysisQueue() {
    // 严格检查：如果正在解读或队列为空，直接返回
    if (isAnalyzing) {
        return; // 已有任务在执行，不启动新任务
    }
    if (analysisQueue.length === 0) {
        return; // 队列为空
    }

    // 原子性设置：先设置标志，再取任务
    isAnalyzing = true;
    const paperId = analysisQueue.shift();
    saveQueuesToStorage();

    try {
        // 更新状态为解读中
        updateAnalysisStatus(paperId, 'analyzing');

        // 获取设置
        const settings = getAnalysisSettings();
        if (!settings) {
            throw new Error('设置未配置');
        }

        // 调用后端API
        const response = await fetch('/api/paper/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                mineru_server_url: settings.mineruServerUrl,
                openai_base_url: settings.openaiBaseUrl,
                openai_api_key: settings.openaiApiKey,
                system_prompt: settings.systemPrompt
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            // 保存 task_id
            updateAnalysisStatus(paperId, 'analyzing', null, result.task_id);
            
            // 开始轮询日志
            startAnalysisLogPolling(result.task_id, paperId);
            
            // 轮询任务状态
            pollAnalysisStatus(result.task_id, paperId);
        } else {
            throw new Error(result.error || '启动解读失败');
        }
    } catch (error) {
        console.error('解读失败:', error);
        showMessage(`解读失败: ${error.message}`, 'error');
        updateAnalysisStatus(paperId, 'error');
        saveQueuesToStorage();
        isAnalyzing = false;
        processAnalysisQueue(); // 继续处理队列
    }
}

// 轮询解读状态
async function pollAnalysisStatus(taskId, paperId) {
    const maxAttempts = 3600; // 最多轮询1小时（每秒一次）
    let attempts = 0;

    const poll = async () => {
        if (attempts >= maxAttempts) {
            updateAnalysisStatus(paperId, 'error');
            isAnalyzing = false;
            processAnalysisQueue();
            return;
        }

        try {
            const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
            const result = await response.json();

            if (response.ok && result.success) {
                if (result.status === 'completed') {
                    updateAnalysisStatus(paperId, 'completed');
                    const paper = papers.find(p => p.id === paperId);
                    if (paper && result.result && result.result.success) {
                        paper.has_analysis_result = true;
                        paper.analysis_result_path = result.result.result_file;
                    }
                    isAnalyzing = false;
                    stopAnalysisLogPolling(taskId);
                    showMessage('解读完成，可以查看结果', 'success');
                    renderPapersList();
                    renderRecentIfNoCategory();
                    if (currentPaperId === paperId) {
                        loadPaperInfo(paperId);
                    }
                    processAnalysisQueue(); // 继续处理队列
                } else if (result.status === 'failed' || result.status === 'cancelled') {
                    updateAnalysisStatus(paperId, 'error');
                    isAnalyzing = false;
                    stopAnalysisLogPolling(taskId);
                    showMessage(`解读失败: ${result.result?.error || '未知错误'}`, 'error');
                    processAnalysisQueue(); // 继续处理队列
                } else {
                    // 仍在运行，继续轮询
                    attempts++;
                    setTimeout(poll, 1000);
                }
            } else {
                throw new Error(result.error || '获取状态失败');
            }
        } catch (error) {
            console.error('轮询状态失败:', error);
            attempts++;
            setTimeout(poll, 1000);
        }
    };

    poll();
}

// 更新解读状态
function updateAnalysisStatus(paperId, status, queuePosition = null, taskId = null) {
    if (!analysisStatus[paperId]) {
        analysisStatus[paperId] = {};
    }
    
    analysisStatus[paperId].status = status;
    if (queuePosition !== null) {
        analysisStatus[paperId].queuePosition = queuePosition;
    }
    if (taskId !== null || analysisStatus[paperId].taskId) {
        analysisStatus[paperId].taskId = taskId || analysisStatus[paperId].taskId;
    }
    
    // 如果完成或出错，从状态中移除（避免旋转状态一直显示）
    if (status === 'completed' || status === 'error') {
        delete analysisStatus[paperId];
    }
    
    // 更新状态显示（根据当前视图模式）
    if (currentViewMode === 'analyzing') {
        // 如果正在查看解读列表，刷新列表
        showAnalyzingPapers();
    } else if (currentViewMode === 'reading-list') {
        // 如果正在查看待读列表，只更新单个论文状态，不重新加载整个列表
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        // 如果没有选中分类，重新渲染最近阅读列表以更新状态
        renderRecentIfNoCategory();
    }
    updateTaskIndicator();
    saveQueuesToStorage();
}

// 更新论文状态显示（不重新加载整个列表）
function updatePaperStatusDisplay(paperId) {
    const paperItem = document.querySelector(`.paper-item[data-paper-id="${paperId}"]`);
    if (!paperItem) return;
    
    const paperMeta = paperItem.querySelector('.paper-meta');
    if (paperMeta) {
        const paper = papers.find(p => p.id === paperId);
        if (paper) {
            // 更新翻译状态
            const translationStatusHtml = getTranslationStatusText(paperId);
            const oldTranslationStatus = paperMeta.querySelector('.translation-status');
            if (oldTranslationStatus) {
                oldTranslationStatus.remove();
            }
            if (translationStatusHtml) {
                const statusDiv = document.createElement('span');
                statusDiv.className = 'translation-status';
                statusDiv.innerHTML = translationStatusHtml;
                // 插入到 meta 的开始位置
                paperMeta.insertBefore(statusDiv, paperMeta.firstChild);
            }
            
            // 更新解读状态
            const analysisStatusHtml = getAnalysisStatusText(paperId);
            const oldAnalysisStatus = paperMeta.querySelector('.analysis-status');
            if (oldAnalysisStatus) {
                oldAnalysisStatus.remove();
            }
            if (analysisStatusHtml) {
                const statusDiv = document.createElement('span');
                statusDiv.className = 'analysis-status';
                statusDiv.innerHTML = analysisStatusHtml;
                paperMeta.appendChild(statusDiv);
            }
            
            // 更新查看结果按钮
            // 检查是否需要显示"查看中文版"按钮
            const existingChineseBtn = paperItem.querySelector('.chinese-version-btn-container .chinese-version-btn[onclick*="openChineseVersion"]');
            if (paper.has_chinese_version && !existingChineseBtn) {
                const btnContainer = paperItem.querySelector('.paper-details');
                if (btnContainer) {
                    const btnHtml = `
                        <div class="chinese-version-btn-container" style="margin-top: 5px;">
                            <button class="chinese-version-btn" onclick="openChineseVersion('${paperId}', event)" title="查看中文版PDF">
                                <i class="fas fa-language"></i> 查看中文版
                            </button>
                        </div>
                    `;
                    btnContainer.insertAdjacentHTML('beforeend', btnHtml);
                }
            }
            
            // 检查是否需要显示"查看 AI 解读"按钮
            const existingAnalysisBtn = paperItem.querySelector('.chinese-version-btn-container .chinese-version-btn[onclick*="viewAnalysisResult"]');
            if (paper.has_analysis_result) {
                if (!existingAnalysisBtn) {
                    const btnContainer = paperItem.querySelector('.paper-details');
                    if (btnContainer) {
                        const btnHtml = `
                            <div class="chinese-version-btn-container" style="margin-top: 5px;">
                                <button class="chinese-version-btn" onclick="viewAnalysisResult('${paperId}', event)" title="查看 AI 解读" style="background: #6f42c1; color: white; border-color: #6f42c1;">
                                    <i class="fas fa-brain"></i> 查看 AI 解读
                                </button>
                            </div>
                        `;
                        btnContainer.insertAdjacentHTML('beforeend', btnHtml);
                    }
                }
            }
        }
    }
}

// 获取解读状态显示文本
function getAnalysisStatusText(paperId) {
    const status = analysisStatus[paperId];
    if (!status) return '';
    
    if (status.status === 'analyzing') {
        const step = status.step === 'pdf2md' ? 'PDF转Markdown' : status.step === 'llm_analysis' ? 'LLM解读' : '解读中';
        return `<span class="translation-status translating">
            <i class="fas fa-spinner fa-spin"></i> 正在解读 (${step})...
            <button class="status-cancel-btn" onclick="cancelAnalysisFromStatus('${paperId}', event)" title="取消解读">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'queued') {
        const currentIndex = analysisQueue.indexOf(paperId) + 1;
        return `<span class="translation-status queued">
            <i class="fas fa-clock"></i> 解读队列中 (${currentIndex}/${analysisQueue.length})
            <button class="status-cancel-btn" onclick="cancelAnalysisFromQueue('${paperId}', event)" title="取消队列">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'completed') {
        // 完成时不显示状态文本，因为已经有"查看 AI 解读"按钮了
        return '';
    }
    return '';
}

// 开始轮询解读日志
function startAnalysisLogPolling(taskId, paperId) {
    if (analysisLogInterval[taskId]) {
        clearInterval(analysisLogInterval[taskId]);
    }
    
    analysisLogInterval[taskId] = setInterval(async () => {
        try {
            const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
            const result = await response.json();
            
            if (response.ok && result.success) {
                const status = result.status;
                
                // 检测任务是否被终止或失败
                if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                    clearInterval(analysisLogInterval[taskId]);
                    delete analysisLogInterval[taskId];
                    
                    // 更新状态
                    if (status === 'completed') {
                        updateAnalysisStatus(paperId, 'completed');
                        showMessage('解读完成，可以查看结果', 'success');
                    } else {
                        updateAnalysisStatus(paperId, 'error');
                        showMessage(`解读${status === 'cancelled' ? '已取消' : '失败'}: ${result.result?.error || '未知错误'}`, 'error');
                    }
                    
                    // 继续处理队列
                    isAnalyzing = false;
                    updatePaperStatusDisplay(paperId);
                    processAnalysisQueue();
                } else {
                    // 更新步骤信息（不重新加载整个列表，避免闪烁）
                    if (result.step && analysisStatus[paperId]) {
                        analysisStatus[paperId].step = result.step;
                        updatePaperStatusDisplay(paperId);
                    }
                }
            } else {
                // 如果任务不存在（可能被外部删除或服务器重启），停止轮询并清理状态
                if (response.status === 404) {
                    clearInterval(analysisLogInterval[taskId]);
                    delete analysisLogInterval[taskId];
                    // 从队列中移除
                    const queueIndex = analysisQueue.indexOf(paperId);
                    if (queueIndex !== -1) {
                        analysisQueue.splice(queueIndex, 1);
                    }
                    // 删除状态
                    delete analysisStatus[paperId];
                    // 重置标志
                    isAnalyzing = false;
                    saveQueuesToStorage();
                    updateTaskIndicator();
                    // 根据当前视图模式更新显示
                    if (currentViewMode === 'reading-list') {
                        updatePaperStatusDisplay(paperId);
                    } else if (currentCategoryId) {
                        updatePaperStatusDisplay(paperId);
                    } else {
                        renderRecentIfNoCategory();
                    }
                    processAnalysisQueue();
                }
            }
        } catch (error) {
            console.error('获取日志失败:', error);
        }
    }, 2000); // 每2秒轮询一次
}

// 停止轮询解读日志
function stopAnalysisLogPolling(taskId) {
    if (analysisLogInterval[taskId]) {
        clearInterval(analysisLogInterval[taskId]);
        delete analysisLogInterval[taskId];
    }
}

// 显示解读日志
async function showAnalysisLogs(paperId, event) {
    if (event) {
        event.stopPropagation();
    }

    const status = analysisStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('未找到解读任务', 'error');
        return;
    }

    const taskId = status.taskId;

    try {
        const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
        const result = await response.json();

        if (response.ok && result.success) {
            showAnalysisLogModal(taskId, result.logs, result.status, result.step, paperId);
        } else {
            showMessage(result.error || '获取日志失败', 'error');
        }
    } catch (error) {
        console.error('获取日志失败:', error);
        showMessage('获取日志失败', 'error');
    }
}

// 显示解读日志模态框
function showAnalysisLogModal(taskId, logs, status, step, paperId) {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');
    
    modalTitle.textContent = '解读日志';
    modalBody.innerHTML = `
        <div style="margin-bottom: 10px;">
            <strong>状态:</strong> <span id="log-status">${getStatusText(status)}</span>
            ${step ? `<br><strong>当前步骤:</strong> ${step === 'pdf2md' ? 'PDF转Markdown' : step === 'llm_analysis' ? 'LLM解读' : step}` : ''}
        </div>
        <div style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 4px; max-height: 400px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word;" id="log-content">
            ${logs.map(log => escapeHtml(log)).join('\n')}
        </div>
    `;
    
    confirmBtn.style.display = status === 'running' ? 'inline-block' : 'none';
    confirmBtn.textContent = '取消解读';
    cancelBtn.textContent = '关闭';
    
    // 清除之前的事件监听器
    const confirmBtnClone = confirmBtn.cloneNode(true);
    const cancelBtnClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmBtnClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelBtnClone, cancelBtn);
    
    const newConfirmBtn = document.getElementById('modal-confirm');
    const newCancelBtn = document.getElementById('modal-cancel');
    
    if (status === 'running') {
        newConfirmBtn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            await cancelAnalysis(taskId, paperId);
        };
    }
    
    newCancelBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideModal();
    };
    
    showModal();
    
    // 如果任务正在运行，开始自动刷新日志
    if (status === 'running') {
        const logInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
                const result = await response.json();
                
                if (response.ok && result.success) {
                    const logContent = document.getElementById('log-content');
                    const logStatus = document.getElementById('log-status');
                    if (logContent) {
                        logContent.textContent = result.logs.map(log => escapeHtml(log)).join('\n');
                        logContent.scrollTop = logContent.scrollHeight;
                    }
                    if (logStatus) {
                        logStatus.textContent = getStatusText(result.status);
                    }
                    
                    // 如果任务完成，停止刷新
                    if (result.status !== 'running') {
                        clearInterval(logInterval);
                        if (result.status === 'completed') {
                            showMessage('解读完成', 'success');
                            // 更新状态显示（不重新加载整个列表，避免闪烁）
                            updateAnalysisStatus(paperId, 'completed');
                            updatePaperStatusDisplay(paperId);
                        }
                    }
                }
            } catch (error) {
                console.error('刷新日志失败:', error);
            }
        }, 2000);
        
        // 当模态框关闭时，清除定时器
        const originalHideModal = window.hideModal;
        window.hideModal = function() {
            clearInterval(logInterval);
            if (originalHideModal) {
                originalHideModal();
            }
        };
    }
}

// 取消解读（从状态中取消，需要taskId）
async function cancelAnalysis(taskId, paperId) {
    try {
        const response = await fetch(`/api/paper/analyze/${taskId}/cancel`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showMessage('解读已取消', 'success');
            updateAnalysisStatus(paperId, 'error');
            isAnalyzing = false;
            processAnalysisQueue();
            hideModal();
        } else {
            // 如果任务不存在（服务器重启等情况），清理前端状态
            if (response.status === 404 || (result.error && result.error.includes('任务不存在'))) {
                showMessage('任务不存在，已清理状态', 'warning');
                // 检查是否正在解读（在删除状态前检查）
                const wasAnalyzing = isAnalyzing && analysisStatus[paperId] && analysisStatus[paperId].taskId === taskId;
                // 清理前端状态
                stopAnalysisLogPolling(taskId);
                // 从队列中移除
                const queueIndex = analysisQueue.indexOf(paperId);
                if (queueIndex !== -1) {
                    analysisQueue.splice(queueIndex, 1);
                }
                // 删除状态
                delete analysisStatus[paperId];
                // 如果正在解读，重置标志
                if (wasAnalyzing) {
                    isAnalyzing = false;
                }
                saveQueuesToStorage();
                updateTaskIndicator();
                if (currentCategoryId) {
                    updatePaperStatusDisplay(paperId);
                } else {
                    renderRecentIfNoCategory();
                }
                hideModal();
                // 继续处理队列
                processAnalysisQueue();
            } else {
                showMessage(result.error || '取消失败', 'error');
            }
        }
    } catch (error) {
        console.error('取消解读失败:', error);
        showMessage('取消失败', 'error');
    }
}

// 从状态中取消解读（通过paperId查找taskId）
async function cancelAnalysisFromStatus(paperId, event) {
    if (event) event.stopPropagation();
    const status = analysisStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('未找到解读任务', 'warning');
        return;
    }
    if (!confirm('确定要终止解读吗？')) {
        return;
    }
    await cancelAnalysis(status.taskId, paperId);
}

// 从队列中取消解读
async function cancelAnalysisFromQueue(paperId, event) {
    if (event) event.stopPropagation();
    const index = analysisQueue.indexOf(paperId);
    if (index === -1) {
        showMessage('论文不在队列中', 'warning');
        return;
    }
    analysisQueue.splice(index, 1);
    saveQueuesToStorage();
    delete analysisStatus[paperId];
    updateAnalysisStatus(paperId, 'error');
    showMessage('已从队列中移除', 'success');
}

// 查看解读结果（右侧信息面板内展示，放宽面板宽度）
async function viewAnalysisResult(paperId, event) {
    if (event) { event.stopPropagation(); }

    try {
        const response = await fetch(`/api/paper/${paperId}/analysis/result`);
        const result = await response.json();
        if (!response.ok || !result.success) {
            showMessage(result.error || '获取结果失败', 'error');
            return;
        }

        const panel = document.querySelector('.info-panel');
        const paperInfoEl = document.getElementById('paper-info');
        if (!panel || !paperInfoEl) return;

        // 加宽面板
        panel.classList.add('wide');

        // 处理图片路径
        let markdownContent = result.content || '';
        const imageRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
        markdownContent = markdownContent.replace(imageRegex, (match, alt, src) => {
            if (!src.startsWith('http') && !src.startsWith('/')) {
                const encodedPath = encodeURIComponent(src);
                return `![${alt}](/api/paper/${paperId}/analysis/image?path=${encodedPath})`;
            }
            return match;
        });

        // 渲染 markdown
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
                highlight: function(code, lang) {
                    if (typeof hljs !== 'undefined' && lang) {
                        try { return hljs.highlight(code, { language: lang }).value; }
                        catch (e) { return hljs.highlightAuto(code).value; }
                    }
                    return code;
                }
            });
        }

        let htmlContent = '';
        if (typeof marked !== 'undefined') {
            htmlContent = marked.parse(markdownContent);
        } else {
            htmlContent = `<pre style="white-space: pre-wrap;">${escapeHtml(markdownContent)}</pre>`;
        }

        // 注入工具栏 + 内容
        paperInfoEl.innerHTML = `
            <div class="paper-info-toolbar">
                <div style="font-weight:600;">AI 解读</div>
                <div>
                    <button class="btn" onclick="closeAnalysisView()"><i class="fas fa-times"></i> 关闭</button>
                </div>
            </div>
            <div class="paper-info-content markdown-viewer">${htmlContent}</div>
        `;

        // 代码高亮
        if (typeof hljs !== 'undefined') {
            paperInfoEl.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
        }

        // 应用样式（若需要）
        if (typeof applyMarkdownStyles === 'function') {
            applyMarkdownStyles();
        }
    } catch (e) {
        console.error('获取结果失败:', e);
        showMessage('获取结果失败', 'error');
    }
}

function closeAnalysisView() {
    const panel = document.querySelector('.info-panel');
    if (panel) panel.classList.remove('wide');
    // 还原当前论文信息
    if (currentPaperId) {
        loadPaperInfo(currentPaperId);
    } else {
        document.getElementById('paper-info').innerHTML = '';
    }
}

// 应用 Markdown 样式
function applyMarkdownStyles() {
    const style = document.createElement('style');
    style.id = 'markdown-viewer-styles';
    if (document.getElementById('markdown-viewer-styles')) {
        return; // 样式已存在
    }
    style.textContent = `
        .markdown-viewer h1, .markdown-viewer h2, .markdown-viewer h3, 
        .markdown-viewer h4, .markdown-viewer h5, .markdown-viewer h6 {
            margin-top: 24px;
            margin-bottom: 16px;
            font-weight: 600;
            line-height: 1.25;
        }
        .markdown-viewer h1 { font-size: 2em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
        .markdown-viewer h2 { font-size: 1.5em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
        .markdown-viewer h3 { font-size: 1.25em; }
        .markdown-viewer h4 { font-size: 1em; }
        .markdown-viewer p { margin-bottom: 16px; line-height: 1.6; }
        .markdown-viewer ul, .markdown-viewer ol { margin-bottom: 16px; padding-left: 2em; }
        .markdown-viewer li { margin-bottom: 0.25em; }
        .markdown-viewer blockquote {
            padding: 0 1em;
            color: #6a737d;
            border-left: 0.25em solid #dfe2e5;
            margin-bottom: 16px;
        }
        .markdown-viewer code {
            padding: 0.2em 0.4em;
            margin: 0;
            font-size: 85%;
            background-color: rgba(27,31,35,0.05);
            border-radius: 3px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }
        .markdown-viewer pre {
            padding: 16px;
            overflow: auto;
            font-size: 85%;
            line-height: 1.45;
            background-color: #f6f8fa;
            border-radius: 6px;
            margin-bottom: 16px;
        }
        .markdown-viewer pre code {
            display: inline;
            padding: 0;
            margin: 0;
            overflow: visible;
            line-height: inherit;
            word-wrap: normal;
            background-color: transparent;
            border: 0;
        }
        .markdown-viewer img {
            max-width: 100%;
            height: auto;
            margin: 16px 0;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .markdown-viewer table {
            border-collapse: collapse;
            margin-bottom: 16px;
            width: 100%;
        }
        .markdown-viewer table th,
        .markdown-viewer table td {
            padding: 6px 13px;
            border: 1px solid #dfe2e5;
        }
        .markdown-viewer table th {
            background-color: #f6f8fa;
            font-weight: 600;
        }
        .markdown-viewer hr {
            height: 0.25em;
            padding: 0;
            margin: 24px 0;
            background-color: #e1e4e8;
            border: 0;
        }
        .markdown-viewer a {
            color: #0366d6;
            text-decoration: none;
        }
        .markdown-viewer a:hover {
            text-decoration: underline;
        }
    `;
    document.head.appendChild(style);
}

// 左侧分类栏宽度调整功能
function setupSidebarResizing() {
    const resizer = document.getElementById('sidebar-resizer');
    const sidebar = document.querySelector('.sidebar');
    
    if (!resizer || !sidebar) return;
    
    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const startX = e.pageX;
        const startWidth = sidebar.offsetWidth;
        
        resizer.classList.add('resizing');
        
        const onMouseMove = (e) => {
            e.preventDefault();
            // 向右拖是正数，向左拖是负数
            const diff = e.pageX - startX;
            const newWidth = Math.max(200, Math.min(window.innerWidth * 0.5, startWidth + diff));
            
            requestAnimationFrame(() => {
                sidebar.style.width = newWidth + 'px';
            });
        };
        
        const onMouseUp = () => {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };
        
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// 右侧面板宽度调整功能
function setupInfoPanelResizing() {
    const resizer = document.getElementById('info-panel-resizer');
    const panel = document.getElementById('info-panel');
    
    if (!resizer || !panel) return;
    
    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        
        const startX = e.pageX;
        const startWidth = panel.offsetWidth;
        
        resizer.classList.add('resizing');
        
        const onMouseMove = (e) => {
            e.preventDefault();
            // 向左拖是正数，向右拖是负数
            const diff = startX - e.pageX;
            const newWidth = Math.max(280, Math.min(window.innerWidth * 0.7, startWidth + diff));
            
            requestAnimationFrame(() => {
                panel.style.width = newWidth + 'px';
            });
        };
        
        const onMouseUp = () => {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };
        
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// 列宽调整功能
function setupColumnResizing() {
    const resizers = document.querySelectorAll('.paper-header-resizer');
    const header = document.querySelector('.paper-header');
    
    resizers.forEach(resizer => {
        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const startX = e.pageX;
            const colIndex = parseInt(resizer.dataset.col);
            
            // 获取当前网格模板
            const style = window.getComputedStyle(header);
            const cols = style.gridTemplateColumns.split(' ');
            const startWidth = parseFloat(cols[colIndex]);
            
            resizer.classList.add('resizing');
            
            // 缓存所有需要更新的元素
            const items = Array.from(document.querySelectorAll('.paper-item'));
            
            const onMouseMove = (e) => {
                e.preventDefault();
                const diff = e.pageX - startX;
                const newWidth = Math.max(60, startWidth + diff);
                
                // 直接更新，不使用中间变量
                cols[colIndex] = newWidth + 'px';
                const newTemplate = cols.join(' ');
                
                // 使用 requestAnimationFrame 优化性能
                requestAnimationFrame(() => {
                    header.style.gridTemplateColumns = newTemplate;
                    // 批量更新所有行
                    items.forEach(item => {
                        item.style.gridTemplateColumns = newTemplate;
                    });
                });
            };
            
            const onMouseUp = () => {
                resizer.classList.remove('resizing');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            };
            
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    });
}

// 取消翻译
function cancelTranslation(paperId, event) {
    if (event) event.stopPropagation();
    
    const status = translationStatus[paperId];
    if (!status) return;
    
    // 从队列中移除
    const queueIndex = translationQueue.indexOf(paperId);
    if (queueIndex > -1) {
        translationQueue.splice(queueIndex, 1);
    }
    
    // 如果正在翻译，停止任务
    if (status.taskId) {
        fetch(`/api/paper/${paperId}/translation/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showMessage('已取消翻译', 'success');
                }
            })
            .catch(err => console.error('取消翻译失败:', err));
    }
    
    // 清理状态
    delete translationStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();
    
    // 刷新显示
    if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderAllPapers();
    }
}

// 取消解读
function cancelAnalysis(paperId, event) {
    if (event) event.stopPropagation();
    
    const status = analysisStatus[paperId];
    if (!status) return;
    
    // 从队列中移除
    const queueIndex = analysisQueue.indexOf(paperId);
    if (queueIndex > -1) {
        analysisQueue.splice(queueIndex, 1);
    }
    
    // 如果正在解读，停止任务
    if (status.taskId) {
        fetch(`/api/paper/${paperId}/analysis/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showMessage('已取消解读', 'success');
                }
            })
            .catch(err => console.error('取消解读失败:', err));
    }
    
    // 清理状态
    delete analysisStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();
    
    // 刷新显示
    if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderAllPapers();
    }
}

