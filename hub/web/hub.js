const HubApi = {
  async get(path) {
    const r = await fetch(path, { credentials: "same-origin" });
    if (!r.ok) {
      const text = await parseError(r);
      throw new Error(text || r.statusText);
    }
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      const text = await parseError(r);
      throw new Error(text || r.statusText);
    }
    return r.json();
  },
  async patch(path, body) {
    const r = await fetch(path, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      const text = await parseError(r);
      throw new Error(text || r.statusText);
    }
    return r.json();
  },
  async delete(path) {
    const r = await fetch(path, {
      method: "DELETE",
      credentials: "same-origin",
    });
    if (!r.ok) {
      const text = await parseError(r);
      throw new Error(text || r.statusText);
    }
    return r.json();
  },
};

const HUB_TABS = {
  all: {
    title: "Все проекты",
    desc: "Публичный каталог — деревья гипотез и канбан без кода.",
    api: "/api/catalog/public",
    requiresAuth: false,
  },
  subscriptions: {
    title: "Подписки",
    desc: "Проекты авторов, на которых вы подписаны, и сохранённые по ссылке (в т.ч. unlisted с token).",
    api: "/api/catalog/network",
    requiresAuth: true,
  },
  mine: {
    title: "Мои проекты",
    desc: "Ваши репозитории в Hub: sync с GitHub, видимость, вкл/выкл в каталоге.",
    api: "/api/projects/mine",
    requiresAuth: true,
    manage: true,
  },
};

const VISIBILITY_LABELS = {
  public: "Публичный",
  network: "Сеть",
  unlisted: "По ссылке",
};

