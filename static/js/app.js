// 全局变量
let categories = {};
let currentCategoryId = null;
let currentPaperId = null;
let papers = [];
let expandedCategories = new Set(); // 记录展开的分类
let draggedPaper = null; // 当前拖拽的论文
let draggedCategory = null; // 当前拖拽的目录（单个）
let draggedCategories = []; // 当前拖拽的多个目录（批量拖拽）
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

// 论文多选相关
let isMultiSelectMode = false;
let selectedPaperIds = new Set();
let lastSelectedIndex = null; // 用于 shift 选择

// 目录多选相关
let isCategoryMultiSelectMode = false;
let selectedCategoryIds = new Set();
let lastSelectedCategoryIndex = null; // 用于 shift 选择目录

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
    // 检查当前是否在 Setting 界面
    const settingView = document.getElementById('setting-view');
    const isSettingView = settingView && settingView.style.display !== 'none';
    
    // 检查是否在 Daily arXiv 界面
    const dailyArxivView = document.getElementById('daily-arxiv-view');
    const isDailyArxivView = dailyArxivView && dailyArxivView.style.display !== 'none';
    
    // 获取当前激活的 setting 面板
    let settingPanel = null;
    if (isSettingView) {
        const activeNav = document.querySelector('.setting-nav-item.active');
        settingPanel = activeNav?.dataset.setting || 'overview';
    }
    
    let tabName = 'paper';
    if (isSettingView) tabName = 'setting';
    else if (isDailyArxivView) tabName = 'daily-arxiv';
    
    const state = {
        viewMode: currentViewMode,
        categoryId: currentCategoryId,
        tabName: tabName,
        settingPanel: settingPanel,
        dailyArxivCategory: dailyArxivCurrentCategory,
        dailyArxivDate: dailyArxivCurrentDate,
        // 保存 Daily arXiv 过滤器状态
        dailyArxivFilters: {
            selectedAffiliations: Array.from(dailyArxivSelectedAffiliations),
            selectedCountries: Array.from(dailyArxivSelectedCountries),
            selectedKeywords: Array.from(dailyArxivSelectedKeywords),
            excludedAffiliations: Array.from(dailyArxivExcludedAffiliations),
            excludedCountries: Array.from(dailyArxivExcludedCountries),
            excludedKeywords: Array.from(dailyArxivExcludedKeywords),
            filterFirstAffiliation: dailyArxivFilterFirstAffiliation,
            hideUnknownFirstAffiliation: dailyArxivHideUnknownFirstAffiliation,
            searchQuery: dailyArxivSearchQuery
        }
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
                // 恢复到具体的 setting 面板
                if (state.settingPanel) {
                    switchSettingPanel(state.settingPanel);
                }
                return;
            }
            
            // 恢复 Daily arXiv 视图
            if (state.tabName === 'daily-arxiv') {
                // 恢复选中的分区和日期
                if (state.dailyArxivCategory) {
                    dailyArxivCurrentCategory = state.dailyArxivCategory;
                }
                if (state.dailyArxivDate) {
                    dailyArxivCurrentDate = state.dailyArxivDate;
                }
                // 恢复过滤器状态
                if (state.dailyArxivFilters) {
                    const filters = state.dailyArxivFilters;
                    if (filters.selectedAffiliations) {
                        dailyArxivSelectedAffiliations = new Set(filters.selectedAffiliations);
                    }
                    if (filters.selectedCountries) {
                        dailyArxivSelectedCountries = new Set(filters.selectedCountries);
                    }
                    if (filters.selectedKeywords) {
                        dailyArxivSelectedKeywords = new Set(filters.selectedKeywords);
                    }
                    if (filters.excludedAffiliations) {
                        dailyArxivExcludedAffiliations = new Set(filters.excludedAffiliations);
                    }
                    if (filters.excludedCountries) {
                        dailyArxivExcludedCountries = new Set(filters.excludedCountries);
                    }
                    if (filters.excludedKeywords) {
                        dailyArxivExcludedKeywords = new Set(filters.excludedKeywords);
                    }
                    if (typeof filters.filterFirstAffiliation === 'boolean') {
                        dailyArxivFilterFirstAffiliation = filters.filterFirstAffiliation;
                    }
                    if (typeof filters.hideUnknownFirstAffiliation === 'boolean') {
                        dailyArxivHideUnknownFirstAffiliation = filters.hideUnknownFirstAffiliation;
                    }
                    if (filters.searchQuery) {
                        dailyArxivSearchQuery = filters.searchQuery;
                        // 恢复搜索框的值
                        const searchInput = document.getElementById('daily-arxiv-search');
                        if (searchInput) {
                            searchInput.value = filters.searchQuery;
                        }
                    }
                }
                switchTab('daily-arxiv');
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
                // 先展开到目标分类的路径
                expandToCategoryPath(state.categoryId);
                // 选中目标分类
                const categoryItem = document.querySelector(`.category-item[data-category-id="${state.categoryId}"]`);
                if (categoryItem) {
                    // 手动设置选中状态
                    document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
                    categoryItem.classList.add('selected');
                }
                // 直接加载该分类的论文（确保 await）
                await loadPapers(state.categoryId);
                return;
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

// 展开到目标分类的路径
function expandToCategoryPath(targetCategoryId) {
    // 查找分类的路径（从根到目标）
    function findCategoryPath(node, targetId, path = []) {
        if (node.id === targetId) {
            return path;
        }
        if (node.children) {
            for (const child of node.children) {
                const result = findCategoryPath(child, targetId, [...path, node.id]);
                if (result) return result;
            }
        }
        return null;
    }
    
    const path = findCategoryPath(categories, targetCategoryId, []);
    if (path) {
        // 展开路径上的所有分类
        path.forEach(categoryId => {
            if (categoryId === 'root') return;
            const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
            if (categoryElement) {
                const container = categoryElement.closest('.category-container');
                const toggle = container?.querySelector('.category-toggle');
                const children = container?.querySelector('.category-children');
                
                if (toggle && children) {
                    toggle.classList.add('expanded');
                    children.classList.remove('collapsed');
                    expandedCategories.add(categoryId);
                }
            }
        });
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', async function() {
    await loadCategories();
    setupEventListeners();
    setupNavigation();
    loadAgenticSettings();  // 统一的AI功能配置
    await initImportFeature();
    // 初始化 Daily arXiv
    await initDailyArxiv();
    // 初始化导航栏头像
    updateAvatars();
    // 先更新待读列表计数（在恢复视图状态之前）
    await updateReadingListCount();
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
    // 恢复上次视图状态（此时 readingListCount 已经加载好了）
    await restoreViewState();
    updateTaskIndicator();
});

// 设置事件监听器
function setupEventListeners() {
    // 添加分类按钮 - 根据是否有选中的分类来决定添加位置
    document.getElementById('add-root-category').addEventListener('click', () => {
        if (currentCategoryId && currentCategoryId !== 'root') {
            // 如果有选中的分类，在该分类下添加子分类
            startInlineAddCategory(currentCategoryId);
        } else {
            // 如果没有选中分类，添加根分类
            startInlineAddCategory('root');
        }
    });

    // 上传按钮
    document.getElementById('upload-btn').addEventListener('click', () => {
        // 如果在待读列表界面，也允许上传
        if (currentCategoryId || currentViewMode === 'reading-list') {
            fileInput.click();
        } else {
            showMessage('请先选择一个分类', 'warning');
        }
    });

    // arXiv 导入按钮
    document.getElementById('upload-arxiv-btn').addEventListener('click', () => {
        // 如果在待读列表界面，也允许上传
        if (currentCategoryId || currentViewMode === 'reading-list') {
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
    const batchDelete = document.getElementById('batch-delete');
    const batchCancel = document.getElementById('batch-cancel');
    if (batchAnalyze) batchAnalyze.addEventListener('click', onBatchAnalyze);
    if (batchTranslate) batchTranslate.addEventListener('click', onBatchTranslate);
    if (batchDelete) batchDelete.addEventListener('click', onBatchDelete);
    if (batchCancel) batchCancel.addEventListener('click', (e)=>{ e.stopPropagation(); exitMultiSelectMode(); });

    // Logo 点击返回主界面
    const navbarBrand = document.getElementById('navbar-brand');
    const navbarLogo = document.getElementById('navbar-logo');
    const navbarBrandText = document.getElementById('navbar-brand-text');
    if (navbarBrand) {
        navbarBrand.addEventListener('click', returnToHome);
    }
    if (navbarLogo) {
        navbarLogo.addEventListener('click', returnToHome);
    }
    if (navbarBrandText) {
        navbarBrandText.addEventListener('click', returnToHome);
    }

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
        // 论文多选状态下，点击主要区域空白退出
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
        // 目录多选状态下，点击非目录项区域退出
        if (isCategoryMultiSelectMode) {
            const isCategoryItem = e.target.closest && e.target.closest('.category-item');
            const isCategoryBatchMenu = e.target.closest && e.target.closest('.category-batch-menu');
            // 如果点击的不是目录项，也不是批量操作菜单，则退出多选
            if (!isCategoryItem && !isCategoryBatchMenu) {
                exitCategoryMultiSelectMode();
            }
        }
    });

    // 点击分类树空白区域
    categoryTree.addEventListener('click', (e) => {
        if (e.target === categoryTree) {
            // 如果有多选目录，不清空，保持多选状态
            if (!isCategoryMultiSelectMode) {
                document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
                currentCategoryId = null;
                // 只有当前不在待读列表时才切换到待读列表
                if (currentViewMode !== 'reading-list') {
                    showReadingList();
                    clearPaperInfo();
                }
            }
        }
    });
    
    // 分类树空白区域右键菜单（支持多选目录的批量操作）
    categoryTree.addEventListener('contextmenu', (e) => {
        // 如果点击的是分类树空白区域，且有多选目录，显示批量菜单
        if (e.target === categoryTree && isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            e.preventDefault();
            showCategoryBatchContextMenu(e);
        }
    });
}

// 加载分类数据
async function loadCategories(silent = false) {
    try {
        if (!silent) {
            showLoading(true);
        }
        const response = await fetch('/api/categories');
        categories = await response.json();
        renderCategoryTree();
    } catch (error) {
        console.error('加载分类失败:', error);
        showMessage('加载分类失败', 'error');
    } finally {
        if (!silent) {
            showLoading(false);
        }
    }
}

// 渲染分类树
function renderCategoryTree() {
    categoryTree.innerHTML = '';
    if (categories.children) {
        // 顶层分类排序：置顶 > Others > 按名称
        const sorted = [...categories.children].sort((a, b) => {
            // 置顶目录优先
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            // 然后 Others 目录
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            // 最后按名称排序
            return (a.name || '').localeCompare(b.name || '');
        });
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
    if (category.pinned) {
        div.classList.add('pinned');
    }
    div.dataset.categoryId = category.id;
    div.dataset.level = level; // 存储层级
    div.style.paddingLeft = `${level * 20 + 12}px`;
    div.tabIndex = 0; // 使元素可聚焦，支持键盘事件

    const hasChildren = category.children && category.children.length > 0;
    
    // 获取图标颜色：自定义颜色 > Others灰色 > 默认紫色
    const isOthers = category.name === 'Others';
    const folderColor = category.iconColor || (isOthers ? '#8b949e' : '#7d4a9d');
    
    // 置顶图标
    const pinIcon = category.pinned ? '<i class="fas fa-thumbtack pin-icon"></i>' : '';
    
    div.innerHTML = `
        ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span class="category-toggle-placeholder"></span>'}
        <i class="fas fa-folder" style="margin-right: 6px; color: ${folderColor}; font-size: 12px;"></i>
        <span class="category-name">${category.name}</span>${pinIcon}
        <span class="pdf-count">${category.pdf_count || 0}</span>
    `;

    // 点击事件 - 支持多选
    div.addEventListener('click', (e) => {
        e.stopPropagation();
        
        // Ctrl/Cmd + 点击：切换多选
        if (e.ctrlKey || e.metaKey) {
            handleCategoryMultiSelectClick(e, category.id, div);
            return;
        }
        
        // Shift + 点击：范围选择
        if (e.shiftKey && lastSelectedCategoryIndex !== null) {
            handleCategoryShiftSelect(category.id, div);
            return;
        }
        
        // 普通点击 - 清除多选状态
        if (isCategoryMultiSelectMode) {
            exitCategoryMultiSelectMode();
        }
        
        // 无论点击分类项的哪个位置，都先展开其子目录（若存在）
        const children = container.querySelector('.category-children');
        const toggle = div.querySelector('.category-toggle');
        if (children && children.classList.contains('collapsed')) {
            children.classList.remove('collapsed');
            if (toggle) toggle.classList.add('expanded');
            expandedCategories.add(category.id);
        }
        
        // 若重复点击已选中的分类，则取消选中并显示待读列表
        if (div.classList.contains('selected')) {
            div.classList.remove('selected');
            currentCategoryId = null;
            // 显示待读列表
            showReadingList();
            clearPaperInfo();
            return;
        }
        
        // 记录选择索引
        lastSelectedCategoryIndex = getCategoryIndex(category.id);
        // 选择分类并加载论文（无论是否有子目录，都要显示该目录下的论文）
        // 确保即使展开子目录后，也会加载并显示当前目录的论文
        console.log(`[分类点击] 选择分类: ${category.name} (ID: ${category.id}, Level: ${level})`);
        selectCategory(category.id, category.name, level);
    });

    // 右键菜单
    div.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        // 如果有多选目录，显示批量菜单（无论点击的是哪个目录）
        if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            showCategoryBatchContextMenu(e);
        } else {
            // 如果不在多选中，显示单个目录菜单
            showContextMenu(e, category.id);
        }
    });

    // 键盘事件
    div.addEventListener('keydown', (e) => {
        // 回车键 - 重命名
        if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
            e.preventDefault();
            if (isCategoryMultiSelectMode && selectedCategoryIds.size > 1) {
                showMessage('多选模式下不支持重命名', 'warning');
                return;
            }
            startInlineRename(div, category);
        }
        // Delete/Backspace - 删除
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
                confirmDeleteSelectedCategories();
            } else {
                confirmDeleteCategory(category.id);
            }
        }
        // Escape - 退出多选
        if (e.key === 'Escape') {
            if (isCategoryMultiSelectMode) {
                exitCategoryMultiSelectMode();
            }
        }
    });

    // 添加拖拽功能（使目录可被拖拽）- 支持批量拖拽
    setupCategoryDrag(div, category);
    
    // 添加拖拽目标功能（接收论文或目录的拖放）
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
        // 子分类排序：置顶 > Others > 按名称
        const sortedChildren = [...category.children].sort((a, b) => {
            // 置顶目录优先
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            // 然后 Others 目录
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            // 最后按名称排序
            return (a.name || '').localeCompare(b.name || '');
        });
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
function selectCategory(categoryId, categoryName, level = null) {
    // 移除之前的选中状态
    document.querySelectorAll('.category-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // 添加选中状态
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        categoryElement.classList.add('selected');
        // 如果未传入 level，从元素属性获取
        if (level === null) {
            level = parseInt(categoryElement.dataset.level || '0', 10);
        }
    }

    currentCategoryId = categoryId;
    currentCategoryTitle.textContent = categoryName;
    
    // 检查分类是否有子目录，如果有则递归加载所有子目录的论文
    const category = findCategoryById(categories, categoryId);
    const hasChildren = category && category.children && category.children.length > 0;
    
    // 如果有子目录，递归加载；否则只加载当前目录的论文
    const recursive = hasChildren;
    loadPapers(categoryId, recursive);
    
    // 清空右侧信息面板
    clearPaperInfo();
}

// 加载论文列表
// recursive: 是否递归加载所有子目录的论文（用于一级目录/大目录）
async function loadPapers(categoryId, recursive = false) {
    try {
        // 如果 categoryId 为 null/undefined，调用 renderAllPapers 代替
        if (!categoryId) {
            console.log('[loadPapers] categoryId 为空，调用 renderAllPapers');
            await renderAllPapers();
            return;
        }
        
        currentViewMode = 'category';
        currentCategoryId = categoryId;
        saveCurrentViewState();
        // 隐藏"待读列表"标签
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'none';
        }
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
        
        // 根据 recursive 参数决定 API 路径
        const apiUrl = recursive 
            ? `/api/papers/${categoryId}/recursive`
            : `/api/papers/${categoryId}`;
        
        const response = await fetch(apiUrl);
        if (!response.ok) {
            console.error(`加载论文失败: ${response.status} ${response.statusText}`);
            showMessage('加载论文失败', 'error');
            return;
        }
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
        // 隐藏"待读列表"标签
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'none';
        }
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
        // 显示"待读列表"标签
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'inline-block';
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
        // 更新计数和ID集合（确保在渲染前完成）
        readingListCount = papers.length;
        readingListPaperIds.clear();
        papers.forEach(p => readingListPaperIds.add(p.id));
        // 更新UI显示
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
        // 先尝试移除，看是否需要确认
        const response = await fetch(`/api/reading-list/${paperId}/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: false })
        });
        
        const data = await response.json();
        
        if (data.requires_confirmation) {
            // 需要确认删除，显示弹窗
            const confirmed = confirm(data.message || '该论文还未移动到某个目录，是否要删除论文文件、AI解读和AI翻译？');
            if (confirmed) {
                // 用户确认，删除文件
                const deleteResponse = await fetch(`/api/reading-list/${paperId}/remove`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delete_files: true })
                });
                const deleteData = await deleteResponse.json();
                if (deleteData.success) {
                    showMessage('已从待读列表移除并删除相关文件', 'success');
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
                    showMessage(deleteData.error || '删除失败', 'error');
                }
            }
            // 用户取消，不做任何操作
            return;
        }
        
        if (response.ok && data.success) {
            const message = data.deleted_files 
                ? '已从待读列表移除并删除相关文件' 
                : '已从待读列表移除';
            showMessage(message, 'success');
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
        } else if (!data.requires_confirmation) {
            // 如果不是需要确认的情况，显示错误
            showMessage(data.error || '移除失败', 'error');
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
        // 隐藏"待读列表"标签
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'none';
        }
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
    
    // 标题列（包含阅读时间）
    const readTimeText = getTotalReadTimeText(paper);
    const titleCol = `
        <div class="paper-col-title" title="${paper.title || paper.filename}">
            ${paper.title || paper.filename}${readTimeText}
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
    
    // 待读列
    const isInReadingList = readingListPaperIds.has(paper.id);
    let readingCol = '';
    if (isInReadingList) {
        readingCol = `<div class="paper-col-action"><button class="paper-col-btn reading in-list icon-only" onclick="removeFromReadingList('${paper.id}', event)" title="移出待读列表"><i class="fas fa-times"></i></button></div>`;
    } else {
        readingCol = `<div class="paper-col-action"><button class="paper-col-btn reading icon-only" onclick="addToReadingList('${paper.id}', event)" title="加入待读列表"><i class="fas fa-book-open"></i></button></div>`;
    }
    
    return iconCol + titleCol + dateCol + translateCol + analyzeCol + readingCol;
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
            <div class="paper-header-col">AI 解读<div class="paper-header-resizer" data-col="4"></div></div>
            <div class="paper-header-col">待读</div>
        </div>
    `;
    
    // 添加列宽调整功能
    setupColumnResizing();
    
    sortedPapers.forEach(paper => {
        const div = document.createElement('div');
        const isSelected = selectedPaperIds.has(paper.id);
        // 如果当前选中的论文是这篇，添加 selected 类
        const isCurrentSelected = currentPaperId === paper.id;
        div.className = `paper-item${isSelected ? ' multi-selected' : ''}${isCurrentSelected ? ' selected' : ''}`;
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

        // 双击打开 PDF 阅读器（忽略在按钮上的双击）
        div.addEventListener('dblclick', (e) => {
            // 如果双击的是按钮或按钮内的元素，不触发打开
            if (e.target.closest('button') || e.target.closest('.paper-col-btn')) {
                return;
            }
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
    // 先设置 currentPaperId，这样 renderPapersList 会自动选中
    currentPaperId = paperId;
    
    // 移除之前的选中状态
    document.querySelectorAll('.paper-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // 添加选中状态
    const paperElement = document.querySelector(`.paper-item[data-paper-id="${paperId}"]`);
    if (paperElement) {
        paperElement.classList.add('selected');
    } else {
        // 如果元素不存在，可能是列表还没渲染完成
        // 触发一次重新渲染（如果列表已存在）
        if (papers.length > 0) {
            renderPapersList();
        }
    }

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

// 渲染论文信息（重构版：紧凑+折叠）
function renderPaperInfo(paper) {
    // 辅助函数：格式化arXiv日期（去掉年份重复）
    const formatArxivDate = (dateString) => {
        if (!dateString) return '';
        try {
            const date = new Date(dateString);
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}/${month}/${day}`;
        } catch (e) {
            return dateString;
        }
    };
    
    // 辅助函数：创建可展开的文本块
    const createExpandableTextBlock = (label, content, field, multiline = false, defaultExpanded = false, editable = true) => {
        if (!content) return '';
        
        // 简单判断是否需要展开：检查文本长度或换行数
        // 对于单行文本，如果超过一定长度可能需要展开
        // 对于多行文本，如果超过3行需要展开
        let needsExpand = false;
        if (multiline) {
            const lines = content.split('\n');
            needsExpand = lines.length > 3 || content.length > 200;
        } else {
            // 单行文本，如果太长也可能需要展开
            needsExpand = content.length > 100;
        }
        
        const isCollapsed = needsExpand && !defaultExpanded;
        const collapsedClass = isCollapsed ? 'text-collapsed' : '';
        const editableClass = editable ? 'editable' : '';
        const editableAttr = editable ? 'contenteditable="true"' : '';
        
        return `
            <div class="info-section compact" data-field="${field}">
                <div class="info-header">
                    <span class="info-label">${label}</span>
                </div>
                <div class="info-content">
                    <div class="info-value text-block ${collapsedClass} ${editableClass}" 
                         data-field="${field}" 
                         ${editableAttr}
                         data-full-text="${escapeHtml(content)}"
                         style="${multiline ? 'white-space: pre-wrap;' : ''}">${escapeHtml(content || '')}</div>
                    ${needsExpand ? `
                    <div class="text-expand-btn" onclick="toggleTextExpand(this)" style="display: ${isCollapsed ? 'block' : 'none'}">
                        <i class="fas fa-chevron-down"></i> 展开
                    </div>
                    <div class="text-collapse-btn" onclick="toggleTextCollapse(this)" style="display: ${isCollapsed ? 'none' : 'block'}">
                        <i class="fas fa-chevron-up"></i> 收起
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    };
    
    // HTML转义函数
    const escapeHtml = (text) => {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
    
    paperInfo.innerHTML = `
        <div class="paper-info-container compact-mode">
            <!-- 基本信息 -->
            ${createExpandableTextBlock('标题', paper.title, 'title', false, false, true)}
            ${createExpandableTextBlock('作者', paper.authors, 'authors', false, false, true)}
            ${paper.arxiv_id || paper.arxiv_url ? `
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">URL</span>
                </div>
                <div class="info-content">
                    <div class="info-value">
                        ${paper.arxiv_url ? `
                        <a href="${paper.arxiv_url}" target="_blank" rel="noopener noreferrer" class="paper-url-link">
                            <i class="fas fa-external-link-alt"></i> ${paper.arxiv_url}
                        </a>
                        ` : paper.arxiv_id ? `
                        <a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank" rel="noopener noreferrer" class="paper-url-link">
                            <i class="fas fa-external-link-alt"></i> https://arxiv.org/abs/${paper.arxiv_id}
                        </a>
                        ` : '<span style="color: #999; font-style: italic;">无 URL</span>'}
                    </div>
                </div>
            </div>
            ` : ''}
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">Github</span>
                </div>
                <div class="info-content">
                    <div class="info-value editable" contenteditable="true" data-field="github" data-url-field="true" data-full-text="${escapeHtml(paper.github || '')}">
                        ${paper.github ? `
                            <a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" rel="noopener noreferrer" class="paper-url-link" onclick="event.stopPropagation();">
                                <i class="fab fa-github"></i> ${paper.github}
                            </a>
                        ` : '<span style="color: #999; font-style: italic;">点击添加 GitHub 仓库 URL</span>'}
                    </div>
                </div>
            </div>
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">Homepage</span>
                </div>
                <div class="info-content">
                    <div class="info-value editable" contenteditable="true" data-field="homepage" data-url-field="true" data-full-text="${escapeHtml(paper.homepage || '')}">
                        ${paper.homepage ? `
                            <a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" rel="noopener noreferrer" class="paper-url-link" onclick="event.stopPropagation();">
                                <i class="fas fa-home"></i> ${paper.homepage}
                            </a>
                        ` : '<span style="color: #999; font-style: italic;">点击添加项目主页 URL</span>'}
                    </div>
                </div>
            </div>
            ${createExpandableTextBlock('单位', paper.affiliation, 'affiliation', true, false, true)}
            
            <!-- 时间信息 -->
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">时间</span>
                </div>
                <div class="info-content">
                    <div class="info-value compact-text">
                        ${paper.arxiv_published_date ? `<span><i class="fas fa-clock"></i> arXiv: ${formatArxivDate(paper.arxiv_published_date)}</span>` : ''}
                        ${paper.year && !paper.arxiv_published_date ? `<span><i class="fas fa-calendar"></i> ${paper.year}</span>` : ''}
                    </div>
                </div>
            </div>
            
            <!-- 摘要 -->
            ${createExpandableTextBlock('摘要 (Abstract)', paper.abstract, 'abstract', true, false, true)}
            
            <!-- BibTeX -->
            ${paper.bibtex ? `
            <div class="info-section compact collapsed" data-field="bibtex">
                <div class="info-header" onclick="toggleInfoSection(this)">
                    <span class="info-label">BibTeX</span>
                    <button class="btn-icon" onclick="event.stopPropagation(); copyBibtex('${paper.id}')" title="复制">
                        <i class="fas fa-copy"></i>
                    </button>
                    <i class="fas fa-chevron-down toggle-icon"></i>
                </div>
                <div class="info-content">
                    <pre class="bibtex-content" id="bibtex-${paper.id}">${escapeHtml(paper.bibtex || '')}</pre>
                </div>
            </div>
            ` : ''}
            
            <!-- 备注 -->
            <div class="info-section compact ${paper.notes ? '' : 'collapsed'}" data-field="notes">
                <div class="info-header" onclick="toggleInfoSection(this)">
                    <span class="info-label">备注</span>
                    <i class="fas fa-chevron-down toggle-icon"></i>
                </div>
                <div class="info-content">
                    <div class="info-value text-block editable notes-editable" 
                         data-field="notes" 
                         contenteditable="true"
                         data-full-text="${escapeHtml(paper.notes || '')}"
                         data-placeholder="点击添加备注..."
                         style="white-space: pre-wrap; min-height: 40px;">${escapeHtml(paper.notes || '')}</div>
                </div>
            </div>
            
            <!-- 中文版本 -->
            ${paper.has_chinese_version ? `
            <div class="info-section compact">
                <div class="info-content">
                    <button class="btn btn-primary btn-block" onclick="openChineseVersion('${paper.id}')">
                        <i class="fas fa-language"></i> 打开中文版本
                    </button>
                </div>
            </div>
            ` : ''}
        </div>
    `;

    // 添加编辑事件监听器（只针对可编辑字段）
    paperInfo.querySelectorAll('.editable').forEach(element => {
        // URL 字段特殊处理（github, homepage）
        if (element.dataset.urlField === 'true') {
            // 聚焦时：提取纯文本 URL（如果有链接）
            element.addEventListener('focus', () => {
                const link = element.querySelector('a');
                if (link) {
                    // 提取链接的 href 或文本内容
                    let url = link.href || link.textContent.trim();
                    // 移除协议前缀（如果有）
                    url = url.replace(/^https?:\/\//, '').replace(/^\/\//, '');
                    // 移除图标和多余空格
                    url = url.replace(/^\s*[^\s]+\s+/, '').trim();
                    element.textContent = url;
                } else {
                    // 如果没有链接，检查是否有 placeholder 文本
                    const text = element.textContent.trim();
                    if (text && !text.includes('点击添加')) {
                        element.textContent = text;
                    } else {
                        element.textContent = '';
                    }
                }
            });
            
            // 失去焦点时：保存并重新渲染为链接
            element.addEventListener('blur', () => {
                let content = element.textContent.trim();
                
                // 如果为空或包含 placeholder 文本，保存空字符串
                if (!content || content.includes('点击添加')) {
                    content = '';
                }
                
                // 保存
                savePaperField(paper.id, element.dataset.field, content);
                
                // 重新渲染论文信息以显示链接
                if (currentPaperId) {
                    loadPaperInfo(currentPaperId);
                }
            });
        } else {
            // 普通字段处理
            element.addEventListener('blur', () => {
                // 获取内容并保存
                const content = element.textContent.trim();
                savePaperField(paper.id, element.dataset.field, content);
                
                // 备注栏 placeholder 处理：如果为空，清空内容以显示 placeholder
                if (element.dataset.field === 'notes' && !content) {
                    element.textContent = '';
                }
            });
        }
        
        element.addEventListener('keydown', (e) => {
            const isMultiline = ['abstract', 'notes'].includes(element.dataset.field);
            if (e.key === 'Enter' && !e.shiftKey && !isMultiline) {
                e.preventDefault();
                element.blur();
            }
        });
        
        // 备注栏 placeholder 处理
        if (element.dataset.field === 'notes') {
            // 初始化：如果为空，清空内容以显示 placeholder
            if (!element.textContent.trim()) {
                element.textContent = '';
            }
            
            // 聚焦时：如果为空，确保可以输入
            element.addEventListener('focus', () => {
                // placeholder 会通过 CSS 自动隐藏
            });
        }
    });
    
    // 初始化文本块的展开/折叠状态
    paperInfo.querySelectorAll('.text-block').forEach(block => {
        const fullText = block.dataset.fullText || block.textContent;
        block.dataset.fullText = fullText;
    });
}

// 切换信息区域折叠状态
function toggleInfoSection(header) {
    const section = header.closest('.info-section');
    section.classList.toggle('collapsed');
}

// 切换文本展开/折叠状态
function toggleTextExpand(btn) {
    const content = btn.previousElementSibling;
    if (!content || !content.classList.contains('text-block')) return;
    
    // 展开
    content.classList.remove('text-collapsed');
    btn.style.display = 'none';
    
    // 显示折叠按钮
    const collapseBtn = content.parentElement.querySelector('.text-collapse-btn');
    if (collapseBtn) {
        collapseBtn.style.display = 'block';
    }
}

// 折叠文本
function toggleTextCollapse(btn) {
    const content = btn.previousElementSibling.previousElementSibling;
    if (!content || !content.classList.contains('text-block')) return;
    
    content.classList.add('text-collapsed');
    btn.style.display = 'none';
    
    // 显示展开按钮
    const expandBtn = content.parentElement.querySelector('.text-expand-btn');
    if (expandBtn) {
        expandBtn.style.display = 'block';
    }
}

// 复制 BibTeX
function copyBibtex(paperId) {
    const bibtexElem = document.getElementById(`bibtex-${paperId}`);
    if (bibtexElem) {
        const text = bibtexElem.textContent;
        navigator.clipboard.writeText(text).then(() => {
            showMessage('BibTeX 已复制到剪贴板', 'success', 2000);
        }).catch(err => {
            console.error('复制失败:', err);
            showMessage('复制失败', 'error');
        });
    }
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
        
        // 检查是否拖拽的是分类（单个或批量）
        const isDraggingCategory = draggedCategory || draggedCategories.length > 0;
        
        if (isDraggingCategory) {
            // 如果拖拽的是分类，检查是否在某个category-item上
            const categoryItem = e.target.closest('.category-item');
            if (!categoryItem) {
                // 在空白区域，允许移动到根目录
                e.dataTransfer.dropEffect = 'move';
                categoryTree.classList.add('drag-over-root');
                return;
            }
        }
        
        // 默认处理文件拖拽
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
        // 检查是否真的离开了categoryTree（而不是进入子元素）
        const rect = categoryTree.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;
        
        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
            categoryTree.classList.remove('drag-over-root');
        }
    });

    categoryTree.addEventListener('drop', (e) => {
        preventDefaults(e);
        
        // 检查是否拖拽的是分类（单个或批量）
        const isDraggingCategory = draggedCategory || draggedCategories.length > 0;
        
        if (isDraggingCategory) {
            const categoryItem = e.target.closest('.category-item');
            
            // 如果不在任何category-item上，说明拖到了空白区域，移动到根目录
            if (!categoryItem) {
                categoryTree.classList.remove('drag-over-root');
                
                // 批量移动
                if (draggedCategories.length > 0) {
                    console.log(`批量放置 ${draggedCategories.length} 个目录到根目录`);
                    moveCategories(draggedCategories.map(c => c.id), 'root');
                }
                // 单个移动
                else if (draggedCategory) {
                    console.log('放置目录到根目录:', draggedCategory.name);
                    moveCategory(draggedCategory.id, 'root');
                }
                return;
            }
            // 如果在category-item上，由setupCategoryDropTarget处理
            return;
        }
        
        // 处理文件拖拽
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
        // 支持待读列表的拖拽上传
        if (currentViewMode === 'reading-list' || currentCategoryId) {
            papersList.classList.add('drag-over');
        }
    });

    papersList.addEventListener('dragleave', (e) => {
        papersList.classList.remove('drag-over');
    });

    papersList.addEventListener('drop', (e) => {
        preventDefaults(e);
        papersList.classList.remove('drag-over');
        // 支持待读列表的拖拽上传
        if (currentViewMode === 'reading-list') {
            handleFilesWithCategory(e.dataTransfer.files, 'reading_list_temp');
        } else if (currentCategoryId) {
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
            // 支持待读列表的拖拽上传
            if (currentViewMode === 'reading-list') {
                handleFilesWithCategory(e.dataTransfer.files, 'reading_list_temp');
            } else if (currentCategoryId) {
                handleFilesWithCategory(e.dataTransfer.files, currentCategoryId);
            } else {
                showMessage('请先选择一个分类', 'warning');
            }
        }, false);
        uploadZone.addEventListener('click', () => {
            // 支持待读列表的点击上传
            if (currentViewMode === 'reading-list') {
                fileInput.click();
            } else if (currentCategoryId) {
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
    // 支持待读列表的文件选择上传
    if (currentViewMode === 'reading-list') {
        handleFilesWithCategory(files, 'reading_list_temp');
    } else if (currentCategoryId) {
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

    // 不再前端解析，全部交给后端处理（使用字体大小 + arXiv 搜索）
    // 这样更准确，且不阻塞用户操作
    
    try {
        // 异步上传，完全静默处理，不显示任何提示
        fetch('/api/upload', {
            method: 'POST',
            body: formData
        }).then(response => response.json())
        .then(result => {
            if (result.success) {
                // 静默刷新，不显示成功提示
                // 如果上传到当前选中的分类，立即刷新列表（显示占位符）
                if (currentCategoryId === categoryId) {
                    loadPapers(currentCategoryId);
                }
                // 如果上传到待读列表，刷新待读列表
                if (categoryId === 'reading_list_temp' && currentViewMode === 'reading-list') {
                    showReadingList();
                }
                // 同步更新分类计数和待读列表计数
                updateCategoriesData();
                renderCategoryTreeWithState();
                updateReadingListCount();
                
                // 启动后台轮询，检查元数据是否更新完成
                if (result.paper && result.paper.id) {
                    // 使用占位符 paper 数据作为初始快照
                    const initialSnapshot = {
                        title: result.paper.title || '',
                        authors: result.paper.authors || '',
                        abstract: result.paper.abstract || '',
                        bibtex: result.paper.bibtex || '',
                        arxiv_id: result.paper.arxiv_id || '',
                    };
                    startPollingPaperUpdate(result.paper.id, categoryId, initialSnapshot);
                }
            } else {
                // 只在失败时显示错误
                showMessage(`上传失败: ${result.error}`, 'error');
            }
        }).catch(error => {
            console.error('上传文件失败:', error);
            showMessage(`${file.name} 上传失败`, 'error');
        });
        
        // 立即返回，不阻塞用户操作
        return;
        
    } catch (error) {
        console.error('上传请求失败:', error);
        showMessage('上传失败', 'error');
    }
}

// 轮询检查论文更新（用于后台元数据处理）
// initialSnapshot 可以是初始快照对象或初始标题字符串（向后兼容）
function startPollingPaperUpdate(paperId, categoryId, initialSnapshotOrTitle, maxAttempts = 20) {
    let attempts = 0;
    let previousSnapshot = null; // 保存初始快照用于比较
    
    // 处理参数：如果是字符串，转换为快照对象；如果是对象，直接使用
    if (typeof initialSnapshotOrTitle === 'string') {
        // 向后兼容：如果传入的是字符串（标题），创建快照对象
        previousSnapshot = {
            title: initialSnapshotOrTitle || '',
            authors: '',
            abstract: '',
            bibtex: '',
            arxiv_id: '',
        };
        console.log(`[轮询] 开始轮询论文更新: ${paperId}, 初始标题: ${initialSnapshotOrTitle}`);
    } else {
        // 如果传入的是快照对象，直接使用
        previousSnapshot = initialSnapshotOrTitle || {
            title: '',
            authors: '',
            abstract: '',
            bibtex: '',
            arxiv_id: '',
        };
        console.log(`[轮询] 开始轮询论文更新: ${paperId}, 初始快照: title="${previousSnapshot.title}"`);
    }
    
    const checkUpdate = async () => {
        try {
            attempts++;
            
            // 获取论文最新信息
            const response = await fetch(`/api/paper/${paperId}`);
            if (!response.ok) {
                console.log(`[轮询] 论文 ${paperId} 不存在或已删除`);
                return; // 停止轮询
            }
            
            const paper = await response.json();
            const currentTitle = paper.title || '';
            
            // 创建当前快照用于比较
            const currentSnapshot = {
                title: paper.title || '',
                authors: paper.authors || '',
                abstract: paper.abstract || '',
                bibtex: paper.bibtex || '',
                arxiv_id: paper.arxiv_id || '',
            };
            
            // 检查关键字段是否有变化（不仅仅是 title）
            const hasChanged = 
                currentSnapshot.title !== previousSnapshot.title ||
                currentSnapshot.authors !== previousSnapshot.authors ||
                currentSnapshot.abstract !== previousSnapshot.abstract ||
                currentSnapshot.bibtex !== previousSnapshot.bibtex ||
                currentSnapshot.arxiv_id !== previousSnapshot.arxiv_id;
            
            console.log(`[轮询] 第 ${attempts} 次检查: title="${currentTitle}"`);
            
            if (hasChanged) {
                console.log(`[轮询] ✅ 检测到论文更新!`);
                if (currentSnapshot.title !== previousSnapshot.title) {
                    console.log(`[轮询]    标题: "${previousSnapshot.title}" → "${currentSnapshot.title}"`);
                }
                if (currentSnapshot.authors !== previousSnapshot.authors) {
                    console.log(`[轮询]    作者: "${previousSnapshot.authors}" → "${currentSnapshot.authors}"`);
                }
                if (currentSnapshot.abstract !== previousSnapshot.abstract) {
                    console.log(`[轮询]    摘要: 已更新`);
                }
                if (currentSnapshot.bibtex !== previousSnapshot.bibtex) {
                    console.log(`[轮询]    BibTeX: 已更新`);
                }
                
                // 如果当前还在同一个分类（或都是全部论文视图），刷新列表
                if (currentCategoryId === categoryId) {
                    console.log(`[轮询] 刷新论文列表...`);
                    if (currentCategoryId) {
                        await loadPapers(currentCategoryId);
                    } else {
                        // 如果 categoryId 为 null，说明是在"所有论文"视图
                        await renderAllPapers();
                    }
                    
                    // 如果当前选中的就是这个论文，刷新详情
                    if (currentPaperId === paperId) {
                        console.log(`[轮询] 刷新论文详情...`);
                        renderPaperInfo(paper);
                    }
                } else {
                    // 即使不在当前分类，如果选中了这个论文，也要刷新详情
                    if (currentPaperId === paperId) {
                        console.log(`[轮询] 刷新论文详情（跨分类）...`);
                        renderPaperInfo(paper);
                    }
                }
                
                // 更新分类树（文件名可能变了）
                await updateCategoriesData();
                renderCategoryTreeWithState();
                
                console.log(`[轮询] 更新完成，停止轮询`);
                return; // 更新完成，停止轮询
            }
            
            // 如果还没达到最大尝试次数，继续轮询
            if (attempts < maxAttempts) {
                setTimeout(checkUpdate, 2000); // 2秒后再次检查
            } else {
                console.log(`[轮询] ⚠️ 已达到最大尝试次数 (${maxAttempts})，停止轮询`);
            }
            
        } catch (error) {
            console.error('[轮询] ❌ 检查更新失败:', error);
            // 出错也继续尝试
            if (attempts < maxAttempts) {
                setTimeout(checkUpdate, 2000);
            }
        }
    };
    
    // 延迟1秒后开始第一次检查（给后台处理一些时间，但不要太长）
    // 对于上传场景，后台可能很快完成，所以延迟不要太长
    setTimeout(checkUpdate, 1000);
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
    modal.classList.add('show');
}

// 隐藏模态框
function hideModal() {
    modal.classList.remove('show');
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
// 导出分类的 BibTeX
async function exportCategoryBibtex(categoryId) {
    try {
        showMessage('正在导出 BibTeX...', 'info', 2000);
        
        const response = await fetch(`/api/categories/${categoryId}/export-bibtex`, {
            method: 'GET'
        });
        
        if (!response.ok) {
            const error = await response.json();
            showMessage(`导出失败: ${error.error}`, 'error');
            return;
        }
        
        // 获取文件名（从 Content-Disposition 头或使用默认名称）
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'export.bib';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }
        
        // 获取文件内容
        const blob = await response.blob();
        
        // 创建下载链接
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        
        // 清理
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        showMessage('BibTeX 导出成功', 'success');
    } catch (error) {
        console.error('导出 BibTeX 失败:', error);
        showMessage('导出失败，请稍后重试', 'error');
    }
}

async function copyCategoryArxivUrls(categoryId) {
    try {
        showMessage('正在获取 arXiv URL...', 'info', 2000);
        
        const response = await fetch(`/api/categories/${categoryId}/copy-arxiv-urls`, {
            method: 'GET'
        });
        
        const result = await response.json();
        
        if (!response.ok || !result.success) {
            showMessage(`获取失败: ${result.error || '未知错误'}`, 'error');
            return;
        }
        
        // 复制到剪贴板
        const text = result.text;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            showMessage(`已复制 ${result.count} 个 arXiv URL 到剪贴板`, 'success');
        } else {
            // 降级方案：使用传统的复制方法
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                showMessage(`已复制 ${result.count} 个 arXiv URL 到剪贴板`, 'success');
            } catch (err) {
                showMessage('复制失败，请手动复制', 'error');
                console.error('复制失败:', err);
            }
            document.body.removeChild(textarea);
        }
    } catch (error) {
        console.error('复制 arXiv URL 失败:', error);
        showMessage('复制失败，请稍后重试', 'error');
    }
}

async function deleteCategory(categoryId) {
    try {
        const response = await fetch(`/api/categories/${categoryId}`, {
            method: 'DELETE'
        });

        const result = await response.json();
        
        if (result.success) {
            // 如果删除的是当前选中的分类，显示待读列表
            if (currentCategoryId === categoryId) {
                currentCategoryId = null;
                showReadingList();
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
        startInlineAddCategory(categoryId);
        contextMenu.style.display = 'none';
    });

    // 置顶/取消置顶
    document.getElementById('toggle-pin-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        togglePinCategory(categoryId);
        contextMenu.style.display = 'none';
    });

    // 颜色选择
    document.querySelectorAll('.color-submenu .color-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            const categoryId = contextMenu.dataset.categoryId;
            const color = option.dataset.color;
            changeCategoryColor(categoryId, color);
            contextMenu.style.display = 'none';
        });
    });

    document.getElementById('export-bibtex').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        exportCategoryBibtex(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('copy-arxiv-urls').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        copyCategoryArxivUrls(categoryId);
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
    
    // 更新置顶按钮文本
    const category = findCategoryById(categories, categoryId);
    const pinText = document.getElementById('pin-text');
    if (pinText && category) {
        pinText.textContent = category.pinned ? '取消置顶' : '置顶';
        // 更新图标
        const pinIcon = document.querySelector('#toggle-pin-category i');
        if (pinIcon) {
            pinIcon.className = category.pinned ? 'fas fa-thumbtack' : 'far fa-thumbtack';
            pinIcon.style.color = category.pinned ? '#ffc107' : '#666';
        }
    }
    
    // 更新颜色选择中的选中状态
    const currentColor = category?.iconColor || '#7d4a9d';
    document.querySelectorAll('.color-submenu .color-option').forEach(option => {
        option.classList.toggle('selected', option.dataset.color === currentColor);
    });
    
    contextMenu.style.display = 'block';
    contextMenu.style.left = e.pageX + 'px';
    contextMenu.style.top = e.pageY + 'px';
}

