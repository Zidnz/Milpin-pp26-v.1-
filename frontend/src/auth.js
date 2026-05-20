const MILPIN_AUTH = (() => {
    const API_BASE = "http://localhost:8000/api";
    const STORAGE_KEY = "milpin.currentUser";

    let currentUser = null;

    function _readStoredUser() {
        try {
            const raw = window.localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }

    function _saveUser(user) {
        currentUser = user;
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
    }

    function _clearUser() {
        currentUser = null;
        window.localStorage.removeItem(STORAGE_KEY);
    }

    function getCurrentUser() {
        return currentUser;
    }

    function getUserId() {
        return currentUser?.id_usuario || null;
    }

    function getParcelasQuery() {
        // Admin ve todas las parcelas: no se añade filtro de usuario
        if (currentUser?.rol === "admin") return "";
        return currentUser?.id_usuario
            ? `?id_usuario=${encodeURIComponent(currentUser.id_usuario)}`
            : "";
    }

    function isAdmin() {
        return currentUser?.rol === "admin";
    }

    function _setStatus(message, isError = false) {
        const el = document.getElementById("login-status");
        if (!el) return;
        el.textContent = message || "";
        el.className = isError ? "login-status login-status--error" : "login-status";
    }

    function _renderUserPreview(user) {
        const box = document.getElementById("login-user-preview");
        if (!box) return;
        if (!user) {
            box.innerHTML = "";
            return;
        }
        const isAdminUser = user.rol === "admin";
        const rolLabel = isAdminUser
            ? '<span style="background:#0F6CBD;color:#fff;font-size:0.7rem;font-weight:700;padding:2px 8px;border-radius:20px;margin-left:6px;">ADMIN</span>'
            : "";
        const scope = isAdminUser
            ? "Acceso completo · Todas las parcelas"
            : `${user.modulo_dr041 || "DR-041"} · Usuario activo`;
        box.innerHTML = `
            <div class="login-preview-name">${user.nombre_completo}${rolLabel}</div>
            <div class="login-preview-email">${user.email}</div>
            <div class="login-preview-role">${scope}</div>
        `;
    }

    function _updateProfileUI() {
        const user = currentUser;
        const nameEl = document.getElementById("profile-name") || document.querySelector(".ajustes-profile-name");
        const emailEl = document.getElementById("profile-email") || document.querySelector(".ajustes-profile-email");
        const roleEl = document.getElementById("profile-role") || document.querySelector(".ajustes-profile-role");
        const avatarEl = document.getElementById("profile-avatar") || document.querySelector(".ajustes-avatar");
        const badgeEl = document.getElementById("session-user-badge");

        if (!user) {
            if (nameEl) nameEl.textContent = "Sesión no iniciada";
            if (emailEl) emailEl.textContent = "Selecciona un usuario del dataset";
            if (roleEl) roleEl.textContent = "MILPÍN · DR-041";
            if (avatarEl) avatarEl.textContent = "MP";
            if (badgeEl) badgeEl.textContent = "Sin sesión";
            return;
        }

        const initials = user.nombre_completo
            .split(" ")
            .filter(Boolean)
            .slice(0, 2)
            .map(part => part[0]?.toUpperCase() || "")
            .join("");

        if (nameEl) nameEl.textContent = user.nombre_completo;
        if (emailEl) emailEl.textContent = user.email;
        if (roleEl) roleEl.textContent = user.rol === "admin"
            ? "Administrador · Acceso completo DR-041"
            : `${user.modulo_dr041 || "DR-041"} · Valle del Yaqui`;
        if (avatarEl) avatarEl.textContent = initials || "MP";
        if (badgeEl) badgeEl.textContent = `Sesión: ${user.nombre_completo}`;
    }

    function _showLogin() {
        const overlay = document.getElementById("login-screen");
        if (overlay) overlay.style.display = "flex";
        document.body.classList.add("login-open");
        _updateProfileUI();
    }

    function _hideLogin() {
        const overlay = document.getElementById("login-screen");
        if (overlay) overlay.style.display = "none";
        document.body.classList.remove("login-open");
        _updateProfileUI();
    }

    async function _loadUsers() {
        const select = document.getElementById("login-user-select");
        if (!select) return [];

        select.innerHTML = '<option value="">Selecciona un usuario del dataset</option>';
        _setStatus("Cargando usuarios del dataset...");

        const res = await fetch(`${API_BASE}/usuarios`);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const users = await res.json();
        users.forEach(user => {
            const opt = document.createElement("option");
            opt.value = user.email;
            opt.textContent = `${user.nombre_completo} · ${user.modulo_dr041 || "DR-041"}`;
            opt.dataset.user = JSON.stringify(user);
            select.appendChild(opt);
        });

        const selectedOption = select.options[1];
        if (selectedOption) {
            select.value = selectedOption.value;
            _renderUserPreview(JSON.parse(selectedOption.dataset.user));
        }
        _setStatus("");
        return users;
    }

    async function login(email) {
        const btn = document.getElementById("login-submit-btn");
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Validando acceso...";
        }
        _setStatus("");

        try {
            const res = await fetch(`${API_BASE}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email }),
            });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(payload.detail || `HTTP ${res.status}`);
            }

            _saveUser(payload);
            _hideLogin();
            window.location.reload();
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = "Entrar con este usuario";
            }
        }
    }

    async function logout() {
        _clearUser();
        window.location.reload();
    }

    async function init() {
        currentUser = _readStoredUser();
        _updateProfileUI();

        const select = document.getElementById("login-user-select");
        const form = document.getElementById("login-form");
        if (!select || !form) return;

        select.addEventListener("change", () => {
            const selected = select.options[select.selectedIndex];
            if (!selected?.dataset?.user) {
                _renderUserPreview(null);
                return;
            }
            _renderUserPreview(JSON.parse(selected.dataset.user));
        });

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!select.value) {
                _setStatus("Selecciona un usuario válido.", true);
                return;
            }
            try {
                await login(select.value);
            } catch (err) {
                _setStatus(err.message, true);
            }
        });

        try {
            await _loadUsers();
        } catch (err) {
            _setStatus(`No se pudo cargar el dataset de usuarios: ${err.message}`, true);
        }

        if (currentUser?.id_usuario) {
            _hideLogin();
        } else {
            _showLogin();
        }
    }

    return {
        init,
        login,
        logout,
        getCurrentUser,
        getUserId,
        getParcelasQuery,
        isAdmin,
    };
})();

window.MILPIN_AUTH = MILPIN_AUTH;
