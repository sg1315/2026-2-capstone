/*
 * 화면 ↔ view 통신 공통 함수
 *
 * 서버(view) 응답 규칙 (JSON)
 *   성공: 200 { message, redirect_url }
 *   입력 오류: 400 { message, errors: { 필드명: 오류 메시지 } }
 *   로그인 필요: 401 { message, redirect_url }
 */

/** 페이지의 CSRF 토큰 ({% csrf_token %} 이 출력한 hidden input) */
function getCsrfToken() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
}

/** 응답 본문을 JSON 으로 읽는다. JSON 이 아니면(서버 오류 페이지 등) 기본 메시지로 대체 */
async function readJson(response) {
    try {
        return await response.json();
    } catch (e) {
        return { message: '서버 응답을 처리할 수 없습니다. (상태 코드: ' + response.status + ')' };
    }
}

/**
 * FormData 를 POST 로 전송하고 { ok, status, data } 를 돌려준다.
 * onProgress(0~100) 를 넘기면 업로드 진행률을 알려준다. (파일 업로드용, XHR 사용)
 */
function postForm(url, formData, onProgress) {
    return new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', url);
        xhr.setRequestHeader('X-CSRFToken', getCsrfToken());
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

        if (onProgress) {
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
            });
        }

        xhr.onload = () => {
            let data;
            try {
                data = JSON.parse(xhr.responseText);
            } catch (e) {
                data = { message: '서버 응답을 처리할 수 없습니다. (상태 코드: ' + xhr.status + ')' };
            }
            resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, data });
        };
        xhr.onerror = () => resolve({ ok: false, status: 0, data: { message: '서버와 통신 중 문제가 발생했습니다.' } });
        xhr.send(formData);
    });
}

/** 목록 등 HTML 조각을 GET 으로 받아온다. */
async function fetchPartial(url) {
    const response = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!response.ok) throw new Error('목록을 불러오지 못했습니다. (상태 코드: ' + response.status + ')');
    return response.text();
}

/* ---------- 폼 오류 표시 ---------- */

/** 폼 안의 필드 오류 메시지를 모두 지운다. */
function clearFormErrors(form) {
    form.querySelectorAll('.form-error[data-error-for]').forEach((el) => {
        el.textContent = '';
        el.hidden = true;
    });
    form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
    const alertBox = form.querySelector('[data-form-alert]');
    if (alertBox) {
        alertBox.textContent = '';
        alertBox.hidden = true;
    }
}

/** { 필드명: 메시지 } 를 각 필드 아래 <p class="form-error" data-error-for="필드명"> 에 표시 */
function showFormErrors(form, errors) {
    let firstField = null;
    Object.entries(errors || {}).forEach(([name, message]) => {
        const box = form.querySelector('.form-error[data-error-for="' + name + '"]');
        if (box) {
            box.textContent = message;
            box.hidden = false;
        }
        // 같은 name 이 여러 개(RadioNodeList)거나 hidden 이면 표시/포커스할 입력칸이 아니다
        const field = form.elements[name];
        if (field instanceof Element && field.type !== 'hidden') {
            field.setAttribute('aria-invalid', 'true');
            firstField = firstField || field;
        } else if (box) {
            box.scrollIntoView({ block: 'nearest' });
        }
    });
    if (firstField) firstField.focus();
}

/** 필드와 무관한 오류(통신 실패 등)를 폼 상단 알림에 표시 */
function showFormAlert(form, message) {
    const alertBox = form.querySelector('[data-form-alert]');
    if (alertBox) {
        alertBox.textContent = message;
        alertBox.hidden = false;
        alertBox.scrollIntoView({ block: 'nearest' });
    } else {
        alert(message);
    }
}

/** 전송 중 버튼 잠금/해제 */
function setSubmitting(button, submitting, busyText) {
    if (!button) return;
    if (submitting) {
        button.dataset.originalText = button.textContent;
        button.textContent = busyText || '처리 중...';
        button.disabled = true;
    } else {
        button.textContent = button.dataset.originalText || button.textContent;
        button.disabled = false;
    }
}

/**
 * 폼 전송 공통 처리: 오류 초기화 → 전송 → 성공 시 redirect_url 로 이동, 실패 시 오류 표시
 * options: { url, validate(form) -> {필드: 메시지}, buildData(form) -> FormData, busyText, onProgress }
 */
async function submitForm(form, options) {
    clearFormErrors(form);

    const clientErrors = options.validate ? options.validate(form) : {};
    if (Object.keys(clientErrors).length) {
        showFormErrors(form, clientErrors);
        return;
    }

    const button = form.querySelector('[type=submit]');
    setSubmitting(button, true, options.busyText);

    const formData = options.buildData ? options.buildData(form) : new FormData(form);
    const { ok, status, data } = await postForm(options.url, formData, options.onProgress);

    if (ok || status === 401) {
        window.location.href = data.redirect_url || window.location.href;
        return;
    }

    setSubmitting(button, false);
    if (data.errors && Object.keys(data.errors).length) {
        showFormErrors(form, data.errors);
    } else {
        showFormAlert(form, data.message || '요청을 처리하지 못했습니다.');
    }
    if (options.onFail) options.onFail();
}