// 切换目录置顶状态
async function togglePinCategory(categoryId) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;
    
    const newPinned = !category.pinned;
    const originalPinned = category.pinned;
    
    // 立即更新UI（乐观更新）
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        // 更新pinned类
        if (newPinned) {
            categoryElement.classList.add('pinned');
        } else {
            categoryElement.classList.remove('pinned');
        }
        
        // 更新置顶图标
        let pinIcon = categoryElement.querySelector('.pin-icon');
        if (newPinned) {
            if (!pinIcon) {
                // 如果还没有图标，添加一个
                const categoryName = categoryElement.querySelector('.category-name');
                if (categoryName) {
                    pinIcon = document.createElement('i');
                    pinIcon.className = 'fas fa-thumbtack pin-icon';
                    categoryName.insertAdjacentElement('afterend', pinIcon);
                }
            } else {
                pinIcon.className = 'fas fa-thumbtack pin-icon';
            }
        } else {
            if (pinIcon) {
                pinIcon.remove();
            }
        }
        
        // 重新排序（将置顶的移到前面）
        const container = categoryElement.closest('.category-container');
        if (container) {
            const parent = container.parentElement;
            if (parent && (parent.classList.contains('category-children') || parent.id === 'category-tree')) {
                // 获取所有兄弟容器（排除当前容器）
                const siblings = Array.from(parent.children).filter(child => 
                    child.classList.contains('category-container') && child !== container
                );
                
                if (newPinned) {
                    // 置顶：找到第一个非置顶的容器，插入到它前面
                    let insertBefore = null;
                    for (const sibling of siblings) {
                        const siblingItem = sibling.querySelector('.category-item');
                        if (siblingItem && !siblingItem.classList.contains('pinned')) {
                            insertBefore = sibling;
                            break;
                        }
                    }
                    // 插入到正确位置
                    if (insertBefore) {
                        parent.insertBefore(container, insertBefore);
                    } else {
                        // 如果没有非置顶的，插入到最前面
                        const firstContainer = siblings.find(s => {
                            const item = s.querySelector('.category-item');
                            return item && item.classList.contains('pinned');
                        });
                        if (firstContainer) {
                            parent.insertBefore(container, firstContainer);
                        } else {
                            parent.insertBefore(container, parent.firstChild);
                        }
                    }
                } else {
                    // 取消置顶：找到最后一个置顶的容器，插入到它后面
                    let insertAfter = null;
                    for (let i = siblings.length - 1; i >= 0; i--) {
                        const siblingItem = siblings[i].querySelector('.category-item');
                        if (siblingItem && siblingItem.classList.contains('pinned')) {
                            insertAfter = siblings[i];
                            break;
                        }
                    }
                    // 插入到正确位置
                    if (insertAfter) {
                        parent.insertBefore(container, insertAfter.nextSibling);
                    } else {
                        // 如果没有置顶的，插入到非置顶的第一个位置
                        let insertBefore = null;
                        for (const sibling of siblings) {
                            const siblingItem = sibling.querySelector('.category-item');
                            if (siblingItem && !siblingItem.classList.contains('pinned')) {
                                insertBefore = sibling;
                                break;
                            }
                        }
                        if (insertBefore) {
                            parent.insertBefore(container, insertBefore);
                        } else {
                            parent.appendChild(container);
                        }
                    }
                }
            }
        }
    }
    
    // 更新本地数据
    category.pinned = newPinned;
    
    // 更新右键菜单中的按钮状态（如果菜单正在显示）
    const contextMenu = document.getElementById('context-menu');
    if (contextMenu && contextMenu.dataset.categoryId === categoryId) {
        const pinText = document.getElementById('pin-text');
        if (pinText) {
            pinText.textContent = newPinned ? '取消置顶' : '置顶';
        }
        const pinIcon = document.querySelector('#toggle-pin-category i');
        if (pinIcon) {
            pinIcon.className = newPinned ? 'fas fa-thumbtack' : 'far fa-thumbtack';
            pinIcon.style.color = newPinned ? '#ffc107' : '#666';
        }
    }
    
    // 显示成功消息
    showMessage(newPinned ? '已置顶' : '已取消置顶', 'success');
    
    // 异步保存到服务器（不阻塞UI）
    fetch(`/api/categories/${categoryId}/pin`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: newPinned })
    })
    .then(response => response.json())
    .then(result => {
        if (!result.success) {
            // 如果失败，恢复原状态
            category.pinned = originalPinned;
            // 重新渲染以恢复状态
            renderCategoryTreeWithState();
            showMessage('操作失败', 'error');
        }
    })
    .catch(e => {
        console.error('置顶操作失败:', e);
        // 如果失败，恢复原状态
        category.pinned = originalPinned;
        // 重新渲染以恢复状态
        renderCategoryTreeWithState();
        showMessage('操作失败', 'error');
    });
}

// 更换目录图标颜色
async function changeCategoryColor(categoryId, color) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;
    
    // 保存原始颜色（用于失败时恢复）
    const isOthers = category.name === 'Others';
    const originalColor = category.iconColor || (isOthers ? '#8b949e' : '#7d4a9d');
    
    // 立即更新UI（乐观更新）
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        const folderIcon = categoryElement.querySelector('.fa-folder');
        if (folderIcon) {
            folderIcon.style.color = color;
        }
    }
    
    // 更新本地数据
    category.iconColor = color;
    
    // 异步更新服务器（不阻塞UI）
    fetch(`/api/categories/${categoryId}/color`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ color: color })
    })
    .then(response => response.json())
    .then(result => {
        if (!result.success) {
            // 如果失败，恢复原颜色
            if (categoryElement) {
                const folderIcon = categoryElement.querySelector('.fa-folder');
                if (folderIcon) {
                    folderIcon.style.color = originalColor;
                }
            }
            category.iconColor = originalColor;
            showMessage('更新失败', 'error');
        }
    })
    .catch(e => {
        console.error('更新颜色失败:', e);
        // 如果失败，恢复原颜色
        if (categoryElement) {
            const folderIcon = categoryElement.querySelector('.fa-folder');
            if (folderIcon) {
                folderIcon.style.color = originalColor;
            }
        }
        category.iconColor = originalColor;
        showMessage('更新失败', 'error');
    });
}

// 设置论文右键菜单
function setupPaperContextMenu() {
    document.getElementById('paper-refresh-metadata').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        refreshPaperMetadata(paperId);
        paperContextMenu.style.display = 'none';
    });
    
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

// 显示消息（支持自定义持续时间）
function showMessage(message, type = 'info', duration = 3000) {
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
    
    // 指定时间后自动移除
    setTimeout(() => {
        messageDiv.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.parentNode.removeChild(messageDiv);
            }
        }, 300);
    }, duration);
}

