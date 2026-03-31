const API_BASE = '';

let reposData = [];

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    fetchRepos();

    // Filtros
    document.getElementById('filterStatus').addEventListener('change', renderRepos);
    document.getElementById('filterVisibility').addEventListener('change', renderRepos);
    document.getElementById('filterType').addEventListener('change', renderRepos);
    document.getElementById('searchInput').addEventListener('input', renderRepos);
    document.getElementById('btnRefreshRepos').addEventListener('click', fetchRepos);

    // Auditoría & Herramientas
    document.getElementById('btnRunAudit').addEventListener('click', runAudit);
    document.getElementById('btnRunSecrets').addEventListener('click', runSecretScan);
    document.getElementById('btnFindForks').addEventListener('click', findDeadForks);
    document.getElementById('btnBulkDeleteForks').addEventListener('click', () => openModal('bulk-delete-forks', 'ELIMINAR-TODOS-LOS-FORKS', bulkDeleteForks));
    
    // Configurar Modal
    setupModal();
});

// --- Modal Global ---
let pendingModalAction = null;
let expectedModalInput = null;

function setupModal() {
    document.getElementById('btnCancelModal').addEventListener('click', closeModal);
    document.getElementById('btnConfirmModal').addEventListener('click', () => {
        if (pendingModalAction) pendingModalAction();
        closeModal();
    });
    
    document.getElementById('modalInputVerify').addEventListener('input', (e) => {
        const btn = document.getElementById('btnConfirmModal');
        btn.disabled = e.target.value !== expectedModalInput;
    });
}

function openModal(actionType, expectedInput, confirmCallback) {
    const modal = document.getElementById('actionModal');
    const title = document.getElementById('modalTitle');
    const msg = document.getElementById('modalMessage');
    const inputContainer = document.getElementById('modalInputContainer');
    const expectedInputEl = document.getElementById('modalExpectedInput');
    const inputVerify = document.getElementById('modalInputVerify');
    const btnConfirm = document.getElementById('btnConfirmModal');

    pendingModalAction = confirmCallback;
    expectedModalInput = expectedInput;
    inputVerify.value = '';
    
    if (actionType === 'archive-repo') {
        title.innerHTML = '<i class="fa-solid fa-box-archive" style="color: var(--warning);"></i> Archivar Repositorio';
        msg.textContent = `Estás a punto de archivar el repositorio. Pasará a ser de solo lectura.`;
        inputContainer.style.display = 'block';
        expectedInputEl.textContent = expectedInput;
        btnConfirm.disabled = true;
        btnConfirm.className = 'btn btn-warning';
    } else if (actionType === 'delete-repo' || actionType === 'delete-fork') {
        title.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color: var(--danger);"></i> Borrar Repositorio';
        msg.textContent = `Esta acción es IRREVERSIBLE. Se eliminará permanentemente el repositorio.`;
        inputContainer.style.display = 'block';
        expectedInputEl.textContent = expectedInput;
        btnConfirm.disabled = true;
        btnConfirm.className = 'btn btn-danger';
    } else if (actionType === 'bulk-delete-forks') {
        title.innerHTML = '<i class="fa-solid fa-skull" style="color: var(--danger);"></i> Borrado Masivo de Forks';
        msg.textContent = `ATENCIÓN: Se eliminarán TODOS los forks inactivos listados. ¡Esta acción no se puede deshacer!`;
        inputContainer.style.display = 'block';
        expectedInputEl.textContent = expectedInput;
        btnConfirm.disabled = true;
        btnConfirm.className = 'btn btn-danger';
    }

    modal.style.display = 'flex';
}

function closeModal() {
    document.getElementById('actionModal').style.display = 'none';
    pendingModalAction = null;
    expectedModalInput = null;
}

window.openActionModal = function(action, repoName) {
    const actionType = action === 'delete' ? 'delete-repo' : 'archive-repo';
    openModal(actionType, repoName, () => manageRepo(action, repoName));
};

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const views = document.querySelectorAll('.view-container');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetId = item.getAttribute('data-target');
            
            // Highlight nav
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Show view
            views.forEach(view => view.classList.remove('active'));
            document.getElementById(`view-${targetId}`).classList.add('active');
        });
    });
}