/* ---------- 파일 선택 드롭존 (.file-drop) ---------- */

/** 파일을 끌고 들어오면 강조 표시. 실제 파일 선택은 드롭존을 덮고 있는 input 이 처리한다. */
function initFileDrop(zone) {
    let depth = 0; // 자식 요소 사이를 지날 때 깜빡이지 않도록 진입 횟수로 판단
    zone.addEventListener('dragenter', () => {
        depth += 1;
        zone.classList.add('is-dragover');
    });
    zone.addEventListener('dragleave', () => {
        depth = Math.max(0, depth - 1);
        if (depth === 0) zone.classList.remove('is-dragover');
    });
    zone.addEventListener('drop', () => {
        depth = 0;
        zone.classList.remove('is-dragover');
    });
}

/* ---------- 사용자 검색 후 추가 (프로젝트 참여자 등) ---------- */

/**
 * <div data-user-picker data-search-url="..." data-input-name="member_ids" data-max-count="20">
 *     <input type="search" data-user-search>      검색어 입력
 *     <ul data-user-results hidden></ul>          검색 결과
 *     <div data-user-selected>                    선택된 사용자 (서버가 미리 그린 칩 포함 가능)
 *         <span class="user-chip" data-user-id="3"> ... <input type="hidden" name="member_ids" value="3"></span>
 *     </div>
 * </div>
 * 서버 응답: { users: [{ id, username, name }] }
 */
function initUserPicker(root) {
    const searchInput = root.querySelector('[data-user-search]');
    const results = root.querySelector('[data-user-results]');
    const selected = root.querySelector('[data-user-selected]');
    const inputName = root.dataset.inputName;
    const maxCount = Number(root.dataset.maxCount || 0);
    let timer = null;
    let seq = 0;
    let activeIndex = -1;

    function selectedIds() {
        return Array.from(selected.querySelectorAll('[data-user-id]')).map((el) => el.dataset.userId);
    }

    function closeResults() {
        results.hidden = true;
        results.replaceChildren();
        activeIndex = -1;
        searchInput.setAttribute('aria-expanded', 'false');
    }

    function makeChip(user) {
        const label = user.name ? user.name + ' (@' + user.username + ')' : '@' + user.username;
        const chip = document.createElement('span');
        chip.className = 'user-chip';
        chip.dataset.userId = String(user.id);

        const avatar = document.createElement('span');
        avatar.className = 'avatar';
        avatar.textContent = (user.name || user.username).charAt(0);

        const text = document.createElement('span');
        text.textContent = label;

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'user-chip-remove';
        remove.setAttribute('aria-label', label + ' 빼기');
        remove.textContent = '✕';

        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.name = inputName;
        hidden.value = String(user.id);

        chip.append(avatar, text, remove, hidden);
        return chip;
    }

    function addUser(user) {
        const errorBox = root.querySelector('.form-error[data-error-for="' + inputName + '"]');
        if (maxCount && selectedIds().length >= maxCount) {
            if (errorBox) {
                errorBox.textContent = '참여자는 최대 ' + maxCount + '명까지 추가할 수 있습니다.';
                errorBox.hidden = false;
            }
            return;
        }
        if (errorBox) errorBox.hidden = true;
        if (!selectedIds().includes(String(user.id))) selected.append(makeChip(user));
        searchInput.value = '';
        closeResults();
        searchInput.focus();
    }

    function highlight(index) {
        const items = results.querySelectorAll('[role=option]');
        items.forEach((item, i) => item.setAttribute('aria-selected', i === index ? 'true' : 'false'));
        activeIndex = index;
        if (items[index]) items[index].scrollIntoView({ block: 'nearest' });
    }

    function renderResults(users) {
        const ids = selectedIds();
        const available = users.filter((u) => !ids.includes(String(u.id)));
        results.replaceChildren();
        activeIndex = -1;

        if (!available.length) {
            const empty = document.createElement('li');
            empty.className = 'user-result-empty';
            empty.textContent = users.length ? '이미 추가된 사용자입니다.' : '일치하는 사용자가 없습니다.';
            results.append(empty);
        } else {
            available.forEach((user) => {
                const item = document.createElement('li');
                item.setAttribute('role', 'option');
                item.setAttribute('aria-selected', 'false');
                const avatar = document.createElement('span');
                avatar.className = 'avatar';
                avatar.textContent = (user.name || user.username).charAt(0);
                const name = document.createElement('strong');
                name.textContent = user.name || user.username;
                const id = document.createElement('span');
                id.className = 'text-muted';
                id.textContent = '@' + user.username;
                item.append(avatar, name, id);
                // mousedown: input 의 blur 보다 먼저 처리되도록
                item.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    addUser(user);
                });
                results.append(item);
            });
        }
        results.hidden = false;
        searchInput.setAttribute('aria-expanded', 'true');
    }

    async function search() {
        const q = searchInput.value.trim();
        if (!q) {
            closeResults();
            return;
        }
        const current = ++seq;
        try {
            const response = await fetch(root.dataset.searchUrl + '?q=' + encodeURIComponent(q), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            const data = await readJson(response);
            if (current !== seq) return; // 늦게 온 이전 검색 결과는 무시
            renderResults(response.ok ? (data.users || []) : []);
        } catch (e) {
            if (current === seq) renderResults([]);
        }
    }

    searchInput.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(search, 250);
    });

    searchInput.addEventListener('keydown', (e) => {
        const items = results.querySelectorAll('[role=option]');
        if (e.key === 'ArrowDown' && items.length) {
            e.preventDefault();
            highlight((activeIndex + 1) % items.length);
        } else if (e.key === 'ArrowUp' && items.length) {
            e.preventDefault();
            highlight((activeIndex - 1 + items.length) % items.length);
        } else if (e.key === 'Enter') {
            e.preventDefault(); // 폼이 제출되지 않도록
            if (items[activeIndex]) items[activeIndex].dispatchEvent(new MouseEvent('mousedown'));
            else if (items.length === 1) items[0].dispatchEvent(new MouseEvent('mousedown'));
        } else if (e.key === 'Escape') {
            closeResults();
        }
    });

    searchInput.addEventListener('blur', () => setTimeout(closeResults, 100));

    selected.addEventListener('click', (e) => {
        const button = e.target.closest('.user-chip-remove');
        if (button) {
            button.closest('.user-chip').remove();
            searchInput.focus();
        }
    });
}