// 设置论文拖拽功能
function setupPaperDrag(paperElement, paper) {
    paperElement.draggable = true;
    
    paperElement.addEventListener('dragstart', (e) => {
        console.log('开始拖拽论文:', paper.title || paper.filename);
        draggedPaper = paper;
        
        // 延迟添加dragging类，避免影响拖拽图像
        setTimeout(() => {
            paperElement.classList.add('dragging');
        }, 0);
        
        // 设置拖拽数据
        e.dataTransfer.setData('text/plain', paper.id);
        e.dataTransfer.effectAllowed = 'move';
        
        // 创建自定义拖拽图像（半透明的论文条）
        const dragImage = paperElement.cloneNode(true);
        dragImage.style.position = 'absolute';
        dragImage.style.top = '-9999px';
        dragImage.style.left = '-9999px';
        dragImage.style.width = paperElement.offsetWidth + 'px';
        dragImage.style.opacity = '0.7';
        dragImage.style.background = 'white';
        dragImage.style.border = '2px solid #007bff';
        dragImage.style.borderRadius = '4px';
        dragImage.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
        dragImage.style.padding = '6px 10px';
        dragImage.style.pointerEvents = 'none';
        document.body.appendChild(dragImage);
        
        // 计算鼠标相对于元素的位置（从左上角开始）
        const rect = paperElement.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;
        
        // 使用克隆的元素作为拖拽图像，偏移量为鼠标点击位置
        e.dataTransfer.setDragImage(dragImage, offsetX, offsetY);
        
        // 拖拽结束后移除克隆的元素
        setTimeout(() => {
            if (document.body.contains(dragImage)) {
                document.body.removeChild(dragImage);
            }
        }, 0);
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

// 设置目录拖拽功能（使目录可被拖拽）- 支持批量拖拽
function setupCategoryDrag(categoryElement, category) {
    // 不允许拖拽根目录
    if (category.id === 'root') return;
    
    categoryElement.draggable = true;
    
    categoryElement.addEventListener('dragstart', (e) => {
        // 如果正在拖拽论文，不处理
        if (draggedPaper) {
            e.preventDefault();
            return;
        }
        
        // 检查是否在多选模式下
        if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            // 批量拖拽：拖拽所有选中的目录
            draggedCategories = [];
            selectedCategoryIds.forEach(catId => {
                const cat = findCategoryById(categories, catId);
                if (cat && cat.id !== 'root') {
                    draggedCategories.push(cat);
                }
            });
            
            if (draggedCategories.length === 0) {
                e.preventDefault();
                return;
            }
            
            console.log(`开始批量拖拽 ${draggedCategories.length} 个目录`);
            draggedCategory = null; // 清空单个拖拽
            
            // 为所有选中的目录添加 dragging 样式
            selectedCategoryIds.forEach(catId => {
                const el = document.querySelector(`[data-category-id="${catId}"]`);
                if (el) {
                    setTimeout(() => el.classList.add('dragging'), 0);
                }
            });
        } else {
            // 单个拖拽
            console.log('开始拖拽目录:', category.name);
            draggedCategory = category;
            draggedCategories = []; // 清空批量拖拽
            
            // 延迟添加 dragging 类
            setTimeout(() => {
                categoryElement.classList.add('dragging');
            }, 0);
        }
        
        // 阻止事件冒泡，避免触发父元素的拖拽
        e.stopPropagation();
        
        // 设置拖拽数据
        const categoryIds = draggedCategories.length > 0 
            ? draggedCategories.map(c => c.id).join(',')
            : category.id;
        e.dataTransfer.setData('text/plain', `category:${categoryIds}`);
        e.dataTransfer.effectAllowed = 'move';
        
        // 创建自定义拖拽图像
        const dragImage = document.createElement('div');
        dragImage.style.position = 'absolute';
        dragImage.style.top = '-9999px';
        dragImage.style.left = '-9999px';
        dragImage.style.padding = '8px 12px';
        dragImage.style.background = '#f8f9fa';
            dragImage.style.border = '2px solid #7d4a9d';
        dragImage.style.borderRadius = '6px';
        dragImage.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
        dragImage.style.fontSize = '13px';
        dragImage.style.fontWeight = '500';
        dragImage.style.color = '#333';
        dragImage.style.display = 'flex';
        dragImage.style.alignItems = 'center';
        dragImage.style.gap = '6px';
        
        if (draggedCategories.length > 0) {
            dragImage.innerHTML = `<i class="fas fa-folder" style="color: #7d4a9d;"></i> ${draggedCategories.length} 个目录`;
            } else {
            dragImage.innerHTML = `<i class="fas fa-folder" style="color: #7d4a9d;"></i> ${category.name}`;
        }
        
        document.body.appendChild(dragImage);
        
        const rect = categoryElement.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;
        
        e.dataTransfer.setDragImage(dragImage, offsetX, offsetY);
        
        setTimeout(() => {
            if (document.body.contains(dragImage)) {
                document.body.removeChild(dragImage);
            }
        }, 0);
    });
    
    categoryElement.addEventListener('dragend', (e) => {
        console.log('结束拖拽目录');
        categoryElement.classList.remove('dragging');
        
        // 清理所有拖拽状态
        document.querySelectorAll('.category-item.dragging, .category-item.drag-over, .category-item.drag-target').forEach(el => {
            el.classList.remove('dragging', 'drag-over', 'drag-target');
        });
        
        // 清除根目录的拖拽样式
        categoryTree.classList.remove('drag-over-root');
        
        // 清空拖拽数据
        draggedCategory = null;
        draggedCategories = [];
        
        // 清理定时器
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
    });
}

// 设置分类拖拽目标功能（接收论文或目录的拖放）
function setupCategoryDropTarget(categoryElement, category) {
    const container = categoryElement.closest('.category-container');

    function onDragOver(e) {
        // 必须preventDefault才能允许drop
        e.preventDefault();
        e.stopPropagation();
        
        // 检查是否有拖拽的论文或目录（单个或批量）
        if (!draggedPaper && !draggedCategory && draggedCategories.length === 0) {
            return;
        }
        
        // 如果拖拽的是目录（单个或批量），不能拖到自己或自己的子目录
        const categoriesToCheck = draggedCategories.length > 0 ? draggedCategories : (draggedCategory ? [draggedCategory] : []);
        
        for (const draggedCat of categoriesToCheck) {
            if (draggedCat.id === category.id) {
                e.dataTransfer.dropEffect = 'none';
                return;
            }
            // 检查是否是子目录（简单检查：目标是否在拖拽元素的 DOM 子树中）
            const draggedElement = document.querySelector(`[data-category-id="${draggedCat.id}"]`);
            if (draggedElement) {
                const draggedContainer = draggedElement.closest('.category-container');
                if (draggedContainer && draggedContainer.contains(categoryElement)) {
                    e.dataTransfer.dropEffect = 'none';
                    return;
                }
            }
        }
        
        e.dataTransfer.dropEffect = 'move';
        
        // 清除根目录的拖拽样式（如果存在）
        categoryTree.classList.remove('drag-over-root');
        
        // 添加拖拽悬停样式
        categoryElement.classList.add('drag-over');
        
        // 如果有子分类且未展开，设置自动展开
        if (container) {
            const children = container.querySelector('.category-children');
            const toggle = categoryElement.querySelector('.category-toggle');
            
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
    }

    categoryElement.addEventListener('dragenter', (e) => {
        e.preventDefault();
        e.stopPropagation();
        onDragOver(e);
    });
    
    categoryElement.addEventListener('dragover', onDragOver);
    
    categoryElement.addEventListener('dragleave', (e) => {
        if (!draggedPaper && !draggedCategory && draggedCategories.length === 0) return;
        
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
        e.preventDefault();
        e.stopPropagation();
        
        categoryElement.classList.remove('drag-over');
        categoryElement.classList.add('drag-target');
        
        // 清除根目录的拖拽样式
        categoryTree.classList.remove('drag-over-root');
        
        // 清除定时器
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
        
        // 处理论文拖放
        if (draggedPaper) {
            console.log('放置论文到分类:', category.name, '论文:', draggedPaper.title || draggedPaper.filename);
            movePaper(draggedPaper.id, category.id);
        }
        // 处理目录拖放（批量或单个）
        else if (draggedCategories.length > 0) {
            console.log(`批量放置 ${draggedCategories.length} 个目录到分类:`, category.name);
            moveCategories(draggedCategories.map(c => c.id), category.id);
        }
        else if (draggedCategory) {
            console.log('放置目录到分类:', category.name, '目录:', draggedCategory.name);
            moveCategory(draggedCategory.id, category.id);
        }
        else {
            console.log('drop时没有拖拽的论文或目录');
        }
        
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
            // 移动成功，不显示提示
            console.log('论文移动成功');
            
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

// 移动目录到新的父目录
async function moveCategory(categoryId, targetParentId) {
    try {
        const response = await fetch(`/api/categories/${categoryId}/move`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                target_parent_id: targetParentId
            })
        });

        const result = await response.json();
        
        if (result.success) {
            console.log('目录移动成功:', result.old_path, '->', result.new_path);
            showMessage('目录移动成功', 'success');
            
            // 更新本地数据并重新渲染分类树
            await updateCategoriesData();
            await renderCategoryTreeWithState();
            
            // 如果当前选中的分类被移动了，更新选中状态
            if (currentCategoryId === categoryId) {
                // 重新选中该分类
                const categoryItem = document.querySelector(`.category-item[data-category-id="${categoryId}"]`);
                if (categoryItem) {
                    categoryItem.classList.add('selected');
                }
            }
        } else {
            showMessage(`移动失败: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('移动目录失败:', error);
        showMessage('移动目录失败', 'error');
    }
}

// 批量移动多个目录到新的父目录
async function moveCategories(categoryIds, targetParentId) {
    if (!categoryIds || categoryIds.length === 0) return;
    
    let successCount = 0;
    let failCount = 0;
    const errors = [];
    
    // 逐个移动目录
    for (const categoryId of categoryIds) {
        try {
            const response = await fetch(`/api/categories/${categoryId}/move`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    target_parent_id: targetParentId
                })
            });

            const result = await response.json();
            
            if (result.success) {
                successCount++;
                console.log(`目录移动成功: ${categoryId}`);
            } else {
                failCount++;
                errors.push(result.error || '未知错误');
            }
        } catch (error) {
            failCount++;
            errors.push(error.message || '网络错误');
            console.error(`移动目录失败 ${categoryId}:`, error);
        }
    }
    
    // 显示结果
    if (successCount > 0) {
        if (failCount === 0) {
            showMessage(`成功移动 ${successCount} 个目录`, 'success');
        } else {
            showMessage(`成功移动 ${successCount} 个目录，失败 ${failCount} 个`, 'warning');
        }
    } else {
        showMessage(`移动失败: ${errors[0] || '未知错误'}`, 'error');
    }
    
    // 更新本地数据并重新渲染分类树
    if (successCount > 0) {
        await updateCategoriesData();
        await renderCategoryTreeWithState();
    }
    
    // 无论成功与否，都退出多选模式（因为已经完成操作）
    if (isCategoryMultiSelectMode) {
        exitCategoryMultiSelectMode();
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
                // 如果在待读列表界面，使用临时目录；否则使用当前分类
                const isInReadingList = currentViewMode === 'reading-list';
                const requestBody = {
                    arxiv_url: arxivUrl,
                };
                
                if (isInReadingList) {
                    requestBody.use_temp_dir = true;
                } else {
                    requestBody.category_id = currentCategoryId;
                }
                
                const response = await fetch('/api/upload/arxiv', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody)
                });
                const result = await response.json();
                if (response.ok && result.success) {
                    showMessage('论文导入成功', 'success');
                    // 先更新待读列表计数和ID集合，确保状态同步
                    await updateReadingListCount();
                    if (isInReadingList) {
                        // 如果在待读列表界面，刷新待读列表
                        await showReadingList();
                    } else if (currentCategoryId) {
                        loadPapers(currentCategoryId);
                    }
                    await updateCategoriesData();
                    renderCategoryTreeWithState();
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
                // 默认全库搜索：不再自动附带 category_id
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
        // 优先显示匹配字段的上下文片段（notes 优先，然后是 abstract）
        // 如果都没有匹配的片段，则显示摘要前200字符
        let abs = '';
        if (r.notes_snippet) {
            // 如果匹配的是 notes，显示 notes 的上下文片段
            abs = `<div class="search-meta"><strong>备注:</strong> ${hi(r.notes_snippet)}</div>`;
        } else if (r.abstract_snippet) {
            // 如果匹配的是 abstract，显示 abstract 的上下文片段
            abs = `<div class="search-meta">${hi(r.abstract_snippet)}</div>`;
        } else if (r.abstract) {
            // 如果没有上下文片段，显示摘要前200字符
            abs = `<div class="search-meta">${hi(r.abstract.slice(0,200))}...</div>`;
        }
        // 添加 category_id 属性，用于点击时切换分类
        const categoryId = r.category_id || '';
        return `<div class="search-item" data-paper-id="${r.id}" data-category-id="${categoryId}">
            <div class="search-title">${hi(r.title || r.filename || '')} ${fields}</div>
            ${authors}
            ${abs}
        </div>`;
    }).join('');
    panel.style.display = 'block';
    panel.querySelectorAll('.search-item').forEach(item => {
        item.addEventListener('click', async () => {
            const pid = item.getAttribute('data-paper-id');
            const categoryId = item.getAttribute('data-category-id');
            
            // 隐藏搜索结果面板
            panel.style.display = 'none';
            
            // 优化：先检查论文是否已经在当前列表中
            const existingPaperItem = document.querySelector(`.paper-item[data-paper-id="${pid}"]`);
            if (existingPaperItem && currentCategoryId === categoryId) {
                // 论文已经在当前分类中，直接选中并滚动
                selectPaper(pid);
                setTimeout(() => {
                    existingPaperItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
                return;
            }
            
            // 如果论文有分类信息，先切换到那个分类
            if (categoryId && categoryId !== 'null' && categoryId !== 'undefined') {
                try {
                    // 先获取论文信息，用于快速显示
                    const paperResponse = await fetch(`/api/paper/${pid}`);
                    let targetPaper = null;
                    if (paperResponse.ok) {
                        targetPaper = await paperResponse.json();
                    }
                    
                    // 获取分类信息
                    const categories = await fetch('/api/categories').then(r => r.json());
                    const category = findCategoryById(categories, categoryId);
                    
                    if (category) {
                        // 先设置 currentPaperId，这样 renderPapersList 会自动选中
                        currentPaperId = pid;
                        
                        // 如果目标论文信息已获取，先显示它（优化体验）
                        if (targetPaper) {
                            // 临时显示目标论文，提供即时反馈
                            papersList.innerHTML = `
                                <div class="paper-header">
                                    <div class="paper-header-col"></div>
                                    <div class="paper-header-col">标题<div class="paper-header-resizer" data-col="1"></div></div>
                                    <div class="paper-header-col">日期<div class="paper-header-resizer" data-col="2"></div></div>
                                    <div class="paper-header-col">AI 翻译<div class="paper-header-resizer" data-col="3"></div></div>
                                    <div class="paper-header-col">AI 解读<div class="paper-header-resizer" data-col="4"></div></div>
                                    <div class="paper-header-col">待读</div>
                                </div>
                            `;
                            // 添加列宽调整功能
                            setupColumnResizing();
                            const tempDiv = document.createElement('div');
                            tempDiv.className = 'paper-item selected';
                            tempDiv.dataset.paperId = targetPaper.id;
                            tempDiv.innerHTML = generatePaperItemHTML(targetPaper, true);
                            papersList.appendChild(tempDiv);
                            setupPaperDrag(tempDiv, targetPaper);
                            tempDiv.addEventListener('click', () => selectPaper(pid));
                            tempDiv.addEventListener('dblclick', (e) => {
                                if (!e.target.closest('button') && !e.target.closest('.paper-col-btn')) {
                                    e.preventDefault();
                                    openPDFViewer(pid);
                                }
                            });
                            // 立即选中并加载论文信息
                            selectPaper(pid);
                            loadPaperInfo(pid);
                        }
                        
                        // 切换到该分类（异步加载完整列表）
                        selectCategory(categoryId, category.name);
                        
                        // 等待论文列表加载完成后再确保选中状态
                        // 使用更智能的等待机制
                        let attempts = 0;
                        const maxAttempts = 50; // 最多等待 5 秒（论文多时可能需要更长时间）
                        const checkAndSelect = setInterval(() => {
                            attempts++;
                            const paperItem = document.querySelector(`.paper-item[data-paper-id="${pid}"]`);
                            if (paperItem) {
                                clearInterval(checkAndSelect);
                                // 确保选中状态
                                selectPaper(pid);
                                // 滚动到论文项
                                setTimeout(() => {
                                    paperItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                }, 100);
                            } else if (attempts >= maxAttempts) {
                                clearInterval(checkAndSelect);
                                // 超时后直接尝试选中（可能论文已经在列表中）
                                selectPaper(pid);
                            }
                        }, 100);
                    } else {
                        // 找不到分类，直接尝试选中论文
                        selectPaper(pid);
                    }
                } catch (error) {
                    console.error('切换分类失败:', error);
                    // 失败时直接尝试选中论文
                    selectPaper(pid);
                }
            } else {
                // 没有分类信息，直接尝试选中论文
                selectPaper(pid);
            }
        });
    });
}

function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Daily arXiv 搜索高亮
function highlightDailyArxiv(text) {
    if (!text || !dailyArxivSearchQuery || !dailyArxivSearchQuery.trim()) {
        return escapeHtml(text || '');
    }
    const q = dailyArxivSearchQuery.trim();
    const escaped = escapeRegExp(q);
    const re = new RegExp(`(${escaped})`, 'ig');
    return escapeHtml(text || '').replace(re, '<mark>$1</mark>');
}

// 删除论文
// 重新抓取 PDF 元数据
async function refreshPaperMetadata(paperId) {
    try {
        const paper = papers.find(p => p.id === paperId);
        if (!paper) {
            showMessage('论文未找到', 'error');
            return;
        }
        
        showMessage('正在重新抓取元数据...', 'info', 2000);
        
        const response = await fetch(`/api/paper/${paperId}/refresh-metadata`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const result = await response.json();
            showMessage('元数据抓取成功，正在更新...', 'success', 2000);
            
            // 启动轮询检测更新
            const initialTitle = paper.title;
            startPollingPaperUpdate(paperId, currentCategoryId, initialTitle);
            
        } else {
            const error = await response.json();
            showMessage(`抓取失败: ${error.error}`, 'error');
        }
    } catch (error) {
        console.error('重新抓取元数据失败:', error);
        showMessage('抓取失败，请稍后重试', 'error');
    }
}

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
                    const result = await updateResponse.json();
                    showMessage('论文信息更新成功', 'success');
                    hideModal();
                    
                    // 如果标题被修改，后台会自动重新抓取，启动轮询
                    if (result.auto_refresh_triggered && updatedPaper.title) {
                        console.log('[自动重抓] 标题已修改，后台正在重新抓取 arXiv 信息...');
                        
                        // 先刷新一次列表，显示用户手动更新的内容
                        if (currentCategoryId) {
                            await loadPapers(currentCategoryId);
                            // 如果当前选中的就是这个论文，刷新详情
                            if (currentPaperId === paperId) {
                                const paperResponse = await fetch(`/api/paper/${paperId}`);
                                if (paperResponse.ok) {
                                    const updatedPaperData = await paperResponse.json();
                                    renderPaperInfo(updatedPaperData);
                                }
                            }
                        }
                        
                        // 延迟启动轮询，给后台一些处理时间，并传入更新后的 title
                        setTimeout(() => {
                            startPollingPaperUpdate(paperId, currentCategoryId, updatedPaper.title, 15);
                        }, 2000);
                    } else {
                        // 刷新当前分类的论文列表
                        if (currentCategoryId) {
                            loadPapers(currentCategoryId);
                        }
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
        const isOthers = node.name === 'Others';
        const folderColor = isOthers ? '#8b949e' : '#7d4a9d';
        item.innerHTML = `
            ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span style="width: 16px; margin-right: 5px;"></span>'}
            <i class="fas fa-folder" style="margin-right: 8px; color: ${folderColor};"></i>
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
            const sortedChildren = [...node.children].sort((a, b) => {
                if (a.pinned && !b.pinned) return -1;
                if (!a.pinned && b.pinned) return 1;
                if (a.name === 'Others') return -1;
                if (b.name === 'Others') return 1;
                return (a.name || '').localeCompare(b.name || '');
            });
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
        const sortedTop = [...root.children].sort((a, b) => {
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            return (a.name || '').localeCompare(b.name || '');
        });
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

// ========== 论文多选逻辑 ==========
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

// ========== 目录多选逻辑 ==========

// 获取所有可见目录元素的有序列表
function getAllVisibleCategoryElements() {
    return Array.from(document.querySelectorAll('.category-item[data-category-id]'));
}

// 获取目录在可见列表中的索引
function getCategoryIndex(categoryId) {
    const elements = getAllVisibleCategoryElements();
    return elements.findIndex(el => el.dataset.categoryId === categoryId);
}

// 处理 Ctrl + 点击目录多选
function handleCategoryMultiSelectClick(e, categoryId, element) {
    if (!isCategoryMultiSelectMode) {
        isCategoryMultiSelectMode = true;
    }
    
    if (selectedCategoryIds.has(categoryId)) {
        selectedCategoryIds.delete(categoryId);
        element.classList.remove('multi-selected');
    } else {
        selectedCategoryIds.add(categoryId);
        element.classList.add('multi-selected');
    }
    
    lastSelectedCategoryIndex = getCategoryIndex(categoryId);
    
    // 如果没有选中任何目录，退出多选模式
    if (selectedCategoryIds.size === 0) {
        exitCategoryMultiSelectMode();
    }
    
    updateCategoryBatchUI();
}

// 处理 Shift + 点击目录范围选择
function handleCategoryShiftSelect(categoryId, element) {
    const currentIndex = getCategoryIndex(categoryId);
    if (currentIndex === -1 || lastSelectedCategoryIndex === null) return;
    
    const elements = getAllVisibleCategoryElements();
    const start = Math.min(lastSelectedCategoryIndex, currentIndex);
    const end = Math.max(lastSelectedCategoryIndex, currentIndex);
    
    if (!isCategoryMultiSelectMode) {
        isCategoryMultiSelectMode = true;
    }
    
    // 选中范围内的所有目录
    for (let i = start; i <= end; i++) {
        const el = elements[i];
        if (el) {
            const id = el.dataset.categoryId;
            selectedCategoryIds.add(id);
            el.classList.add('multi-selected');
        }
    }
    
    updateCategoryBatchUI();
}

// 退出目录多选模式
function exitCategoryMultiSelectMode() {
    if (!isCategoryMultiSelectMode) return;
    isCategoryMultiSelectMode = false;
    selectedCategoryIds.clear();
    lastSelectedCategoryIndex = null;
    
    // 移除所有多选样式
    document.querySelectorAll('.category-item.multi-selected').forEach(el => {
        el.classList.remove('multi-selected');
    });
    
    updateCategoryBatchUI();
}

// 更新目录批量操作 UI
function updateCategoryBatchUI() {
    // 可以在这里添加批量操作工具栏的显示逻辑
    console.log(`已选中 ${selectedCategoryIds.size} 个目录`);
}

// 显示目录批量操作右键菜单
function showCategoryBatchContextMenu(e) {
    const menu = document.createElement('div');
    menu.className = 'context-menu category-batch-menu';
    menu.style.cssText = `
        position: fixed;
        left: ${e.clientX}px;
        top: ${e.clientY}px;
        z-index: 10000;
        background: white;
        border: 1px solid #ddd;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        padding: 4px 0;
        min-width: 150px;
    `;
    
    menu.innerHTML = `
        <div class="context-menu-item" data-action="delete" style="padding: 8px 16px; cursor: pointer; display: flex; align-items: center; gap: 8px;">
            <i class="fas fa-trash" style="color: #dc3545;"></i>
            <span>删除选中目录 (${selectedCategoryIds.size})</span>
        </div>
    `;
    
    // 点击删除
    menu.querySelector('[data-action="delete"]').addEventListener('click', () => {
        confirmDeleteSelectedCategories();
        document.body.removeChild(menu);
    });
    
    // 鼠标悬停效果
    menu.querySelectorAll('.context-menu-item').forEach(item => {
        item.addEventListener('mouseenter', () => item.style.background = '#f5f5f5');
        item.addEventListener('mouseleave', () => item.style.background = 'transparent');
    });
    
    // 点击其他地方关闭菜单
    const closeMenu = (ev) => {
        if (!menu.contains(ev.target)) {
            if (document.body.contains(menu)) {
                document.body.removeChild(menu);
            }
            document.removeEventListener('click', closeMenu);
        }
    };
    setTimeout(() => document.addEventListener('click', closeMenu), 0);
    
    document.body.appendChild(menu);
}

// 确认删除选中的多个目录
async function confirmDeleteSelectedCategories() {
    const count = selectedCategoryIds.size;
    if (count === 0) return;
    
    const confirmed = confirm(`确定要删除选中的 ${count} 个目录吗？\n此操作将同时删除目录内的所有论文，且不可恢复！`);
    if (!confirmed) return;
    
    const ids = Array.from(selectedCategoryIds);
    let successCount = 0;
    let failCount = 0;
    
    for (const categoryId of ids) {
        try {
            const response = await fetch(`/api/categories/${categoryId}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            if (result.success) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (e) {
            failCount++;
        }
    }
    
    exitCategoryMultiSelectMode();
    await updateCategoriesData();
    await renderCategoryTreeWithState();
    
    if (failCount === 0) {
        showMessage(`成功删除 ${successCount} 个目录`, 'success');
    } else {
        showMessage(`删除完成：成功 ${successCount}，失败 ${failCount}`, 'warning');
    }
}

// 确认删除单个目录
function confirmDeleteCategory(categoryId) {
    const categoryNode = findCategoryNodeLocal(categories, categoryId);
    const name = categoryNode ? categoryNode.name : '该目录';
    
    const confirmed = confirm(`确定要删除目录"${name}"吗？\n此操作将同时删除目录内的所有论文，且不可恢复！`);
    if (confirmed) {
        deleteCategory(categoryId);
    }
}

// 在本地数据中查找目录节点
function findCategoryNodeLocal(node, targetId) {
    if (node.id === targetId) return node;
    if (node.children) {
        for (const child of node.children) {
            const found = findCategoryNodeLocal(child, targetId);
            if (found) return found;
        }
    }
    return null;
}

// 开始内联重命名
function startInlineRename(element, category) {
    const nameSpan = element.querySelector('.category-name');
    if (!nameSpan) return;
    
    const oldName = category.name;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'category-rename-input';
    input.style.cssText = `
        font-size: inherit;
        padding: 2px 4px;
        border: 1px solid #007bff;
        border-radius: 3px;
        outline: none;
        width: ${Math.max(nameSpan.offsetWidth + 20, 100)}px;
        background: white;
    `;
    
    nameSpan.style.display = 'none';
    nameSpan.parentNode.insertBefore(input, nameSpan.nextSibling);
    input.focus();
    input.select();
    
    const finishRename = async () => {
        const newName = input.value.trim();
        input.remove();
        nameSpan.style.display = '';
        
        if (newName && newName !== oldName) {
            await renameCategory(category.id, newName);
        }
    };
    
    input.addEventListener('blur', finishRename);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
        }
        if (e.key === 'Escape') {
            input.value = oldName;
            input.blur();
        }
    });
}

// 内联添加新分类
function startInlineAddCategory(parentId) {
    // 找到父分类的容器
    let parentContainer;
    let insertPosition;
    let level = 0;
    
    if (parentId === 'root') {
        // 在根目录下添加
        parentContainer = categoryTree;
        insertPosition = parentContainer.firstChild;
        level = 0;
    } else {
        // 在子目录下添加
        const parentElement = document.querySelector(`[data-category-id="${parentId}"]`);
        if (!parentElement) {
            showMessage('找不到父分类', 'error');
            return;
        }
        
        level = parseInt(parentElement.dataset.level || '0') + 1;
        const parentCategoryContainer = parentElement.closest('.category-container');
        
        // 确保父分类已展开
        const childrenContainer = parentCategoryContainer.querySelector('.category-children');
        const toggle = parentElement.querySelector('.category-toggle');
        
        if (childrenContainer) {
            childrenContainer.classList.remove('collapsed');
            if (toggle) {
                toggle.classList.add('expanded');
            }
            expandedCategories.add(parentId);
            parentContainer = childrenContainer;
            insertPosition = parentContainer.firstChild;
        } else {
            // 如果没有子分类容器，创建一个
            const newChildrenContainer = document.createElement('div');
            newChildrenContainer.className = 'category-children';
            parentCategoryContainer.appendChild(newChildrenContainer);
            
            // 更新父元素的展开按钮
            const togglePlaceholder = parentElement.querySelector('.category-toggle-placeholder');
            if (togglePlaceholder) {
                togglePlaceholder.outerHTML = '<button class="category-toggle expanded"><i class="fas fa-chevron-right"></i></button>';
                // 重新绑定事件
                const newToggle = parentElement.querySelector('.category-toggle');
                if (newToggle) {
                    newToggle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const category = findCategoryById(categories, parentId);
                        if (category) {
                            toggleCategoryChildren(parentCategoryContainer, category);
                        }
                    });
                }
            }
            
            expandedCategories.add(parentId);
            parentContainer = newChildrenContainer;
            insertPosition = null;
        }
    }
    
    // 创建临时的新分类容器
    const tempContainer = document.createElement('div');
    tempContainer.className = 'category-container temp-new-category';
    
    const tempDiv = document.createElement('div');
    tempDiv.className = 'category-item editing';
    tempDiv.dataset.parentId = parentId;
    tempDiv.style.paddingLeft = `${level * 20 + 12}px`;
    
    // 临时占位的展开按钮
    tempDiv.innerHTML = `
        <span class="category-toggle-placeholder"></span>
        <i class="fas fa-folder" style="margin-right: 6px; color: #7d4a9d; font-size: 12px;"></i>
        <span class="category-name" style="display: none;"></span>
        <span class="pdf-count">0</span>
    `;
    
    tempContainer.appendChild(tempDiv);
    
    // 插入到适当位置
    if (insertPosition) {
        parentContainer.insertBefore(tempContainer, insertPosition);
    } else {
        parentContainer.appendChild(tempContainer);
    }
    
    // 创建输入框
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '输入分类名称';
    input.className = 'category-rename-input';
    input.style.cssText = `
        font-size: inherit;
        padding: 2px 4px;
        border: 1px solid #28a745;
        border-radius: 3px;
        outline: none;
        width: 150px;
        background: white;
        box-shadow: 0 0 0 2px rgba(40, 167, 69, 0.1);
    `;
    
    const nameSpan = tempDiv.querySelector('.category-name');
    nameSpan.parentNode.insertBefore(input, nameSpan.nextSibling);
    input.focus();
    
    // 完成添加或取消
    const finishAdd = async () => {
        const newName = input.value.trim();
        
        if (newName) {
            // 创建新分类
            try {
                const response = await fetch('/api/categories', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        parent_id: parentId,
                        name: newName
                    })
                });

                const result = await response.json();
                
                if (result.success) {
                    showMessage('分类添加成功', 'success');
                    // 移除临时元素
                    tempContainer.remove();
                    // 更新并重新渲染
                    await updateCategoriesData();
                    await renderCategoryTreeWithState();
                } else {
                    showMessage(`添加失败: ${result.error}`, 'error');
                    tempContainer.remove();
                }
            } catch (error) {
                console.error('添加分类失败:', error);
                showMessage('添加分类失败', 'error');
                tempContainer.remove();
            }
        } else {
            // 用户取消或输入为空，移除临时元素
            tempContainer.remove();
        }
    };
    
    // 失去焦点时完成
    input.addEventListener('blur', finishAdd);
    
    // 键盘事件
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            input.blur();
        }
        if (e.key === 'Escape') {
            input.value = ''; // 清空输入，表示取消
            input.blur();
        }
    });
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
    // 已提交解读，状态列会自动更新
}

async function onBatchTranslate() {
    if (selectedPaperIds.size === 0) { showMessage('请先选择论文', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    for (const id of ids) {
        await requestTranslation(id);
    }
    // 已提交翻译，状态列会自动更新
    updateTaskIndicator();
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
            case 'published_date_desc':
                // 按 arXiv 发布日期降序排序（最新的在前）
                const dateA = a.arxiv_published_date || '';
                const dateB = b.arxiv_published_date || '';
                if (!dateA && !dateB) return 0;
                if (!dateA) return 1;  // 没有日期的排在后面
                if (!dateB) return -1;
                return new Date(dateB) - new Date(dateA);
            case 'published_date_asc':
                // 按 arXiv 发布日期升序排序（最旧的在前）
                const dateA2 = a.arxiv_published_date || '';
                const dateB2 = b.arxiv_published_date || '';
                if (!dateA2 && !dateB2) return 0;
                if (!dateA2) return 1;  // 没有日期的排在后面
                if (!dateB2) return -1;
                return new Date(dateA2) - new Date(dateB2);
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
    
    // 导航栏头像点击事件
    const navAvatar = document.getElementById('nav-avatar');
    if (navAvatar) {
        navAvatar.addEventListener('click', () => {
            switchTab('setting');
        });
    }

    // 设置页左侧导航
    document.addEventListener('click', (e) => {
        const item = e.target.closest && e.target.closest('.setting-nav-item');
        if (!item) return;
        const key = item.getAttribute('data-setting');
        if (key) {
            switchSettingPanel(key);
        }
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

// 返回主界面
function returnToHome() {
    // 切换到 Paper 视图
    switchTab('paper');
    
    // 清除分类选中状态
    currentCategoryId = null;
    currentViewMode = 'category';
    
    // 清除分类树中的选中状态
    document.querySelectorAll('.category-item.selected').forEach(item => {
        item.classList.remove('selected');
    });
    
    // 清除论文选中状态
    currentPaperId = null;
    document.querySelectorAll('.paper-item.selected').forEach(item => {
        item.classList.remove('selected');
    });
    
    // 清除多选模式
    if (isMultiSelectMode) {
        exitMultiSelectMode();
    }
    
    // 显示待读列表
    showReadingList();
    
    // 保存视图状态
    saveCurrentViewState();
}

// 切换标签页
function switchTab(tabName) {
    const paperView = document.getElementById('paper-view');
    const settingView = document.getElementById('setting-view');
    const dailyArxivView = document.getElementById('daily-arxiv-view');
    const navTabs = document.querySelectorAll('.nav-tab');
    const navAvatar = document.getElementById('nav-avatar');
    
    navTabs.forEach(tab => {
        if (tab.dataset.tab === tabName) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });
    
    // 更新头像导航状态
    if (navAvatar) {
        if (tabName === 'setting') {
            navAvatar.classList.add('active');
        } else {
            navAvatar.classList.remove('active');
        }
    }
    
    if (tabName === 'paper') {
        paperView.style.display = 'flex';
        settingView.style.display = 'none';
        if (dailyArxivView) dailyArxivView.style.display = 'none';
        // 不调用 renderRecentIfNoCategory，让调用者决定显示什么
    } else if (tabName === 'setting') {
        paperView.style.display = 'none';
        settingView.style.display = 'flex';
        if (dailyArxivView) dailyArxivView.style.display = 'none';
        // 初始化 Settings 页面
        initSettingsPage();
    } else if (tabName === 'daily-arxiv') {
        paperView.style.display = 'none';
        settingView.style.display = 'none';
        if (dailyArxivView) dailyArxivView.style.display = 'block';
        // 初始化 Daily arXiv 页面
        showDailyArxivView();
        return; // showDailyArxivView 会自己保存状态
    }
    saveCurrentViewState();
}

// 保存翻译设置
// ========== Agentic 设置（统一的AI功能配置）==========
async function saveAgenticSettings(silent = false) {
    const promptEl = document.getElementById('analysis-system-prompt');
    const modelEl = document.getElementById('llm-model');
    const baseUrlEl = document.getElementById('llm-base-url');
    const apiKeyEl = document.getElementById('llm-api-key');
    const mineruEl = document.getElementById('mineru-server-url');
    
    // 检查元素是否存在
    if (!promptEl || !modelEl || !baseUrlEl || !apiKeyEl || !mineruEl) {
        console.error('保存设置失败: 找不到设置输入元素');
        if (!silent) {
            showMessage('保存失败: 找不到设置输入元素', 'error');
        }
        return;
    }
    
    const promptValue = promptEl.value.trim();
    const settings = {
        llmModel: modelEl.value.trim(),
        llmBaseUrl: baseUrlEl.value.trim(),
        llmApiKey: apiKeyEl.value.trim(),
        mineruServerUrl: mineruEl.value.trim(),
        // 如果用户清空了提示词，保存为空字符串（后端会使用默认值）
        analysisSystemPrompt: promptValue
    };
    
    console.log('[保存设置] 准备保存:', {
        llmModel: settings.llmModel ? '***' : '(空)',
        llmBaseUrl: settings.llmBaseUrl ? '***' : '(空)',
        llmApiKey: settings.llmApiKey ? '***' : '(空)',
        mineruServerUrl: settings.mineruServerUrl ? '***' : '(空)',
        hasPrompt: !!settings.analysisSystemPrompt
    });
    
    try {
        const response = await fetch('/api/settings/agentic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            console.log('[保存设置] ✅ 保存成功');
            // 更新 Daily arXiv 的 LLM 配置状态
            if (typeof checkDailyArxivLLMConfig === 'function') {
                await checkDailyArxivLLMConfig();
                // 如果配置完整，重新渲染网格以更新按钮状态
                if (typeof renderDailyArxivGrid === 'function') {
                    renderDailyArxivGrid();
                }
            }
            
            if (!silent) {
                showMessage('AI功能设置已保存', 'success');
            }
        } else {
            const errorMsg = result.error || '保存失败';
            console.error('[保存设置] ❌ 保存失败:', errorMsg);
            if (!silent) {
                showMessage(`保存失败: ${errorMsg}`, 'error');
            }
        }
    } catch (e) {
        console.error('[保存设置] ❌ 保存异常:', e);
        if (!silent) {
            showMessage(`保存失败: ${e.message}`, 'error');
        }
    }
}

// 防抖函数
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// 自动保存 Agentic 设置（防抖）
const autoSaveAgenticSettings = debounce(() => {
    saveAgenticSettings(true); // silent mode
}, 500);

// 加载 Agentic 设置
async function loadAgenticSettings() {
    try {
        const response = await fetch('/api/settings/agentic');
        if (response.ok) {
            const settings = await response.json();
            const modelEl = document.getElementById('llm-model');
            const baseUrlEl = document.getElementById('llm-base-url');
            const apiKeyEl = document.getElementById('llm-api-key');
            const mineruEl = document.getElementById('mineru-server-url');
            const promptEl = document.getElementById('analysis-system-prompt');
            
            if (modelEl) {
                modelEl.value = settings.llmModel || '';
                modelEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (baseUrlEl) {
                baseUrlEl.value = settings.llmBaseUrl || '';
                baseUrlEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (apiKeyEl) {
                apiKeyEl.value = settings.llmApiKey || '';
                apiKeyEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (mineruEl) {
                mineruEl.value = settings.mineruServerUrl || '';
                mineruEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (promptEl) {
                // 保存默认提示词（用于恢复）
                const defaultPrompt = settings.analysisSystemPrompt || '';
                const isDefaultPrompt = settings._isDefaultPrompt || false;
                
                // 显示 System Prompt（如果后端返回了默认值，也会显示）
                promptEl.value = defaultPrompt;
                promptEl.placeholder = '请输入 AI 解读的系统提示词...';
                
                // 更新状态文本
                const statusText = document.getElementById('prompt-status-text');
                if (statusText) {
                    if (isDefaultPrompt) {
                        statusText.textContent = '当前显示的是默认提示词，修改后将保存为自定义提示词';
                        statusText.style.color = '#666';
                    } else if (defaultPrompt) {
                        statusText.textContent = '当前使用的是自定义提示词';
                        statusText.style.color = '#28a745';
                    } else {
                        statusText.textContent = '提示：修改后将保存为自定义提示词';
                        statusText.style.color = '#666';
                    }
                }
                
                // 监听输入变化，更新状态
                promptEl.addEventListener('input', () => {
                    if (statusText) {
                        const currentValue = promptEl.value.trim();
                        if (currentValue) {
                            statusText.textContent = '当前使用的是自定义提示词';
                            statusText.style.color = '#28a745';
                        } else {
                            statusText.textContent = '提示：留空将使用默认提示词';
                            statusText.style.color = '#666';
                        }
                    }
                    autoSaveAgenticSettings();
                });
            }
            
            // 绑定测试按钮事件
            const testLlmBtn = document.getElementById('test-llm-api');
            const testMineruBtn = document.getElementById('test-mineru-api');
            
            if (testLlmBtn) {
                testLlmBtn.addEventListener('click', testLLMAPI);
            }
            if (testMineruBtn) {
                testMineruBtn.addEventListener('click', testMineruAPI);
            }
        }
    } catch (e) {
        console.error('加载AI功能设置失败:', e);
    }
}

// 测试 LLM API（核心逻辑，可复用）
async function testLLMAPICore(llmModel, llmBaseUrl, llmApiKey) {
    if (!llmModel || !llmBaseUrl || !llmApiKey) {
        return {
            success: false,
            error: '请先填写完整的 LLM API 配置（Model、Base URL、API Key）'
        };
    }
    
    try {
        const response = await fetch('/api/settings/test/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                llmModel: llmModel,
                llmBaseUrl: llmBaseUrl,
                llmApiKey: llmApiKey
            })
        });
        
        const data = await response.json();
        return data;
    } catch (error) {
        return {
            success: false,
            error: `网络错误: ${error.message}`
        };
    }
}

// 测试 LLM API（Settings 界面使用）
async function testLLMAPI() {
    const btn = document.getElementById('test-llm-api');
    const resultDiv = document.getElementById('llm-test-result');
    
    if (!btn || !resultDiv) return;
    
    // 获取当前配置
    const llmModel = document.getElementById('llm-model').value.trim();
    const llmBaseUrl = document.getElementById('llm-base-url').value.trim();
    const llmApiKey = document.getElementById('llm-api-key').value.trim();
    
    if (!llmModel || !llmBaseUrl || !llmApiKey) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; color: #856404;">
                <i class="fas fa-exclamation-triangle"></i> 请先填写完整的 LLM API 配置
            </div>
        `;
        resultDiv.style.display = 'block';
        return;
    }
    
    // 更新按钮状态
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 测试中...';
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `
        <div style="padding: 12px; background: #e7f3ff; border: 1px solid #2196F3; border-radius: 6px; color: #0d47a1;">
            <i class="fas fa-spinner fa-spin"></i> 正在测试 LLM API 连接...
        </div>
    `;
    
    // 调用核心测试函数
    const data = await testLLMAPICore(llmModel, llmBaseUrl, llmApiKey);
    
    if (data.success) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #d4edda; border: 1px solid #28a745; border-radius: 6px; color: #155724;">
                <i class="fas fa-check-circle"></i> <strong>${data.message}</strong>
                ${data.reply ? `<div style="margin-top: 8px; font-size: 13px;">回复: "${data.reply}"</div>` : ''}
            </div>
        `;
    } else {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                <i class="fas fa-times-circle"></i> <strong>测试失败</strong>
                <div style="margin-top: 8px; font-size: 13px;">${data.error || '未知错误'}</div>
            </div>
        `;
    }
    
    btn.disabled = false;
    btn.innerHTML = originalHTML;
}

// 测试 MinerU API
async function testMineruAPI() {
    const btn = document.getElementById('test-mineru-api');
    const resultDiv = document.getElementById('mineru-test-result');
    
    if (!btn || !resultDiv) return;
    
    // 获取当前配置
    const mineruServerUrl = document.getElementById('mineru-server-url').value.trim();
    
    if (!mineruServerUrl) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; color: #856404;">
                <i class="fas fa-exclamation-triangle"></i> 请先填写 MinerU Server URL
            </div>
        `;
        resultDiv.style.display = 'block';
        return;
    }
    
    // 更新按钮状态
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 测试中...';
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `
        <div style="padding: 12px; background: #e7f3ff; border: 1px solid #2196F3; border-radius: 6px; color: #0d47a1;">
            <i class="fas fa-spinner fa-spin"></i> 正在测试 MinerU API 连接...
        </div>
    `;
    
    try {
        const response = await fetch('/api/settings/test/mineru', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mineruServerUrl: mineruServerUrl
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #d4edda; border: 1px solid #28a745; border-radius: 6px; color: #155724;">
                    <i class="fas fa-check-circle"></i> <strong>${data.message}</strong>
                    ${data.tested_url ? `<div style="margin-top: 8px; font-size: 13px;">测试地址: ${data.tested_url}</div>` : ''}
                </div>
            `;
        } else {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                    <i class="fas fa-times-circle"></i> <strong>测试失败</strong>
                    <div style="margin-top: 8px; font-size: 13px;">${data.error || '未知错误'}</div>
                </div>
            `;
        }
    } catch (error) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                <i class="fas fa-times-circle"></i> <strong>测试失败</strong>
                <div style="margin-top: 8px; font-size: 13px;">网络错误: ${error.message}</div>
            </div>
        `;
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

// 获取 Agentic 设置
async function getAgenticSettings() {
    try {
        const response = await fetch('/api/settings/agentic');
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.error('获取AI功能设置失败:', e);
    }
    return null;
}

// ========== 废弃的设置函数（保留以兼容） ==========
async function saveTranslationSettings() {
    console.warn('saveTranslationSettings is deprecated, use saveAgenticSettings instead');
    return saveAgenticSettings();
}

async function loadTranslationSettings() {
    console.warn('loadTranslationSettings is deprecated, use loadAgenticSettings instead');
    return loadAgenticSettings();
}

async function getTranslationSettings() {
    console.warn('getTranslationSettings is deprecated, use getAgenticSettings instead');
    return getAgenticSettings();
}

// ==================== 翻译功能 ====================

// ========== General 设置（已废弃）==========
async function saveGeneralSettings() {
    console.warn('saveGeneralSettings is deprecated, General settings have been removed');
    showMessage('General 设置已废弃', 'warning');
}

async function loadGeneralSettings() {
    console.warn('loadGeneralSettings is deprecated, General settings have been removed');
}

// ========================================
// Settings 页面 - 热力图和统计
// ========================================

let settingsNavInitialized = false;
let currentHeatmapYear = new Date().getFullYear();

// ========================================
// 用户头像和名字设置
// ========================================

// 生成像素头像 (GitHub 风格 identicon)
function generateIdenticon(seed, size = 5) {
    // 简单的哈希函数
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
        const char = seed.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    
    // 生成颜色 - 使用种子生成一个漂亮的颜色
    const hue = Math.abs(hash % 360);
    const saturation = 65 + Math.abs((hash >> 8) % 20);
    const lightness = 45 + Math.abs((hash >> 16) % 15);
    const bgColor = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    const fgColor = `hsl(${hue}, ${saturation}%, ${lightness + 35}%)`;
    
    // 生成像素图案 (5x5 对称)
    const pattern = [];
    for (let y = 0; y < size; y++) {
        pattern[y] = [];
        for (let x = 0; x < Math.ceil(size / 2); x++) {
            // 使用哈希值的不同位来决定像素
            const bitIndex = y * 3 + x;
            const pixel = (Math.abs(hash >> bitIndex) % 2) === 1;
            pattern[y][x] = pixel;
            // 镜像
            pattern[y][size - 1 - x] = pixel;
        }
    }
    
    return { pattern, bgColor, fgColor, size };
}

// 在 canvas 上绘制像素头像
function drawIdenticon(canvas, seed) {
    const ctx = canvas.getContext('2d');
    const { pattern, bgColor, fgColor, size } = generateIdenticon(seed);
    
    const cellSize = canvas.width / size;
    
    // 绘制背景
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // 绘制像素
    ctx.fillStyle = fgColor;
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            if (pattern[y][x]) {
                ctx.fillRect(
                    x * cellSize + cellSize * 0.1,
                    y * cellSize + cellSize * 0.1,
                    cellSize * 0.8,
                    cellSize * 0.8
                );
            }
        }
    }
}

// 用户设置缓存（避免频繁请求后端）
let userSettingsCache = null;

// 获取用户设置（异步）
async function getUserSettings() {
    // 如果有缓存，直接返回
    if (userSettingsCache) {
        return userSettingsCache;
    }
    try {
        const response = await fetch('/api/settings/user');
        if (response.ok) {
            userSettingsCache = await response.json();
            return userSettingsCache;
        }
    } catch (e) {
        console.error('读取用户设置失败:', e);
    }
    return {
        name: 'Paper Reader',
        avatar: null,
        heatmapColorScheme: 'green',
        onboardingDontShow: false
    };
}

// 获取用户设置（同步版本，使用缓存）
function getUserSettingsSync() {
    if (userSettingsCache) {
        return userSettingsCache;
    }
    return {
        name: 'Paper Reader',
        avatar: null,
        heatmapColorScheme: 'green',
        onboardingDontShow: false
    };
}

// 保存用户设置
async function saveUserSettings(settings) {
    try {
        const response = await fetch('/api/settings/user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (response.ok) {
            // 更新缓存
            userSettingsCache = { ...userSettingsCache, ...settings };
        }
    } catch (e) {
        console.error('保存用户设置失败:', e);
    }
}

// 上传头像到服务器
async function uploadAvatar(avatarData) {
    try {
        const response = await fetch('/api/settings/avatar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ avatarData })
        });
        if (response.ok) {
            const result = await response.json();
            // 更新缓存
            if (userSettingsCache) {
                userSettingsCache.avatar = result.avatar;
            }
            return result.avatar;
        }
    } catch (e) {
        console.error('上传头像失败:', e);
    }
    return null;
}

// 更新所有头像显示
async function updateAvatars() {
    const userSettings = await getUserSettings();
    
    // 绘制头像到 canvas 的辅助函数
    const drawAvatarToCanvas = (canvas, avatarUrl, userName) => {
        if (avatarUrl) {
            // 使用服务器上的图片
            const img = new Image();
            img.onload = () => {
                const ctx = canvas.getContext('2d');
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                // 圆形裁剪
                ctx.save();
                ctx.beginPath();
                ctx.arc(canvas.width / 2, canvas.height / 2, canvas.width / 2, 0, Math.PI * 2);
                ctx.closePath();
                ctx.clip();
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                ctx.restore();
            };
            img.onerror = () => {
                // 加载失败时使用像素头像
                drawIdenticon(canvas, userName);
            };
            img.src = avatarUrl + '?t=' + Date.now(); // 添加时间戳避免缓存
        } else {
            // 使用生成的像素头像
            drawIdenticon(canvas, userName);
        }
    };
    
    const avatarUrl = userSettings.avatar ? '/api/settings/avatar' : null;
    
    // 导航栏头像
    const navCanvas = document.getElementById('nav-avatar-canvas');
    if (navCanvas) {
        drawAvatarToCanvas(navCanvas, avatarUrl, userSettings.name);
    }
    
    // Settings 页面头像
    const settingCanvas = document.getElementById('setting-avatar-canvas');
    if (settingCanvas) {
        drawAvatarToCanvas(settingCanvas, avatarUrl, userSettings.name);
    }
    
    // 更新名字显示
    const nameEl = document.getElementById('setting-user-name');
    if (nameEl) {
        nameEl.textContent = userSettings.name;
    }
}

// 设置用户头像和名字的事件监听
function setupUserProfileEvents() {
    // 头像上传
    const settingAvatar = document.getElementById('setting-user-avatar');
    const avatarUpload = document.getElementById('avatar-upload');
    
    if (settingAvatar && avatarUpload) {
        settingAvatar.addEventListener('click', () => {
            avatarUpload.click();
        });
        
        avatarUpload.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (file) {
                if (!file.type.startsWith('image/')) {
                    showMessage('请选择图片文件', 'warning');
                    return;
                }
                
                const reader = new FileReader();
                reader.onload = async (event) => {
                    const img = new Image();
                    img.onload = async () => {
                        // 压缩图片到合适大小
                        const canvas = document.createElement('canvas');
                        const maxSize = 200;
                        let width = img.width;
                        let height = img.height;
                        
                        if (width > height) {
                            if (width > maxSize) {
                                height *= maxSize / width;
                                width = maxSize;
                            }
                        } else {
                            if (height > maxSize) {
                                width *= maxSize / height;
                                height = maxSize;
                            }
                        }
                        
                        canvas.width = width;
                        canvas.height = height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, width, height);
                        
                        const avatarData = canvas.toDataURL('image/jpeg', 0.8);
                        
                        // 上传到服务器
                        const result = await uploadAvatar(avatarData);
                        if (result) {
                            await updateAvatars();
                            showMessage('头像已更新', 'success');
                        } else {
                            showMessage('头像上传失败', 'error');
                        }
                    };
                    img.src = event.target.result;
                };
                reader.readAsDataURL(file);
            }
        });
    }
    
    // 名字编辑 (双击)
    const nameEl = document.getElementById('setting-user-name');
    if (nameEl) {
        nameEl.addEventListener('dblclick', () => {
            nameEl.contentEditable = true;
            nameEl.classList.add('editing');
            nameEl.focus();
            
            // 选中文本
            const range = document.createRange();
            range.selectNodeContents(nameEl);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        });
        
        nameEl.addEventListener('blur', async () => {
            nameEl.contentEditable = false;
            nameEl.classList.remove('editing');
            
            const newName = nameEl.textContent.trim();
            if (newName) {
                const userSettings = await getUserSettings();
                if (newName !== userSettings.name) {
                    await saveUserSettings({ name: newName });
                    // 如果没有自定义头像，则重新生成像素头像
                    if (!userSettings.avatar) {
                        await updateAvatars();
                    }
                    showMessage('名字已更新', 'success');
                }
            } else {
                // 恢复原名字
                const userSettings = await getUserSettings();
                nameEl.textContent = userSettings.name;
            }
        });
        
        nameEl.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                nameEl.blur();
            } else if (e.key === 'Escape') {
                const userSettings = await getUserSettings();
                nameEl.textContent = userSettings.name;
                nameEl.blur();
            }
        });
    }
}

// 初始化 Settings 页面
async function initSettingsPage() {
    console.log('初始化 Settings 页面, 已初始化:', settingsNavInitialized);
    if (!settingsNavInitialized) {
        setupSettingsNavigation();
        setupHeatmapControls();
        setupUserProfileEvents();
        settingsNavInitialized = true;
    }
    // 先加载用户设置和阅读历史到缓存（强制刷新）
    await getUserSettings();
    // 清除缓存，强制从服务器重新加载
    readingHistoryCache = null;
    await getDailyReadingData();
    // 更新头像和名字
    await updateAvatars();
    // 加载保存的色系（现在从服务器加载）
    await loadHeatmapColorScheme();
    // 更新年份显示
    updateYearDisplay();
    renderHeatmap(currentHeatmapYear);
    renderOverviewStats();
    renderRecentActivity();
}

// 获取有阅读数据的年份范围
function getReadingYearRange() {
    const historyData = getDailyReadingDataSync();
    const dailyData = getDailyReadingMinutes(historyData);
    const years = new Set();
    
    Object.keys(dailyData).forEach(dateStr => {
        if (dailyData[dateStr] > 0) {
            const year = parseInt(dateStr.split('-')[0], 10);
            years.add(year);
        }
    });
    
    if (years.size === 0) {
        // 没有任何数据，返回当前年
        const thisYear = new Date().getFullYear();
        return { minYear: thisYear, maxYear: thisYear };
    }
    
    const yearArray = Array.from(years).sort((a, b) => a - b);
    return {
        minYear: yearArray[0],
        maxYear: yearArray[yearArray.length - 1]
    };
}

// 设置热力图控件（年份选择、色系选择）
function setupHeatmapControls() {
    // 年份选择
    const prevBtn = document.getElementById('year-prev');
    const nextBtn = document.getElementById('year-next');
    
    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            const { minYear } = getReadingYearRange();
            if (currentHeatmapYear > minYear) {
                currentHeatmapYear--;
                updateYearDisplay();
                renderHeatmap(currentHeatmapYear);
            }
        });
    }
    
    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            const thisYear = new Date().getFullYear();
            if (currentHeatmapYear < thisYear) {
                currentHeatmapYear++;
                updateYearDisplay();
                renderHeatmap(currentHeatmapYear);
            }
        });
    }
    
    // 色系选择
    const legend = document.getElementById('heatmap-legend');
    const dropdown = document.getElementById('color-scheme-dropdown');
    
    if (legend && dropdown) {
        legend.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });
        
        // 点击其他地方关闭下拉框
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !legend.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
        
        // 色系选项点击
        dropdown.querySelectorAll('.color-scheme-option').forEach(option => {
            option.addEventListener('click', () => {
                const scheme = option.dataset.scheme;
                setHeatmapColorScheme(scheme);
                dropdown.classList.remove('show');
            });
        });
    }
}

// 更新年份显示
function updateYearDisplay() {
    const yearEl = document.getElementById('heatmap-year');
    const prevBtn = document.getElementById('year-prev');
    const nextBtn = document.getElementById('year-next');
    const thisYear = new Date().getFullYear();
    const { minYear } = getReadingYearRange();
    
    if (yearEl) {
        yearEl.textContent = currentHeatmapYear;
    }
    
    // 禁用上一年按钮如果已经是最早有数据的年份
    if (prevBtn) {
        prevBtn.disabled = currentHeatmapYear <= minYear;
    }
    
    // 禁用下一年按钮如果已经是今年
    if (nextBtn) {
        nextBtn.disabled = currentHeatmapYear >= thisYear;
    }
}

// 设置热力图色系
function setHeatmapColorScheme(scheme, save = true) {
    const container = document.querySelector('.heatmap-container');
    const dropdown = document.getElementById('color-scheme-dropdown');
    
    if (container) {
        container.setAttribute('data-scheme', scheme);
    }
    
    // 更新选中状态
    if (dropdown) {
        dropdown.querySelectorAll('.color-scheme-option').forEach(option => {
            option.classList.toggle('active', option.dataset.scheme === scheme);
        });
    }
    
    // 保存到服务器
    if (save) {
        saveUserSettings({ heatmapColorScheme: scheme });
        console.log('色系已保存:', scheme);
    }
}

// 加载保存的色系
async function loadHeatmapColorScheme() {
    const userSettings = await getUserSettings();
    const scheme = userSettings.heatmapColorScheme || 'green';
    setHeatmapColorScheme(scheme, false); // 不重复保存
}

// 设置 Settings 导航切换
function setupSettingsNavigation() {
    const navItems = document.querySelectorAll('.setting-sidebar-nav .setting-nav-item');
    const panels = document.querySelectorAll('.setting-main .setting-panel');
    
    console.log('设置导航初始化, navItems:', navItems.length, 'panels:', panels.length);
    
    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const targetPanel = this.dataset.setting;
            console.log('点击导航:', targetPanel);
            
            // 更新导航状态
            navItems.forEach(nav => nav.classList.remove('active'));
            this.classList.add('active');
            
            // 切换面板
            panels.forEach(panel => {
                if (panel.id === `setting-panel-${targetPanel}`) {
                    panel.style.display = 'block';
                    console.log('显示面板:', panel.id);
                    
                    // 如果切换到 Daily arXiv 面板，加载设置并绑定事件
                    if (targetPanel === 'daily-arxiv') {
                        loadDailyArxivSettings().then(() => {
                            setupDailyArxivKeywordInput();
                        });
                    }
                } else {
                    panel.style.display = 'none';
                }
            });
        });
    });
}