async function fetchRepos() {
    const grid = document.getElementById('reposGrid');
    grid.innerHTML = `
        <div class="loader-container">
            <span class="loader"></span>
            <p>Cargando repositorios desde GitHub...</p>
        </div>
    `;

    try {
        const response = await fetch(`${API_BASE}/repos`);
        if (response.status === 401) {
            // Not authenticated -> show login button
            grid.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 4rem; text-align: center;">
                    <i class="fa-brands fa-github mb-3" style="font-size: 3rem; color: var(--text-primary);"></i>
                    <h2 class="mb-3">Autenticación Requerida</h2>
                    <p class="mb-4" style="color: var(--text-secondary);">Debes iniciar sesión con GitHub para analizar tu cuenta de forma segura.</p>
                    <a href="/auth/login" class="btn btn-primary" style="text-decoration: none; padding: 0.75rem 1.5rem; font-size: 1.1rem;">
                        <i class="fa-solid fa-arrow-right-to-bracket"></i> Iniciar Sesión con GitHub
                    </a>
                </div>
            `;
            return;
        }

        if (!response.ok) throw new Error('Failed to fetch');
        
        const data = await response.json();
        reposData = data.repos || [];
        
        updateUserProfile(data.user);
        updateOverviewStats();
        renderRepos();

    } catch (error) {
        console.error(error);
        grid.innerHTML = `
            <div class="loader-container">
                <i class="fa-solid fa-triangle-exclamation" style="font-size: 2rem; color: var(--danger); margin-bottom: 1rem;"></i>
                <p>Error cargando datos. Verifica que el servidor backend esté corriendo y el token de GitHub configurado.</p>
            </div>
        `;
    }
}

function updateUserProfile(user) {
    if (!user) return;
    document.getElementById('userName').textContent = user.name || user.login;
    document.getElementById('userLogin').textContent = `@${user.login}`;
    if (user.avatar_url) {
        document.getElementById('userAvatar').src = user.avatar_url;
    }
}

function updateOverviewStats() {
    const totalCount = reposData.length;
    const inactiveCount = reposData.filter(r => r.days_inactive > 180).length; // >6m
    const totalStars = reposData.reduce((acc, r) => acc + r.stars, 0);
    const totalForks = reposData.filter(r => r.is_fork).length;

    document.getElementById('stat-total-repos').textContent = totalCount;
    document.getElementById('stat-inactive-repos').textContent = inactiveCount;
    document.getElementById('stat-total-stars').textContent = totalStars;
    document.getElementById('stat-total-forks').textContent = totalForks;
}

function renderRepos() {
    const grid = document.getElementById('reposGrid');
    
    // Obtener valores de filtros
    const statusFilter = document.getElementById('filterStatus').value;
    const visibilityFilter = document.getElementById('filterVisibility').value;
    const typeFilter = document.getElementById('filterType').value;
    const searchQuerwy = document.getElementById('searchInput').value.toLowerCase();

    // Aplicar filtros
    let filtered = reposData.filter(repo => {
        // Search
        if (searchQuerwy && !repo.name.toLowerCase().includes(searchQuerwy) && !(repo.description || "").toLowerCase().includes(searchQuerwy)) {
            return false;
        }
        
        // Status
        const isInactive = repo.days_inactive > 180;
        if (statusFilter === 'active' && isInactive) return false;
        if (statusFilter === 'inactive' && !isInactive) return false;

        // Visibility
        if (visibilityFilter !== 'all' && repo.visibility !== visibilityFilter) return false;

        // Type
        if (typeFilter === 'source' && repo.is_fork) return false;
        if (typeFilter === 'fork' && !repo.is_fork) return false;

        return true;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 3rem; text-align: center; color: var(--text-secondary);">
                <i class="fa-solid fa-folder-open mb-3" style="font-size: 2.5rem;"></i>
                <p>No se encontraron repositorios con estos filtros.</p>
            </div>
        `;
        return;
    }

    // Render HTML
    grid.innerHTML = filtered.map(repo => {
        const isInactive = repo.days_inactive > 180;
        const commitMsg = repo.recent_commits && repo.recent_commits.length > 0 
            ? repo.recent_commits[0].message 
            : "Sin commits";
        
        let timeText = "No data";
        if (repo.last_commit_date) {
            timeText = `Hace ${repo.days_inactive} días`;
        }

        return `
            <div class="repo-card glass-card">
                <div class="repo-header">
                    <div class="repo-title">
                        <i class="fa-${repo.is_fork ? 'solid fa-code-fork' : 'regular fa-folder'}"></i>
                        <a href="${repo.url}" target="_blank">${repo.name}</a>
                    </div>
                    ${repo.is_archived ? '<span class="badge" style="border-color: var(--warning); color: var(--warning)">Archived</span>' :
                    `<span class="badge" style="border-color: ${repo.visibility === 'public' ? 'var(--success)' : 'var(--warning)'}; color: ${repo.visibility === 'public' ? 'var(--success)' : 'var(--warning)'}">
                        ${repo.visibility}
                    </span>`}
                </div>
                
                <div class="repo-actions">
                    ${!repo.is_archived ? `<button class="btn-icon warning" title="Archivar Repositorio" onclick="openActionModal('archive', '${repo.name}')"><i class="fa-solid fa-box-archive"></i></button>` : ''}
                    <button class="btn-icon danger" title="Borrar Repositorio" onclick="openActionModal('delete', '${repo.name}')"><i class="fa-solid fa-trash-can"></i></button>
                </div>
                
                <div class="repo-desc">
                    ${repo.description || '<em>Sin descripción</em>'}
                </div>
                
                <div class="repo-meta">
                    ${repo.language ? `
                    <div class="meta-item">
                        <span class="lang-color" style="background-color: var(--accent-primary);"></span>
                        ${repo.language}
                    </div>` : ''}
                    <div class="meta-item" title="Estrellas">
                        <i class="fa-regular fa-star"></i> ${repo.stars}
                    </div>
                    <div class="meta-item" title="Ramas">
                        <i class="fa-solid fa-code-branch"></i> ${repo.branches_count}
                    </div>
                </div>

                <div class="repo-commit ${isInactive ? 'inactive' : 'active'}">
                    <div class="commit-msg" title="${commitMsg}">
                        <i class="fa-solid fa-code-commit"></i> ${commitMsg}
                    </div>
                    <div class="commit-date">
                        <small>${timeText}</small>
                        <small style="color: ${isInactive ? 'var(--danger)' : 'var(--success)'}">
                            ${isInactive ? 'Inactivo' : 'Activo'}
                        </small>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}


// --- Auditoria Automatica ---
async function runAudit() {
    const btn = document.getElementById('btnRunAudit');
    const resultsPanel = document.getElementById('auditResults');
    
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Auditando...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/account-audit`);
        if (!response.ok) throw new Error('Failed to audit');
        
        const data = await response.json();
        
        document.getElementById('audit-ssh-count').textContent = data.old_ssh_keys ? data.old_ssh_keys.length : 0;
        document.getElementById('audit-gists-count').textContent = data.public_gists_count || 0;
        document.getElementById('audit-apps-count').textContent = data.installed_apps ? data.installed_apps.length : 0;

        const tbody = document.querySelector('#appsTable tbody');
        if (data.installed_apps && data.installed_apps.length > 0) {
            tbody.innerHTML = data.installed_apps.map(app => `
                <tr>
                    <td><strong>${app.app_slug}</strong></td>
                    <td><span class="badge">${app.repository_selection}</span></td>
                    <td>
                        <div style="display:flex; flex-wrap:wrap; gap:4px;">
                            ${Object.entries(app.permissions).map(([k,v]) => `<span style="font-size:0.7rem; background:rgba(255,255,255,0.05); padding:2px 6px; border-radius:4px;">${k}:${v}</span>`).join('')}
                        </div>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding: 2rem;">No hay aplicaciones de terceros instaladas.</td></tr>`;
        }

        resultsPanel.style.display = 'block';

    } catch (error) {
        console.error(error);
        alert('Error ejecutando auditoría.');
    } finally {
        btn.innerHTML = 'Ejecutar Auditoría';
        btn.disabled = false;
    }
}

// --- Integración Nueva Funcionalidad ---

async function manageRepo(action, repoName) {
    try {
        const res = await fetch(`${API_BASE}/manage-repo?action=${action}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ repo_name: repoName, confirm: true })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error en la acción');
        
        // Quitar de reposData
        if (action === 'delete') {
            reposData = reposData.filter(r => r.name !== repoName);
        } else if (action === 'archive') {
            const r = reposData.find(r => r.name === repoName);
            if (r) r.is_archived = true;
        }
        renderRepos();
        updateOverviewStats();
    } catch (err) {
        alert(err.message);
    }
}

async function runSecretScan() {
    const btn = document.getElementById('btnRunSecrets');
    const resultsPanel = document.getElementById('secretsResultsPanel');
    const tbody = document.querySelector('#secretsTable tbody');
    
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Escaneando...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/scan-secrets`);
        if (!response.ok) throw new Error('Failed to scan secrets');
        
        const data = await response.json();
        
        let html = '';
        if (data.repos.length === 0 || data.findings_count === 0) {
            html = `<tr><td colspan="4" style="text-align:center; padding: 2rem; color: var(--success);"><i class="fa-solid fa-check-circle"></i> No se encontraron secretos expuestos.</td></tr>`;
        } else {
            data.repos.forEach(repo => {
                repo.findings.forEach(finding => {
                    html += `
                        <tr>
                            <td><strong>${repo.repo_name}</strong></td>
                            <td style="word-break: break-all;"><code>${finding.file_path}</code></td>
                            <td><span class="badge" style="border-color: var(--danger); color: var(--danger)">${finding.secret_type}</span></td>
                            <td>${finding.line_number}</td>
                        </tr>
                    `;
                });
            });
        }
        tbody.innerHTML = html;
        resultsPanel.style.display = 'block';

    } catch (error) {
        console.error(error);
        alert('Error ejecutando escaner de secretos.');
    } finally {
        btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Escanear Repos';
        btn.disabled = false;
    }
}

async function findDeadForks() {
    const btn = document.getElementById('btnFindForks');
    const resultsPanel = document.getElementById('forksResultsPanel');
    const tbody = document.querySelector('#forksTable tbody');
    const btnBulk = document.getElementById('btnBulkDeleteForks');
    
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Buscando...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE}/dead-forks`);
        if (!response.ok) throw new Error('Failed to fetch forks');
        
        const data = await response.json();
        
        let html = '';
        if (data.dead_forks_count === 0) {
            html = `<tr><td colspan="3" style="text-align:center; padding: 2rem; color: var(--success);"><i class="fa-solid fa-check-circle"></i> No tienes forks abandonados.</td></tr>`;
            btnBulk.style.display = 'none';
        } else {
            data.forks.forEach(fork => {
                const date = fork.last_commit_date ? new Date(fork.last_commit_date).toLocaleDateString() : 'Desconocido';
                html += `
                    <tr>
                        <td><strong><a href="${fork.url}" target="_blank" style="color: var(--accent-primary); text-decoration: none;">${fork.name}</a></strong></td>
                        <td><a href="${fork.parent_url}" target="_blank" style="color: var(--text-secondary);"><i class="fa-solid fa-code-branch"></i> ${fork.parent_name}</a></td>
                        <td>${date}</td>
                    </tr>
                `;
            });
            btnBulk.style.display = 'inline-flex';
        }
        tbody.innerHTML = html;
        resultsPanel.style.display = 'block';

    } catch (error) {
        console.error(error);
        alert('Error buscando forks abandonados.');
    } finally {
        btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Buscar Forks';
        btn.disabled = false;
    }
}

async function bulkDeleteForks() {
    try {
        const res = await fetch(`${API_BASE}/bulk-delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ delete_all_candidates: true, confirm: true, repo_names: [] })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error en el borrado masivo');
        
        alert(`¡Completado! Elementos borrados: ${data.deleted_count}. Fallidos: ${data.failed_count}`);
        
        document.getElementById('forksResultsPanel').style.display = 'none';
        document.getElementById('btnBulkDeleteForks').style.display = 'none';
        
        const deletedNames = data.results.filter(r => r.status === 'deleted').map(r => r.repo_name);
        reposData = reposData.filter(r => !deletedNames.includes(r.name));
        renderRepos();
        updateOverviewStats();
        
    } catch (err) {
        alert(err.message);
    }
}