const HUB_ICONS = {
  user: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 12a4.5 4.5 0 1 0-4.5-4.5A4.5 4.5 0 0 0 12 12zm0 2.25c-3.6 0-6.75 1.8-6.75 4.125V20h13.5v-1.625C18.75 16.05 15.6 14.25 12 14.25z"/></svg>',
  repo: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4.75 3A1.75 1.75 0 0 0 3 4.75v14.5c0 .966.784 1.75 1.75 1.75h4.5V19h-4.5a.25.25 0 0 1-.25-.25V4.75a.25.25 0 0 1 .25-.25h10.5a.25.25 0 0 1 .25.25V9H17V4.75A1.75 1.75 0 0 0 15.25 3zm7.72 9.22a.75.75 0 0 1 1.06 0l2.72 2.72V12.5a.75.75 0 0 1 1.5 0v4.25a.75.75 0 0 1-.75.75H12.5a.75.75 0 0 1 0-1.5h2.19l-2.22-2.22a.75.75 0 0 1 0-1.06z"/></svg>',
  branch:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9.25 5.5a2.25 2.25 0 1 0-1.5 0v4.09a3.75 3.75 0 0 0 3 3.66V16a2.25 2.25 0 1 0 1.5 0v-2.75a5.25 5.25 0 0 1-4.5-5.2zm-2.25.25a.75.75 0 1 1 1.5 0 .75.75 0 0 1-1.5 0zM15.25 17.5a.75.75 0 1 1 0 1.5.75.75 0 0 1 0-1.5zM16.75 4.5a2.25 2.25 0 0 0-2.12 1.5h-.38a.75.75 0 0 0 0 1.5h.38a2.25 2.25 0 1 0 2.12-3z"/></svg>',
  clock:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3.5A8.5 8.5 0 1 0 20.5 12 8.51 8.51 0 0 0 12 3.5zm0 15A6.5 6.5 0 1 1 18.5 12 6.51 6.51 0 0 1 12 18.5zm.75-10v3.69l2.56 1.48a.75.75 0 1 1-.75 1.3l-3-1.73A.75.75 0 0 1 11 12.5v-4a.75.75 0 0 1 1.5 0z"/></svg>',
  globe:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3.5A8.5 8.5 0 1 0 20.5 12 8.51 8.51 0 0 0 12 3.5zm0 1.5a7 7 0 0 1 5.9 3.25H14.5a14.7 14.7 0 0 0-2.5-3.1A7 7 0 0 1 12 5zm-1.6.2A14.7 14.7 0 0 0 7.9 8.25H5.1A7 7 0 0 1 10.4 5.2zM4.5 12c0-.6.08-1.18.22-1.75h3.1A16.3 16.3 0 0 0 7.5 12c0 .6.1 1.18.32 1.75h-3.1A7 7 0 0 1 4.5 12zm.6 3.25h2.8a14.7 14.7 0 0 0 2.5 3.1 7 7 0 0 1-5.3-3.1zm5.9 3.55A14.7 14.7 0 0 0 14.5 15.75h3.4A7 7 0 0 1 11 18.8zm4.18-5.05c.22-.57.32-1.15.32-1.75s-.1-1.18-.32-1.75h3.1A7 7 0 0 1 19.5 12a7 7 0 0 1-.22 1.75z"/></svg>',
  users:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8.5 11a3.5 3.5 0 1 0-3.5-3.5A3.5 3.5 0 0 0 8.5 11zm7 0a3.5 3.5 0 1 0-3.5-3.5A3.5 3.5 0 0 0 15.5 11zM8.5 12.5C5.74 12.5 3 14.12 3 16.75V19h11v-2.25C14 14.12 11.26 12.5 8.5 12.5zm7 0c-.4 0-.8.04-1.18.1 1.3.9 2.18 2.2 2.18 3.9V19h5v-2.25c0-2.63-2.74-4.25-5.5-4.25z"/></svg>',
  link: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10.6 13.4a3.5 3.5 0 0 1 0-4.95l2.12-2.12a3.5 3.5 0 0 1 4.95 4.95l-1.06 1.06a.75.75 0 0 0 1.06 1.06l1.06-1.06a5 5 0 0 0-7.07-7.07L9.54 7.39a5 5 0 0 0 0 7.07.75.75 0 0 0 1.06-1.06zm2.8-2.8a3.5 3.5 0 0 1 0 4.95l-2.12 2.12a3.5 3.5 0 1 1-4.95-4.95l1.06-1.06a.75.75 0 1 0-1.06-1.06L5.27 11.6a5 5 0 1 0 7.07 7.07l2.12-2.12a5 5 0 0 0 0-7.07.75.75 0 0 0-1.06 1.06z"/></svg>',
  heart:
    '<svg class="hub-ico hub-ico--heart" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12.1 20.3 11 19.3C6.4 15.1 3.5 12.5 3.5 9.3A4.3 4.3 0 0 1 7.8 5a4.7 4.7 0 0 1 4.3 2.5A4.7 4.7 0 0 1 16.4 5a4.3 4.3 0 0 1 4.3 4.3c0 3.2-2.9 5.8-7.5 10l-1.1 1z"/></svg>',
  heartOutline:
    '<svg class="hub-ico hub-ico--heart" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" d="M12.1 19.6 11 18.6C6.7 14.7 4 12.3 4 9.4A3.9 3.9 0 0 1 7.9 5.5a4.3 4.3 0 0 1 4.2 2.4 4.3 4.3 0 0 1 4.2-2.4A3.9 3.9 0 0 1 20 9.4c0 2.9-2.7 5.3-7 9.2l-.9 1z"/></svg>',
  userPlus:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M10 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4zm0 1.5c-3.2 0-6 1.6-6 3.75V19h12v-1.75C16 15.1 13.2 13.5 10 13.5zM18.25 8v-.75a.75.75 0 0 1 1.5 0V8H20.5a.75.75 0 0 1 0 1.5h-.75V10a.75.75 0 0 1-1.5 0V9.5H17a.75.75 0 0 1 0-1.5z"/></svg>',
  arrow:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M13.5 5.5a1 1 0 0 1 1.4 0l5.1 5.1a1 1 0 0 1 0 1.4l-5.1 5.1a1 1 0 1 1-1.4-1.4l3.4-3.4H4.5a1 1 0 0 1 0-2h12.4l-3.4-3.4a1 1 0 0 1 0-1.4z"/></svg>',
  sync: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7.5 7.5A6 6 0 0 1 18 9h-2.25a.75.75 0 0 0 0 1.5H19a.75.75 0 0 0 .75-.75V6.5a.75.75 0 0 0-1.5 0v1.3A7.5 7.5 0 0 0 6.2 6.2a.75.75 0 1 0 1.06 1.06zM16.5 16.5A6 6 0 0 1 6 15h2.25a.75.75 0 0 0 0-1.5H5a.75.75 0 0 0-.75.75v3.25a.75.75 0 0 0 1.5 0v-1.3a7.5 7.5 0 0 0 12.05 1.6.75.75 0 1 0-1.06-1.06z"/></svg>',
  edit: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16.7 3.3a1.75 1.75 0 0 1 2.48 0l1.52 1.52a1.75 1.75 0 0 1 0 2.48L8.25 19.75 3 21l1.25-5.25L16.7 3.3zm1.24 1.06a.25.25 0 0 0-.18.07l-1.45 1.45 1.81 1.81 1.45-1.45a.25.25 0 0 0 0-.36l-1.52-1.52a.25.25 0 0 0-.11-.07zM15.25 6.94 5.62 16.56l-.55 2.37 2.37-.55 9.62-9.63-1.81-1.81z"/></svg>',
  trash:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 4.75A1.75 1.75 0 0 1 10.75 3h2.5A1.75 1.75 0 0 1 15 4.75V6h3.25a.75.75 0 0 1 0 1.5H18v10.75A2.75 2.75 0 0 1 15.25 21h-6.5A2.75 2.75 0 0 1 6 18.25V7.5h-.25a.75.75 0 0 1 0-1.5H9zm1.5 0V6h3V4.75a.25.25 0 0 0-.25-.25h-2.5a.25.25 0 0 0-.25.25zM7.5 7.5v10.75c0 .69.56 1.25 1.25 1.25h6.5c.69 0 1.25-.56 1.25-1.25V7.5z"/></svg>',
  eye: '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5.5c4.4 0 7.95 2.95 9.35 5.9a1.1 1.1 0 0 1 0 1.2C19.95 15.55 16.4 18.5 12 18.5S4.05 15.55 2.65 12.6a1.1 1.1 0 0 1 0-1.2C4.05 8.45 7.6 5.5 12 5.5zm0 2A7.9 7.9 0 0 0 4.5 12 7.9 7.9 0 0 0 12 16.5 7.9 7.9 0 0 0 19.5 12 7.9 7.9 0 0 0 12 7.5zm0 2.25A2.25 2.25 0 1 1 9.75 12 2.25 2.25 0 0 1 12 9.75z"/></svg>',
  eyeOff:
    '<svg class="hub-ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3.28 2.22a.75.75 0 1 0-1.06 1.06l2.1 2.1C2.85 6.7 1.7 8.2 1.15 9.4a1.9 1.9 0 0 0 0 1.7C2.7 14.4 6.7 18 12 18c1.7 0 3.22-.35 4.55-.9l4.17 4.18a.75.75 0 1 0 1.06-1.06zM12 7c.7 0 1.36.12 1.98.33l-1.5 1.5A2.25 2.25 0 0 0 9.83 11.5L8.3 13A4 4 0 0 1 12 7zm0 9.5c-3.9 0-6.85-2.5-8.3-5.1.55-1 1.45-2.15 2.65-3.1l1.55 1.55A4 4 0 0 0 12.9 14.9l1.7 1.7c-.82.26-1.7.4-2.6.4zm8.3-5.1c-.3.55-.7 1.15-1.2 1.7l-1.2-1.2c.3-.4.55-.85.7-1.3C17.5 8.9 15 7 12 7h-.2l-1.55-1.55C11.1 5.3 11.55 5.25 12 5.25c4.5 0 7.9 2.85 9.35 5.55a1.9 1.9 0 0 1 0 1.6z"/></svg>',
};