// 格式化日期为 YYYY-MM-DD（使用本地时间，避免时区问题）
function formatDateLocal(date) {
    const d = date || new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// 记录每日阅读时间
function recordDailyReadingTime(minutes) {
    const today = formatDateLocal(new Date());
    
    // 发送到服务器
    fetch('/api/settings/reading-history/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes, date: today })
    }).catch(e => {
        console.error('记录每日阅读时间失败:', e);
    });
    
    // 同时更新本地缓存（用于即时显示）
    if (readingHistoryCache) {
        readingHistoryCache[today] = (readingHistoryCache[today] || 0) + minutes;
    }
}

// 获取每日阅读数据
// 阅读历史缓存
let readingHistoryCache = null;

async function getDailyReadingData() {
    // 如果有缓存，直接返回
    if (readingHistoryCache) {
        return readingHistoryCache;
    }
    try {
        const response = await fetch('/api/settings/reading-history');
        if (response.ok) {
            readingHistoryCache = await response.json();
            return readingHistoryCache;
        }
    } catch (e) {
        console.error('获取每日阅读数据失败:', e);
    }
    return {};
}

// 同步版本（使用缓存）
function getDailyReadingDataSync() {
    if (readingHistoryCache) {
        return readingHistoryCache;
    }
    return {};
}

// 从阅读历史中获取每日阅读时长（兼容新旧格式）
// 新格式: { "date": { "total": minutes, "papers": [...] } }
// 旧格式: { "date": minutes }
function getDailyReadingMinutes(historyData) {
    const result = {};
    for (const [date, value] of Object.entries(historyData)) {
        if (typeof value === 'object' && value !== null) {
            // 新格式
            result[date] = value.total || 0;
        } else {
            // 旧格式
            result[date] = value || 0;
        }
    }
    return result;
}

// 添加测试阅读数据
async function addTestReadingData() {
    const today = formatDateLocal(new Date());
    
    try {
        // 添加今天的测试数据（30分钟）
        await fetch('/api/settings/reading-history/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ minutes: 30, date: today })
        });
        
        // 添加过去一周的随机数据
        for (let i = 1; i <= 7; i++) {
            const date = new Date();
            date.setDate(date.getDate() - i);
            const dateStr = formatDateLocal(date);
            const minutes = Math.floor(Math.random() * 60) + 10; // 10-70分钟
            await fetch('/api/settings/reading-history/record', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ minutes, date: dateStr })
            });
        }
        
        // 清除缓存并重新加载
        readingHistoryCache = null;
        await getDailyReadingData();
        
        console.log('测试数据已添加');
        showMessage('已添加测试数据，刷新热力图...', 'success');
        
        // 刷新热力图
        renderHeatmap();
        renderOverviewStats();
    } catch (e) {
        console.error('添加测试数据失败:', e);
        showMessage('添加测试数据失败', 'error');
    }
}

// 清除所有阅读数据
async function clearReadingData() {
    if (confirm('确定要清除所有阅读数据吗？此操作不可撤销。')) {
        try {
            await fetch('/api/settings/reading-history/clear', { method: 'POST' });
            readingHistoryCache = null;
            console.log('阅读数据已清除');
            showMessage('阅读数据已清除', 'success');
            
            // 刷新热力图
            renderHeatmap();
            renderOverviewStats();
        } catch (e) {
            console.error('清除数据失败:', e);
            showMessage('清除数据失败', 'error');
        }
    }
}

// 渲染热力图
function renderHeatmap(year) {
    const grid = document.getElementById('heatmap-grid');
    const monthsContainer = document.getElementById('heatmap-months');
    
    if (!grid || !monthsContainer) {
        console.log('热力图元素未找到', { grid, monthsContainer });
        return;
    }
    
    year = year || new Date().getFullYear();
    // 使用同步缓存版本，调用前需确保数据已加载
    const historyData = getDailyReadingDataSync();
    const data = getDailyReadingMinutes(historyData);
    console.log('热力图数据:', data, '年份:', year);
    
    const today = new Date();
    const isCurrentYear = year === today.getFullYear();
    
    // 清空现有内容
    grid.innerHTML = '';
    monthsContainer.innerHTML = '';
    
    // 计算该年的起始和结束日期
    const yearStart = new Date(year, 0, 1);
    const yearEnd = isCurrentYear ? today : new Date(year, 11, 31);
    
    // 找到该年第一天所在周的周日
    const startDate = new Date(yearStart);
    startDate.setDate(startDate.getDate() - startDate.getDay());
    
    // 计算阅读时间的分级阈值
    const allValues = Object.values(data).filter(v => v > 0);
    let thresholds = [0, 15, 30, 60, 120]; // 默认阈值（分钟）
    
    if (allValues.length > 0) {
        const sorted = [...allValues].sort((a, b) => a - b);
        const p25 = sorted[Math.floor(sorted.length * 0.25)] || 15;
        const p50 = sorted[Math.floor(sorted.length * 0.5)] || 30;
        const p75 = sorted[Math.floor(sorted.length * 0.75)] || 60;
        thresholds = [0, p25, p50, p75, p75 * 1.5];
    }
    
    // 获取阅读等级
    function getLevel(minutes) {
        if (!minutes || minutes <= 0) return 0;
        if (minutes < thresholds[1]) return 1;
        if (minutes < thresholds[2]) return 2;
        if (minutes < thresholds[3]) return 3;
        return 4;
    }
    
    // 格式化时间
    function formatMinutes(mins) {
        if (mins < 60) return `${mins} 分钟`;
        const hours = Math.floor(mins / 60);
        const minutes = mins % 60;
        return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }
    
    // 月份名称
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    
    // 生成月份标签（固定12个）
    monthNames.forEach(name => {
        const monthSpan = document.createElement('span');
        monthSpan.textContent = name;
        monthsContainer.appendChild(monthSpan);
    });
    
    let totalActiveDays = 0;
    let totalYearMinutes = 0;
    
    // 生成整年的周
    const currentDate = new Date(startDate);
    const endOfYear = new Date(year, 11, 31);
    // 找到年末所在周的周六
    const finalDate = new Date(endOfYear);
    finalDate.setDate(finalDate.getDate() + (6 - finalDate.getDay()));
    
    while (currentDate <= finalDate) {
        const weekDiv = document.createElement('div');
        weekDiv.className = 'heatmap-week';
        
        // 生成一周的7天
        for (let day = 0; day < 7; day++) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'heatmap-day';
            
            const dateYear = currentDate.getFullYear();
            const isInYear = dateYear === year;
            const isInFuture = currentDate > today;
            const isValidDate = isInYear && !isInFuture;
            
            if (isValidDate) {
                // 使用本地时间格式化日期（避免时区问题）
                const year = currentDate.getFullYear();
                const month = String(currentDate.getMonth() + 1).padStart(2, '0');
                const day = String(currentDate.getDate()).padStart(2, '0');
                const dateStr = `${year}-${month}-${day}`;
                const minutes = data[dateStr] || 0;
                const level = getLevel(minutes);
                
                dayDiv.setAttribute('data-level', level);
                dayDiv.setAttribute('data-date', dateStr);
                
                // 顶部两行（周日和周一）的 tooltip 向下显示
                if (day <= 1) {
                    dayDiv.classList.add('tooltip-bottom');
                }
                
                // 格式化日期显示
                const displayDate = currentDate.toLocaleDateString('zh-CN', {
                    month: 'short',
                    day: 'numeric',
                    weekday: 'short'
                });
                
                const tooltip = minutes > 0 
                    ? `${displayDate}: ${formatMinutes(minutes)}`
                    : `${displayDate}: 无阅读记录`;
                dayDiv.setAttribute('data-tooltip', tooltip);
                
                if (minutes > 0) {
                    totalActiveDays++;
                    totalYearMinutes += minutes;
                }
            } else {
                // 不在当年或未来的日期，显示为空
                dayDiv.style.visibility = 'hidden';
            }
            
            weekDiv.appendChild(dayDiv);
            currentDate.setDate(currentDate.getDate() + 1);
        }
        
        grid.appendChild(weekDiv);
    }
    
    // 更新总活动数
    const totalEl = document.getElementById('heatmap-total');
    if (totalEl) {
        const totalHours = Math.floor(totalYearMinutes / 60);
        const timeStr = totalHours > 0 ? `${totalHours}h` : `${totalYearMinutes}m`;
        totalEl.textContent = `${totalActiveDays} 天有阅读活动，共 ${timeStr}`;
    }
}

// 渲染统计卡片
async function renderOverviewStats() {
    try {
        // 获取所有论文数量
        let totalPapers = 0;
        try {
            const response = await fetch('/api/papers/all');
            if (response.ok) {
                const papers = await response.json();
                totalPapers = papers.length;
            }
        } catch (e) {
            console.error('获取论文数量失败:', e);
        }
        
        // 从服务器获取每日阅读数据计算总阅读时长
        const historyData = getDailyReadingDataSync();
        const dailyData = getDailyReadingMinutes(historyData);
        
        // 计算总阅读时长（分钟，因为 dailyData 中存储的就是分钟）
        let totalMinutes = 0;
        Object.values(dailyData).forEach(minutes => {
            totalMinutes += (minutes || 0);
        });
        const totalHours = Math.floor(totalMinutes / 60);
        const remainingMinutes = totalMinutes % 60;
        
        // 计算本周数据（从本周一到今天）
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const dayOfWeek = today.getDay(); // 0 = Sunday, 1 = Monday, ..., 6 = Saturday
        const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek; // 如果是周日，往前推6天；否则推到周一
        const monday = new Date(today);
        monday.setDate(today.getDate() + mondayOffset);
        
        let weekMinutes = 0;
        const weekDates = [];
        for (let i = 0; i <= dayOfWeek || (dayOfWeek === 0 && i <= 6); i++) {
            const date = new Date(monday);
            date.setDate(monday.getDate() + i);
            const dateStr = formatDateLocal(date);
            weekDates.push(dateStr);
            weekMinutes += (dailyData[dateStr] || 0);
        }
        
        const weekHours = Math.floor(weekMinutes / 60);
        const weekRemainingMinutes = weekMinutes % 60;
        
        // 计算本周阅读的论文数（精确计算）
        let weekPapers = 0;
        try {
            const response = await fetch('/api/settings/reading-history/week-papers');
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    weekPapers = data.count || 0;
                }
            }
        } catch (e) {
            console.error('获取本周阅读论文数失败:', e);
            // 如果API失败，使用估算方法作为后备
            if (weekMinutes > 0) {
                const estimatedPapers = Math.round(weekMinutes / 45);
                const weekActiveDays = weekDates.filter(dateStr => dailyData[dateStr] && dailyData[dateStr] > 0).length;
                const maxPapers = weekActiveDays * 3;
                weekPapers = Math.max(1, Math.min(estimatedPapers, maxPapers));
            }
        }
        
        // 格式化本周时间显示
        let weekTimeDisplay;
        if (weekHours > 0) {
            weekTimeDisplay = weekRemainingMinutes > 0 ? `${weekHours}h ${weekRemainingMinutes}m` : `${weekHours}h`;
        } else {
            weekTimeDisplay = `${weekMinutes}m`;
        }
        
        // 计算连续阅读天数
        const { currentStreak, bestStreak } = calculateStreaks(dailyData);
        
        // 格式化时间显示
        let timeDisplay;
        if (totalHours > 0) {
            timeDisplay = remainingMinutes > 0 ? `${totalHours}h ${remainingMinutes}m` : `${totalHours}h`;
        } else {
            timeDisplay = `${totalMinutes}m`;
        }
        
        // 更新 UI
        const totalPapersEl = document.getElementById('stat-total-papers');
        const totalTimeEl = document.getElementById('stat-total-time');
        const weekPapersEl = document.getElementById('stat-week-papers');
        const weekTimeEl = document.getElementById('stat-week-time');
        const currentStreakEl = document.getElementById('stat-current-streak');
        const bestStreakEl = document.getElementById('stat-best-streak');
        const userStatsEl = document.getElementById('setting-total-stats');
        
        if (totalPapersEl) totalPapersEl.textContent = totalPapers;
        if (totalTimeEl) totalTimeEl.textContent = timeDisplay;
        if (weekPapersEl) weekPapersEl.textContent = weekPapers;
        if (weekTimeEl) weekTimeEl.textContent = weekTimeDisplay;
        if (currentStreakEl) currentStreakEl.textContent = currentStreak;
        if (bestStreakEl) bestStreakEl.textContent = bestStreak;
        
        // 用户统计摘要
        const summaryHours = totalHours > 0 ? `${totalHours}h` : `${totalMinutes}m`;
        if (userStatsEl) userStatsEl.textContent = `${totalPapers} 篇论文 · ${summaryHours} 阅读`;
        
        console.log('统计数据:', { totalPapers, totalMinutes, totalHours, currentStreak, bestStreak });
        
    } catch (e) {
        console.error('渲染统计数据失败:', e);
    }
}

// 计算连续阅读天数
function calculateStreaks(dailyData) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    let currentStreak = 0;
    let bestStreak = 0;
    let tempStreak = 0;
    
    // 从今天开始往回检查
    const checkDate = new Date(today);
    
    // 检查今天是否有阅读
    const todayStr = formatDateLocal(checkDate);
    if (dailyData[todayStr] && dailyData[todayStr] > 0) {
        currentStreak = 1;
        tempStreak = 1;
    }
    
    // 往回检查
    checkDate.setDate(checkDate.getDate() - 1);
    
    while (true) {
        const dateStr = formatDateLocal(checkDate);
        const hasReading = dailyData[dateStr] && dailyData[dateStr] > 0;
        
        if (hasReading) {
            tempStreak++;
            if (currentStreak > 0 || tempStreak === 1) {
                currentStreak = tempStreak;
            }
        } else {
            if (tempStreak > bestStreak) {
                bestStreak = tempStreak;
            }
            if (currentStreak > 0) {
                // 已经断了，停止计算当前连续
                tempStreak = 0;
            } else {
                tempStreak = 0;
            }
        }
        
        checkDate.setDate(checkDate.getDate() - 1);
        
        // 最多检查 400 天
        const daysDiff = Math.floor((today - checkDate) / (1000 * 60 * 60 * 24));
        if (daysDiff > 400) break;
    }
    
    if (tempStreak > bestStreak) {
        bestStreak = tempStreak;
    }
    if (currentStreak > bestStreak) {
        bestStreak = currentStreak;
    }
    
    return { currentStreak, bestStreak };
}

// 渲染最近阅读活动
function renderRecentActivity() {
    const container = document.getElementById('recent-activity-list');
    if (!container) return;
    
    try {
        const key = 'recentPapers';
        const saved = localStorage.getItem(key);
        let recentItems = [];
        
        if (saved) {
            recentItems = JSON.parse(saved) || [];
        }
        
        // 取最近 5 条
        const displayItems = recentItems.slice(0, 5);
        
        if (displayItems.length === 0) {
            container.innerHTML = `
                <div class="recent-empty">
                    <i class="fas fa-book-open"></i>
                    <p>暂无阅读记录</p>
                </div>
            `;
            return;
        }
        
        // 获取论文信息并渲染
        Promise.all(displayItems.map(async item => {
            try {
                const response = await fetch(`/api/paper/${item.paperId}`);
                if (response.ok) {
                    const paper = await response.json();
                    return { ...item, paper };
                }
            } catch (e) {
                console.error('获取论文信息失败:', e);
            }
            return null;
        })).then(results => {
            const validResults = results.filter(r => r && r.paper);
            
            if (validResults.length === 0) {
                container.innerHTML = `
                    <div class="recent-empty">
                        <i class="fas fa-book-open"></i>
                        <p>暂无阅读记录</p>
                    </div>
                `;
                return;
            }
            
            container.innerHTML = validResults.map(item => {
                const paper = item.paper;
                const viewedAt = new Date(item.viewedAt);
                const timeAgo = getTimeAgo(viewedAt);
                // 计算总阅读时长（PDF + AI解读）
                const totalSeconds = (paper.read_time || 0) + (paper.analysis_view_time || 0);
                const totalMinutes = Math.floor(totalSeconds / 60);
                const readTimeDisplay = totalMinutes > 0 ? `已读 ${totalMinutes} 分钟` : '未读';
                
                return `
                    <div class="recent-item" onclick="openPaperFromRecent('${paper.id}')">
                        <div class="recent-item-icon">
                            <i class="fas fa-file-pdf"></i>
                        </div>
                        <div class="recent-item-content">
                            <div class="recent-item-title">${escapeHtml(paper.title || paper.filename)}</div>
                            <div class="recent-item-meta">${readTimeDisplay}</div>
                        </div>
                        <div class="recent-item-time">${timeAgo}</div>
                    </div>
                `;
            }).join('');
        });
        
    } catch (e) {
        console.error('渲染最近阅读失败:', e);
        container.innerHTML = `
            <div class="recent-empty">
                <i class="fas fa-exclamation-circle"></i>
                <p>加载失败</p>
            </div>
        `;
    }
}

// 计算时间差显示
function getTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins} 分钟前`;
    if (diffHours < 24) return `${diffHours} 小时前`;
    if (diffDays < 7) return `${diffDays} 天前`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} 周前`;
    return date.toLocaleDateString('zh-CN');
}

// 从最近阅读打开论文
function openPaperFromRecent(paperId) {
    switchTab('paper');
    // 打开 PDF 阅读器
    window.open(`/viewer/${paperId}`, '_blank');
}

// ========== Habit 设置 (保留兼容) ==========
function saveHabitSettings() {
    const countEl = document.getElementById('habit-recent-count');
    const count = countEl ? parseInt(countEl.value, 10) : 10;
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

// 显示空状态（未选择任何目录时）
function showEmptyState() {
    // 默认显示待读列表，而不是空状态
    showReadingList();
}

// 保留旧函数名作为别名，默认显示待读列表
async function renderAllPapers() {
    await showReadingList();
}

async function renderRecentIfNoCategory() {
    await showReadingList();
}

// 根据当前视图模式刷新列表（通用函数）
async function refreshCurrentViewList() {
    switch (currentViewMode) {
        case 'translating':
            await showTranslatingPapers();
            break;
        case 'analyzing':
            await showAnalyzingPapers();
            break;
        case 'reading-list':
            await showReadingList();
            break;
        case 'category':
        default:
            if (currentCategoryId) {
                await loadPapers(currentCategoryId);
            } else {
                await renderAllPapers();
            }
            break;
    }
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
    
    // 检查设置（使用新的Agentic统一配置）
    const settings = await getAgenticSettings();
    if (!settings || !settings.llmModel || !settings.llmBaseUrl || !settings.llmApiKey) {
        showMessage('请先在设置中配置AI功能参数（LLM API）', 'warning');
        switchTab('setting');
        return;
    }
    
    // 添加到队列
    if (translationStatus[paperId]) {
        // 该论文已在翻译队列中，不重复添加
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
        
        const settings = await getTranslationSettings();
        const response = await fetch('/api/paper/translate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                openai_model: settings.llmModel,
                openai_base_url: settings.llmBaseUrl,
                openai_api_key: settings.llmApiKey
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
            // 不显示启动提示，用户可以通过状态列看到进度
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
                        // 翻译完成，状态列会自动更新
                    } else {
                        updateTranslationStatus(paperId, 'error', 0, currentTaskId);
                        // 取消时不显示错误消息
                        // 退出码 -15 是 SIGTERM，表示用户主动取消，不显示错误
                        const errorMsg = result.result?.error || '';
                        const isCancelled = status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                        if (status === 'failed' && !isCancelled) {
                            showMessage(errorMsg || '翻译失败', 'error');
                        }
                    }
                    
                    // 继续处理队列
                    isTranslating = false;
                    // 根据当前视图模式刷新列表
                    await refreshCurrentViewList();
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
                    // 根据当前视图模式刷新列表
                    await refreshCurrentViewList();
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
            // 翻译已取消，状态列会自动更新
            stopLogPolling(taskId);
            updateTranslationStatus(paperId, 'error', 0, taskId);
            isTranslating = false;
            // 根据当前视图模式刷新列表
            await refreshCurrentViewList();
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
                // 根据当前视图模式刷新列表
                await refreshCurrentViewList();
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
    // 已从队列中移除，状态列会自动更新
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

// ========== AI解读相关函数（已废弃，使用Agentic统一配置）==========

// 保存解读设置（已废弃）
async function saveAnalysisSettings() {
    console.warn('saveAnalysisSettings is deprecated, use saveAgenticSettings instead');
    return saveAgenticSettings();
}

// 加载解读设置（已废弃）
async function loadAnalysisSettings() {
    console.warn('loadAnalysisSettings is deprecated, use loadAgenticSettings instead');
    return loadAgenticSettings();
}

// 获取解读设置（已废弃）
async function getAnalysisSettings() {
    console.warn('getAnalysisSettings is deprecated, use getAgenticSettings instead');
    return getAgenticSettings();
}

// ========== Zotero 导入相关函数 ==========

// 导入状态
let importEventSource = null;
let importInProgress = false;
let currentImportTaskId = null;

// 初始化导入功能
async function initImportFeature() {
    // 初始化导入类型选项卡切换
    const importTypeTabs = document.querySelectorAll('.import-type-tab');
    importTypeTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const importType = tab.getAttribute('data-import-type');
            switchImportType(importType);
        });
    });
    
    // 初始化 Zotero 导入
    const dropZone = document.getElementById('import-drop-zone');
    const fileInput = document.getElementById('rdf-file-input');
    
    if (!dropZone || !fileInput) return;
    
    // 拖拽事件
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-over');
    });
    
    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleRdfFile(files[0]);
        }
    });
    
    // 点击上传
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleRdfFile(e.target.files[0]);
        }
    });
    
    // 填充目标目录选择列表（获取最新数据）
    await populateImportTargetCategories();
    
    // 检查是否有正在进行的导入任务（页面刷新后恢复）
    checkExistingImportTask();
    
    // 初始化从导出文件导入
    initExportFileImport();
    
    console.log('Import 功能初始化完成');
}

// 切换导入类型
function switchImportType(type) {
    // 更新选项卡状态
    document.querySelectorAll('.import-type-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.getAttribute('data-import-type') === type) {
            tab.classList.add('active');
        }
    });
    
    // 切换面板显示
    const zoteroPanel = document.getElementById('import-zotero-panel');
    const exportPanel = document.getElementById('import-export-panel');
    
    if (type === 'zotero') {
        zoteroPanel.style.display = 'block';
        exportPanel.style.display = 'none';
    } else if (type === 'export') {
        zoteroPanel.style.display = 'none';
        exportPanel.style.display = 'block';
    }
}

// 初始化从导出文件导入
function initExportFileImport() {
    const dropZone = document.getElementById('export-import-drop-zone');
    const fileInput = document.getElementById('export-file-input');
    
    if (!dropZone || !fileInput) return;
    
    // 拖拽事件
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-over');
    });
    
    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleExportZipFile(files[0]);
        }
    });
    
    // 点击上传
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleExportZipFile(e.target.files[0]);
        }
    });
}

// 处理导出 ZIP 文件
async function handleExportZipFile(file) {
    if (!file.name.toLowerCase().endsWith('.zip')) {
        showMessage('请选择 ZIP 文件', 'error');
        return;
    }
    
    const dropZone = document.getElementById('export-import-drop-zone');
    const dropZoneContent = document.getElementById('export-drop-zone-content');
    const progressContainer = document.getElementById('export-import-progress-container');
    
    // 隐藏拖拽区域内容，显示进度
    if (dropZoneContent) dropZoneContent.style.display = 'none';
    progressContainer.style.display = 'block';
    
    // 重置进度
    updateExportImportProgress({
        status: 'uploading',
        progress: 0,
        current: 0,
        total: 0,
        message: '正在上传文件...',
        success_count: 0,
        failed_count: 0,
        skipped_count: 0,
        duplicate_count: 0,
    });
    
    // 使用 XMLHttpRequest 以支持上传进度
    const formData = new FormData();
    formData.append('file', file);
    
    const xhr = new XMLHttpRequest();
    
    // 监听上传进度
    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
            const percentComplete = Math.round((e.loaded / e.total) * 100);
            updateExportImportProgress({
                status: 'uploading',
                progress: percentComplete,
                current: e.loaded,
                total: e.total,
                message: `正在上传文件... ${percentComplete}%`,
                success_count: 0,
                failed_count: 0,
                skipped_count: 0,
                duplicate_count: 0,
            });
        }
    });
    
    // 监听上传完成
    xhr.addEventListener('load', () => {
        if (xhr.status === 200) {
            try {
                const data = JSON.parse(xhr.responseText);
                
                if (!data.success) {
                    showMessage(data.error || '导入失败', 'error');
                    if (dropZoneContent) dropZoneContent.style.display = 'flex';
                    progressContainer.style.display = 'none';
                    return;
                }
                
                // 上传完成，开始处理
                updateExportImportProgress({
                    status: 'processing',
                    progress: 100,
                    current: 0,
                    total: 0,
                    message: '文件上传完成，开始解压并导入...',
                    success_count: 0,
                    failed_count: 0,
                    skipped_count: 0,
                    duplicate_count: 0,
                });
                
                // 开始监听导入进度
                const taskId = data.task_id;
                startExportImportProgressStream(taskId);
                
                showMessage('导入任务已启动', 'success');
                
            } catch (error) {
                console.error('解析响应失败:', error);
                showMessage('导入失败: ' + error.message, 'error');
                if (dropZoneContent) dropZoneContent.style.display = 'flex';
                progressContainer.style.display = 'none';
            }
        } else {
            showMessage(`上传失败: HTTP ${xhr.status}`, 'error');
            if (dropZoneContent) dropZoneContent.style.display = 'flex';
            progressContainer.style.display = 'none';
        }
    });
    
    // 监听上传错误
    xhr.addEventListener('error', () => {
        showMessage('上传失败: 网络错误', 'error');
        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        progressContainer.style.display = 'none';
    });
    
    // 监听上传取消
    xhr.addEventListener('abort', () => {
        showMessage('上传已取消', 'error');
        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        progressContainer.style.display = 'none';
    });
    
    // 发送请求
    xhr.open('POST', '/api/import/from-export');
    xhr.send(formData);
}

// 开始监听导出文件导入进度（SSE）
function startExportImportProgressStream(taskId) {
    let exportImportEventSource = new EventSource(`/api/import/zotero/progress/${taskId}`);
    
    exportImportEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateExportImportProgress(data);
            
            // 如果完成或失败，关闭连接
            if (data.status === 'completed' || data.status === 'error') {
                exportImportEventSource.close();
                
                // 确保关闭加载状态
                showLoading(false);
                
                // 立即重置 UI，移除进度显示
                const dropZoneContent = document.getElementById('export-drop-zone-content');
                const progressContainer = document.getElementById('export-import-progress-container');
                if (dropZoneContent) dropZoneContent.style.display = 'flex';
                if (progressContainer) progressContainer.style.display = 'none';
                
                // 静默刷新分类树（不显示加载状态）
                loadCategories(true).catch(err => {
                    console.error('刷新分类树失败:', err);
                });
            }
        } catch (e) {
            console.error('解析进度数据失败:', e);
        }
    };
    
    exportImportEventSource.onerror = (e) => {
        console.error('SSE 连接错误:', e);
        if (exportImportEventSource) {
            exportImportEventSource.close();
        }
    };
}

// 更新导出文件导入进度
function updateExportImportProgress(data) {
    const { status, progress, current, total, message, success_count, failed_count, skipped_count, duplicate_count } = data;
    
    const statusText = document.getElementById('export-import-status-text');
    const progressPercent = document.getElementById('export-import-progress-percent');
    const progressFill = document.getElementById('export-import-progress-fill');
    const currentItem = document.getElementById('export-import-current-item');
    const successCountEl = document.getElementById('export-import-success-count');
    const failedCountEl = document.getElementById('export-import-failed-count');
    const skippedCountEl = document.getElementById('export-import-skipped-count');
    const duplicateCountEl = document.getElementById('export-import-duplicate-count');
    
    if (status === 'parsing' || status === 'uploading') {
        statusText.textContent = message || '正在处理...';
        progressPercent.textContent = '0%';
        progressFill.style.width = '0%';
    } else if (status === 'importing') {
        statusText.textContent = '正在导入论文...';
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        progressPercent.textContent = `${percent}%`;
        progressFill.style.width = percent + '%';
        currentItem.textContent = message || '';
    } else if (status === 'completed') {
        statusText.textContent = '导入完成！';
        statusText.style.color = '#2da44e';
        progressPercent.textContent = '100%';
        progressFill.style.width = '100%';
        currentItem.textContent = `成功导入 ${success_count} 篇论文`;
        currentItem.style.color = '#2da44e';
    } else if (status === 'error') {
        statusText.textContent = '导入失败';
        statusText.style.color = '#d73a49';
        currentItem.textContent = message || '未知错误';
        currentItem.style.color = '#d73a49';
    }
    
    // 更新计数
    if (successCountEl) successCountEl.textContent = success_count || 0;
    if (failedCountEl) failedCountEl.textContent = failed_count || 0;
    if (skippedCountEl) skippedCountEl.textContent = skipped_count || 0;
    if (duplicateCountEl) duplicateCountEl.textContent = duplicate_count || 0;
}

// 填充导入目标目录选择列表（异步获取最新目录数据）
async function populateImportTargetCategories() {
    const select = document.getElementById('import-target-category');
    if (!select) return;
    
    // 保留当前选中的值
    const currentValue = select.value;
    
    // 保留默认选项
    select.innerHTML = '<option value="">根目录（默认）</option>';
    
    try {
        // 从 API 获取最新的目录数据
        const response = await fetch('/api/categories');
        const latestCategories = await response.json();
        
        // 递归添加目录选项
        function addCategoryOptions(node, level = 0) {
            if (!node.children) return;
            
            node.children.forEach(child => {
                const indent = '　'.repeat(level); // 使用全角空格缩进
                const option = document.createElement('option');
                option.value = child.id;
                option.textContent = `${indent}📁 ${child.name}`;
                select.appendChild(option);
                
                // 递归添加子目录
                if (child.children && child.children.length > 0) {
                    addCategoryOptions(child, level + 1);
                }
            });
        }
        
        addCategoryOptions(latestCategories);
        
        // 恢复之前选中的值（如果仍然存在）
        if (currentValue) {
            const optionExists = Array.from(select.options).some(opt => opt.value === currentValue);
            if (optionExists) {
                select.value = currentValue;
            }
        }
        
        // 同时更新全局变量，保持一致性
        categories = latestCategories;
    } catch (error) {
        console.error('获取目录数据失败:', error);
        // 如果获取失败，使用全局变量作为后备
        function addCategoryOptions(node, level = 0) {
            if (!node.children) return;
            
            node.children.forEach(child => {
                const indent = '　'.repeat(level);
                const option = document.createElement('option');
                option.value = child.id;
                option.textContent = `${indent}📁 ${child.name}`;
                select.appendChild(option);
                
                if (child.children && child.children.length > 0) {
                    addCategoryOptions(child, level + 1);
                }
            });
        }
        addCategoryOptions(categories);
    }
}

// 检查是否有正在进行的导入任务
async function checkExistingImportTask() {
    try {
        const response = await fetch('/api/import/zotero/status');
        const data = await response.json();
        
        if (data.has_task && data.status !== 'completed' && data.status !== 'error') {
            console.log('发现正在进行的导入任务:', data.task_id);
            importInProgress = true;
            
            // 显示进度界面
            document.getElementById('drop-zone-content').style.display = 'none';
            document.getElementById('import-progress-container').style.display = 'block';
            document.getElementById('import-result').style.display = 'none';
            
            // 更新当前进度
            updateImportStatus(
                `正在导入论文 (${data.current}/${data.total})...`,
                data.progress,
                data.message || '处理中...'
            );
            
            // 重新连接 SSE
            currentImportTaskId = data.task_id;
            startImportProgressStream(data.task_id);
        } else if (data.has_task && data.status === 'completed') {
            // 任务已完成，直接重置界面，不显示结果
            importInProgress = false;
            currentImportTaskId = null;
            showLoading(false);
            
            const dropZoneContent = document.getElementById('drop-zone-content');
            const progressContainer = document.getElementById('import-progress-container');
            const importResult = document.getElementById('import-result');
            
            if (dropZoneContent) dropZoneContent.style.display = 'flex';
            if (progressContainer) progressContainer.style.display = 'none';
            if (importResult) importResult.style.display = 'none';
            
            // 显示成功消息
            const msg = `导入完成！成功 ${data.success_count || 0} 篇`;
            showMessage(msg, 'success');
            
            // 静默刷新分类树（不显示加载状态）
            loadCategories(true).catch(err => {
                console.error('刷新分类树失败:', err);
            });
        }
    } catch (e) {
        console.log('检查导入任务状态失败:', e);
    }
}

// 处理 RDF 文件上传
async function handleRdfFile(file) {
    if (!file.name.toLowerCase().endsWith('.rdf')) {
        showMessage('请上传 .rdf 格式的文件', 'error');
        return;
    }
    
    if (importInProgress) {
        showMessage('正在导入中，请等待完成', 'warning');
        return;
    }
    
    importInProgress = true;
    
    // 隐藏上传区域，显示进度
    document.getElementById('drop-zone-content').style.display = 'none';
    document.getElementById('import-progress-container').style.display = 'block';
    document.getElementById('import-result').style.display = 'none';
    
    updateImportStatus('正在上传 RDF 文件...', 0, '准备中...');
    
    // 获取目标目录
    const targetCategoryId = document.getElementById('import-target-category')?.value || '';
    
    // 上传文件
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_category_id', targetCategoryId);
    
    try {
        const response = await fetch('/api/import/zotero', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '上传失败');
        }
        
        const result = await response.json();
        
        if (result.success) {
            // 如果有恢复导入的信息，显示提示
            if (result.already_imported > 0) {
                showMessage(
                    `检测到 ${result.already_imported} 篇论文已导入，将从第 ${result.already_imported + 1} 篇开始继续导入`,
                    'info'
                );
            }
            
            // 开始监听导入进度
            startImportProgressStream(result.task_id);
        } else {
            // 如果所有论文都已导入，显示特殊提示
            if (result.already_imported && result.original_total && result.already_imported === result.original_total) {
                showMessage('所有论文都已导入，无需重复导入', 'info');
                resetImport();
            } else {
                throw new Error(result.error || '导入失败');
            }
        }
    } catch (error) {
        console.error('导入失败:', error);
        showMessage('导入失败: ' + error.message, 'error');
        resetImport();
    }
}

// 开始监听导入进度（SSE）
function startImportProgressStream(taskId) {
    if (importEventSource) {
        importEventSource.close();
    }
    
    currentImportTaskId = taskId;
    
    // 取消按钮已隐藏，不再显示
    // const cancelBtn = document.getElementById('cancel-import-btn');
    // if (cancelBtn) {
    //     cancelBtn.style.display = 'inline-block';
    // }
    
    importEventSource = new EventSource(`/api/import/zotero/progress/${taskId}`);
    
    importEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleImportProgress(data);
        } catch (e) {
            console.error('解析进度数据失败:', e);
        }
    };
    
    importEventSource.onerror = (e) => {
        console.error('SSE 连接错误:', e);
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
    };
}

// 处理导入进度更新
let lastRefreshTime = 0;
const REFRESH_INTERVAL = 3000; // 每3秒刷新一次论文列表