/* ---------- 확인 후 실행하는 버튼 (삭제 등) ---------- */

/**
 * <form data-confirm-action="확인 메시지" action="...Action/"> 를 제출하면
 * 확인창을 띄운 뒤 POST 로 보내고, 성공하면 redirect_url 로 이동한다.
 */
function initConfirmAction(form) {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!window.confirm(form.dataset.confirmAction)) return;

        const button = form.querySelector('[type=submit]');
        setSubmitting(button, true, '처리 중...');
        const { ok, status, data } = await postForm(form.action, new FormData(form));

        if (ok || status === 401) {
            window.location.href = data.redirect_url || window.location.href;
            return;
        }
        setSubmitting(button, false);
        alert(data.message || '요청을 처리하지 못했습니다.');
    });
}

/* ---------- 목록 실시간 검색 ---------- */

/**
 * 검색창 입력/탭 클릭 시 목록 영역만 서버에서 다시 받아 교체한다.
 * root: data-list-root 요소 (안에 [data-list-search] 폼, [data-list-tab] 링크, [data-list-results] 영역)
 */
function initLiveList(root) {
    const searchForm = root.querySelector('[data-list-search]');
    const results = root.querySelector('[data-list-results]');
    const tabs = root.querySelectorAll('[data-list-tab]');
    let timer = null;
    let requestSeq = 0;

    async function load(params) {
        const url = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        const seq = ++requestSeq;
        results.setAttribute('aria-busy', 'true');
        try {
            const html = await fetchPartial(url);
            if (seq !== requestSeq) return; // 늦게 도착한 이전 요청은 무시
            results.innerHTML = html;
            window.history.replaceState(null, '', url);
        } catch (e) {
            results.innerHTML = '<div class="alert alert-danger mt-4">' + e.message + '</div>';
        } finally {
            if (seq === requestSeq) results.removeAttribute('aria-busy');
        }
    }

    function currentParams() {
        return new URLSearchParams(new FormData(searchForm));
    }

    if (searchForm) {
        searchForm.addEventListener('submit', (e) => {
            e.preventDefault();
            clearTimeout(timer);
            load(currentParams());
        });
        searchForm.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(() => load(currentParams()), 300);
        });
    }

    tabs.forEach((tab) => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            tabs.forEach((t) => {
                t.classList.toggle('is-active', t === tab);
                t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
            });
            const tabInput = searchForm && searchForm.elements.tab;
            if (tabInput) tabInput.value = tab.dataset.listTab;
            load(currentParams());
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-list-root]').forEach(initLiveList);
    document.querySelectorAll('form[data-confirm-action]').forEach(initConfirmAction);
    document.querySelectorAll('[data-file-drop]').forEach(initFileDrop);
    document.querySelectorAll('[data-user-picker]').forEach(initUserPicker);
});