async function parseError(r) {
  const text = await r.text();
  try {
    const data = JSON.parse(text);
    if (data && data.detail) {
      return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
  } catch (_err) {
    /* keep raw text */
  }
  return text;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showBootError(message) {
  const banner = document.createElement("div");
  banner.style.cssText =
    "background:#5c1f1f;color:#fff;padding:0.75rem 1rem;margin:0;border-bottom:1px solid #8b3030";
  banner.textContent = message;
  document.body.insertBefore(banner, document.body.firstChild);
}

function parseTabFromUrl() {
  const tab = new URLSearchParams(location.search).get("tab");
  if (tab && HUB_TABS[tab]) return tab;
  if (tab === "public") return "all";
  if (tab === "network") return "subscriptions";
  return "all";
}

function setTabInUrl(tab) {
  const url = new URL(location.href);
  if (tab === "all") url.searchParams.delete("tab");
  else url.searchParams.set("tab", tab);
  history.replaceState({ tab }, "", url.pathname + url.search);
}

function formatRelativeRu(iso) {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return String(iso);
  const sec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (sec < 60) return "только что";
  const min = Math.round(sec / 60);
  if (min < 60) return min + " мин назад";
  const hr = Math.round(min / 60);
  if (hr < 24) return hr + " ч назад";
  const day = Math.round(hr / 24);
  if (day < 7) return day + " дн назад";
  const d = new Date(ts);
  return d.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function visibilityBadge(visibility) {
  const key = visibility || "public";
  const label = VISIBILITY_LABELS[key] || key;
  const icon =
    key === "network"
      ? HUB_ICONS.users
      : key === "unlisted"
        ? HUB_ICONS.link
        : HUB_ICONS.globe;
  return (
    '<span class="hub-badge hub-badge--icon hub-badge--' +
    escapeHtml(key) +
    '" title="' +
    escapeHtml(label) +
    '" aria-label="' +
    escapeHtml(label) +
    '">' +
    icon +
    "</span>"
  );
}

function metaChip(icon, text, title) {
  if (!text) return "";
  return (
    '<span class="hub-meta-chip" title="' +
    escapeHtml(title || text) +
    '">' +
    icon +
    '<span class="hub-meta-chip__text">' +
    escapeHtml(text) +
    "</span></span>"
  );
}

function projectMetaChips(p, { showOwner = true } = {}) {
  const chips = [];
  if (showOwner && p.owner_login) {
    chips.push(metaChip(HUB_ICONS.user, "@" + p.owner_login, "Автор"));
  }
  if (p.repo_full_name) {
    const short =
      !showOwner && p.repo_full_name.includes("/")
        ? p.repo_full_name.split("/").slice(1).join("/")
        : p.repo_full_name.includes("/")
          ? p.repo_full_name.split("/").pop()
          : p.repo_full_name;
    chips.push(metaChip(HUB_ICONS.repo, short, p.repo_full_name));
  }
  if (p.branch && p.branch !== "koi/research") {
    chips.push(metaChip(HUB_ICONS.branch, p.branch, "Ветка " + p.branch));
  } else if (p.branch) {
    chips.push(
      '<span class="hub-meta-chip hub-meta-chip--icon" title="Ветка ' +
        escapeHtml(p.branch) +
        '" aria-label="Ветка ' +
        escapeHtml(p.branch) +
        '">' +
        HUB_ICONS.branch +
        "</span>"
    );
  }
  chips.push(
    '<span class="hub-meta-chip hub-meta-chip--time" title="' +
      escapeHtml(p.last_sync_at || "") +
      '">' +
      HUB_ICONS.clock +
      '<span class="hub-meta-chip__text">' +
      escapeHtml(formatRelativeRu(p.last_sync_at)) +
      "</span></span>"
  );
  return '<div class="hub-project-card__meta-row">' + chips.join("") + "</div>";
}

function projectHref(p) {
  return p.view_href || p.view_url || "/p/" + encodeURIComponent(p.slug);
}

function projectShareToken(p) {
  const href = projectHref(p);
  try {
    return new URL(href, location.origin).searchParams.get("token") || "";
  } catch (_) {
    return "";
  }
}

function likeButtonHtml(p) {
  const liked = p.liked_by_me === true;
  const count = Number(p.like_count) || 0;
  const token = projectShareToken(p);
  return (
    '<button type="button" class="hub-project-card__like' +
    (liked ? " is-liked" : "") +
    '" data-action="like" data-slug="' +
    escapeHtml(p.slug || "") +
    '"' +
    (token ? ' data-token="' + escapeHtml(token) + '"' : "") +
    ' aria-pressed="' +
    (liked ? "true" : "false") +
    '" title="' +
    (liked ? "Убрать лайк" : "Лайк") +
    '" aria-label="' +
    (liked ? "Убрать лайк" : "Поставить лайк") +
    '">' +
    '<span class="hub-project-card__like-mark" aria-hidden="true">' +
    (liked ? HUB_ICONS.heart : HUB_ICONS.heartOutline) +
    "</span>" +
    '<span class="hub-project-card__like-count">' +
    escapeHtml(String(count)) +
    "</span>" +
    "</button>"
  );
}

function cardTitleBlock(p, badgesHtml) {
  return (
    '<div class="hub-project-card__head">' +
    '<div class="hub-project-card__title-row">' +
    '<h3 title="' +
    escapeHtml(p.title || p.slug) +
    '">' +
    escapeHtml(p.title || p.slug) +
    "</h3>" +
    (badgesHtml
      ? '<div class="hub-project-card__badges">' + badgesHtml + "</div>"
      : "") +
    "</div>"
  );
}

function cardFooter(startHtml, endHtml) {
  return (
    '<div class="hub-project-card__footer">' +
    '<div class="hub-project-card__footer-start">' +
    (startHtml || "") +
    "</div>" +
    '<div class="hub-project-card__footer-end">' +
    (endHtml || "") +
    "</div></div>"
  );
}

function renderBrowseCard(p, { tab = "all" } = {}) {
  const href = projectHref(p);
  const showVis = p.visibility && p.visibility !== "public";
  const showFollow =
    tab === "all" && !p.is_self && p.is_following !== true;
  const savedBadge = p.saved_by_link
    ? '<span class="hub-badge hub-badge--icon hub-badge--link" title="Добавлен по ссылке" aria-label="Добавлен по ссылке">' +
      HUB_ICONS.link +
      "</span>"
    : "";
  const badges = savedBadge + (showVis ? visibilityBadge(p.visibility) : "");

  let endActions = "";
  if (showFollow) {
    const ownerId = p.owner_github_id != null ? String(p.owner_github_id) : "";
    const ownerLogin = p.owner_login || "автора";
    endActions =
      '<button type="button" class="hub-project-card__icon-btn hub-project-card__follow" data-action="follow" data-owner-id="' +
      escapeHtml(ownerId) +
      '" title="Подписаться на @' +
      escapeHtml(ownerLogin) +
      '" aria-label="Подписаться на @' +
      escapeHtml(ownerLogin) +
      '">' +
      HUB_ICONS.userPlus +
      "</button>";
  }

  return (
    '<article class="hub-project-card">' +
    '<a class="hub-project-card__main" href="' +
    href +
    '">' +
    cardTitleBlock(p, badges) +
    projectMetaChips(p) +
    "</div></a>" +
    cardFooter(likeButtonHtml(p), endActions) +
    "</article>"
  );
}

function renderMineCard(p) {
  const on = p.enabled !== false;
  const dup = p.is_canonical === false;
  const href = projectHref(p);
  const shareUrl = p.share_url || "";
  const badges =
    visibilityBadge(p.visibility) +
    (on
      ? ""
      : '<span class="hub-badge hub-badge--off" title="Скрыт в каталоге">Скрыт</span>');

  const endActions =
    (shareUrl
      ? '<button type="button" class="hub-project-card__icon-btn hub-copy-link" data-action="copy-link" data-share-url="' +
        escapeHtml(shareUrl) +
        '" title="Скопировать ссылку" aria-label="Скопировать ссылку">' +
        HUB_ICONS.link +
        "</button>"
      : "") +
    '<button type="button" class="hub-project-card__icon-btn hub-edit-btn" data-action="edit" title="Редактировать" aria-label="Редактировать">' +
    HUB_ICONS.edit +
    "</button>" +
    '<button type="button" class="hub-project-card__icon-btn hub-enable-btn' +
    (on ? " is-on" : "") +
    '" data-action="enabled" data-enabled="' +
    (on ? "true" : "false") +
    '" title="' +
    (on ? "Скрыть из каталога" : "Показать в каталоге") +
    '" aria-label="' +
    (on ? "Скрыть из каталога" : "Показать в каталоге") +
    '" aria-pressed="' +
    (on ? "true" : "false") +
    '">' +
    (on ? HUB_ICONS.eye : HUB_ICONS.eyeOff) +
    "</button>" +
    '<button type="button" class="hub-project-card__icon-btn hub-sync-btn" data-action="sync" title="Синхронизировать" aria-label="Синхронизировать">' +
    HUB_ICONS.sync +
    "</button>" +
    (dup
      ? '<button type="button" class="hub-project-card__icon-btn hub-delete-btn" data-action="delete" title="Удалить дубликат" aria-label="Удалить дубликат">' +
        HUB_ICONS.trash +
        "</button>"
      : "");

  return (
    '<article class="hub-project-card hub-project-card--mine' +
    (on ? "" : " hub-project-card--off") +
    (dup ? " hub-project-card--dup" : "") +
    '" data-slug="' +
    escapeHtml(p.slug) +
    '" data-repo="' +
    escapeHtml(p.repo_full_name || "") +
    '" data-branch="' +
    escapeHtml(p.branch || "") +
    '" data-visibility="' +
    escapeHtml(p.visibility || "public") +
    '">' +
    '<a class="hub-project-card__main" href="' +
    escapeHtml(href) +
    '">' +
    cardTitleBlock(p, badges) +
    projectMetaChips(p, { showOwner: false }) +
    "</div></a>" +
    (dup
      ? '<p class="hub-project-card__dup">Дубликат · основной: <a href="/p/' +
        escapeHtml(p.canonical_slug || "") +
        '">' +
        escapeHtml(p.canonical_slug || "") +
        "</a></p>"
      : "") +
    cardFooter(likeButtonHtml(p), endActions) +
    "</article>"
  );
}

function renderAddProjectCard() {
  return (
    '<a class="hub-project-card hub-project-card--add" href="/connect">' +
    '<span class="hub-project-card__add-icon" aria-hidden="true">+</span>' +
    '<span class="hub-project-card__add-label">Подключить проект</span>' +
    "</a>"
  );
}

function renderProjectGrid(projects, { manage = false, tab = "all" } = {}) {
  const cards = projects.map(function (p) {
    return manage ? renderMineCard(p) : renderBrowseCard(p, { tab });
  });
  if (manage) {
    return (
      '<div class="hub-grid">' + renderAddProjectCard() + cards.join("") + "</div>"
    );
  }
  if (!cards.length) return "";
  return '<div class="hub-grid">' + cards.join("") + "</div>";
}

function renderEmptyState(tab) {
  if (tab === "all") {
    return (
      '<div class="hub-empty-state">' +
      "<p>Пока нет публичных проектов.</p>" +
      '<p class="hub-empty-state__hint">Подключите свой репозиторий и выберите visibility «Публичный».</p>' +
      '<a class="btn btn-primary" href="/connect">Подключить проект</a>' +
      "</div>"
    );
  }
  if (tab === "subscriptions") {
    return (
      '<div class="hub-empty-state">' +
      "<p>Лента подписок пуста.</p>" +
      '<p class="hub-empty-state__hint">Подпишитесь на авторов или добавьте проект по секретной ссылке.</p>' +
      '<button type="button" class="btn btn-primary" data-action="open-link-modal">Добавить по ссылке</button>' +
      "</div>"
    );
  }
  return (
    '<div class="hub-empty-state">' +
    "<p>Вы ещё не подключили проекты.</p>" +
    '<p class="hub-empty-state__hint">Нажмите <strong>+</strong> слева, чтобы подключить репозиторий.</p>' +
    "</div>"
  );
}

function renderAuthRequired(tab) {
  const cfg = HUB_TABS[tab];
  return (
    '<div class="hub-empty-state">' +
    "<p>Нужен вход через GitHub</p>" +
    '<p class="hub-empty-state__hint">' +
    escapeHtml(cfg.desc) +
    "</p>" +
    '<a class="btn btn-primary" href="/auth/github">Войти через GitHub</a>' +
    "</div>"
  );
}

async function renderAuthToolbar() {
  if (window.HubShell && typeof window.HubShell.renderAuthToolbar === "function") {
    return window.HubShell.renderAuthToolbar();
  }
  const el = document.getElementById("auth-toolbar");
  if (!el) return null;
  try {
    const me = await HubApi.get("/api/me");
    if (!me.authenticated) {
      el.innerHTML =
        '<a class="btn btn-primary hub-login-btn" href="/auth/github">Войти</a>';
      return me;
    }
    const u = me.user;
    el.innerHTML =
      '<div class="hub-account">' +
      '<button type="button" class="user-chip hub-account__trigger" id="hub-account-trigger" aria-expanded="false" aria-haspopup="menu" aria-controls="hub-account-menu">' +
      '<img src="' + escapeHtml(u.avatar_url) + '" alt="" width="24" height="24" />' +
      "<span>@" + escapeHtml(u.login) + "</span>" +
      '<span class="hub-account__chevron" aria-hidden="true">▾</span>' +
      "</button>" +
      '<div class="hub-account__menu hidden" id="hub-account-menu" role="menu">' +
      '<a class="hub-account__item" href="/connect" role="menuitem">+ Подключить репозиторий</a>' +
      '<button type="button" class="hub-account__item hub-account__item--danger" data-action="logout" role="menuitem">Выйти</button>' +
      "</div>" +
      "</div>";
    bindAccountMenu(el);
    return me;
  } catch (err) {
    el.innerHTML = '<span class="meta">Auth: ' + escapeHtml(err.message) + "</span>";
    return null;
  }
}

function bindAccountMenu(root) {
  const trigger = root.querySelector("#hub-account-trigger");
  const menu = root.querySelector("#hub-account-menu");
  if (!trigger || !menu) return;

  function closeMenu() {
    menu.classList.add("hidden");
    trigger.setAttribute("aria-expanded", "false");
  }

  function openMenu() {
    menu.classList.remove("hidden");
    trigger.setAttribute("aria-expanded", "true");
  }

  trigger.addEventListener("click", function (e) {
    e.stopPropagation();
    if (menu.classList.contains("hidden")) openMenu();
    else closeMenu();
  });

  menu.querySelector('[data-action="logout"]')?.addEventListener("click", async function () {
    closeMenu();
    await HubApi.post("/auth/logout");
    location.reload();
  });

  document.addEventListener("click", function (e) {
    if (!root.contains(e.target)) closeMenu();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMenu();
  });
}

function syncHubPanelCta(authState, href) {
  if (document.body.getAttribute("data-page") !== "index") return;
  const cta = document.getElementById("hub-panel-cta");
  if (!cta) return;
  if (!href) {
    const isGuest = !authState || !authState.authenticated;
    href = isGuest ? "/auth/github" : "/connect";
  }

  cta.classList.remove("hidden");
  cta.innerHTML =
    '<a href="' +
    escapeHtml(href) +
    '" class="btn btn-primary hub-enter-btn">Войти в мир исследований</a>';
}

async function resolveEnterWorldHref(projects, authState) {
  if (projects && projects.length > 0) {
    return projectHref(projects[0]);
  }
  try {
    const data = await HubApi.get("/api/catalog/public");
    const pub = (data.projects || [])[0];
    if (pub) return projectHref(pub);
  } catch (_err) {
    /* fallback below */
  }
  const isGuest = !authState || !authState.authenticated;
  return isGuest ? "/auth/github" : "/connect";
}

function updatePanel(tab) {
  const cfg = HUB_TABS[tab];
  const title = document.getElementById("hub-panel-title");
  const desc = document.getElementById("hub-panel-desc");
  if (title) title.textContent = cfg.title;
  if (desc) desc.textContent = cfg.desc;
  document.title = cfg.title + " · ResearchOS Hub";
}

function setActiveTabUi(tab) {
  document.querySelectorAll(".hub-panel__tab").forEach(function (btn) {
    const on = btn.getAttribute("data-tab") === tab;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
}

function renderSubscriptionsBar() {
  return (
    '<div class="hub-subscriptions-bar">' +
    '<button type="button" class="btn btn-primary" data-action="open-link-modal">+ Добавить по ссылке</button>' +
    "</div>"
  );
}

function initLinkModal(onSuccess) {
  const modal = document.getElementById("hub-link-modal");
  const form = document.getElementById("hub-link-form");
  const input = document.getElementById("hub-link-input");
  const status = document.getElementById("hub-link-status");
  if (!modal || !form || !input) return;

  function openModal() {
    modal.classList.remove("hidden");
    input.value = "";
    if (status) status.textContent = "";
    input.focus();
  }

  function closeModal() {
    modal.classList.add("hidden");
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest('[data-action="open-link-modal"]')) {
      e.preventDefault();
      openModal();
    }
    if (
      e.target.closest('[data-action="close-link-modal"]') ||
      e.target.dataset.close === "hub-link-modal"
    ) {
      closeModal();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    const url = input.value.trim();
    if (!url) return;
    if (status) status.textContent = "Проверка ссылки…";
    try {
      const result = await HubApi.post("/api/subscriptions/by-link", { url });
      closeModal();
      if (typeof onSuccess === "function") await onSuccess(result);
    } catch (err) {
      if (status) status.textContent = err.message;
    }
  });
}

function initProjectEditModal(onSuccess) {
  const modal = document.getElementById("hub-project-edit-modal");
  const form = document.getElementById("hub-project-edit-form");
  const repo = document.getElementById("hub-project-edit-repo");
  const branch = document.getElementById("hub-project-edit-branch");
  const visibility = document.getElementById("hub-project-edit-visibility");
  const hint = document.getElementById("hub-project-edit-branch-hint");
  const status = document.getElementById("hub-project-edit-status");
  if (!modal || !form || !repo || !branch || !visibility) return function () {};

  let slug = "";
  let originalBranch = "";

  function closeModal() {
    modal.classList.add("hidden");
  }

  function updateHint() {
    if (!hint) return;
    hint.classList.toggle("hidden", branch.value.trim() === originalBranch);
  }

  document.addEventListener("click", function (e) {
    if (
      e.target.closest('[data-action="close-project-edit-modal"]') ||
      e.target.dataset.close === "hub-project-edit-modal"
    ) {
      closeModal();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
  });
  branch.addEventListener("input", updateHint);

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!slug) return;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    if (status) status.textContent = "Проверка и сохранение…";
    try {
      const result = await HubApi.patch(
        "/api/projects/" + encodeURIComponent(slug),
        { branch: branch.value.trim(), visibility: visibility.value }
      );
      closeModal();
      if (typeof onSuccess === "function") await onSuccess(result);
    } catch (err) {
      if (status) status.textContent = err.message;
    } finally {
      if (submit) submit.disabled = false;
    }
  });

  return function openModal(card) {
    if (!card) return;
    slug = card.dataset.slug || "";
    originalBranch = card.dataset.branch || "";
    repo.value = card.dataset.repo || "";
    branch.value = originalBranch;
    visibility.value = card.dataset.visibility || "public";
    if (status) status.textContent = "";
    updateHint();
    modal.classList.remove("hidden");
    branch.focus();
  };
}

function initIndexPage() {
  let activeTab = parseTabFromUrl();
  let authState = null;
  let manageBound = false;
  let followBound = false;
  let likeBound = false;

  function setStatus(msg) {
    const el = document.getElementById("hub-status");
    if (el) el.textContent = msg || "";
  }

  const openProjectEditModal = initProjectEditModal(async function () {
    setStatus("Настройки проекта сохранены.");
    await loadCatalog();
  });

  async function refreshEnterWorldCta(projects) {
    const href = await resolveEnterWorldHref(projects, authState);
    syncHubPanelCta(authState, href);
  }

  async function loadCatalog() {
    const root = document.getElementById("catalog");
    if (!root) return;
    const cfg = HUB_TABS[activeTab];
    updatePanel(activeTab);
    setActiveTabUi(activeTab);
    setTabInUrl(activeTab);
    setStatus("");
    root.innerHTML = '<p class="hub-empty">Загрузка…</p>';

    if (cfg.requiresAuth && (!authState || !authState.authenticated)) {
      root.innerHTML = renderAuthRequired(activeTab);
      await refreshEnterWorldCta([]);
      return;
    }

    try {
      const data = await HubApi.get(cfg.api);
      const projects = data.projects || [];
      if (!projects.length && !cfg.manage) {
        root.innerHTML =
          (activeTab === "subscriptions" ? renderSubscriptionsBar() : "") +
          renderEmptyState(activeTab);
        await refreshEnterWorldCta([]);
        return;
      }
      root.innerHTML =
        (activeTab === "subscriptions" ? renderSubscriptionsBar() : "") +
        renderProjectGrid(projects, {
          manage: !!cfg.manage,
          tab: activeTab,
        });
      if (cfg.manage && !manageBound) bindManageActions(root);
      if (!cfg.manage && !followBound) bindFollowActions(root);
      if (!likeBound) bindLikeActions(root);
      await refreshEnterWorldCta(projects);
    } catch (err) {
      const msg = /sign in|auth|401|403|session/i.test(String(err.message))
        ? "Войдите через GitHub, чтобы открыть этот раздел."
        : err.message;
      root.innerHTML = '<p class="hub-empty">' + escapeHtml(msg) + "</p>";
      await refreshEnterWorldCta([]);
    }
  }

  function bindFollowActions(root) {
    if (followBound) return;
    followBound = true;

    root.addEventListener("click", async function (e) {
      const btn = e.target.closest('[data-action="follow"]');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      if (!authState || !authState.authenticated) {
        location.href = "/auth/github";
        return;
      }
      const ownerId = Number(btn.dataset.ownerId);
      if (!ownerId) return;
      btn.disabled = true;
      setStatus("");
      try {
        await HubApi.post("/api/follow", { github_id: ownerId });
        setStatus("Подписка оформлена — network-проекты автора появятся во вкладке «Подписки».");
        await loadCatalog();
      } catch (err) {
        setStatus(err.message);
        btn.disabled = false;
      }
    });
  }

  function bindLikeActions(root) {
    if (likeBound) return;
    likeBound = true;

    root.addEventListener("click", async function (e) {
      const btn = e.target.closest('[data-action="like"]');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      if (!authState || !authState.authenticated) {
        location.href = "/auth/github";
        return;
      }
      const slug = btn.dataset.slug;
      if (!slug) return;
      const token = btn.dataset.token || "";
      let path =
        "/api/projects/" + encodeURIComponent(slug) + "/like";
      if (token) path += "?token=" + encodeURIComponent(token);
      btn.disabled = true;
      setStatus("");
      try {
        const result = await HubApi.post(path, {});
        const liked = result.liked === true;
        const count = Number(result.count) || 0;
        btn.classList.toggle("is-liked", liked);
        btn.setAttribute("aria-pressed", liked ? "true" : "false");
        btn.title = liked ? "Убрать лайк" : "Лайк";
        btn.setAttribute(
          "aria-label",
          liked ? "Убрать лайк" : "Поставить лайк"
        );
        const mark = btn.querySelector(".hub-project-card__like-mark");
        const countEl = btn.querySelector(".hub-project-card__like-count");
        if (mark) {
          mark.innerHTML = liked ? HUB_ICONS.heart : HUB_ICONS.heartOutline;
        }
        if (countEl) countEl.textContent = String(count);
      } catch (err) {
        setStatus(err.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

  function bindManageActions(root) {
    if (manageBound) return;
    manageBound = true;

    root.addEventListener("click", async function (e) {
      const editBtn = e.target.closest('[data-action="edit"]');
      if (editBtn) {
        const card = editBtn.closest(".hub-project-card--mine");
        openProjectEditModal(card);
        return;
      }
      const enableBtn = e.target.closest('[data-action="enabled"]');
      if (enableBtn) {
        const card = enableBtn.closest(".hub-project-card--mine");
        const slug = card && card.getAttribute("data-slug");
        if (!slug) return;
        const nextEnabled = enableBtn.getAttribute("data-enabled") !== "true";
        enableBtn.disabled = true;
        setStatus("");
        try {
          await HubApi.patch("/api/projects/" + encodeURIComponent(slug), {
            enabled: nextEnabled,
          });
          await loadCatalog();
          setStatus(
            nextEnabled
              ? "Проект снова виден в каталоге (если visibility public или network)."
              : "Проект скрыт из каталога."
          );
        } catch (err) {
          setStatus(err.message);
          enableBtn.disabled = false;
        }
        return;
      }

      const copyBtn = e.target.closest('[data-action="copy-link"]');
      if (copyBtn) {
        const url = copyBtn.dataset.shareUrl;
        if (!url) return;
        try {
          await navigator.clipboard.writeText(url);
          setStatus("Ссылка скопирована.");
        } catch (_err) {
          window.prompt("Скопируйте ссылку:", url);
        }
        return;
      }
      const delBtn = e.target.closest('[data-action="delete"]');
      if (delBtn) {
        const card = delBtn.closest(".hub-project-card--mine");
        const slug = card && card.getAttribute("data-slug");
        if (!slug || !window.confirm("Удалить дубликат «" + slug + "»?")) return;
        delBtn.disabled = true;
        setStatus("Удаление…");
        try {
          await HubApi.delete("/api/projects/" + encodeURIComponent(slug));
          setStatus("Дубликат удалён.");
          await loadCatalog();
        } catch (err) {
          setStatus(err.message);
          delBtn.disabled = false;
        }
        return;
      }
      const btn = e.target.closest('[data-action="sync"]');
      if (!btn) return;
      const card = btn.closest(".hub-project-card--mine");
      const slug = card && card.getAttribute("data-slug");
      if (!slug) return;
      btn.disabled = true;
      setStatus("Синхронизация с GitHub…");
      try {
        await HubApi.post("/api/projects/" + encodeURIComponent(slug) + "/sync");
        setStatus("Синхронизация завершена.");
        await loadCatalog();
      } catch (err) {
        setStatus(err.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

  document.querySelectorAll(".hub-panel__tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      activeTab = btn.getAttribute("data-tab") || "all";
      loadCatalog();
    });
  });

  window.addEventListener("popstate", function () {
    activeTab = parseTabFromUrl();
    loadCatalog();
  });

  renderAuthToolbar().then(function (me) {
    authState = me;
    initLinkModal(async function (result) {
      if (activeTab !== "subscriptions") {
        activeTab = "subscriptions";
      }
      setStatus(
        result.already_saved
          ? "Проект уже был в подписках: " + (result.title || result.slug)
          : "Добавлено в подписки: " + (result.title || result.slug)
      );
      await loadCatalog();
    });
    loadCatalog();
  });
}

async function initConnectPage() {
  await renderAuthToolbar();
  try {
    const me = await HubApi.get("/api/me");
    if (!me.authenticated) {
      location.href = "/auth/github";
      return;
    }
  } catch (err) {
    showBootError("Не удалось проверить сессию: " + err.message);
    return;
  }

  const select = document.getElementById("repo");
  if (!select) return;
  select.innerHTML = '<option value="">Загрузка…</option>';
  try {
    const data = await HubApi.get("/api/repos");
    const repos = data.repos || [];
    if (!repos.length) {
      select.innerHTML = '<option value="">Репозитории не найдены</option>';
      return;
    }
    select.innerHTML = repos
      .map(function (r) {
        return (
          '<option value="' +
          escapeHtml(r.full_name) +
          '">' +
          escapeHtml(r.full_name) +
          (r.private ? " (private)" : "") +
          "</option>"
        );
      })
      .join("");
  } catch (err) {
    document.getElementById("status").textContent = err.message;
  }

  const form = document.getElementById("connect-form");
  if (!form) return;
  let syncing = false;
  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (syncing) return;
    syncing = true;
    const status = document.getElementById("status");
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    status.textContent = "Синхронизация с GitHub… (до минуты)";
    try {
      const result = await HubApi.post("/api/projects", {
        repo_full_name: document.getElementById("repo").value,
        branch: document.getElementById("branch").value,
        title: document.getElementById("title").value,
        visibility: document.getElementById("visibility").value,
      });
      const viewUrl = result.view_url || "/p/" + encodeURIComponent(result.slug);
      let html =
        'Готово: <a href="' +
        escapeHtml(viewUrl) +
        '">' +
        escapeHtml(result.title || result.slug) +
        "</a> · " +
        '<a href="/?tab=mine">Мои проекты</a>';
      if (result.secret_token) {
        html +=
          '<br><span class="meta">Unlisted: /p/' +
          escapeHtml(result.slug) +
          "?token=" +
          escapeHtml(result.secret_token) +
          "</span>";
      }
      if (result.reused_existing) {
        html = "Уже подключено — обновлено: " + html;
      }
      status.innerHTML = html;
    } catch (err) {
      status.textContent = err.message;
      if (submitBtn) submitBtn.disabled = false;
      syncing = false;
    }
  });
}

function boot() {
  const page = document.body.getAttribute("data-page");
  if (page === "index") initIndexPage();
  else if (page === "connect") initConnectPage();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