function handleImportProgress(data) {
    const { status, progress, current, total, message, success_count, failed_count, skipped_count, duplicate_count, others_count, original_total, already_imported_count } = data;
    
    if (status === 'parsing') {
        updateImportStatus('正在解析 RDF 文件...', 0, message || '获取论文信息中...');
    } else if (status === 'importing') {
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        let statusText = `正在导入论文 (${current}/${total})...`;
        let detailText = message || `处理中...`;
        
        // 如果有恢复导入的信息，显示在详情中
        if (already_imported_count > 0 && original_total) {
            const actualCurrent = already_imported_count + current;
            statusText = `正在导入论文 (${actualCurrent}/${original_total})...`;
            if (!message || !message.includes('已导入')) {
                detailText = `已跳过 ${already_imported_count} 篇已导入的论文，${message || '处理中...'}`;
            }
        }
        
        updateImportStatus(
            statusText,
            percent,
            detailText
        );
        
        // 定期刷新论文列表（如果当前在主页）
        const now = Date.now();
        if (now - lastRefreshTime > REFRESH_INTERVAL) {
            lastRefreshTime = now;
            // 如果当前在分类视图，刷新论文列表
            if (currentCategoryId) {
                loadPapers(currentCategoryId).catch(err => {
                    console.error('刷新论文列表失败:', err);
                });
            }
        }
    } else if (status === 'cancelled' || status === 'cancelling') {
        // 导入已取消
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;
        
        // 隐藏取消按钮
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }
        
        // 更新状态显示
        updateImportStatus('导入已取消', progress || 0, message || '导入任务已取消');
        
        // 移除所有加载状态
        showLoading(false);
        
        // 显示取消消息
        showMessage('导入已取消', 'warning');
        
        // 延迟后重置界面
        setTimeout(() => {
            resetImport();
        }, 2000);
    } else if (status === 'completed') {
        // 导入完成
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;
        
        // 隐藏取消按钮
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }
        
        // 移除所有加载状态
        showLoading(false);
        
        // 直接隐藏所有导入相关的UI，恢复到正常状态
        const dropZoneContent = document.getElementById('drop-zone-content');
        const progressContainer = document.getElementById('import-progress-container');
        const importResult = document.getElementById('import-result');
        
        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        if (progressContainer) progressContainer.style.display = 'none';
        if (importResult) importResult.style.display = 'none';
        
        // 重置文件输入
        const fileInput = document.getElementById('rdf-file-input');
        if (fileInput) fileInput.value = '';
        
        // 静默刷新分类树（不显示加载状态）
        loadCategories(true).catch(err => {
            console.error('刷新分类树失败:', err);
        });
        
        // 如果当前在分类视图，刷新论文列表
        if (currentCategoryId) {
            loadPapers(currentCategoryId).catch(err => {
                console.error('刷新论文列表失败:', err);
            });
        }
    } else if (status === 'error') {
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;
        
        // 隐藏取消按钮
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }
        
        // 移除加载状态
        showLoading(false);
        showMessage('导入失败: ' + (message || '未知错误'), 'error');
        resetImport();
    }
}

// 取消导入
async function cancelImport() {
    if (!currentImportTaskId) {
        showMessage('没有正在进行的导入任务', 'warning');
        return;
    }
    
    const cancelBtn = document.getElementById('cancel-import-btn');
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 取消中...';
    }
    
    try {
        const response = await fetch(`/api/import/zotero/cancel/${currentImportTaskId}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('正在取消导入...', 'info');
        } else {
            showMessage('取消失败: ' + (result.error || '未知错误'), 'error');
            if (cancelBtn) {
                cancelBtn.disabled = false;
                cancelBtn.innerHTML = '<i class="fas fa-times"></i> 取消导入';
            }
        }
    } catch (error) {
        console.error('取消导入失败:', error);
        showMessage('取消导入失败: ' + error.message, 'error');
        if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<i class="fas fa-times"></i> 取消导入';
        }
    }
}

// 更新导入状态显示
function updateImportStatus(statusText, percent, detail) {
    const statusTextEl = document.getElementById('import-status-text');
    const progressFill = document.getElementById('import-progress-fill');
    const progressDetail = document.getElementById('import-progress-detail');
    
    if (statusTextEl) statusTextEl.textContent = statusText;
    if (progressFill) progressFill.style.width = percent + '%';
    if (progressDetail) progressDetail.textContent = detail;
}

// 显示导入结果（已废弃，导入完成后直接重置界面，不显示结果）
function showImportResult(successCount, failedCount, skippedCount, duplicateCount = 0, othersCount = 0) {
    // 不再显示结果界面，直接重置
    importInProgress = false;
    currentImportTaskId = null;
    showLoading(false);
    
    const dropZoneContent = document.getElementById('drop-zone-content');
    const progressContainer = document.getElementById('import-progress-container');
    const importResult = document.getElementById('import-result');
    
    if (dropZoneContent) dropZoneContent.style.display = 'flex';
    if (progressContainer) progressContainer.style.display = 'none';
    if (importResult) importResult.style.display = 'none';
    
    // 显示成功消息
    let msg = `导入完成！成功 ${successCount} 篇`;
    if (failedCount > 0) msg += `，失败 ${failedCount} 篇`;
    if (skippedCount > 0) msg += `，跳过 ${skippedCount} 篇`;
    if (duplicateCount > 0) msg += `，重复 ${duplicateCount} 篇`;
    showMessage(msg, 'success');
}

// 重置导入界面
function resetImport() {
    importInProgress = false;
    currentImportTaskId = null;
    
    if (importEventSource) {
        importEventSource.close();
        importEventSource = null;
    }
    
    // 隐藏取消按钮
    const cancelBtn = document.getElementById('cancel-import-btn');
    if (cancelBtn) {
        cancelBtn.style.display = 'none';
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = '<i class="fas fa-times"></i> 取消导入';
    }
    
    document.getElementById('drop-zone-content').style.display = 'flex';
    document.getElementById('import-progress-container').style.display = 'none';
    document.getElementById('import-result').style.display = 'none';
    
    // 重置文件输入
    const fileInput = document.getElementById('rdf-file-input');
    if (fileInput) fileInput.value = '';
}

// 切换到指定的 setting 面板
async function switchSettingPanel(panelName) {
    document.querySelectorAll('.setting-nav-item').forEach(b => b.classList.remove('active'));
    const targetBtn = document.querySelector(`.setting-nav-item[data-setting="${panelName}"]`);
    if (targetBtn) targetBtn.classList.add('active');
    
    document.querySelectorAll('.setting-panel').forEach(p => p.style.display = 'none');
    const targetPanel = document.getElementById(`setting-panel-${panelName}`);
    if (targetPanel) targetPanel.style.display = 'block';
    
    // 如果切换到 Import 面板，刷新目录选择列表（获取最新数据）
    if (panelName === 'import') {
        await populateImportTargetCategories();
    }
    
    // 如果切换到 Export 面板，重置 UI
    if (panelName === 'export') {
        resetExportUI();
    }
    
    // 如果切换到 Daily arXiv 面板，加载设置
    if (panelName === 'daily-arxiv') {
        await loadDailyArxivSettings();
        const maxKeywordsInput = document.getElementById('daily-arxiv-max-keywords');
        if (maxKeywordsInput) {
            maxKeywordsInput.value = dailyArxivSettings.maxKeywords || 1;
        }
        // 绑定关键词输入框回车事件
        setupDailyArxivKeywordInput();
    }
    
    // 保存状态
    saveCurrentViewState();
}

// 切换到概览页面
function switchToOverview() {
    switchSettingPanel('overview');
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
        // 注意：不在这里刷新视图，由 restoreViewState 统一处理
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

    // 检查设置（使用新的Agentic统一配置）
    const settings = await getAgenticSettings();
    if (!settings || !settings.mineruServerUrl || !settings.llmBaseUrl || !settings.llmApiKey) {
        showMessage('请先在设置中配置AI功能参数（LLM API和MinerU服务）', 'warning');
        // 切换到设置页面
        document.querySelector('.nav-tab[data-tab="setting"]').click();
        return;
    }
    // 注意：systemPrompt 可以为空，使用默认值

    // 检查是否已在队列中或正在解读
    if (analysisStatus[paperId]) {
        const status = analysisStatus[paperId].status;
        if (status === 'analyzing' || status === 'queued') {
            // 该论文已在解读队列中，不重复添加
            return;
        }
    }

    // 添加到队列
    analysisQueue.push(paperId);
    
    // 更新状态
    const queuePosition = analysisQueue.length;
    updateAnalysisStatus(paperId, 'queued', queuePosition);
    saveQueuesToStorage();
    
    // 立即更新显示（根据当前视图模式）
    if (currentViewMode === 'reading-list') {
        // 待读列表中只更新单个论文状态，不刷新整个列表
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        renderPapersList();
    } else {
        renderAllPapers();
    }
    
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
        const settings = await getAnalysisSettings();
        if (!settings) {
            throw new Error('设置未配置');
        }

        // 调用后端API（使用新的Agentic统一配置）
        const response = await fetch('/api/paper/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                mineru_server_url: settings.mineruServerUrl,
                openai_base_url: settings.llmBaseUrl,
                openai_api_key: settings.llmApiKey,
                system_prompt: settings.analysisSystemPrompt || ''
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
                    // 解读完成，状态列会自动更新
                    // 根据当前视图模式刷新列表
                    await refreshCurrentViewList();
                    if (currentPaperId === paperId) {
                        loadPaperInfo(paperId);
                    }
                    processAnalysisQueue(); // 继续处理队列
                } else if (result.status === 'failed' || result.status === 'cancelled') {
                    updateAnalysisStatus(paperId, 'error');
                    isAnalyzing = false;
                    stopAnalysisLogPolling(taskId);
                    // 取消时不显示错误消息，只有真正失败时才显示
                    // 退出码 -15 是 SIGTERM，表示用户主动取消，不显示错误
                    const errorMsg = result.result?.error || '';
                    const isCancelled = result.status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                    if (result.status === 'failed' && !isCancelled) {
                        showMessage(`解读失败: ${errorMsg || '未知错误'}`, 'error');
                    }
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
    
    const paper = papers.find(p => p.id === paperId);
    if (!paper) return;
    
    // 更新列表视图中的状态列（.paper-col-action）
    const actionCols = paperItem.querySelectorAll('.paper-col-action');
    if (actionCols.length >= 2) {
        // 翻译列是第一个 .paper-col-action（索引0是图标列后的第一个操作列）
        // 实际上按顺序是：icon, title, date, translate(0), analyze(1), reading(2)
        // 但 .paper-col-action 只包括 translate, analyze, reading
        const translateActionCol = actionCols[0];
        const analyzeActionCol = actionCols[1];
        
        // 更新翻译列
        const tStatus = translationStatus[paperId];
        let translateColHtml = '';
        if (tStatus && tStatus.status === 'translating') {
            translateColHtml = `<span class="paper-action-status processing"><i class="fas fa-spinner fa-spin"></i> 翻译中...<button class="paper-action-stop" onclick="cancelTranslation('${paperId}', event)" title="停止翻译"><i class="fas fa-times"></i></button></span>`;
        } else if (tStatus && tStatus.status === 'queued') {
            translateColHtml = `<span class="paper-action-status processing"><i class="fas fa-clock"></i> 队列中<button class="paper-action-stop" onclick="cancelTranslation('${paperId}', event)" title="取消队列"><i class="fas fa-times"></i></button></span>`;
        } else if (paper.has_chinese_version) {
            translateColHtml = `<button class="paper-col-btn view chinese" onclick="openChineseVersion('${paperId}', event)"><i class="fas fa-language"></i> 中文版</button>`;
        } else {
            translateColHtml = `<button class="paper-col-btn translate icon-only" onclick="requestTranslation('${paperId}', event)" title="AI翻译"><i class="fas fa-language"></i></button>`;
        }
        translateActionCol.innerHTML = translateColHtml;
        
        // 更新解读列
        const aStatus = analysisStatus[paperId];
        let analyzeColHtml = '';
        if (aStatus && aStatus.status === 'analyzing') {
            const step = aStatus.step === 'pdf2md' ? 'PDF解析中...' : 'LLM解读中...';
            analyzeColHtml = `<span class="paper-action-status processing"><i class="fas fa-spinner fa-spin"></i> ${step}<button class="paper-action-stop" onclick="cancelAnalysis('${paperId}', event)" title="停止解读"><i class="fas fa-times"></i></button></span>`;
        } else if (aStatus && aStatus.status === 'queued') {
            analyzeColHtml = `<span class="paper-action-status processing"><i class="fas fa-clock"></i> 队列中<button class="paper-action-stop" onclick="cancelAnalysis('${paperId}', event)" title="取消队列"><i class="fas fa-times"></i></button></span>`;
        } else if (paper.has_analysis_result) {
            analyzeColHtml = `<button class="paper-col-btn view analysis" onclick="viewAnalysisResult('${paperId}', event)"><i class="fas fa-brain"></i> AI解读</button>`;
        } else {
            analyzeColHtml = `<button class="paper-col-btn analyze icon-only" onclick="requestAnalysis('${paperId}', event)" title="AI解读"><i class="fas fa-brain"></i></button>`;
        }
        analyzeActionCol.innerHTML = analyzeColHtml;
    }
    
    // 同时更新 .paper-meta 中的状态（用于详情视图）
    const paperMeta = paperItem.querySelector('.paper-meta');
    if (paperMeta) {
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
                        // 解读完成，状态列会自动更新
                    } else {
                        updateAnalysisStatus(paperId, 'error');
                        // 取消时不显示错误消息，只有真正失败时才显示
                        // 退出码 -15 是 SIGTERM，表示用户主动取消，不显示错误
                        const errorMsg = result.result?.error || '';
                        const isCancelled = status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                        if (status === 'failed' && !isCancelled) {
                            showMessage(`解读失败: ${errorMsg || '未知错误'}`, 'error');
                        }
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
            await cancelAnalysisTask(taskId, paperId);
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
                            // 解读完成，状态列会自动更新
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

// 取消解读任务（从状态中取消，需要taskId）
async function cancelAnalysisTask(taskId, paperId) {
    try {
        const response = await fetch(`/api/paper/analyze/${taskId}/cancel`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // 解读已取消，状态列会自动更新
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
                // 根据当前视图模式更新显示
                if (currentViewMode === 'reading-list' || currentViewMode === 'analyzing') {
                    updatePaperStatusDisplay(paperId);
                } else if (currentCategoryId) {
                    updatePaperStatusDisplay(paperId);
                } else {
                    await refreshCurrentViewList();
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
    await cancelAnalysisTask(status.taskId, paperId);
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
    // 直接更新显示，不调用 updateAnalysisStatus（因为状态已删除）
    updatePaperStatusDisplay(paperId);
    updateTaskIndicator();
    // 已从队列中移除，状态列会自动更新
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
            </div>
            <button class="analysis-fullscreen-btn" onclick="openAnalysisFullscreen('${paperId}')" title="全屏查看"><i class="fas fa-expand"></i></button>
            <button class="analysis-close-btn" onclick="closeAnalysisView()" title="关闭"><i class="fas fa-times"></i></button>
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

// 全屏查看 AI 解读
function openAnalysisFullscreen(paperId) {
    // 在新窗口中打开全屏查看器
    const url = `/viewer/analysis/${paperId}`;
    window.open(url, '_blank', 'width=1200,height=800');
}

function closeAnalysisView() {
    const panel = document.querySelector('.info-panel');
    if (panel) {
        panel.classList.remove('wide');
        // 清除内联样式，恢复默认宽度（通过CSS类控制）
        panel.style.width = '';
    }
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
    if (status.taskId && status.status === 'translating') {
        fetch(`/api/paper/translate/${status.taskId}/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // 已取消翻译，状态列会自动更新
                    // 如果当前正在翻译的是这个任务，重置翻译标志
                    if (isTranslating) {
                        isTranslating = false;
                        // 继续处理队列中的下一个任务
                        processTranslationQueue();
                    }
                } else {
                    showMessage(data.error || '取消翻译失败', 'error');
                }
            })
            .catch(err => {
                console.error('取消翻译失败:', err);
                showMessage('取消翻译失败', 'error');
            });
    }
    
    // 清理状态
    delete translationStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();
    
    // 刷新显示（根据当前视图模式）
    if (currentViewMode === 'reading-list' || currentViewMode === 'translating') {
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
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
    if (status.taskId && status.status === 'analyzing') {
        fetch(`/api/paper/analyze/${status.taskId}/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // 已取消解读，状态列会自动更新
                    // 如果当前正在解读的是这个任务，重置解读标志
                    if (isAnalyzing) {
                        isAnalyzing = false;
                        // 继续处理队列中的下一个任务
                        processAnalysisQueue();
                    }
                } else {
                    showMessage(data.error || '取消解读失败', 'error');
                }
            })
            .catch(err => {
                console.error('取消解读失败:', err);
                showMessage('取消解读失败', 'error');
            });
    }
    
    // 清理状态
    delete analysisStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();
    
    // 刷新显示（根据当前视图模式）
    if (currentViewMode === 'reading-list' || currentViewMode === 'analyzing') {
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderAllPapers();
    }
}

// ========================================
// Daily arXiv 功能
// ========================================

let dailyArxivPapers = {};  // 按日期和分区存储: {date: {category: [papers]}}
let dailyArxivCategories = [];
let dailyArxivCurrentCategory = 'all';  // 当前选中的分区，'all' 表示显示所有分区
let dailyArxivCurrentDate = null;  // 当前选中的日期
let dailyArxivAvailableDates = [];  // 可用的日期列表
let dailyArxivSettings = {
    categories: [],
    retentionDays: 7,
    checkIntervalMinutes: 10,
};
let dailyArxivProgressIntervals = {};  // 每个分区的进度轮询定时器: {category: intervalId}
let dailyArxivSearchQuery = '';        // Daily arXiv 页面搜索查询
let dailyArxivLLMConfigured = false;  // LLM 配置状态
let dailyArxivSlowDownloadNotified = {};  // 记录每个分区是否已显示慢速下载提示: {category: true}
let dailyArxivLastPaperKey = '';  // 跟踪上一个论文的key，用于检测论文切换
let dailyArxivSelectedAffiliations = new Set(); // 当前选中的单位过滤条件
let dailyArxivSelectedCountries = new Set(); // 当前选中的地区过滤条件
let dailyArxivSelectedKeywords = new Set(); // 当前选中的关键词过滤条件
let dailyArxivExcludedAffiliations = new Set(); // 被排除的单位（反向过滤）
let dailyArxivExcludedCountries = new Set(); // 被排除的地区（反向过滤）
let dailyArxivExcludedKeywords = new Set(); // 被排除的关键词（反向过滤）
let dailyArxivKnownInstitutions = new Set(); // 所有已知机构（系统预设 + 用户自定义）
let dailyArxivFilterFirstAffiliation = false; // 是否过滤第一单位
let dailyArxivFilterKnownInstitutions = false; // 是否只显示常见机构
let dailyArxivHideUnknownFirstAffiliation = false; // 是否隐藏第一单位属于"其他机构"的论文

// 地区名称标准化映射表
function normalizeCountryName(countryName) {
    if (!countryName) return '';
    
    const normalized = countryName.trim();
    
    // 标准化映射表：将各种变体映射到标准名称
    const normalizationMap = {
        // 美国的各种变体 -> United States
        'USA': 'United States',
        'US': 'United States',
        'U.S.': 'United States',
        'U.S.A.': 'United States',
        'United States of America': 'United States',
        
        // 英国的各种变体 -> United Kingdom
        'UK': 'United Kingdom',
        'U.K.': 'United Kingdom',
        'Great Britain': 'United Kingdom',
        'Britain': 'United Kingdom',
        
        // 中国的各种变体 -> China
        'PRC': 'China',
        'P.R.C.': 'China',
        "People's Republic of China": 'China',
        
        // 韩国的各种变体 -> South Korea
        'Korea': 'South Korea',
        'Republic of Korea': 'South Korea',
        'ROK': 'South Korea',
        
        // 香港的各种变体 -> Hong Kong
        'Hong Kong SAR': 'Hong Kong',
        'Hong Kong SAR China': 'Hong Kong',
        'Hong Kong, SAR China': 'Hong Kong',
        'Hong Kong SAR, China': 'Hong Kong',
        'Hong Kong, China': 'Hong Kong',
        'HK': 'Hong Kong',
        
        // 澳门的各种变体 -> Macao
        'Macau': 'Macao',
        'Macao SAR': 'Macao',
        'Macao SAR China': 'Macao',
        'Macao, SAR China': 'Macao',
        'Macao SAR, China': 'Macao',
        'Macao, China': 'Macao',
        'Macau SAR': 'Macao',
        'Macau SAR China': 'Macao',
        'Macau, SAR China': 'Macao',
        'Macau SAR, China': 'Macao',
        'Macau, China': 'Macao',
        
        // 阿联酋的各种变体 -> United Arab Emirates
        'UAE': 'United Arab Emirates',
        'U.A.E.': 'United Arab Emirates',
    };
    
    // 先尝试精确匹配
    if (normalizationMap[normalized]) {
        return normalizationMap[normalized];
    }
    
    // 不区分大小写匹配
    const normalizedLower = normalized.toLowerCase();
    for (const [variant, standard] of Object.entries(normalizationMap)) {
        if (variant.toLowerCase() === normalizedLower) {
            return standard;
        }
    }
    
    // 如果没有找到映射，返回原始名称
    return normalized;
}

// 地区名称到国旗 emoji 的映射
function getCountryFlag(countryName) {
    if (!countryName) return '';
    
    // 扩展的国家映射表，包含更多国家和变体
    const countryMap = {
        // 主要国家
        'United States': '🇺🇸', 'USA': '🇺🇸', 'US': '🇺🇸', 'U.S.': '🇺🇸', 'U.S.A.': '🇺🇸', 'United States of America': '🇺🇸',
        'China': '🇨🇳', 'PRC': '🇨🇳', 'P.R.C.': '🇨🇳', "People's Republic of China": '🇨🇳',
        'United Kingdom': '🇬🇧', 'UK': '🇬🇧', 'U.K.': '🇬🇧', 'Great Britain': '🇬🇧', 'Britain': '🇬🇧',
        'Germany': '🇩🇪',
        'France': '🇫🇷',
        'Japan': '🇯🇵',
        'Canada': '🇨🇦',
        'Australia': '🇦🇺',
        'Italy': '🇮🇹',
        'Spain': '🇪🇸',
        'Netherlands': '🇳🇱',
        'Switzerland': '🇨🇭',
        'Sweden': '🇸🇪',
        'Singapore': '🇸🇬',
        'South Korea': '🇰🇷', 'Korea': '🇰🇷', 'Republic of Korea': '🇰🇷', 'ROK': '🇰🇷',
        'India': '🇮🇳',
        'Israel': '🇮🇱',
        'Belgium': '🇧🇪',
        'Austria': '🇦🇹',
        'Denmark': '🇩🇰',
        'Finland': '🇫🇮',
        'Norway': '🇳🇴',
        'Poland': '🇵🇱',
        'Russia': '🇷🇺', 'Russian Federation': '🇷🇺',
        'Brazil': '🇧🇷',
        'Mexico': '🇲🇽',
        'Taiwan': '🇹🇼',
        'Hong Kong': '🇭🇰', 'Hong Kong SAR': '🇭🇰', 'Hong Kong SAR China': '🇭🇰', 'Hong Kong, SAR China': '🇭🇰', 'Hong Kong SAR, China': '🇭🇰', 'Hong Kong, China': '🇭🇰', 'HK': '🇭🇰',
        'Macao': '🇲🇴', 'Macao SAR': '🇲🇴', 'Macao SAR China': '🇲🇴', 'Macao, SAR China': '🇲🇴', 'Macao SAR, China': '🇲🇴', 'Macao, China': '🇲🇴',
        'Macau': '🇲🇴', 'Macau SAR': '🇲🇴', 'Macau SAR China': '🇲🇴', 'Macau, SAR China': '🇲🇴', 'Macau SAR, China': '🇲🇴', 'Macau, China': '🇲🇴',
        'New Zealand': '🇳🇿',
        'Ireland': '🇮🇪',
        'Portugal': '🇵🇹',
        'Greece': '🇬🇷',
        'Czech Republic': '🇨🇿', 'Czechia': '🇨🇿',
        'Hungary': '🇭🇺',
        'Romania': '🇷🇴',
        'Turkey': '🇹🇷', 'Türkiye': '🇹🇷',
        'Saudi Arabia': '🇸🇦',
        'United Arab Emirates': '🇦🇪', 'UAE': '🇦🇪',
        'Thailand': '🇹🇭',
        'Malaysia': '🇲🇾',
        'Indonesia': '🇮🇩',
        'Philippines': '🇵🇭',
        'Vietnam': '🇻🇳', 'Viet Nam': '🇻🇳',
        'Chile': '🇨🇱',
        'Argentina': '🇦🇷',
        'South Africa': '🇿🇦',
        'Egypt': '🇪🇬',
        // 添加更多国家
        'Luxembourg': '🇱🇺',
        'Iceland': '🇮🇸',
        'Estonia': '🇪🇪',
        'Latvia': '🇱🇻',
        'Lithuania': '🇱🇹',
        'Slovenia': '🇸🇮',
        'Slovakia': '🇸🇰',
        'Croatia': '🇭🇷',
        'Serbia': '🇷🇸',
        'Bulgaria': '🇧🇬',
        'Ukraine': '🇺🇦',
        'Belarus': '🇧🇾',
        'Moldova': '🇲🇩',
        'Georgia': '🇬🇪',
        'Armenia': '🇦🇲',
        'Azerbaijan': '🇦🇿',
        'Kazakhstan': '🇰🇿',
        'Uzbekistan': '🇺🇿',
        'Bangladesh': '🇧🇩',
        'Pakistan': '🇵🇰',
        'Sri Lanka': '🇱🇰',
        'Nepal': '🇳🇵',
        'Myanmar': '🇲🇲', 'Burma': '🇲🇲',
        'Cambodia': '🇰🇭',
        'Laos': '🇱🇦',
        'Mongolia': '🇲🇳',
        'North Korea': '🇰🇵', 'DPRK': '🇰🇵', "Democratic People's Republic of Korea": '🇰🇵',
        'Iran': '🇮🇷',
        'Iraq': '🇮🇶',
        'Jordan': '🇯🇴',
        'Lebanon': '🇱🇧',
        'Qatar': '🇶🇦',
        'Kuwait': '🇰🇼',
        'Oman': '🇴🇲',
        'Bahrain': '🇧🇭',
        'Yemen': '🇾🇪',
        'Cyprus': '🇨🇾',
        'Malta': '🇲🇹',
        'Colombia': '🇨🇴',
        'Peru': '🇵🇪',
        'Venezuela': '🇻🇪',
        'Ecuador': '🇪🇨',
        'Bolivia': '🇧🇴',
        'Paraguay': '🇵🇾',
        'Uruguay': '🇺🇾',
        'Costa Rica': '🇨🇷',
        'Panama': '🇵🇦',
        'Guatemala': '🇬🇹',
        'Honduras': '🇭🇳',
        'El Salvador': '🇸🇻',
        'Nicaragua': '🇳🇮',
        'Cuba': '🇨🇺',
        'Jamaica': '🇯🇲',
        'Trinidad and Tobago': '🇹🇹',
        'Dominican Republic': '🇩🇴',
        'Puerto Rico': '🇵🇷',
        'Morocco': '🇲🇦',
        'Algeria': '🇩🇿',
        'Tunisia': '🇹🇳',
        'Libya': '🇱🇾',
        'Sudan': '🇸🇩',
        'Ethiopia': '🇪🇹',
        'Kenya': '🇰🇪',
        'Tanzania': '🇹🇿',
        'Uganda': '🇺🇬',
        'Ghana': '🇬🇭',
        'Nigeria': '🇳🇬',
        'Senegal': '🇸🇳',
        'Ivory Coast': '🇨🇮', "Côte d'Ivoire": '🇨🇮',
        'Cameroon': '🇨🇲',
        'Angola': '🇦🇴',
        'Mozambique': '🇲🇿',
        'Madagascar': '🇲🇬',
        'Mauritius': '🇲🇺',
        'Botswana': '🇧🇼',
        'Namibia': '🇳🇦',
        'Zimbabwe': '🇿🇼',
        'Zambia': '🇿🇲',
        'Malawi': '🇲🇼',
        'Rwanda': '🇷🇼',
        'Burundi': '🇧🇮',
        'New Caledonia': '🇳🇨',
        'Fiji': '🇫🇯',
        'Papua New Guinea': '🇵🇬',
    };
    
    // 精确匹配
    if (countryMap[countryName]) {
        return countryMap[countryName];
    }
    
    // 模糊匹配（不区分大小写）
    const countryLower = countryName.toLowerCase().trim();
    for (const [key, flag] of Object.entries(countryMap)) {
        if (key.toLowerCase() === countryLower) {
            return flag;
        }
    }
    
    // 部分匹配（用于处理 "Hong Kong SAR China" 这样的情况）
    // 检查是否包含已知地区名称
    for (const [key, flag] of Object.entries(countryMap)) {
        const keyLower = key.toLowerCase();
        // 如果输入包含关键词，且关键词长度大于3（避免误匹配）
        if (keyLower.length > 3 && countryLower.includes(keyLower)) {
            return flag;
        }
    }
    
    // 反向匹配：如果映射表中的键包含输入的国家名称（用于处理缩写等情况）
    for (const [key, flag] of Object.entries(countryMap)) {
        const keyLower = key.toLowerCase();
        if (keyLower.length > 3 && keyLower.includes(countryLower)) {
            return flag;
        }
    }
    
    // 如果找不到，返回空字符串
    return '';
}

// 生成字符串的 hash 值（用于颜色生成）
function stringHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash);
}

// 根据字符串生成颜色
function getColorForString(str) {
    const hash = stringHash(str);
    // 使用 HSL 颜色空间，固定饱和度和亮度，只变化色相
    const hue = hash % 360;
    return `hsl(${hue}, 70%, 45%)`;
}

// 根据字符串生成背景色（浅色版本）
function getBgColorForString(str) {
    const hash = stringHash(str);
    const hue = hash % 360;
    return `hsl(${hue}, 70%, 92%)`;
}

// 移除通知（带动画效果）
function removeNotificationWithAnimation(notificationId = 'daily-arxiv-api-notification') {
    const notification = document.getElementById(notificationId);
    if (notification) {
        notification.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 300);
    }
}

// 重启 Daily arXiv 抓取（先测试 LLM API，然后开始抓取）
async function restartDailyArxivFetch() {
    // 先移除现有通知（如果有），给用户反馈
    removeNotificationWithAnimation('daily-arxiv-api-notification');
    
    // 等待动画完成后再测试
    await new Promise(resolve => setTimeout(resolve, 350));
    
    // 先测试 LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        // 测试失败，重新显示错误提示（带刷新效果）
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="重新测试并启动抓取">
                <i class="fas fa-redo"></i> 重启
            </button>
        `;
        showRoundedNotification('LLM API 调用失败，停止 Daily arXiv，请检查 LLM API 设置。', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }
    
    // 测试通过，更新配置状态
    dailyArxivLLMConfigured = true;
    
    // 使用当前查看的日期（如果没有则使用今天的日期）
    const dateToFetch = dailyArxivCurrentDate || new Date().toISOString().split('T')[0];
    
    // 开始抓取（根据当前视图决定抓取单个分区还是所有分区）
    if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
        // 抓取当前分区
        await triggerFetchPapers(false);
    } else {
        // 抓取所有分区（使用当前查看的日期）
        await triggerFetchAllCategories(false, dateToFetch);
    }
}

// 检查 Daily arXiv LLM 配置
async function checkDailyArxivLLMConfig() {
    try {
        const res = await fetch('/api/daily-arxiv/check-llm-config');
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                dailyArxivLLMConfigured = data.is_configured;
                
                // 检查 LLM API 是否失败
                if (data.llm_api_failed) {
                    // 显示常驻弹窗，带重启按钮
                    const actionButton = `
                        <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                            background: #c62828;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 4px 12px;
                            font-size: 12px;
                            cursor: pointer;
                            margin-left: 8px;
                            transition: background 0.2s;
                        " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="重新测试并启动抓取">
                            <i class="fas fa-redo"></i> 重启
                        </button>
                    `;
                    showRoundedNotification('LLM API 调用失败，停止 Daily arXiv，请检查 LLM API 设置。', 'error', true, 'daily-arxiv-api-notification', actionButton);
                } else {
                    // 如果 API 正常，移除弹窗（如果存在，带动画）
                    removeNotificationWithAnimation('daily-arxiv-api-notification');
                }
            }
        }
    } catch (err) {
        console.error('检查 LLM 配置失败:', err);
        dailyArxivLLMConfigured = false;
    }
}

// 初始化 Daily arXiv
async function initDailyArxiv() {
    // 检查 LLM 配置
    await checkDailyArxivLLMConfig();
    
    // 加载设置
    await loadDailyArxivSettings();
    
    // 加载可用日期
    await loadAvailableDates();
    
    // 绑定事件
    const settingsBtn = document.getElementById('daily-arxiv-settings');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', showDailyArxivSettingsModal);
    }
    
    // 日期导航按钮
    const prevDateBtn = document.getElementById('daily-arxiv-prev-date');
    const nextDateBtn = document.getElementById('daily-arxiv-next-date');
    if (prevDateBtn) {
        prevDateBtn.addEventListener('click', () => navigateDate(-1));
    }
    if (nextDateBtn) {
        nextDateBtn.addEventListener('click', () => navigateDate(1));
    }
    
    const emptyEl = document.getElementById('daily-arxiv-empty');
    const gridEl = document.getElementById('daily-arxiv-grid');
    const filterBtn = document.getElementById('daily-arxiv-filter');
    const filterPanel = document.getElementById('daily-arxiv-filter-panel');
    const filterClearBtn = document.getElementById('daily-arxiv-filter-clear');
    const searchInput = document.getElementById('daily-arxiv-search');

    // Daily arXiv 搜索：title / authors / affiliations / abstract
    if (searchInput) {
        let searchTimer = null;
        searchInput.addEventListener('input', () => {
            const query = searchInput.value || '';
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                dailyArxivSearchQuery = query.trim();
                renderDailyArxivGrid();
            }, 250);
        });

        // ESC 清空搜索
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                searchInput.value = '';
                dailyArxivSearchQuery = '';
                renderDailyArxivGrid();
            }
        });
    }

    // 过滤按钮：展开/收起过滤器面板
    if (filterBtn && filterPanel) {
        filterBtn.addEventListener('click', () => {
            // 每次打开前，基于当前分区 & 日期重新渲染一遍单位列表、地区列表和关键词列表
            if (filterPanel.style.display === 'none' || !filterPanel.style.display) {
                renderDailyArxivFilterAffiliations();
                renderDailyArxivFilterCountries();
                renderDailyArxivFilterKeywords();
                // 第一次显示时初始化resizer
                setTimeout(() => setupDailyArxivFilterResizing(), 50);
            }
            const isVisible = filterPanel.style.display !== 'none';
            filterPanel.style.display = isVisible ? 'none' : 'block';
        });
    }

    // 清除过滤条件
    if (filterClearBtn) {
        filterClearBtn.addEventListener('click', () => {
            dailyArxivSelectedAffiliations.clear();
            dailyArxivSelectedCountries.clear();
            dailyArxivSelectedKeywords.clear();
            dailyArxivExcludedAffiliations.clear();
            dailyArxivExcludedCountries.clear();
            dailyArxivExcludedKeywords.clear();
            renderDailyArxivFilterAffiliations();
            renderDailyArxivFilterCountries();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    }
    
    // 如果有配置分区，初始化显示并尝试加载论文
    if (dailyArxivCategories.length > 0) {
        // 隐藏未配置分区的空状态提示
        if (emptyEl) emptyEl.style.display = 'none';
        
        // 默认显示所有分区
        dailyArxivCurrentCategory = 'all';
        renderDailyArxivCategoryTags();
        
        // 加载论文
        await loadPapersForCurrentDate();
        
        // 检查是否有分区正在抓取，如果有则开始轮询
        checkAndStartProgressPolling();
    } else {
        // 没有配置分区，显示空状态
        if (emptyEl) emptyEl.style.display = 'flex';
        if (gridEl) gridEl.innerHTML = '';
    }
    
    // 设置过滤器面板的拖动调整宽度功能
    setupDailyArxivFilterResizing();
    
    // 初始化过滤器分区折叠状态（默认展开）
    const filterSections = document.querySelectorAll('.filter-section-box');
    filterSections.forEach(section => {
        // 默认展开，不添加collapsed类
    });
}

// 切换过滤器分区折叠/展开
function toggleFilterSection(header) {
    const sectionBox = header.closest('.filter-section-box');
    if (sectionBox) {
        sectionBox.classList.toggle('collapsed');
    }
}

// 设置 Daily arXiv 过滤器面板的拖动调整宽度功能
let filterResizerInitialized = false;
function setupDailyArxivFilterResizing() {
    // 防止重复初始化
    if (filterResizerInitialized) {
        console.log('过滤器resizer已经初始化过了');
        return;
    }
    
    const filterPanel = document.getElementById('daily-arxiv-filter-panel');
    const resizer = document.getElementById('daily-arxiv-filter-resizer');
    
    if (!filterPanel || !resizer) {
        console.warn('过滤器面板或调整手柄未找到', {filterPanel, resizer});
        return;
    }
    
    // 检查元素是否可见
    const isVisible = filterPanel.offsetParent !== null;
    console.log('过滤器面板是否可见:', isVisible, '宽度:', filterPanel.offsetWidth);
    console.log('Resizer元素:', resizer, 'offsetWidth:', resizer.offsetWidth, 'offsetHeight:', resizer.offsetHeight);
    
    filterResizerInitialized = true;
    console.log('✅ 过滤器面板拖动调整功能已初始化');
    
    let isResizing = false;
    let startX = 0;
    let startWidth = 0;
    
    // 添加测试用的hover效果
    resizer.addEventListener('mouseenter', () => {
        console.log('🖱️ 鼠标进入resizer区域');
    });
    
    resizer.addEventListener('mouseleave', () => {
        console.log('🖱️ 鼠标离开resizer区域');
    });
    
    // 防止事件冒泡
    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = filterPanel.offsetWidth;
        resizer.classList.add('resizing');
        
        console.log('🔵 开始调整过滤器宽度:', startWidth, 'px, 鼠标位置:', startX);
        
        // 阻止默认行为和事件冒泡
        e.preventDefault();
        e.stopPropagation();
        
        // 添加全局样式以改善拖动体验
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        e.preventDefault();
        
        const deltaX = e.clientX - startX;
        const newWidth = startWidth + deltaX;
        
        // 限制最小和最大宽度
        const minWidth = 240;
        const maxWidth = 600;
        
        if (newWidth >= minWidth && newWidth <= maxWidth) {
            filterPanel.style.width = `${newWidth}px`;
        }
    });
    
    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('resizing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            
            const finalWidth = filterPanel.style.width;
            console.log('✅ 调整完成，最终宽度:', finalWidth);
            
            // 保存宽度到 localStorage
            try {
                localStorage.setItem('dailyArxivFilterPanelWidth', finalWidth);
            } catch (e) {
                console.error('保存过滤器面板宽度失败:', e);
            }
        }
    });
    
    // 从 localStorage 恢复宽度
    try {
        const savedWidth = localStorage.getItem('dailyArxivFilterPanelWidth');
        if (savedWidth) {
            filterPanel.style.width = savedWidth;
            console.log('📏 恢复过滤器宽度:', savedWidth);
        }
    } catch (e) {
        console.error('恢复过滤器面板宽度失败:', e);
    }
}

// 检查是否有分区正在抓取，如果有则开始轮询
async function checkAndStartProgressPolling() {
    let hasActiveTask = false;
    
    // 检查所有分区，为所有正在进行的任务启动轮询
    for (const cat of dailyArxivCategories) {
        try {
            const res = await fetch(`/api/daily-arxiv/progress/${cat}`);
            if (res.ok) {
                const data = await res.json();
                const progress = data.progress;
                if (progress.status === 'fetching' || progress.status === 'processing') {
                    hasActiveTask = true;
                    // 启动该分区的轮询
                    startProgressPolling(cat);
                    
                    // 如果该分区是当前查看的分区（或"全部"），立即更新进度显示
                    if (dailyArxivCurrentCategory === 'all' || cat === dailyArxivCurrentCategory) {
                        updateProgressUI(cat, progress);
                        
                        // 如果有已抓取的论文，立即更新显示
                        if (progress.papers && progress.papers.length > 0) {
                            // 应用前端标准化
                            const normalizedPapers = applyFrontendNormalizationToPapers(progress.papers);
                            
                            // 更新论文缓存
                            normalizedPapers.forEach(paper => {
                                const paperDate = paper.announced 
                                    ? paper.announced.split('T')[0] 
                                    : dailyArxivCurrentDate;
                                const cacheKey = `${paperDate}_${cat}`;
                                
                                if (!dailyArxivPapers[cacheKey]) {
                                    dailyArxivPapers[cacheKey] = [];
                                }
                                
                                // 检查是否已存在
                                const existingIndex = dailyArxivPapers[cacheKey].findIndex(
                                    p => p.arxiv_id === paper.arxiv_id
                                );
                                
                                if (existingIndex >= 0) {
                                    // 更新现有论文
                                    dailyArxivPapers[cacheKey][existingIndex] = paper;
                                } else {
                                    // 添加新论文
                                    dailyArxivPapers[cacheKey].push(paper);
                                }
                            });
                            
                            // 刷新网格显示
                            renderDailyArxivGrid();
                        }
                    }
                }
            }
        } catch (err) {
            console.error(`检查 ${cat} 进度失败:`, err);
        }
    }
    
    // 如果有活动任务，刷新可用日期列表（可能新增了日期）
    if (hasActiveTask) {
        await loadAvailableDates();
    }
}

// 加载可用日期列表
async function loadAvailableDates() {
    try {
        const res = await fetch('/api/daily-arxiv/dates');
        if (res.ok) {
            const data = await res.json();
            dailyArxivAvailableDates = data.dates || [];
            const today = data.today;
            
            // 默认显示有论文的最新日期，如果没有则显示今天
            if (dailyArxivAvailableDates.length > 0) {
                dailyArxivCurrentDate = dailyArxivAvailableDates[0];  // 最新日期
            } else {
                dailyArxivCurrentDate = today;
                dailyArxivAvailableDates = [today];
            }
            
            updateDateDisplay();
            updateDateNavButtons();
        }
    } catch (err) {
        console.error('加载可用日期失败:', err);
    }
}

// 更新日期显示
function updateDateDisplay() {
    const dateEl = document.getElementById('daily-arxiv-current-date');
    if (dateEl && dailyArxivCurrentDate) {
        const date = new Date(dailyArxivCurrentDate + 'T00:00:00');
        const options = { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' };
        dateEl.textContent = date.toLocaleDateString('zh-CN', options);
    }
}

// 更新日期导航按钮状态
function updateDateNavButtons() {
    const prevBtn = document.getElementById('daily-arxiv-prev-date');
    const nextBtn = document.getElementById('daily-arxiv-next-date');
    
    if (!dailyArxivAvailableDates.length) {
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
    }
    
    const currentIndex = dailyArxivAvailableDates.indexOf(dailyArxivCurrentDate);
    
    // 日期列表是降序的（最新在前）
    if (prevBtn) {
        prevBtn.disabled = currentIndex >= dailyArxivAvailableDates.length - 1;
    }
    if (nextBtn) {
        nextBtn.disabled = currentIndex <= 0;
    }
}

// 日期导航
async function navigateDate(direction) {
    const currentIndex = dailyArxivAvailableDates.indexOf(dailyArxivCurrentDate);
    // direction: -1 表示往前（更旧），1 表示往后（更新）
    // 日期列表是降序的，所以 -1 对应 index+1，1 对应 index-1
    const newIndex = currentIndex - direction;
    
    if (newIndex >= 0 && newIndex < dailyArxivAvailableDates.length) {
        dailyArxivCurrentDate = dailyArxivAvailableDates[newIndex];
        saveCurrentViewState();  // 保存状态
        updateDateDisplay();
        updateDateNavButtons();
        
        // 加载该日期的论文（即使有分区正在抓取，也能切换查看其他日期）
        await loadPapersForCurrentDate();
        
        // 检查切换到的日期是否有分区正在抓取
        if (dailyArxivCurrentCategory) {
            checkCategoryProgress(dailyArxivCurrentCategory);
        }
    }
}

// 加载当前日期的论文
async function loadPapersForCurrentDate() {
    if (!dailyArxivCurrentDate) {
        return;
    }
    
    const emptyEl = document.getElementById('daily-arxiv-empty');
    
    // 已配置分区，隐藏空状态提示
    if (dailyArxivCategories.length > 0 && emptyEl) {
        emptyEl.style.display = 'none';
    }
    
    // 如果是"全部"，加载所有分区；否则加载指定分区
    const categoriesToLoad = dailyArxivCurrentCategory === 'all' 
        ? dailyArxivCategories 
        : [dailyArxivCurrentCategory];
    
    const loadingEl = document.getElementById('daily-arxiv-loading');
    let needsLoading = false;
    
    // 检查是否需要从服务器加载
    for (const cat of categoriesToLoad) {
        const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
        if (!dailyArxivPapers[cacheKey]) {
            needsLoading = true;
            break;
        }
    }
    
    if (needsLoading) {
        if (loadingEl) loadingEl.style.display = 'flex';
        
        try {
            // 加载所有需要的分区
            await Promise.all(categoriesToLoad.map(async (cat) => {
                const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
                if (!dailyArxivPapers[cacheKey]) {
                    const res = await fetch(`/api/daily-arxiv/papers/${dailyArxivCurrentDate}?category=${cat}`);
                    if (res.ok) {
                        const data = await res.json();
                        let papers = data.papers || [];
                        // 应用前端机构标准化
                        papers = applyFrontendNormalizationToPapers(papers);
                        dailyArxivPapers[cacheKey] = papers;
                    }
                }
            }));
        } catch (err) {
            console.error('加载论文失败:', err);
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }
    
    // 论文数据加载完成后，先刷新过滤器选项，再渲染网格
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterCountries();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
    renderDailyArxivCategoryTags();
}

// 自动保存 Daily arXiv 设置（防抖）
const autoSaveDailyArxivSettings = debounce(() => {
    saveDailyArxivSettings(true); // silent mode
}, 500);

// 加载 Daily arXiv 设置
async function loadDailyArxivSettings() {
    try {
        const res = await fetch('/api/settings/daily-arxiv');
        if (res.ok) {
            dailyArxivSettings = await res.json();
            dailyArxivCategories = dailyArxivSettings.categories || [];
            
            // 更新设置面板的值
            const retentionDaysEl = document.getElementById('daily-arxiv-retention-days');
            const checkIntervalEl = document.getElementById('daily-arxiv-check-interval');
            const maxKeywordsEl = document.getElementById('daily-arxiv-max-keywords');
            
            if (retentionDaysEl) {
                retentionDaysEl.value = dailyArxivSettings.retentionDays || 7;
                retentionDaysEl.addEventListener('change', autoSaveDailyArxivSettings);
            }
            if (checkIntervalEl) {
                checkIntervalEl.value = dailyArxivSettings.checkIntervalMinutes || 10;
                checkIntervalEl.addEventListener('change', autoSaveDailyArxivSettings);
            }
            if (maxKeywordsEl) {
                maxKeywordsEl.value = dailyArxivSettings.maxKeywords || 1;
                maxKeywordsEl.addEventListener('change', autoSaveDailyArxivSettings);
            }
            
            renderDailyArxivCategoryTags();
            renderDailyArxivSettingsCategoryList();
            renderDailyArxivKeywordList();
        }
        
        // 加载已知机构列表
        await loadKnownInstitutions();
    } catch (err) {
        console.error('加载 Daily arXiv 设置失败:', err);
    }
}

// 加载所有已知机构列表（系统预设 + 用户自定义）
async function loadKnownInstitutions() {
    try {
        const res = await fetch('/api/all-known-institutions');
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                dailyArxivKnownInstitutions = new Set(data.institutions || []);
                console.log(`[DailyArxiv] 已加载 ${dailyArxivKnownInstitutions.size} 个已知机构`);
            }
        }
    } catch (err) {
        console.error('加载已知机构列表失败:', err);
    }
}

// 保存 Daily arXiv 设置
async function saveDailyArxivSettings(silent = false) {
    try {
        const retentionDays = parseInt(document.getElementById('daily-arxiv-retention-days')?.value) || 7;
        const checkInterval = parseInt(document.getElementById('daily-arxiv-check-interval')?.value) || 10;
        const maxKeywords = parseInt(document.getElementById('daily-arxiv-max-keywords')?.value) || 1;
        
        // 限制最多关键词数在 1-3 范围内
        const clampedMaxKeywords = Math.max(1, Math.min(3, maxKeywords));
        
        // 获取关键词列表（从渲染的DOM中提取）
        const keywordList = [];
        const keywordItems = document.querySelectorAll('.daily-arxiv-keyword-item .keyword-text');
        keywordItems.forEach(item => {
            const keyword = item.textContent.trim();
            if (keyword) {
                keywordList.push(keyword);
            }
        });
        
        dailyArxivSettings.categories = dailyArxivCategories;
        dailyArxivSettings.retentionDays = retentionDays;
        dailyArxivSettings.checkIntervalMinutes = checkInterval;
        dailyArxivSettings.maxKeywords = clampedMaxKeywords;
        dailyArxivSettings.keywordList = keywordList;
        
        const res = await fetch('/api/settings/daily-arxiv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dailyArxivSettings)
        });
        
        if (res.ok) {
            if (!silent) {
                showMessage('Daily arXiv 设置已保存', 'success');
            }
            renderDailyArxivCategoryTags();
        } else {
            showMessage('保存设置失败', 'error');
        }
    } catch (err) {
        console.error('保存 Daily arXiv 设置失败:', err);
        showMessage('保存设置失败', 'error');
    }
}

// 添加 arXiv 分区
function addDailyArxivCategory() {
    const input = document.getElementById('daily-arxiv-new-category');
    if (!input) return;
    
    const category = input.value.trim().toLowerCase();
    if (!category) {
        showMessage('请输入分区名称', 'warning');
        return;
    }
    
    if (dailyArxivCategories.includes(category)) {
        showMessage('该分区已存在', 'warning');
        return;
    }
    
    dailyArxivCategories.push(category);
    input.value = '';
    renderDailyArxivSettingsCategoryList();
    renderDailyArxivCategoryTags();
    // 自动保存
    autoSaveDailyArxivSettings();
}

// 快速添加分区
function addDailyArxivCategoryQuick(category) {
    if (dailyArxivCategories.includes(category)) {
        showMessage('该分区已存在', 'warning');
        return;
    }
    
    dailyArxivCategories.push(category);
    renderDailyArxivSettingsCategoryList();
    renderDailyArxivCategoryTags();
    // 自动保存
    autoSaveDailyArxivSettings();
}

// 移除 arXiv 分区
function removeDailyArxivCategory(category) {
    const index = dailyArxivCategories.indexOf(category);
    if (index > -1) {
        dailyArxivCategories.splice(index, 1);
        renderDailyArxivSettingsCategoryList();
        renderDailyArxivCategoryTags();
        // 自动保存
        autoSaveDailyArxivSettings();
    }
}

// 渲染设置面板中的分区列表
function renderDailyArxivSettingsCategoryList() {
    const container = document.getElementById('daily-arxiv-category-list');
    if (!container) return;
    
    if (dailyArxivCategories.length === 0) {
        container.innerHTML = '';
        return;
    }
    
    container.innerHTML = dailyArxivCategories.map(cat => `
        <div class="daily-arxiv-category-item">
            <span>${cat}</span>
            <button class="remove-btn" onclick="removeDailyArxivCategory('${cat}')" title="移除">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');
}

// 渲染关键词列表
function renderDailyArxivKeywordList() {
    const container = document.getElementById('daily-arxiv-keyword-list');
    if (!container) return;
    
    const keywordList = dailyArxivSettings.keywordList || [];
    
    if (keywordList.length === 0) {
        container.innerHTML = '<div style="color: #8b949e; font-size: 13px; padding: 8px;">暂无关键词，请在下方输入框添加</div>';
        return;
    }
    
    container.innerHTML = keywordList.map((keyword, index) => {
        // 转义特殊字符，防止 XSS
        const escapedKeyword = keyword.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const escapedKeywordForAttr = keyword.replace(/'/g, "\\'").replace(/"/g, '\\"');
        return `
        <div class="daily-arxiv-keyword-item" data-keyword="${escapedKeyword}">
            <span class="keyword-text">${keyword}</span>
            <button class="remove-keyword-btn" onclick="removeDailyArxivKeyword('${escapedKeywordForAttr}')" title="删除">
                <i class="fas fa-times"></i>
            </button>
        </div>
        `;
    }).join('');
}

// 添加关键词
function addDailyArxivKeyword() {
    const input = document.getElementById('daily-arxiv-new-keyword');
    if (!input) return;
    
    const keyword = input.value.trim();
    if (!keyword) {
        showMessage('请输入关键词', 'warning');
        return;
    }
    
    // 确保 keywordList 存在
    if (!dailyArxivSettings.keywordList) {
        dailyArxivSettings.keywordList = [];
    }
    
    if (dailyArxivSettings.keywordList.includes(keyword)) {
        showMessage('该关键词已存在', 'warning');
        input.value = '';
        return;
    }
    
    dailyArxivSettings.keywordList.push(keyword);
    input.value = '';
    renderDailyArxivKeywordList();
    // 自动保存
    autoSaveDailyArxivSettings();
}

// 删除关键词
function removeDailyArxivKeyword(keyword) {
    if (!dailyArxivSettings.keywordList) {
        dailyArxivSettings.keywordList = [];
    }
    
    const index = dailyArxivSettings.keywordList.indexOf(keyword);
    if (index > -1) {
        dailyArxivSettings.keywordList.splice(index, 1);
        renderDailyArxivKeywordList();
        // 自动保存
        autoSaveDailyArxivSettings();
    }
}

// 设置关键词输入框事件
function setupDailyArxivKeywordInput() {
    const keywordInput = document.getElementById('daily-arxiv-new-keyword');
    if (!keywordInput) return;
    
    // 移除旧的事件监听器（如果存在）
    const newKeywordInput = keywordInput.cloneNode(true);
    keywordInput.parentNode.replaceChild(newKeywordInput, keywordInput);
    
    // 绑定回车事件
    newKeywordInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addDailyArxivKeyword();
        }
    });
}

// 渲染 Daily arXiv 界面的分区标签
function renderDailyArxivCategoryTags() {
    const container = document.getElementById('daily-arxiv-categories');
    if (!container) return;
    
    // 计算每个分区的论文数量
    let allCount = 0;
    const categoryCounts = {};
    
    dailyArxivCategories.forEach(cat => {
        const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
        const papers = dailyArxivPapers[cacheKey] || [];
        categoryCounts[cat] = papers.length;
        allCount += papers.length;
    });
    
    // 添加"全部"标签
    const allTag = `
        <span class="daily-arxiv-category-tag ${dailyArxivCurrentCategory === 'all' ? 'active' : ''}" 
              onclick="switchDailyArxivCategory('all')"
              title="${allCount ? allCount + ' 篇论文' : '全部分区'}">
            全部${allCount ? ' (' + allCount + ')' : ''}
        </span>
    `;
    
    // 生成各个分区标签
    const categoryTags = dailyArxivCategories.map(cat => {
        const isActive = cat === dailyArxivCurrentCategory;
        const count = categoryCounts[cat];
        return `
            <span class="daily-arxiv-category-tag ${isActive ? 'active' : ''}" 
                  onclick="switchDailyArxivCategory('${cat}')"
                  title="${count ? count + ' 篇论文' : '点击加载'}">
                ${cat}${count ? ' (' + count + ')' : ''}
            </span>
        `;
    }).join('');
    
    container.innerHTML = allTag + categoryTags;
}

// 测试 LLM API（用于 Daily arXiv 抓取前，复用 settings 界面的测试逻辑）
async function testLLMAPIForDailyArxiv() {
    try {
        // 获取当前 LLM 配置
        const response = await fetch('/api/settings/agentic');
        const settings = await response.json();
        
        const llmModel = settings.llmModel?.trim() || '';
        const llmBaseUrl = settings.llmBaseUrl?.trim() || '';
        const llmApiKey = settings.llmApiKey?.trim() || '';
        
        // 直接复用 testLLMAPICore 函数
        return await testLLMAPICore(llmModel, llmBaseUrl, llmApiKey);
    } catch (error) {
        return {
            success: false,
            error: `测试失败: ${error.message}`
        };
    }
}

// 显示圆角弹窗提示（参考 ti-item 设计，常驻显示）
function showRoundedNotification(message, type = 'error', persistent = true, notificationId = 'daily-arxiv-api-notification', actionButton = null) {
    // 如果已存在通知，只更新内容
    let notification = document.getElementById(notificationId);
    
    if (notification) {
        // 更新现有通知的内容
        const messageSpan = notification.querySelector('span');
        if (messageSpan) {
            messageSpan.textContent = message;
        }
        // 更新操作按钮（如果提供）
        if (actionButton) {
            const existingActionBtn = notification.querySelector('.notification-action-btn');
            if (existingActionBtn) {
                existingActionBtn.outerHTML = actionButton;
            } else {
                // 在关闭按钮前插入操作按钮
                const closeBtn = notification.querySelector('button[onclick*="remove"]');
                if (closeBtn) {
                    closeBtn.insertAdjacentHTML('beforebegin', actionButton);
                }
            }
        }
        return;
    }
    
    // 创建通知元素
    notification = document.createElement('div');
    notification.id = notificationId;
    notification.style.cssText = `
        position: fixed;
        top: 70px;
        right: 20px;
        z-index: 2000;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 500;
        font-size: 13px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideInRight 0.3s ease-out;
        max-width: 400px;
    `;
    
    // 根据类型设置样式（参考 ti-item 的设计）
    if (type === 'error') {
        notification.style.background = '#fff5f5';
        notification.style.color = '#c62828';
        notification.style.border = '1px solid #ffcccb';
    } else if (type === 'warning') {
        notification.style.background = '#fff8e1';
        notification.style.color = '#9a7b00';
        notification.style.border = '1px solid #ffe08a';
    } else {
        notification.style.background = '#e7f3ff';
        notification.style.color = '#0b61c8';
        notification.style.border = '1px solid #9cc7ff';
    }
    
    notification.innerHTML = `
        <i class="fas fa-exclamation-triangle" style="font-size: 14px;"></i>
        <span>${message}</span>
        ${actionButton || ''}
        <button onclick="removeNotificationWithAnimation('${notificationId}')" style="
            background: none;
            border: none;
            color: inherit;
            cursor: pointer;
            padding: 0;
            margin-left: 8px;
            opacity: 0.7;
            font-size: 16px;
            line-height: 1;
            transition: opacity 0.2s;
        " onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'" title="关闭">
            <i class="fas fa-times"></i>
        </button>
    `;
    
    // 添加动画样式（如果还没有）
    if (!document.getElementById('daily-arxiv-notification-style')) {
        const style = document.createElement('style');
        style.id = 'daily-arxiv-notification-style';
        style.textContent = `
            @keyframes slideInRight {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            @keyframes slideOutRight {
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
    }
    
    document.body.appendChild(notification);
    
    // 如果 persistent 为 false，5秒后自动移除
    if (!persistent) {
        setTimeout(() => {
            removeNotificationWithAnimation(notificationId);
        }, 5000);
    }
}

// 触发抓取论文（当前分区）
async function triggerFetchPapers(force = false) {
    // 检查 LLM 配置
    if (!dailyArxivLLMConfigured) {
        showRoundedNotification('请先在设置中配置 LLM API（Model、Base URL、API Key）', 'warning');
        // 切换到设置页面
        switchTab('setting');
        // 切换到 Agentic 设置面板
        setTimeout(() => {
            const agenticBtn = document.querySelector('[data-setting="agentic"]');
            if (agenticBtn) agenticBtn.click();
        }, 100);
        return;
    }
    
    if (dailyArxivCategories.length === 0) {
        showMessage('请先配置 arXiv 分区', 'warning');
        return;
    }
    
    if (!dailyArxivCurrentCategory) {
        dailyArxivCurrentCategory = dailyArxivCategories[0];
    }
    
    // 在抓取前测试 LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="重新测试并启动抓取">
                <i class="fas fa-redo"></i> 重启抓取
            </button>
        `;
        showRoundedNotification('LLM API 调用失败，停止 Daily arXiv，请检查 LLM API 设置。', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }
    
    try {
        // 触发后台抓取（使用当前查看的日期，如果没有则使用今天的日期）
        const dateToFetch = dailyArxivCurrentDate || new Date().toISOString().split('T')[0];
        const res = await fetch('/api/daily-arxiv/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                category: dailyArxivCurrentCategory,
                date: dateToFetch,
                force: force,
            })
        });
        
        const data = await res.json();
        
        if (data.success) {
            showMessage(`开始抓取 ${dailyArxivCurrentCategory} 论文...`, 'info');
            // 开始轮询进度
            startProgressPolling(dailyArxivCurrentCategory);
        } else {
            showMessage(data.error || '抓取失败', 'error');
        }
    } catch (err) {
        console.error('触发抓取失败:', err);
        showMessage('触发抓取失败', 'error');
    }
}

// 触发抓取所有分区的论文
async function triggerFetchAllCategories(force = false, dateStr = null) {
    // 检查 LLM 配置
    if (!dailyArxivLLMConfigured) {
        showRoundedNotification('请先在设置中配置 LLM API（Model、Base URL、API Key）', 'warning');
        // 切换到设置页面
        switchTab('setting');
        // 切换到 Agentic 设置面板
        setTimeout(() => {
            const agenticBtn = document.querySelector('[data-setting="agentic"]');
            if (agenticBtn) agenticBtn.click();
        }, 100);
        return;
    }
    
    if (dailyArxivCategories.length === 0) {
        showMessage('请先配置 arXiv 分区', 'warning');
        return;
    }
    
    // 在抓取前测试 LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="重新测试并启动抓取">
                <i class="fas fa-redo"></i> 重启抓取
            </button>
        `;
        showRoundedNotification('LLM API 调用失败，停止 Daily arXiv，请检查 LLM API 设置。', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }
    
    try {
        // 触发后台抓取所有分区（如果指定了日期则使用，否则使用今天的日期）
        const dateToFetch = dateStr || new Date().toISOString().split('T')[0];
        const res = await fetch('/api/daily-arxiv/fetch-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                force: force,
                date: dateToFetch
            })
        });
        
        const data = await res.json();
        
        if (data.success) {
            showMessage(`开始抓取 ${dailyArxivCategories.length} 个分区的论文...`, 'info');
            // 为每个分区开始独立的进度轮询
            dailyArxivCategories.forEach(cat => {
                startProgressPolling(cat);
            });
        } else {
            showMessage(data.error || '抓取失败', 'error');
        }
    } catch (err) {
        console.error('触发抓取失败:', err);
        showMessage('触发抓取失败', 'error');
    }
}

// 开始进度轮询（独立管理每个分区）
function startProgressPolling(category) {
    // 如果该分区已经在轮询，先停止
    if (dailyArxivProgressIntervals[category]) {
        clearInterval(dailyArxivProgressIntervals[category]);
    }
    
    let idleCount = 0;
    
    // 开始轮询
    dailyArxivProgressIntervals[category] = setInterval(async () => {
        try {
            const res = await fetch(`/api/daily-arxiv/progress/${category}`);
            if (res.ok) {
                const data = await res.json();
                const progress = data.progress;
                
                // 如果正在处理
                if (progress.status === 'fetching' || progress.status === 'processing') {
                    idleCount = 0;
                    
                    // 当前选中分区或"全部"时更新进度条UI
                    const shouldShowProgress = dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory;
                    if (shouldShowProgress) {
                        const progressEl = document.getElementById('daily-arxiv-progress');
                        const loadingEl = document.getElementById('daily-arxiv-loading');
                        if (progressEl) progressEl.style.display = 'block';
                        if (loadingEl) loadingEl.style.display = 'none';
                        updateProgressUI(category, progress);
                        
                        // 确保隐藏"暂无新论文"界面
                        const gridEl = document.getElementById('daily-arxiv-grid');
                        if (gridEl) {
                            const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
                            if (waitingEl) {
                                gridEl.innerHTML = '';
                            }
                        }
                    }
                    
                    // 实时显示已抓取的论文（所有分区都更新数据）
                    if (progress.papers && progress.papers.length > 0) {
                        let hasNewPaper = false;
                        let hasNewPaperForCurrentView = false;
                        const newDates = new Set();
                        
                        progress.papers.forEach(paper => {
                            const paperDate = paper.announced 
                                ? paper.announced.split('T')[0] 
                                : dailyArxivCurrentDate;
                            const cacheKey = `${paperDate}_${category}`;
                            
                            // 调试日志
                            if (!dailyArxivPapers[cacheKey] || !dailyArxivPapers[cacheKey].some(p => p.arxiv_id === paper.arxiv_id)) {
                                console.log(`[Daily arXiv] 新论文: ${paper.title.substring(0, 50)}... | 日期: ${paperDate} | 分区: ${category} | 当前查看: ${dailyArxivCurrentDate}`);
                            }
                            
                            // 记录新日期
                            if (paperDate && !dailyArxivAvailableDates.includes(paperDate)) {
                                newDates.add(paperDate);
                            }
                            
                            if (!dailyArxivPapers[cacheKey]) {
                                dailyArxivPapers[cacheKey] = [];
                            }
                            const exists = dailyArxivPapers[cacheKey].some(p => p.arxiv_id === paper.arxiv_id);
                            if (!exists) {
                                dailyArxivPapers[cacheKey].push(paper);
                                hasNewPaper = true;
                                // 检查是否是当前查看的日期和分区
                                const isCurrentDate = paperDate === dailyArxivCurrentDate;
                                const isCurrentCategory = dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory;
                                if (isCurrentDate && isCurrentCategory) {
                                    hasNewPaperForCurrentView = true;
                                }
                            }
                        });
                        
                        // 更新可用日期列表
                        if (newDates.size > 0) {
                            newDates.forEach(date => {
                                if (!dailyArxivAvailableDates.includes(date)) {
                                    dailyArxivAvailableDates.push(date);
                                }
                            });
                            // 重新排序（降序，最新在前）
                            dailyArxivAvailableDates.sort((a, b) => b.localeCompare(a));
                            updateDateNavButtons();
                        }
                        
                        // 只有当前分区和日期有新论文时才实时更新显示
                        if (hasNewPaperForCurrentView) {
                            renderDailyArxivGrid();
                        }
                        
                        // 更新所有分区标签（显示论文数量）
                        if (hasNewPaper) {
                            renderDailyArxivCategoryTags();
                        }
                    }
                }
                
                // 如果完成或出错，停止该分区的轮询
                if (progress.status === 'done' || progress.status === 'error') {
                    stopProgressPolling(category);
                    await loadAvailableDates();
                    // 如果当前是"全部"或该分区，刷新显示
                    if (dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory) {
                        await loadPapersForCurrentDate();
                    }
                    // 更新分区标签显示
                    renderDailyArxivCategoryTags();
                }
                
                // 如果空闲状态，增加计数
                if (progress.status === 'idle') {
                    idleCount++;
                    if (idleCount >= 3) {
                        stopProgressPolling(category);
                    }
                }
            }
        } catch (err) {
            console.error(`获取 ${category} 进度失败:`, err);
        }
    }, 1000);
}

// 停止进度轮询（可以停止特定分区或所有分区）
function stopProgressPolling(category = null) {
    if (category) {
        // 停止特定分区
        if (dailyArxivProgressIntervals[category]) {
            clearInterval(dailyArxivProgressIntervals[category]);
            delete dailyArxivProgressIntervals[category];
        }
        
        // 重置该分区的慢速下载提示状态
        delete dailyArxivSlowDownloadNotified[category];
        dailyArxivLastPaperKey = '';
        
        // 移除慢速下载提示（如果存在）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }
        
        // 如果是当前分区或"全部"，且没有其他分区在抓取，隐藏进度条
        const shouldHideProgress = (dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory) 
            && Object.keys(dailyArxivProgressIntervals).length === 0;
        
        if (shouldHideProgress) {
            const progressEl = document.getElementById('daily-arxiv-progress');
            const loadingEl = document.getElementById('daily-arxiv-loading');
            
            if (loadingEl) loadingEl.style.display = 'none';
            if (progressEl) {
                setTimeout(() => {
                    progressEl.style.display = 'none';
                }, 1000);
            }
        }
    } else {
        // 停止所有分区
        Object.keys(dailyArxivProgressIntervals).forEach(cat => {
            clearInterval(dailyArxivProgressIntervals[cat]);
        });
        dailyArxivProgressIntervals = {};
        
        // 重置所有分区的慢速下载提示状态
        dailyArxivSlowDownloadNotified = {};
        dailyArxivLastPaperKey = '';
        
        // 移除慢速下载提示（如果存在）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }
        
        const progressEl = document.getElementById('daily-arxiv-progress');
        const loadingEl = document.getElementById('daily-arxiv-loading');
        
        if (loadingEl) loadingEl.style.display = 'none';
        if (progressEl) {
            setTimeout(() => {
                progressEl.style.display = 'none';
            }, 1000);
        }
    }
}

// 更新进度 UI
function updateProgressUI(category, progress) {
    const titleEl = document.getElementById('daily-arxiv-progress-title');
    const countEl = document.getElementById('daily-arxiv-progress-count');
    const barEl = document.getElementById('daily-arxiv-progress-bar');
    const currentEl = document.getElementById('daily-arxiv-progress-current');
    
    if (titleEl) titleEl.textContent = `正在抓取 ${category} 论文...`;
    if (countEl) countEl.textContent = `${progress.current}/${progress.total}`;
    
    const percent = progress.total > 0 ? (progress.current / progress.total * 100) : 0;
    if (barEl) barEl.style.width = `${percent}%`;
    
    // 跟踪当前论文，用于检测论文切换
    const currentPaperKey = `${category}_${progress.current_paper || ''}`;
    const lastPaperKey = dailyArxivLastPaperKey || '';
    
    // 如果论文切换了，重置慢速下载提示状态并移除提示
    if (currentPaperKey !== lastPaperKey && lastPaperKey) {
        delete dailyArxivSlowDownloadNotified[category];
        // 移除慢速下载提示（如果存在）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }
    }
    dailyArxivLastPaperKey = currentPaperKey;
    
    if (currentEl) {
        if (progress.current_paper) {
            // 格式化已用时间
            const elapsedSeconds = progress.current_paper_elapsed_seconds || 0;
            let timeText = '';
            if (elapsedSeconds < 60) {
                timeText = `${elapsedSeconds}秒`;
            } else if (elapsedSeconds < 3600) {
                const minutes = Math.floor(elapsedSeconds / 60);
                const seconds = elapsedSeconds % 60;
                timeText = `${minutes}分${seconds}秒`;
            } else {
                const hours = Math.floor(elapsedSeconds / 3600);
                const minutes = Math.floor((elapsedSeconds % 3600) / 60);
                timeText = `${hours}小时${minutes}分钟`;
            }
            
            // 格式化文件大小
            const pdfSizeBytes = progress.current_paper_pdf_size || 0;
            let sizeText = '';
            if (pdfSizeBytes > 0) {
                if (pdfSizeBytes < 1024) {
                    sizeText = `${pdfSizeBytes} B`;
                } else if (pdfSizeBytes < 1024 * 1024) {
                    sizeText = `${(pdfSizeBytes / 1024).toFixed(1)} KB`;
                } else {
                    sizeText = `${(pdfSizeBytes / (1024 * 1024)).toFixed(2)} MB`;
                }
            }
            
            // 截断过长的标题
            const maxTitleLength = 50;
            let paperTitle = progress.current_paper;
            if (paperTitle.length > maxTitleLength) {
                paperTitle = paperTitle.substring(0, maxTitleLength) + '...';
            }
            
            // 构建显示文本
            let displayText = `正在下载: ${paperTitle} (已用时: ${timeText})`;
            if (sizeText) {
                displayText += ` | ${sizeText}`;
            }
            currentEl.textContent = displayText;
            
            // 检查下载时间是否超过30秒
            if (elapsedSeconds > 30 && !dailyArxivSlowDownloadNotified[category]) {
                // 显示慢速下载提示（使用独立的通知ID，避免与LLM API失败提示冲突）
                showRoundedNotification('下载 arXiv 论文时间过长，请检查 proxy 是否设置。', 'warning', true, 'daily-arxiv-slow-download-notification');
                dailyArxivSlowDownloadNotified[category] = true;
            }
        } else {
            currentEl.textContent = '';
            // 如果没有当前论文，重置慢速下载提示状态并移除提示
            delete dailyArxivSlowDownloadNotified[category];
            const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
            if (slowDownloadNotification) {
                slowDownloadNotification.remove();
            }
        }
    }
    
    // 确保进度条显示时，隐藏"暂无新论文"界面
    const progressEl = document.getElementById('daily-arxiv-progress');
    if (progressEl && progressEl.style.display !== 'none') {
        // 隐藏"暂无新论文"界面（通过清空 grid 内容）
        const gridEl = document.getElementById('daily-arxiv-grid');
        if (gridEl) {
            // 检查是否显示的是"暂无新论文"界面
            const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
            if (waitingEl) {
                gridEl.innerHTML = '';
            }
        }
    }
}


// 获取 Daily arXiv 论文（从缓存或服务器）
async function fetchDailyArxivPapers(forceRefresh = false) {
    const loadingEl = document.getElementById('daily-arxiv-loading');
    const emptyEl = document.getElementById('daily-arxiv-empty');
    const gridEl = document.getElementById('daily-arxiv-grid');
    
    // 只有在没有配置分区时才显示空状态
    if (dailyArxivCategories.length === 0) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'flex';
        if (gridEl) gridEl.innerHTML = '';
        return;
    }
    
    // 已配置分区，隐藏空状态提示
    if (emptyEl) emptyEl.style.display = 'none';
    
    // 如果没有选中分区，选中第一个
    if (!dailyArxivCurrentCategory) {
        dailyArxivCurrentCategory = dailyArxivCategories[0];
    }
    
    const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
    
    // 如果缓存中已有数据且不强制刷新，直接显示
    if (!forceRefresh && dailyArxivPapers[cacheKey] && dailyArxivPapers[cacheKey].length > 0) {
        renderDailyArxivGrid();
        renderDailyArxivCategoryTags();
        return;
    }
    
    // 从服务器加载
    await loadPapersForCurrentDate();
}

// 切换分区
async function switchDailyArxivCategory(category) {
    dailyArxivCurrentCategory = category;
    saveCurrentViewState();  // 保存状态
    renderDailyArxivCategoryTags();
    
    // 加载该分区（或所有分区）的论文
    await loadPapersForCurrentDate();
    
    // 检查该分区是否正在抓取，如果是则显示进度条
    if (category !== 'all') {
        checkCategoryProgress(category);
    } else {
        // 检查所有分区
        dailyArxivCategories.forEach(cat => {
            checkCategoryProgress(cat);
        });
    }
}

// 检查分区进度状态
async function checkCategoryProgress(category) {
    try {
        const res = await fetch(`/api/daily-arxiv/progress/${category}`);
        if (res.ok) {
            const data = await res.json();
            const progress = data.progress;
            
            // 如果该分区正在抓取，显示进度条
            if (progress.status === 'fetching' || progress.status === 'processing') {
                const progressEl = document.getElementById('daily-arxiv-progress');
                const loadingEl = document.getElementById('daily-arxiv-loading');
                if (progressEl) progressEl.style.display = 'block';
                if (loadingEl) loadingEl.style.display = 'none';
                updateProgressUI(category, progress);
                
                // 确保隐藏"暂无新论文"界面
                const gridEl = document.getElementById('daily-arxiv-grid');
                if (gridEl) {
                    const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
                    if (waitingEl) {
                        gridEl.innerHTML = '';
                    }
                }
            }
        }
    } catch (err) {
        console.error(`检查 ${category} 进度失败:`, err);
    }
}

// 获取当前视图下的 Daily arXiv 论文列表
// applyFilters: 是否应用当前的过滤条件（单位等）；过滤器面板本身会传入 false 来获取完整数据
function getCurrentDailyArxivPapers(applyFilters = true) {
    // 获取原始论文列表：如果是 "全部"，合并所有分区；否则只获取指定分区
    let papers = [];
    if (dailyArxivCurrentCategory === 'all') {
        dailyArxivCategories.forEach(cat => {
            const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
            const catPapers = dailyArxivPapers[cacheKey] || [];
            papers = papers.concat(catPapers);
        });
    } else {
        const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
        papers = dailyArxivPapers[cacheKey] || [];
    }

    // 在 "全部" 视图下，按 arxiv_id 去重，并合并不同分区的标签
    if (dailyArxivCurrentCategory === 'all' && papers.length > 0) {
        const mergedMap = new Map();

        papers.forEach(paper => {
            const key = paper.arxiv_id || `${paper.title || ''}__${paper.pdf_url || ''}`;
            if (!mergedMap.has(key)) {
                const cloned = { ...paper };
                const initialCat = paper.fetch_category || paper.primary_category || null;
                cloned.all_fetch_categories = initialCat ? [initialCat] : [];
                mergedMap.set(key, cloned);
            } else {
                const existing = mergedMap.get(key);
                const newCat = paper.fetch_category || paper.primary_category || null;
                if (newCat && !existing.all_fetch_categories.includes(newCat)) {
                    existing.all_fetch_categories.push(newCat);
                }
            }
        });

        papers = Array.from(mergedMap.values());
    }

    // 应用"第一单位"过滤
    if (applyFilters && dailyArxivFilterFirstAffiliation) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            // 只保留第一个单位（如果有的话）
            return affs.length > 0;
        });
    }

    // 应用单位过滤：如果有选中的单位，则只保留 affiliations 里包含任一选中单位的论文
    if (applyFilters && dailyArxivSelectedAffiliations.size > 0) {
        const selected = new Set(dailyArxivSelectedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            // 如果启用了"第一单位"过滤，只检查第一个单位
            if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
                return selected.has(affs[0]);
            }
            return affs.some(aff => selected.has(aff));
        });
    }

    // 应用单位排除过滤：排除包含被排除单位的论文
    if (applyFilters && dailyArxivExcludedAffiliations.size > 0) {
        const excluded = new Set(dailyArxivExcludedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return !affs.some(aff => excluded.has(aff));
        });
    }

    // 应用地区过滤：如果有选中的地区，则只保留 countries 里包含任一选中地区的论文
    if (applyFilters && dailyArxivSelectedCountries.size > 0) {
        const selected = new Set(dailyArxivSelectedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return countries.some(country => {
                if (!country) return false;
                // 使用标准化的地区名称进行比较
                const normalizedCountry = normalizeCountryName(country);
                return selected.has(normalizedCountry);
            });
        });
    }

    // 应用地区排除过滤：排除包含被排除地区的论文
    if (applyFilters && dailyArxivExcludedCountries.size > 0) {
        const excluded = new Set(dailyArxivExcludedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return !countries.some(country => {
                if (!country) return false;
                // 使用标准化的地区名称进行比较
                const normalizedCountry = normalizeCountryName(country);
                return excluded.has(normalizedCountry);
            });
        });
    }

    // 隐藏第一单位属于"其他机构"的论文：
    // 即第一单位存在且不在已知机构列表中的论文将被过滤掉
    if (applyFilters && dailyArxivHideUnknownFirstAffiliation && dailyArxivKnownInstitutions.size > 0) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (affs.length === 0) return true; // 没有机构信息的不处理
            const firstAff = affs[0];
            // 如果第一单位是已知机构，则保留；否则视为"其他机构"并隐藏
            return dailyArxivKnownInstitutions.has(firstAff);
        });
    }

    // 应用关键词过滤：如果有选中的关键词，则只保留 keywords 里包含任一选中关键词的论文
    if (applyFilters && dailyArxivSelectedKeywords.size > 0) {
        const selected = new Set(dailyArxivSelectedKeywords);
        papers = papers.filter(paper => {
            const keywords = paper.keywords || [];
            return keywords.some(keyword => keyword && selected.has(keyword.trim()));
        });
    }

    // 应用关键词排除过滤：排除包含被排除关键词的论文
    if (applyFilters && dailyArxivExcludedKeywords.size > 0) {
        const excluded = new Set(dailyArxivExcludedKeywords);
        papers = papers.filter(paper => {
            const keywords = paper.keywords || [];
            return !keywords.some(keyword => keyword && excluded.has(keyword.trim()));
        });
    }

    // 应用搜索过滤：在 title、authors、affiliations、abstract 中搜索
    if (applyFilters && dailyArxivSearchQuery && dailyArxivSearchQuery.trim()) {
        const q = dailyArxivSearchQuery.trim().toLowerCase();
        papers = papers.filter(paper => {
            // title
            const title = (paper.title || '').toLowerCase();
            if (title.includes(q)) return true;

            // authors
            const authors = (paper.authors || '').toLowerCase();
            if (authors.includes(q)) return true;

            // affiliations（机构）
            const affs = (paper.affiliations || []).join(' ').toLowerCase();
            if (affs.includes(q)) return true;

            // abstract
            const abstract = (paper.abstract || '').toLowerCase();
            if (abstract.includes(q)) return true;

            return false;
        });
    }

    // 按 published 时间排序（越新越前面，和 arXiv 页面顺序一致）
    return [...papers].sort((a, b) => {
        const timeA = a.published ? new Date(a.published).getTime() : 0;
        const timeB = b.published ? new Date(b.published).getTime() : 0;
        return timeB - timeA;  // 降序，越新越前面
    });
}

// 获取用于关键词过滤统计的论文列表：
// - 基于当前视图（日期 & 分区）
// - 应用“第一单位 / 机构 / 地区”的过滤与排除条件
// - 不应用关键词本身的过滤与排除（避免自我影响）
function getDailyArxivPapersForKeywordFilter() {
    // 先获取未应用任何过滤条件但已做去重/合并的论文列表
    let papers = getCurrentDailyArxivPapers(false);

    // 应用"第一单位"过滤
    if (dailyArxivFilterFirstAffiliation) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return affs.length > 0;
        });
    }

    // 应用单位选择过滤
    if (dailyArxivSelectedAffiliations.size > 0) {
        const selected = new Set(dailyArxivSelectedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
                return selected.has(affs[0]);
            }
            return affs.some(aff => selected.has(aff));
        });
    }

    // 应用单位排除过滤
    if (dailyArxivExcludedAffiliations.size > 0) {
        const excluded = new Set(dailyArxivExcludedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return !affs.some(aff => excluded.has(aff));
        });
    }

    // 应用地区选择过滤
    if (dailyArxivSelectedCountries.size > 0) {
        const selected = new Set(dailyArxivSelectedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return countries.some(country => {
                if (!country) return false;
                const normalizedCountry = normalizeCountryName(country);
                return selected.has(normalizedCountry);
            });
        });
    }

    // 应用地区排除过滤
    if (dailyArxivExcludedCountries.size > 0) {
        const excluded = new Set(dailyArxivExcludedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return !countries.some(country => {
                if (!country) return false;
                const normalizedCountry = normalizeCountryName(country);
                return excluded.has(normalizedCountry);
            });
        });
    }

    // 隐藏第一单位属于"其他机构"的论文（同 getCurrentDailyArxivPapers 中的逻辑）
    if (dailyArxivHideUnknownFirstAffiliation && dailyArxivKnownInstitutions.size > 0) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (affs.length === 0) return true;
            const firstAff = affs[0];
            return dailyArxivKnownInstitutions.has(firstAff);
        });
    }

    return papers;
}

// 渲染论文网格
function renderDailyArxivGrid() {
    const gridEl = document.getElementById('daily-arxiv-grid');
    const emptyEl = document.getElementById('daily-arxiv-empty');
    
    if (!gridEl) return;

    // 每次渲染前先恢复网格的默认布局样式
    gridEl.classList.remove('daily-arxiv-grid-no-results');
    
    // 获取当前视图下的论文（已按时间排序，并在 "全部" 视图下去重合并标签）
    const papers = getCurrentDailyArxivPapers();
    
    if (papers.length === 0) {
        // 检查是否有激活的过滤条件或搜索条件
        const hasActiveFilters = 
            dailyArxivFilterFirstAffiliation || 
            dailyArxivSelectedAffiliations.size > 0 || 
            dailyArxivExcludedAffiliations.size > 0 ||
            dailyArxivSelectedCountries.size > 0 ||
            dailyArxivExcludedCountries.size > 0 ||
            dailyArxivSelectedKeywords.size > 0 ||
            dailyArxivExcludedKeywords.size > 0 ||
            (dailyArxivSearchQuery && dailyArxivSearchQuery.trim().length > 0);
        
        // 如果有过滤/搜索条件导致没有论文，显示"没有符合条件的搜索结果"
        if (hasActiveFilters) {
            // 让整个网格区域改为居中布局
            gridEl.classList.add('daily-arxiv-grid-no-results');
            gridEl.innerHTML = `
                <div class="daily-arxiv-no-results">
                    <i class="fas fa-filter fa-3x" style="margin-bottom: 20px; color: #bbb;"></i>
                    <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">没有符合条件的搜索结果</h3>
                    <p style="font-size: 1em; color: #888;">请尝试调整搜索词或过滤条件</p>
                </div>
            `;
            if (emptyEl) emptyEl.style.display = 'none';
            return;
        }
        
        // 检查是否有任何分区正在抓取
        const isFetching = dailyArxivCurrentCategory === 'all'
            ? Object.keys(dailyArxivProgressIntervals).length > 0
            : dailyArxivProgressIntervals[dailyArxivCurrentCategory] !== undefined;
        
        // 检查进度条是否显示（如果有进度条显示，说明正在抓取，不应该显示"暂无新论文"）
        const progressEl = document.getElementById('daily-arxiv-progress');
        const isProgressVisible = progressEl && progressEl.style.display !== 'none';
        
        // 如果有配置分区但没有论文
        if (dailyArxivCategories.length > 0) {
            // 如果正在抓取或进度条显示，显示空白（等待论文出现）
            if (isFetching || isProgressVisible) {
                gridEl.innerHTML = '';
            } else {
                // 不在抓取，检查其他日期是否有论文
                const today = new Date().toISOString().split('T')[0];
                const isToday = dailyArxivCurrentDate === today;
                const hasOtherDates = dailyArxivAvailableDates.length > 1 || (dailyArxivAvailableDates.length === 1 && dailyArxivAvailableDates[0] !== today);
                
                let hint = '';
                if (isToday && hasOtherDates) {
                    hint = '<p style="margin-top: 15px; font-size: 0.9em; color: #2196F3;"><i class="fas fa-info-circle"></i> 提示：点击上方日期导航查看历史论文</p>';
                }
                
                // 显示"等待中"提示
                // 添加类使 grid 容器居中
                gridEl.classList.add('daily-arxiv-grid-no-results');
                
                // 检查 LLM 配置
                if (!dailyArxivLLMConfigured) {
                    gridEl.innerHTML = `
                        <div class="daily-arxiv-waiting" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; text-align: center; color: #666; width: 100%;">
                            <i class="fas fa-exclamation-triangle fa-3x" style="margin-bottom: 20px; color: #f39c12;"></i>
                            <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">LLM API 未配置</h3>
                            <p style="margin-bottom: 30px; font-size: 1em; color: #888;">Daily arXiv 功能需要配置 LLM API 才能使用。请在设置中配置 LLM API（Model、Base URL、API Key）</p>
                            <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;">
                                <button class="btn btn-primary" onclick="switchTab('setting'); setTimeout(() => { const btn = document.querySelector('[data-setting=\\'agentic\\']'); if (btn) btn.click(); }, 100);">
                                    <i class="fas fa-cog"></i> 前往设置
                                </button>
                            </div>
                        </div>
                    `;
                } else {
                    gridEl.innerHTML = `
                        <div class="daily-arxiv-waiting" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; text-align: center; color: #666; width: 100%;">
                            <i class="fas fa-clock fa-3x" style="margin-bottom: 20px; color: #999;"></i>
                            <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">暂无新论文</h3>
                            <p style="margin-bottom: 30px; font-size: 1em; color: #888;">等待自动抓取，或点击下方按钮手动触发</p>
                            <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;">
                                <button class="btn btn-primary" onclick="triggerFetchPapers(false)">
                                    <i class="fas fa-sync"></i> 抓取当前分区
                                </button>
                                <button class="btn btn-secondary" onclick="triggerFetchAllCategories(false)">
                                    <i class="fas fa-sync-alt"></i> 抓取所有分区
                                </button>
                            </div>
                            ${hint}
                        </div>
                    `;
                }
            }
            if (emptyEl) emptyEl.style.display = 'none';
        } else {
            // 未配置分区，显示配置提示
            gridEl.innerHTML = '';
            if (emptyEl) emptyEl.style.display = 'flex';
        }
        return;
    }
    
    if (emptyEl) emptyEl.style.display = 'none';
    
    gridEl.innerHTML = papers.map((paper, index) => {
        // 使用 announced 日期（公布日期）而不是 published（提交日期）
        const date = paper.announced 
            ? new Date(paper.announced).toLocaleDateString('zh-CN') 
            : (paper.updated ? new Date(paper.updated).toLocaleDateString('zh-CN') : '');
        const authors = paper.authors ? (paper.authors.length > 50 ? paper.authors.substring(0, 50) + '...' : paper.authors) : '';
        
        // 机构信息显示（完整显示，灰色圆角边框，不同单位不同颜色）
        let affiliationsHtml = '';
        if (paper.affiliations && paper.affiliations.length > 0) {
            const affTags = paper.affiliations.map(aff => {
                const color = getColorForString(aff);
                return `<span class="aff-mini-tag" style="color: ${color};">${escapeHtml(aff)}</span>`;
            }).join('');
            affiliationsHtml = `<div class="daily-arxiv-card-affiliations">
                ${affTags}
            </div>`;
        }
        
        // 地区旗帜显示（去重，使用 set）- 将显示在图片左上角，分类标签右侧
        let countriesFlagsHtml = '';
        if (paper.countries && paper.countries.length > 0) {
            const uniqueCountries = [...new Set(paper.countries.filter(c => c && c.trim()))];
            if (uniqueCountries.length > 0) {
                const flagTags = uniqueCountries.map(country => {
                    const flag = getCountryFlag(country);
                    return flag ? `<span class="country-flag-in-thumbnail" title="${escapeHtml(country)}">${flag}</span>` : '';
                }).filter(tag => tag).join('');
                if (flagTags) {
                    countriesFlagsHtml = `<div class="daily-arxiv-card-countries-thumbnail">${flagTags}</div>`;
                }
            }
        }
        
        // 计算用于展示的分类标签：
        // - 优先使用合并后的 all_fetch_categories
        // - 否则退回到单个 fetch_category / 当前分区 / 论文主分类
        let categoryTags = [];
        if (Array.isArray(paper.all_fetch_categories) && paper.all_fetch_categories.length > 0) {
            categoryTags = paper.all_fetch_categories;
        } else if (paper.fetch_category) {
            categoryTags = [paper.fetch_category];
        } else if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
            categoryTags = [dailyArxivCurrentCategory];
        } else if (paper.primary_category) {
            categoryTags = [paper.primary_category];
        }
        const displayCategoryLabel = categoryTags.join(', ');

        // 用于缩略图 API 的分类参数仍然只取一个具体分区，避免路径不合法
        const thumbnailCategory = categoryTags[0] || paper.fetch_category || paper.primary_category || dailyArxivCurrentCategory || '';
        
        // 关键词显示（在日期下方，黑色字体，使用 LLM 原始输出）
        let keywordsHtml = '';
        if (paper.keywords && paper.keywords.length > 0) {
            // 按关键词长度升序排序（最短的排在前面，节约空间）
            const sortedKeywords = [...paper.keywords].sort((a, b) => a.length - b.length);
            const kwTags = sortedKeywords.map(kw => {
                // 直接使用原始关键词，不进行大小写转换
                return `<span class="keyword-mini-tag">${escapeHtml(kw)}</span>`;
            }).join('');
            keywordsHtml = `<div class="daily-arxiv-card-keywords">${kwTags}</div>`;
        }
        
        // 生成缩略图URL
        let thumbnailHtml = '';
        if (paper.thumbnail_path) {
            // 从thumbnail_path提取信息构建URL
            // thumbnail_path格式: /path/to/date/category/arxiv_id_thumbnail.jpg
            const thumbnailUrl = `/api/daily-arxiv/thumbnail/${dailyArxivCurrentDate}/${encodeURIComponent(thumbnailCategory)}/${encodeURIComponent(paper.arxiv_id)}`;
            thumbnailHtml = `
                <img src="${thumbnailUrl}" 
                     loading="lazy"
                     alt="${escapeHtml(paper.title)}" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                     style="width: 100%; height: 100%; object-fit: cover;" />
                <div class="thumbnail-fallback" style="display: none; width: 100%; height: 100%; align-items: center; justify-content: center; background: #f5f5f5;">
                    <i class="fas fa-file-pdf placeholder-icon"></i>
                </div>
            `;
        } else {
            thumbnailHtml = `
                <i class="fas fa-file-pdf placeholder-icon"></i>
            `;
        }
        
        // 高亮函数：仅在有搜索词时对标题/作者/机构做 <mark> 包裹
        const highlight = (text) => highlightDailyArxiv(text);

        return `
            <div class="daily-arxiv-card" data-index="${index}" onclick="showDailyArxivDetail(${index})">
                <div class="daily-arxiv-card-thumbnail">
                    ${thumbnailHtml}
                    <div class="daily-arxiv-card-thumbnail-badges">
                        <span class="daily-arxiv-card-category">${displayCategoryLabel}</span>
                        ${countriesFlagsHtml}
                    </div>
                </div>
                <div class="daily-arxiv-card-body">
                    <div class="daily-arxiv-card-title" title="${escapeHtml(paper.title)}">${highlight(paper.title)}</div>
                    <div class="daily-arxiv-card-authors" title="${escapeHtml(paper.authors)}">${highlight(authors)}</div>
                    ${paper.affiliations && paper.affiliations.length > 0 ? `
                        <div class="daily-arxiv-card-affiliations">
                            ${paper.affiliations.map(aff => {
                                const color = getColorForString(aff);
                                return `<span class="aff-mini-tag" style="color: ${color};">${highlight(aff)}</span>`;
                            }).join('')}
                        </div>
                    ` : ''}
                    <div class="daily-arxiv-card-meta">
                        <span class="daily-arxiv-card-date">${date}</span>
                        <div class="daily-arxiv-card-actions">
                            ${paper.homepage ? `<button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}', '_blank')" title="项目主页">
                                <i class="fas fa-home"></i>
                            </button>` : ''}
                            ${paper.github ? `<button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}', '_blank')" title="GitHub 仓库">
                                <i class="fab fa-github"></i>
                            </button>` : ''}
                            <button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('https://arxiv.org/abs/${paper.arxiv_id}', '_blank')" title="在 arXiv 查看">
                                <i class="fas fa-external-link-alt"></i>
                            </button>
                            ${(() => {
                                // 检查论文是否已在待读列表中
                                const isInReadingList = paper.paper_id && readingListPaperIds.has(paper.paper_id);
                                if (isInReadingList) {
                                    return `<button class="daily-arxiv-card-action add-to-reading-list paper-col-btn reading icon-only in-list" data-paper-id="${paper.paper_id}" onclick="onDailyArxivRemoveFromReadingList(${index}, event)" title="从待读列表移除">
                                        <i class="fas fa-times"></i>
                                    </button>`;
                                } else {
                                    return `<button class="daily-arxiv-card-action add-to-reading-list paper-col-btn reading icon-only" onclick="onDailyArxivAddToReadingList(${index}, event)" title="添加到待读列表">
                                        <i class="fas fa-book-open"></i>
                                    </button>`;
                                }
                            })()}
                        </div>
                    </div>
                    ${keywordsHtml}
                </div>
            </div>
        `;
    }).join('');
}

// 渲染单位过滤器
function renderDailyArxivFilterAffiliations() {
    const container = document.getElementById('daily-arxiv-filter-affiliations');
    if (!container) return;

    // 基于当前视图下的论文计算单位统计（不应用单位/地区过滤，但会考虑"第一单位"配置）
    const papers = getCurrentDailyArxivPapers(false);
    const stats = new Map(); // aff -> { count, color, isKnown }

    // 统计第一单位数量（用于显示总数）
    let firstAffCount = 0;
    // 统计常见机构数量（用于显示总数）
    let knownInstCount = 0;

    papers.forEach(paper => {
        const affs = paper.affiliations || [];
        if (affs.length > 0) {
            firstAffCount++;
            
            // 检查是否有常见机构
            if (affs.some(aff => dailyArxivKnownInstitutions.has(aff))) {
                knownInstCount++;
            }
        }
        
        // 根据特殊过滤条件决定统计哪些机构
        let affsToCount = affs;
        
        // 如果启用了"第一单位"过滤，只统计第一个机构
        if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
            affsToCount = [affs[0]];
        }
        
        affsToCount.forEach(aff => {
            if (!aff) return;
            const key = aff;
            const isKnown = dailyArxivKnownInstitutions.has(aff);
            
            if (!stats.has(key)) {
                stats.set(key, { count: 1, color: getColorForString(key), isKnown });
            } else {
                stats.get(key).count += 1;
            }
        });
    });

    const entries = Array.from(stats.entries());
    // 没有单位时清空即可
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">当前视图暂无机构信息</span>';
        return;
    }

    // 分组：常见机构 vs 其他机构
    const knownEntries = entries.filter(([aff, info]) => info.isKnown);
    const unknownEntries = entries.filter(([aff, info]) => !info.isKnown);

    // 按数量降序，再按名称排序
    const sortFn = (a, b) => {
        const countDiff = b[1].count - a[1].count;
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    };
    knownEntries.sort(sortFn);
    unknownEntries.sort(sortFn);

    // 生成 HTML：特殊过滤项 + 常见机构 + 其他机构
    let html = '';

    // 特殊过滤项
    html += `
        <div class="daily-arxiv-filter-special-items">
            <button 
                class="daily-arxiv-filter-special ${dailyArxivFilterFirstAffiliation ? 'active' : ''}" 
                onclick="toggleFirstAffiliationFilter()"
                title="只显示有第一单位的论文">
                <span class="label">第一单位</span>
                <span class="count">(${firstAffCount})</span>
            </button>
        </div>
    `;

    // 决定是否显示分组标题
    // 如果两种机构都有，才显示分组标题
    const shouldShowGroupTitles = knownEntries.length > 0 && unknownEntries.length > 0;

    // 常见机构列表
    if (knownEntries.length > 0) {
        if (shouldShowGroupTitles) {
            html += '<div class="filter-section-divider">常见机构</div>';
        }
        html += knownEntries.map(([aff, info]) => {
            const isSelected = dailyArxivSelectedAffiliations.has(aff);
            const isExcluded = dailyArxivExcludedAffiliations.has(aff);
            const countLabel = info.count > 1 ? ` (${info.count})` : '';
            const bgColor = getBgColorForString(aff);
            const textColor = info.color;
            const activeClass = isSelected ? 'active' : '';
            const excludedClass = isExcluded ? 'excluded' : '';
            return `
                <button 
                    class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                    data-affiliation="${escapeHtml(aff)}"
                    title="${escapeHtml(aff)}${countLabel}"
                    style="${!isExcluded ? `border-color: ${textColor}; color: ${textColor}; background: ${isSelected ? bgColor : 'transparent'};` : ''}"
                >
                    <span class="dot" style="background:${isExcluded ? '#9ca3af' : textColor};"></span>
                    <span class="label">${escapeHtml(aff)}</span>
                    ${countLabel}
                    <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeAffiliation('${escapeHtml(aff).replace(/'/g, "\\'")}');" title="排除此单位">
                        <i class="fas fa-times"></i>
                    </span>
                </button>
            `;
        }).join('');
    }

    // 其他机构列表
    if (unknownEntries.length > 0) {
        if (shouldShowGroupTitles) {
            html += `
                <div class="filter-section-divider">
                    <span>其他机构</span>
                    <button 
                        class="hide-all-unknown-btn ${dailyArxivHideUnknownFirstAffiliation ? 'active' : ''}" 
                        onclick="hideAllUnknownInstitutions()" 
                        title="隐藏第一单位属于「其他机构」的论文；再次点击可取消隐藏">
                        全部隐藏
                    </button>
                </div>
            `;
        }
        html += unknownEntries.map(([aff, info]) => {
            const isSelected = dailyArxivSelectedAffiliations.has(aff);
            const isManuallyExcluded = dailyArxivExcludedAffiliations.has(aff);
            // 全局“全部隐藏”开启时，这一组本身就代表“其他机构”，视觉上也应表现为排除状态
            const isEffectivelyExcluded = isManuallyExcluded || dailyArxivHideUnknownFirstAffiliation;
            const countLabel = info.count > 1 ? ` (${info.count})` : '';
            const bgColor = getBgColorForString(aff);
            const textColor = info.color;
            const activeClass = isSelected ? 'active' : '';
            const excludedClass = isEffectivelyExcluded ? 'excluded' : '';
            const style = !isEffectivelyExcluded
                ? 'border-color: ' + textColor + '; color: ' + textColor + '; background: ' + (isSelected ? bgColor : 'transparent') + ';'
                : '';
            return `
                <button 
                    class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                    data-affiliation="${escapeHtml(aff)}"
                    title="${escapeHtml(aff)}${countLabel}"
                    style="${style}"
                >
                    <span class="dot" style="background:${isEffectivelyExcluded ? '#9ca3af' : textColor};"></span>
                    <span class="label">${escapeHtml(aff)}</span>
                    ${countLabel}
                    <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeAffiliation('${escapeHtml(aff).replace(/'/g, "\\'")}');" title="排除此单位">
                        <i class="fas fa-times"></i>
                    </span>
                </button>
            `;
        }).join('');
    }

    container.innerHTML = html;

    // 绑定点击事件（多选）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // 如果点击的是 x 按钮，不触发选择
            if (e.target.closest('.filter-remove-btn')) return;
            
            const aff = btn.getAttribute('data-affiliation');
            if (!aff) return;
            // 如果已排除，先取消排除
            if (dailyArxivExcludedAffiliations.has(aff)) {
                dailyArxivExcludedAffiliations.delete(aff);
            }
            if (dailyArxivSelectedAffiliations.has(aff)) {
                dailyArxivSelectedAffiliations.delete(aff);
            } else {
                dailyArxivSelectedAffiliations.add(aff);
            }
            // 重新渲染过滤器和网格，实现实时过滤
            renderDailyArxivFilterAffiliations();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// 渲染地区过滤器
function renderDailyArxivFilterCountries() {
    const container = document.getElementById('daily-arxiv-filter-countries');
    if (!container) return;

    // 基于当前视图下的论文计算地区统计（不应用地区过滤）
    const papers = getCurrentDailyArxivPapers(false);
    const stats = new Map(); // normalized country name -> count

    papers.forEach(paper => {
        const countries = paper.countries || [];
        countries.forEach(country => {
            if (!country || !country.trim()) return;
            // 使用标准化后的地区名称作为key
            const normalizedCountry = normalizeCountryName(country);
            if (!stats.has(normalizedCountry)) {
                stats.set(normalizedCountry, 1);
            } else {
                stats.set(normalizedCountry, stats.get(normalizedCountry) + 1);
            }
        });
    });

    const entries = Array.from(stats.entries());
    // 没有地区时清空即可
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">当前视图暂无地区信息</span>';
        return;
    }

    // 按数量降序，再按名称排序
    entries.sort((a, b) => {
        const countDiff = b[1] - a[1];
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    });

    container.innerHTML = entries.map(([country, count]) => {
        const isSelected = dailyArxivSelectedCountries.has(country);
        const isExcluded = dailyArxivExcludedCountries.has(country);
        // 尝试获取国旗，如果找不到，尝试使用原始国家名称（标准化前的）
        let flag = getCountryFlag(country);
        // 如果还是找不到，尝试一些常见的变体
        if (!flag) {
            // 尝试添加常见后缀/前缀的变体
            const variants = [
                country,
                country.replace(/\s+Republic\s*$/i, ''),
                country.replace(/\s+Kingdom\s*$/i, ''),
                country.replace(/^The\s+/i, ''),
                country.replace(/\s+of\s+.*$/i, ''),
            ];
            for (const variant of variants) {
                flag = getCountryFlag(variant);
                if (flag) break;
            }
        }
        const countLabel = count > 1 ? ` (${count})` : '';
        const activeClass = isSelected ? 'active' : '';
        const excludedClass = isExcluded ? 'excluded' : '';
        
        // 如果没有国旗，显示缩写或简化的名称
        let displayText = flag;
        if (!flag) {
            // 尝试生成缩写（取首字母大写）
            const words = country.split(/\s+/).filter(w => w.length > 0);
            if (words.length > 1 && words.length <= 4) {
                // 如果是多个词，取首字母缩写
                displayText = words.map(w => w[0].toUpperCase()).join('');
            } else if (country.length > 15) {
                // 如果太长，截断
                displayText = country.substring(0, 12) + '...';
            } else {
                displayText = country;
            }
        }
        
        return `
            <button 
                class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                data-country="${escapeHtml(country)}"
                title="${escapeHtml(country)}${countLabel}"
                style="${!isExcluded ? '' : ''}"
            >
                <span class="dot" style="background:transparent;"></span>
                <span class="label country-flag-label ${flag ? '' : 'no-flag'}">${escapeHtml(displayText)}</span>
                ${countLabel}
                <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeCountry('${escapeHtml(country).replace(/'/g, "\\'")}');" title="排除此地区">
                    <i class="fas fa-times"></i>
                </span>
            </button>
        `;
    }).join('');

    // 绑定点击事件（多选）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // 如果点击的是 x 按钮，不触发选择
            if (e.target.closest('.filter-remove-btn')) return;
            
            const country = btn.getAttribute('data-country');
            if (!country) return;
            // 如果已排除，先取消排除
            if (dailyArxivExcludedCountries.has(country)) {
                dailyArxivExcludedCountries.delete(country);
            }
            if (dailyArxivSelectedCountries.has(country)) {
                dailyArxivSelectedCountries.delete(country);
            } else {
                dailyArxivSelectedCountries.add(country);
            }
            // 重新渲染过滤器和网格，实现实时过滤
            renderDailyArxivFilterCountries();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// 切换单位排除状态
// 切换"第一单位"过滤
function toggleFirstAffiliationFilter() {
    dailyArxivFilterFirstAffiliation = !dailyArxivFilterFirstAffiliation;
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

function hideAllUnknownInstitutions() {
    // 作为一个开关使用：
    // - 第一次点击：开启“隐藏第一单位为其他机构”的过滤
    // - 再次点击：关闭该过滤，还原所有论文显示
    dailyArxivHideUnknownFirstAffiliation = !dailyArxivHideUnknownFirstAffiliation;

    // 重新渲染
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

function toggleExcludeAffiliation(aff) {
    if (!aff) return;
    // 如果已选中，先取消选中
    if (dailyArxivSelectedAffiliations.has(aff)) {
        dailyArxivSelectedAffiliations.delete(aff);
    }
    // 切换排除状态
    if (dailyArxivExcludedAffiliations.has(aff)) {
        dailyArxivExcludedAffiliations.delete(aff);
    } else {
        dailyArxivExcludedAffiliations.add(aff);
    }
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// 切换地区排除状态
function toggleExcludeCountry(country) {
    if (!country) return;
    // 如果已选中，先取消选中
    if (dailyArxivSelectedCountries.has(country)) {
        dailyArxivSelectedCountries.delete(country);
    }
    // 切换排除状态
    if (dailyArxivExcludedCountries.has(country)) {
        dailyArxivExcludedCountries.delete(country);
    } else {
        dailyArxivExcludedCountries.add(country);
    }
    renderDailyArxivFilterCountries();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// 渲染关键词过滤器
function renderDailyArxivFilterKeywords() {
    const container = document.getElementById('daily-arxiv-filter-keywords');
    if (!container) return;

    // 基于当前视图下的论文计算关键词统计：
    // - 会考虑当前已选中的单位/地区过滤
    // - 不会应用关键词本身的过滤（避免互相影响）
    const papers = getDailyArxivPapersForKeywordFilter();
    const stats = new Map(); // keyword -> count

    papers.forEach(paper => {
        const keywords = paper.keywords || [];
        keywords.forEach(keyword => {
            if (!keyword || !keyword.trim()) return;
            const key = keyword.trim();
            if (!stats.has(key)) {
                stats.set(key, 1);
            } else {
                stats.set(key, stats.get(key) + 1);
            }
        });
    });

    const entries = Array.from(stats.entries());
    // 没有关键词时清空即可
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">当前视图暂无关键词信息</span>';
        return;
    }

    // 按数量降序，再按名称排序
    entries.sort((a, b) => {
        const countDiff = b[1] - a[1];
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    });

    container.innerHTML = entries.map(([keyword, count]) => {
        const isSelected = dailyArxivSelectedKeywords.has(keyword);
        const isExcluded = dailyArxivExcludedKeywords.has(keyword);
        const countLabel = count > 1 ? ` (${count})` : '';
        const activeClass = isSelected ? 'active' : '';
        const excludedClass = isExcluded ? 'excluded' : '';
        return `
            <button 
                class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                data-keyword="${escapeHtml(keyword)}"
                title="${escapeHtml(keyword)}${countLabel}"
                style="${!isExcluded ? '' : ''}"
            >
                <span class="dot" style="background:transparent;"></span>
                <span class="label">${escapeHtml(keyword)}</span>
                ${countLabel}
                <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeKeyword('${escapeHtml(keyword).replace(/'/g, "\\'")}');" title="排除此关键词">
                    <i class="fas fa-times"></i>
                </span>
            </button>
        `;
    }).join('');

    // 绑定点击事件（多选）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // 如果点击的是 x 按钮，不触发选择
            if (e.target.closest('.filter-remove-btn')) return;
            
            const keyword = btn.getAttribute('data-keyword');
            if (!keyword) return;
            // 如果已排除，先取消排除
            if (dailyArxivExcludedKeywords.has(keyword)) {
                dailyArxivExcludedKeywords.delete(keyword);
            }
            if (dailyArxivSelectedKeywords.has(keyword)) {
                dailyArxivSelectedKeywords.delete(keyword);
            } else {
                dailyArxivSelectedKeywords.add(keyword);
            }
            // 重新渲染过滤器和网格，实现实时过滤
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// 切换关键词排除状态
function toggleExcludeKeyword(keyword) {
    if (!keyword) return;
    // 如果已选中，先取消选中
    if (dailyArxivSelectedKeywords.has(keyword)) {
        dailyArxivSelectedKeywords.delete(keyword);
    }
    // 切换排除状态
    if (dailyArxivExcludedKeywords.has(keyword)) {
        dailyArxivExcludedKeywords.delete(keyword);
    } else {
        dailyArxivExcludedKeywords.add(keyword);
    }
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// HTML 转义
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 显示论文详情
function showDailyArxivDetail(index) {
    // 获取当前显示的论文列表（与 renderDailyArxivGrid 逻辑保持一致，包含合并逻辑）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[index];
    if (!paper) return;
    
    // 使用 announced 日期（公布日期）
    const announcedDate = paper.announced 
        ? new Date(paper.announced).toLocaleDateString('zh-CN') 
        : '';
    const submitDate = paper.published ? new Date(paper.published).toLocaleDateString('zh-CN') : '';
    
    // 机构信息区域（带颜色）
    let affiliationsHtml = '';
    if (paper.affiliations && paper.affiliations.length > 0) {
        const affTags = paper.affiliations.map(aff => {
            const bgColor = getBgColorForString(aff);
            const textColor = getColorForString(aff);
            return `<span class="affiliation-tag" style="background: ${bgColor}; color: ${textColor};">${escapeHtml(aff)}</span>`;
        }).join('');
        
        // 地区旗帜显示（去重）
        let countriesFlagsHtml = '';
        if (paper.countries && paper.countries.length > 0) {
            const uniqueCountries = [...new Set(paper.countries.filter(c => c && c.trim()))];
            if (uniqueCountries.length > 0) {
                const flagTags = uniqueCountries.map(country => {
                    const flag = getCountryFlag(country);
                    return flag ? `<span class="country-flag-large" title="${escapeHtml(country)}">${flag}</span>` : '';
                }).filter(tag => tag).join('');
                if (flagTags) {
                    countriesFlagsHtml = `<div class="country-flags-section">
                        <span class="country-flags-label">Regions:</span>
                        <div class="country-flags">${flagTags}</div>
                    </div>`;
                }
            }
        }
        
        affiliationsHtml = `
            <div class="daily-arxiv-detail-affiliations">
                <h4><i class="fas fa-building"></i> Affiliations</h4>
                <div class="affiliation-tags">${affTags}</div>
                ${countriesFlagsHtml}
            </div>
        `;
    } else {
        affiliationsHtml = `
            <div class="daily-arxiv-detail-affiliations">
                <h4><i class="fas fa-building"></i> Affiliations</h4>
                <div class="affiliation-extract-prompt">
                    <p>机构信息尚未提取</p>
                    <button class="btn btn-secondary btn-sm" onclick="extractAffiliationsForPaper(${index})">
                        <i class="fas fa-magic"></i> 提取机构信息
                    </button>
                </div>
            </div>
        `;
    }
    
    // 关键词区域（黑色字体，使用 LLM 原始输出）
    let keywordsHtml = '';
    if (paper.keywords && paper.keywords.length > 0) {
        // 按关键词长度升序排序（最短的排在前面）
        const sortedKeywords = [...paper.keywords].sort((a, b) => a.length - b.length);
        const kwTags = sortedKeywords.map(kw => {
            // 直接使用原始关键词，不进行大小写转换
            return `<span class="keyword-tag">${escapeHtml(kw)}</span>`;
        }).join('');
        keywordsHtml = `
            <div class="daily-arxiv-detail-keywords">
                <h4><i class="fas fa-key"></i> Keywords</h4>
                <div class="keyword-tags">${kwTags}</div>
            </div>
        `;
    }
    
    // 摘要总结区域（先显示 summary，再显示 abstract）
    let summaryHtml = '';
    if (paper.summary) {
        summaryHtml = `
            <div class="daily-arxiv-detail-summary">
                <h4><i class="fas fa-lightbulb"></i> 简要总结</h4>
                <p>${escapeHtml(paper.summary)}</p>
            </div>
        `;
    }
    
    const modalHtml = `
        <div class="daily-arxiv-detail-modal" onclick="if(event.target === this) closeDailyArxivDetail()">
            <div class="daily-arxiv-detail-content">
                <div class="daily-arxiv-detail-header">
                    <h3>${escapeHtml(paper.title)}</h3>
                    <button class="daily-arxiv-detail-close" onclick="closeDailyArxivDetail()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="daily-arxiv-detail-body">
                    <div class="daily-arxiv-detail-meta">
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-users"></i>
                            <span>${escapeHtml(paper.authors)}</span>
                        </div>
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-tag"></i>
                            <span>${(paper.categories || []).join(', ')}</span>
                        </div>
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-calendar"></i>
                            <span>公布: ${announcedDate} | 提交: ${submitDate}</span>
                        </div>
                        ${paper.homepage ? `<div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-home"></i>
                            <span><a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" style="color: #2196F3; text-decoration: none;">${escapeHtml(paper.homepage)}</a></span>
                        </div>` : ''}
                        ${paper.github ? `<div class="daily-arxiv-detail-meta-item">
                            <i class="fab fa-github"></i>
                            <span><a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" style="color: #2196F3; text-decoration: none;">${escapeHtml(paper.github)}</a></span>
                        </div>` : ''}
                    </div>
                    ${affiliationsHtml}
                    ${keywordsHtml}
                    ${summaryHtml}
                    <div class="daily-arxiv-detail-abstract">
                        <h4><i class="fas fa-file-alt"></i> Abstract</h4>
                        <p>${escapeHtml(paper.abstract)}</p>
                    </div>
                </div>
                <div class="daily-arxiv-detail-footer">
                    <div class="daily-arxiv-detail-links">
                        ${paper.homepage ? `<a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" title="项目主页">
                            <i class="fas fa-home"></i> Homepage
                        </a>` : ''}
                        ${paper.github ? `<a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" title="GitHub 仓库">
                            <i class="fab fa-github"></i> GitHub
                        </a>` : ''}
                        <a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank">
                            <i class="fas fa-external-link-alt"></i> arXiv
                        </a>
                        <a href="${paper.pdf_url}" target="_blank">
                            <i class="fas fa-file-pdf"></i> PDF
                        </a>
                    </div>
                    <button class="daily-arxiv-add-btn" onclick="onDailyArxivAddToReadingList(${index}, event); closeDailyArxivDetail();">
                        <i class="fas fa-book-open"></i> 添加到待读列表
                    </button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

// 关闭论文详情
function closeDailyArxivDetail() {
    const modal = document.querySelector('.daily-arxiv-detail-modal');
    if (modal) {
        modal.remove();
    }
}

// 提取论文机构信息
async function extractAffiliationsForPaper(paperIndex) {
    // 获取当前显示的论文列表（与 renderDailyArxivGrid 逻辑保持一致，包含合并逻辑）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[paperIndex];
    if (!paper) return;
    
    // 获取 Agentic Settings 中的 LLM 配置
    let agenticSettings = {};
    try {
        const res = await fetch('/api/settings/agentic');
        if (res.ok) {
            agenticSettings = await res.json();
        }
    } catch (err) {
        console.error('获取 Agentic Settings 失败:', err);
    }
    
    const llmBaseUrl = agenticSettings.llmBaseUrl;
    const llmApiKey = agenticSettings.llmApiKey;
    
    if (!llmBaseUrl || !llmApiKey) {
        showMessage('请先在设置中配置 Agentic Settings 的 LLM API', 'warning');
        return;
    }
    
    // 更新按钮状态
    const extractBtn = document.querySelector('.affiliation-extract-prompt button');
    if (extractBtn) {
        extractBtn.disabled = true;
        extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 正在提取...';
    }
    
    try {
        // 获取论文的日期和分区信息
        const paperDate = paper.fetch_date || dailyArxivCurrentDate;
        const paperCategory = paper.fetch_category || dailyArxivCurrentCategory;
        
        const res = await fetch('/api/daily-arxiv/extract-affiliations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                arxiv_id: paper.arxiv_id,
                date: paperDate,
                fetch_category: paperCategory,
            })
        });
        
        const data = await res.json();
        
        if (data.success) {
            // 更新本地缓存（使用正确的缓存键）
            const cacheKey = dailyArxivCurrentCategory === 'all' 
                ? null  // 全部模式需要找到对应的缓存
                : `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
            
            if (cacheKey && dailyArxivPapers[cacheKey]) {
                // 找到对应的论文并更新
                const cachedPaper = dailyArxivPapers[cacheKey].find(p => p.arxiv_id === paper.arxiv_id);
                if (cachedPaper) {
                    cachedPaper.affiliations = data.affiliations || [];
                    cachedPaper.countries = data.countries || [];
                    cachedPaper.homepage = data.homepage || null;
                    cachedPaper.github = data.github || null;
                    cachedPaper.affiliations_extracted = true;
                }
            } else if (dailyArxivCurrentCategory === 'all') {
                // 全部模式：需要在所有分区的缓存中查找并更新
                dailyArxivCategories.forEach(cat => {
                    const catCacheKey = `${dailyArxivCurrentDate}_${cat}`;
                    if (dailyArxivPapers[catCacheKey]) {
                        const cachedPaper = dailyArxivPapers[catCacheKey].find(p => p.arxiv_id === paper.arxiv_id);
                        if (cachedPaper) {
                            cachedPaper.affiliations = data.affiliations || [];
                            cachedPaper.countries = data.countries || [];
                            cachedPaper.homepage = data.homepage || null;
                            cachedPaper.github = data.github || null;
                            cachedPaper.affiliations_extracted = true;
                        }
                    }
                });
            }
            
            // 刷新详情模态框
            closeDailyArxivDetail();
            showDailyArxivDetail(paperIndex);
            
            // 刷新网格显示
            renderDailyArxivGrid();
            
            const msgParts = [];
            if (data.affiliations && data.affiliations.length > 0) {
                msgParts.push(`提取到 ${data.affiliations.length} 个机构`);
            }
            if (data.homepage) {
                msgParts.push('提取到 Homepage');
            }
            if (data.github) {
                msgParts.push('提取到 GitHub');
            }
            
            if (msgParts.length > 0) {
                showMessage(msgParts.join('，'), 'success');
            } else {
                showMessage('未能提取到机构信息、homepage 或 github', 'info');
            }
        } else {
            showMessage(data.error || '提取机构信息失败', 'error');
            // 恢复按钮
            if (extractBtn) {
                extractBtn.disabled = false;
                extractBtn.innerHTML = '<i class="fas fa-magic"></i> 提取机构信息';
            }
        }
    } catch (err) {
        console.error('提取机构信息失败:', err);
        const errorMsg = err.message || '提取机构信息失败，请检查网络连接和API配置';
        showMessage(errorMsg, 'error');
        // 恢复按钮
        if (extractBtn) {
            extractBtn.disabled = false;
            extractBtn.innerHTML = '<i class="fas fa-magic"></i> 提取机构信息';
        }
    }
}

// Daily arXiv：一键添加到待读列表（不弹窗）
function onDailyArxivAddToReadingList(paperIndex, event) {
    if (event) {
        event.stopPropagation();
    }

    // 一键直接添加到待读列表（不弹出选择分类的弹窗）
    // 1. 获取当前显示的论文列表（与 renderDailyArxivGrid 逻辑保持一致，包含合并逻辑）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[paperIndex];
    if (!paper) return;

    // 2. 使用待读列表临时目录，不需要选择分类
    // 3. 调用后端：先导入到临时目录，再加入待读列表
    (async () => {
        try {
            // 使用论文自身的抓取分区；如果当前视图是 "all"，不要把 "all" 传给后端
            const fetchCategory =
                paper.fetch_category ||
                (dailyArxivCurrentCategory === 'all' ? null : dailyArxivCurrentCategory);

            const body = {
                arxiv_id: paper.arxiv_id,
                use_temp_dir: true,  // 使用临时目录
                date: dailyArxivCurrentDate,
            };
            if (fetchCategory) {
                body.fetch_category = fetchCategory;
            }

            const res = await fetch('/api/daily-arxiv/add-to-library', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            const data = await res.json();

            if (!data.success) {
                showMessage(data.error || '添加失败', 'error');
                return;
            }

            // 成功导入后，再加入待读列表
            if (data.paper_id) {
                try {
                    const readingRes = await fetch(`/api/reading-list/${data.paper_id}/add`, {
                        method: 'POST',
                    });
                    if (!readingRes.ok) {
                        console.warn('添加到待读列表失败:', await readingRes.text());
                    } else {
                        await updateReadingListCount();

                        // 更新当前卡片按钮为“从待读列表移除”的紫色按钮
                        const card = document.querySelector(`.daily-arxiv-card[data-index="${paperIndex}"]`);
                        if (card) {
                            const btn = card.querySelector('.daily-arxiv-card-action.add-to-reading-list');
                            if (btn) {
                                btn.dataset.paperId = data.paper_id;
                                btn.title = '从待读列表移除';
                                btn.innerHTML = '<i class="fas fa-times"></i>';
                                btn.classList.add('in-list');
                                btn.onclick = (e) => onDailyArxivRemoveFromReadingList(paperIndex, e);
                            }
                        }
                    }
                } catch (e) {
                    console.warn('添加到待读列表异常:', e);
                }
            }
        } catch (err) {
            console.error('添加到文库失败:', err);
            showMessage('添加失败', 'error');
        }
    })();
}

// Daily arXiv：从待读列表移除
async function onDailyArxivRemoveFromReadingList(paperIndex, event) {
    if (event) {
        event.stopPropagation();
    }

    // 找到当前卡片上的按钮，读取 paper_id
    const card = document.querySelector(`.daily-arxiv-card[data-index="${paperIndex}"]`);
    if (!card) return;

    const btn = card.querySelector('.daily-arxiv-card-action.add-to-reading-list');
    if (!btn) return;

    const paperId = btn.dataset.paperId;
    if (!paperId) return;

    try {
        // 先尝试移除，看是否需要确认
        const res = await fetch(`/api/reading-list/${paperId}/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: false })
        });

        if (!res.ok) {
            showMessage('移除失败', 'error');
            return;
        }

        const data = await res.json();
        
        if (data.requires_confirmation) {
            // 需要确认删除，显示弹窗
            const confirmed = confirm(data.message || '该论文还未移动到某个目录，是否要删除论文文件、AI解读和AI翻译？');
            if (confirmed) {
                // 用户确认，删除文件
                const deleteResponse = await fetch(`/api/reading-list/${paperId}/remove`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delete_files: true })
                });
                const deleteData = await deleteResponse.json();
                if (deleteData.success) {
                    await updateReadingListCount();
                    // 恢复为“添加到待读列表”的紫色书本按钮
                    btn.removeAttribute('data-paper-id');
                    btn.title = '添加到待读列表';
                    btn.innerHTML = '<i class="fas fa-book-open"></i>';
                    btn.classList.remove('in-list');
                    btn.onclick = (e) => onDailyArxivAddToReadingList(paperIndex, e);
                    showMessage('已从待读列表移除', 'success');
                } else {
                    showMessage('移除失败', 'error');
                }
            }
        } else if (data.success) {
            // 成功移除
            await updateReadingListCount();
            // 恢复为“添加到待读列表”的紫色书本按钮
            btn.removeAttribute('data-paper-id');
            btn.title = '添加到待读列表';
            btn.innerHTML = '<i class="fas fa-book-open"></i>';
            btn.classList.remove('in-list');
            btn.onclick = (e) => onDailyArxivAddToReadingList(paperIndex, e);
            showMessage('已从待读列表移除', 'success');
        } else {
            showMessage('移除失败', 'error');
        }
    } catch (error) {
        console.error('从待读列表移除失败:', error);
        showMessage('移除失败', 'error');
    }
}

// 显示 Daily arXiv 设置模态框
function showDailyArxivSettingsModal() {
    // 切换到设置界面的 Daily arXiv 面板
    switchTab('setting');
    switchSettingPanel('daily-arxiv');
}

// 切换到 Daily arXiv 视图
async function showDailyArxivView() {
    // 隐藏其他视图
    document.getElementById('paper-view').style.display = 'none';
    document.getElementById('setting-view').style.display = 'none';
    document.getElementById('daily-arxiv-view').style.display = 'block';
    
    // 隐藏"待读列表"标签
    const readingListLabel = document.getElementById('reading-list-label');
    if (readingListLabel) {
        readingListLabel.style.display = 'none';
    }
    
    // 更新导航栏状态
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    const dailyArxivTab = document.querySelector('.nav-tab[data-tab="daily-arxiv"]');
    if (dailyArxivTab) dailyArxivTab.classList.add('active');
    
    // 检查 LLM 配置并加载设置、日期和论文
    // 先检查 LLM API 状态（会显示弹窗如果失败）
    await checkDailyArxivLLMConfig();
    
    await loadDailyArxivSettings();
    // 先加载可用日期（这会设置 dailyArxivCurrentDate）
    await loadAvailableDates();
    
    // 检查缓存中是否有当前日期和分区的论文数据
    const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
    const hasCachedData = dailyArxivPapers[cacheKey] && dailyArxivPapers[cacheKey].length > 0;
    
    if (!hasCachedData && dailyArxivCategories.length > 0 && dailyArxivCurrentDate) {
        // 如果缓存中没有数据，尝试从服务器加载
        await loadPapersForCurrentDate();
    } else if (hasCachedData) {
        // 如果有缓存数据，直接渲染
        renderDailyArxivGrid();
    }
    
    // 检查是否有正在进行的抓取任务，如果有则自动启动进度轮询
    // 这样可以确保用户进入界面时能看到实时进度
    if (dailyArxivCategories.length > 0) {
        // 检查所有分区是否有正在进行的任务
        await checkAndStartProgressPolling();
        
        // 如果当前选中了特定分区，也检查该分区的进度
        if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
            await checkCategoryProgress(dailyArxivCurrentCategory);
        }
    }
    
    saveCurrentViewState();
}
// ==================== 自定义机构配置管理 ====================

let customInstitutions = []; // 存储自定义机构
let currentEditingInstitution = null; // 当前正在编辑的机构

/**
 * 加载自定义机构配置
 */
async function loadCustomInstitutions() {
    try {
        const response = await fetch('/api/custom-institutions');
        const data = await response.json();
        
        if (data.success) {
            customInstitutions = data.institutions || [];
            renderCustomInstitutions();
        } else {
            console.error('加载自定义机构失败:', data.error);
        }
    } catch (error) {
        console.error('加载自定义机构失败:', error);
    }
}

/**
 * 渲染自定义机构列表（类似关键词）
 */
function renderCustomInstitutions() {
    const listContainer = document.getElementById('custom-institution-list');
    
    if (!listContainer) return;
    
    if (customInstitutions.length === 0) {
        listContainer.innerHTML = `
            <div class="custom-institution-empty">
                暂无额外机构配置，点击"添加机构"按钮开始添加
            </div>
        `;
        return;
    }
    
    listContainer.innerHTML = customInstitutions.map(inst => `
        <div class="custom-institution-item" ondblclick="editInstitution('${escapeHtml(inst.abbreviation)}')" title="双击编辑">
            <i class="fas fa-university"></i>
            ${escapeHtml(inst.abbreviation)}
        </div>
    `).join('');
}

/**
 * 显示添加机构模态框
 */
function showAddInstitutionModal() {
    currentEditingInstitution = null;
    document.getElementById('institution-modal-title').textContent = '添加机构映射';
    document.getElementById('modal-institution-abbr').value = '';
    document.getElementById('modal-institution-abbr').disabled = false;
    document.getElementById('modal-variants-list').innerHTML = '';
    document.getElementById('modal-new-variant').value = '';
    document.getElementById('institution-modal-delete').style.display = 'none';
    updateVariantCount();
    
    // 显示模态框
    const modal = document.getElementById('institution-modal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden'; // 防止背景滚动
    
    setTimeout(() => {
        document.getElementById('modal-institution-abbr').focus();
    }, 100);
}

/**
 * 编辑机构（双击标签时）
 */
function editInstitution(abbreviation) {
    const institution = customInstitutions.find(inst => inst.abbreviation === abbreviation);
    if (!institution) return;
    
    currentEditingInstitution = institution;
    document.getElementById('institution-modal-title').textContent = '编辑机构映射';
    document.getElementById('modal-institution-abbr').value = abbreviation;
    document.getElementById('modal-institution-abbr').disabled = true;
    renderModalVariants(institution.variants);
    document.getElementById('modal-new-variant').value = '';
    document.getElementById('institution-modal-delete').style.display = 'inline-flex';
    updateVariantCount();
    
    // 显示模态框
    const modal = document.getElementById('institution-modal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
    
    setTimeout(() => {
        document.getElementById('modal-new-variant').focus();
    }, 100);
}

/**
 * 渲染模态框中的变体列表
 */
function renderModalVariants(variants) {
    const listContainer = document.getElementById('modal-variants-list');
    
    if (!variants || variants.length === 0) {
        listContainer.innerHTML = '';
        updateVariantCount();
        return;
    }
    
    listContainer.innerHTML = variants.map(variant => `
        <div class="institution-variant-tag">
            <span class="variant-text">${escapeHtml(variant)}</span>
            <span class="remove-variant" onclick="removeVariantInModal('${escapeHtml(variant)}')">
                <i class="fas fa-times"></i>
            </span>
        </div>
    `).join('');
    
    updateVariantCount();
}

/**
 * 更新变体数量显示
 */
function updateVariantCount() {
    const variants = getCurrentModalVariants();
    const countEl = document.getElementById('variant-count');
    if (countEl) {
        countEl.textContent = `${variants.length} 个`;
    }
}

/**
 * 根据自定义机构映射标准化机构名称（前端版本）
 */
function normalizeAffiliationFrontend(affiliation) {
    if (!affiliation || !customInstitutions) return affiliation;
    
    const affLower = affiliation.toLowerCase().trim();
    
    // 遍历所有自定义机构映射
    for (const inst of customInstitutions) {
        const abbr = inst.abbreviation;
        const variants = inst.variants || [];
        
        // 检查是否完全匹配某个变体（不区分大小写）
        for (const variant of variants) {
            if (variant.toLowerCase().trim() === affLower) {
                console.log(`[Institution] 标准化: "${affiliation}" -> "${abbr}"`);
                return abbr;
            }
        }
    }
    
    return affiliation; // 没有匹配，返回原值
}

/**
 * 对论文列表应用前端机构标准化
 */
function applyFrontendNormalizationToPapers(papers) {
    if (!papers || !Array.isArray(papers)) return papers;
    
    return papers.map(paper => {
        if (paper.affiliations && Array.isArray(paper.affiliations)) {
            // 标准化机构名称
            const normalizedAffiliations = paper.affiliations.map(aff => 
                normalizeAffiliationFrontend(aff)
            );
            
            // 去重
            const uniqueAffiliations = [...new Set(normalizedAffiliations)];
            
            return {
                ...paper,
                affiliations: uniqueAffiliations
            };
        }
        return paper;
    });
}

/**
 * 机构映射更改后刷新 Daily arXiv
 */
async function refreshDailyArxivAfterInstitutionChange() {
    console.log('[Institution] 开始刷新 Daily arXiv 论文数据...');
    
    // 检查是否在 Daily arXiv 视图
    const dailyArxivSection = document.getElementById('daily-arxiv-section');
    if (!dailyArxivSection) {
        console.log('[Institution] 不在 Daily arXiv 视图，跳过刷新');
        return;
    }
    
    try {
        // 对已缓存的论文应用标准化
        if (typeof dailyArxivPapers !== 'undefined') {
            console.log('[Institution] 对缓存的论文应用标准化...');
            for (const key in dailyArxivPapers) {
                if (dailyArxivPapers[key] && Array.isArray(dailyArxivPapers[key])) {
                    dailyArxivPapers[key] = applyFrontendNormalizationToPapers(dailyArxivPapers[key]);
                }
            }
        }
        
        // 重新渲染网格
        if (typeof renderDailyArxivGrid === 'function') {
            renderDailyArxivGrid();
            console.log('[Institution] 论文网格已刷新');
        }
        
        // 重新渲染过滤器（机构列表会更新）
        if (typeof renderDailyArxivFilterAffiliations === 'function') {
            renderDailyArxivFilterAffiliations();
            console.log('[Institution] 机构过滤器已刷新');
        }
        
    } catch (error) {
        console.error('[Institution] 刷新 Daily arXiv 失败:', error);
    }
}

/**
 * 在模态框中添加变体
 */
function addVariantInModal() {
    const input = document.getElementById('modal-new-variant');
    const variant = input.value.trim();
    
    if (!variant) {
        showMessage('请输入机构全称', 'error');
        return;
    }
    
    // 获取当前变体列表
    const currentVariants = getCurrentModalVariants();
    
    // 检查是否重复
    if (currentVariants.includes(variant)) {
        showMessage('该变体已存在', 'warning');
        return;
    }
    
    // 添加新变体
    currentVariants.push(variant);
    renderModalVariants(currentVariants);
    
    // 清空输入框
    input.value = '';
    input.focus();
    updateVariantCount();
}

/**
 * 在模态框中移除变体
 */
function removeVariantInModal(variant) {
    const currentVariants = getCurrentModalVariants();
    const newVariants = currentVariants.filter(v => v !== variant);
    renderModalVariants(newVariants);
    updateVariantCount();
}

/**
 * 获取模态框当前的变体列表
 */
function getCurrentModalVariants() {
    const listContainer = document.getElementById('modal-variants-list');
    const tags = listContainer.querySelectorAll('.institution-variant-tag');
    
    return Array.from(tags).map(tag => {
        // 通过 .variant-text 获取文本内容
        const textSpan = tag.querySelector('.variant-text');
        return textSpan ? textSpan.textContent.trim() : '';
    }).filter(text => text.length > 0);
}

/**
 * 保存机构（模态框）
 */
async function saveInstitutionInModal() {
    console.log('[Institution] 开始保存机构...');
    
    const abbreviation = document.getElementById('modal-institution-abbr').value.trim();
    const variants = getCurrentModalVariants();
    
    console.log('[Institution] 缩写:', abbreviation);
    console.log('[Institution] 变体:', variants);
    
    if (!abbreviation) {
        showMessage('请输入标准缩写', 'error');
        return;
    }
    
    if (variants.length === 0) {
        showMessage('至少需要添加一个全称变体', 'error');
        return;
    }
    
    try {
        console.log('[Institution] 发送请求到 /api/custom-institutions');
        const response = await fetch('/api/custom-institutions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                abbreviation: abbreviation,
                variants: variants
            })
        });
        
        console.log('[Institution] 收到响应:', response.status);
        const data = await response.json();
        console.log('[Institution] 响应数据:', data);
        
        if (data.success) {
            showMessage('机构已保存，正在刷新论文...', 'success');
            closeInstitutionModal();
            await loadCustomInstitutions();
            
            // 刷新 Daily arXiv 的论文数据，使新的机构映射生效
            await refreshDailyArxivAfterInstitutionChange();
        } else {
            showMessage('保存失败: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('[Institution] 保存机构失败:', error);
        showMessage('保存失败: ' + error.message, 'error');
    }
}

/**
 * 删除机构（模态框）
 */
async function deleteInstitutionInModal() {
    if (!currentEditingInstitution) return;
    
    const abbreviation = currentEditingInstitution.abbreviation;
    
    if (!confirm(`确定要删除机构 ${abbreviation} 吗？`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/custom-institutions/${encodeURIComponent(abbreviation)}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('已删除，正在刷新论文...', 'success');
            closeInstitutionModal();
            await loadCustomInstitutions();
            
            // 刷新 Daily arXiv 的论文数据
            await refreshDailyArxivAfterInstitutionChange();
        } else {
            showMessage('删除失败: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('删除机构失败:', error);
        showMessage('删除失败', 'error');
    }
}

/**
 * 关闭机构编辑模态框
 */
function closeInstitutionModal() {
    document.getElementById('institution-modal').style.display = 'none';
    document.body.style.overflow = ''; // 恢复背景滚动
    currentEditingInstitution = null;
}

/**
 * 初始化自定义机构管理
 */
function initCustomInstitutionManagement() {
    // 模态框回车键支持
    const variantInput = document.getElementById('modal-new-variant');
    if (variantInput) {
        variantInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addVariantInModal();
            }
        });
    }
    
    // ESC 键关闭模态框
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('institution-modal');
            if (modal && modal.style.display === 'flex') {
                closeInstitutionModal();
            }
        }
    });
}

// 在切换到 Daily arXiv 设置面板时加载自定义机构
document.addEventListener('DOMContentLoaded', () => {
    // 初始化自定义机构管理
    initCustomInstitutionManagement();
    
    // 立即加载自定义机构列表（页面加载时）
    loadCustomInstitutions();
    
    // 监听设置面板切换（确保切换到 Daily arXiv 设置时也刷新）
    const dailyArxivSettingBtn = document.querySelector('.setting-nav-item[data-setting="daily-arxiv"]');
    if (dailyArxivSettingBtn) {
        dailyArxivSettingBtn.addEventListener('click', () => {
            // 延迟加载，确保面板已显示
            setTimeout(() => {
                loadCustomInstitutions();
            }, 100);
        });
    }
});

// ==================== Export 功能 ====================
let exportTaskId = null;
let exportProgressInterval = null;

// 初始化导出功能
async function initExportFeature() {
    const btnStartExport = document.getElementById('btn-start-export');
    const btnCancelExport = document.getElementById('btn-cancel-export');
    const btnDownloadExport = document.getElementById('btn-download-export');
    
    if (btnStartExport) {
        btnStartExport.addEventListener('click', startExport);
    }
    
    if (btnCancelExport) {
        btnCancelExport.addEventListener('click', cancelExport);
    }
    
    if (btnDownloadExport) {
        btnDownloadExport.addEventListener('click', downloadExport);
    }
    
    // 获取并显示 papers 目录路径
    try {
        const response = await fetch('/api/papers-dir');
        const data = await response.json();
        if (data.success) {
            const pathElement = document.getElementById('papers-dir-path');
            if (pathElement) {
                pathElement.textContent = data.path;
            }
        }
    } catch (error) {
        console.error('获取 papers 目录路径失败:', error);
    }
}

// 开始导出
async function startExport() {
    const btnStart = document.getElementById('btn-start-export');
    const progressContainer = document.getElementById('export-progress-container');
    
    // 禁用开始按钮
    btnStart.disabled = true;
    btnStart.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 启动中...';
    
    try {
        const response = await fetch('/api/export/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({})
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showMessage(data.error || '启动导出失败', 'error');
            btnStart.disabled = false;
            btnStart.innerHTML = '<i class="fas fa-download"></i> 开始导出';
            return;
        }
        
        exportTaskId = data.task_id;
        
        // 显示进度容器
        progressContainer.style.display = 'block';
        btnStart.style.display = 'none';
        
        // 开始轮询进度
        startExportProgressPolling();
        
        showMessage('导出任务已启动', 'success');
        
    } catch (error) {
        console.error('启动导出失败:', error);
        showMessage('启动导出失败: ' + error.message, 'error');
        btnStart.disabled = false;
        btnStart.innerHTML = '<i class="fas fa-download"></i> 开始导出';
    }
}

// 轮询导出进度
function startExportProgressPolling() {
    if (exportProgressInterval) {
        clearInterval(exportProgressInterval);
    }
    
    // 立即查询一次
    checkExportProgress();
    
    // 每秒查询一次
    exportProgressInterval = setInterval(checkExportProgress, 1000);
}

// 检查导出进度
async function checkExportProgress() {
    if (!exportTaskId) return;
    
    try {
        const response = await fetch(`/api/export/status/${exportTaskId}`);
        const data = await response.json();
        
        if (!data.success) {
            stopExportProgressPolling();
            return;
        }
        
        const task = data.task;
        updateExportProgress(task);
        
        // 如果任务完成或失败，停止轮询
        if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
            stopExportProgressPolling();
        }
        
    } catch (error) {
        console.error('查询导出进度失败:', error);
    }
}

// 停止轮询
function stopExportProgressPolling() {
    if (exportProgressInterval) {
        clearInterval(exportProgressInterval);
        exportProgressInterval = null;
    }
}

// 更新导出进度显示
function updateExportProgress(task) {
    const statusText = document.getElementById('export-status-text');
    const progressText = document.getElementById('export-progress-text');
    const progressFill = document.getElementById('export-progress-fill');
    const currentPaper = document.getElementById('export-current-paper');
    const btnDownload = document.getElementById('btn-download-export');
    const btnCancel = document.getElementById('btn-cancel-export');
    
    // 更新状态文本
    if (task.status === 'pending') {
        statusText.textContent = '准备中...';
    } else if (task.status === 'running') {
        statusText.textContent = '正在导出...';
    } else if (task.status === 'completed') {
        statusText.textContent = '导出完成！';
        btnDownload.style.display = 'inline-flex';
        btnCancel.style.display = 'none';
    } else if (task.status === 'failed') {
        statusText.textContent = '导出失败';
        statusText.style.color = '#d73a49';
        currentPaper.textContent = task.error || '未知错误';
        currentPaper.style.color = '#d73a49';
        btnCancel.style.display = 'none';
    } else if (task.status === 'cancelled') {
        statusText.textContent = '已取消';
        statusText.style.color = '#6a737d';
        btnCancel.style.display = 'none';
    }
    
    // 更新进度
    if (task.total > 0) {
        const percent = Math.round((task.progress / task.total) * 100);
        progressText.textContent = `${task.progress} / ${task.total}`;
        progressFill.style.width = percent + '%';
    } else {
        progressText.textContent = '0 / 0';
        progressFill.style.width = '0%';
    }
    
    // 更新当前论文
    if (task.current_paper && task.status === 'running') {
        currentPaper.textContent = task.current_paper;
        currentPaper.style.color = '#57606a';
    }
}

// 取消导出
async function cancelExport() {
    if (!exportTaskId) return;
    
    if (!confirm('确定要取消导出吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/export/cancel/${exportTaskId}`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('已取消导出', 'info');
            resetExportUI();
        } else {
            showMessage(data.error || '取消失败', 'error');
        }
        
    } catch (error) {
        console.error('取消导出失败:', error);
        showMessage('取消导出失败: ' + error.message, 'error');
    }
}

// 下载导出文件
async function downloadExport() {
    if (!exportTaskId) return;
    
    try {
        // 直接通过浏览器下载
        window.location.href = `/api/export/download/${exportTaskId}`;
        
        showMessage('导出文件下载已开始', 'success');
        
        // 下载后重置 UI
        setTimeout(() => {
            resetExportUI();
        }, 2000);
        
    } catch (error) {
        console.error('下载导出文件失败:', error);
        showMessage('下载失败: ' + error.message, 'error');
    }
}

// 重置导出 UI
function resetExportUI() {
    const btnStart = document.getElementById('btn-start-export');
    const progressContainer = document.getElementById('export-progress-container');
    const btnDownload = document.getElementById('btn-download-export');
    const btnCancel = document.getElementById('btn-cancel-export');
    const statusText = document.getElementById('export-status-text');
    const currentPaper = document.getElementById('export-current-paper');
    
    btnStart.disabled = false;
    btnStart.innerHTML = '<i class="fas fa-download"></i> 开始导出';
    btnStart.style.display = 'inline-flex';
    
    progressContainer.style.display = 'none';
    btnDownload.style.display = 'none';
    btnCancel.style.display = 'inline-flex';
    
    statusText.textContent = '正在导出...';
    statusText.style.color = '';
    currentPaper.textContent = '';
    currentPaper.style.color = '';
    
    exportTaskId = null;
    stopExportProgressPolling();
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    initExportFeature();
});

// ========== 新手指引功能 ==========
function showOnboardingModal() {
    const modal = document.getElementById('onboarding-modal');
    if (modal) {
        modal.style.display = 'flex';
        // 防止背景滚动
        document.body.style.overflow = 'hidden';
        console.log('[Onboarding] 新手指引弹窗已显示');
    } else {
        console.error('[Onboarding] 未找到新手指引模态框元素');
    }
}

async function closeOnboardingModal() {
    const modal = document.getElementById('onboarding-modal');
    const checkbox = document.getElementById('onboarding-dont-show');
    
    if (modal) {
        modal.style.display = 'none';
        // 恢复背景滚动
        document.body.style.overflow = '';
    }
    
    // 如果用户勾选了"下次不再提醒"，保存到用户设置
    if (checkbox && checkbox.checked) {
        try {
            await saveUserSettings({ onboardingDontShow: true });
            console.log('[Onboarding] 用户选择不再显示，已保存设置');
        } catch (e) {
            console.error('[Onboarding] 保存新手指引设置失败:', e);
        }
    } else {
        // 用户没有勾选，确保设置为 false，下次还会显示
        try {
            await saveUserSettings({ onboardingDontShow: false });
            console.log('[Onboarding] 用户未勾选"不再提醒"，下次仍会显示');
        } catch (e) {
            console.error('[Onboarding] 保存新手指引设置失败:', e);
        }
    }
}

async function checkAndShowOnboarding() {
    try {
        // 从用户设置中检查是否已经设置过"下次不再提醒"
        const userSettings = await getUserSettings();
        const dontShow = userSettings.onboardingDontShow;
        
        // 如果用户已选择不再显示，跳过弹窗
        if (dontShow === true) {
            console.log('[Onboarding] 用户已选择不再显示，跳过弹窗');
            return;
        }
        
        // 显示新手指引
        // 延迟一点显示，确保页面已完全加载
        console.log('[Onboarding] 显示新手指引弹窗（onboardingDontShow:', dontShow, '）');
        setTimeout(() => {
            showOnboardingModal();
        }, 500);
    } catch (e) {
        console.error('[Onboarding] 检查新手指引设置失败:', e);
    }
}

// 在页面加载完成后检查是否需要显示新手指引
// 使用立即执行函数，支持延迟加载的情况
(function() {
    async function initOnboarding() {
        await checkAndShowOnboarding();
    }
    
    // 如果 DOM 已经加载完成，立即执行
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initOnboarding);
    } else {
        // DOM 已经加载完成，直接执行（支持脚本延迟加载的情况）
        initOnboarding();
    }
})();

