(function () {
  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatSize(n) {
    var bytes = Number(n) || 0;
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function pathParts() {
    var parts = location.pathname.replace(/\/+$/, "").split("/");
    var i = parts.indexOf("skills");
    if (i < 0 || parts.length < i + 3) return null;
    return {
      projectSlug: decodeURIComponent(parts[i + 1]),
      skillId: decodeURIComponent(parts[i + 2]),
    };
  }

  function filesBlock(skill) {
    var files = skill.files || [];
    var downloadUrl = skill.download_url || "";
    var list =
      files.length === 0
        ? '<p class="hub-skill-files__empty">Список файлов появится после следующего sync проекта.</p>'
        : "<ul class=\"hub-skill-files__list\">" +
          files
            .map(function (f) {
              return (
                "<li><code>" +
                esc(f.path) +
                "</code><span>" +
                esc(formatSize(f.size)) +
                "</span></li>"
              );
            })
            .join("") +
          "</ul>";

    return (
      '<aside class="hub-skill-files">' +
      '<div class="hub-skill-files__head">' +
      "<h2>Файлы в пакете</h2>" +
      (downloadUrl
        ? '<a class="btn btn-primary hub-skill-download" href="' +
          esc(downloadUrl) +
          '">Скачать ZIP</a>'
        : "") +
      "</div>" +
      list +
      "</aside>"
    );
  }

  async function load() {
    var article = document.getElementById("skill-article");
    var parts = pathParts();
    if (!parts) {
      article.innerHTML = '<p class="hub-status">Некорректный URL</p>';
      return;
    }
    try {
      var url =
        "/api/skills/" +
        encodeURIComponent(parts.projectSlug) +
        "/" +
        encodeURIComponent(parts.skillId);
      var skill = await fetch(url, { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) throw new Error(r.status === 404 ? "Skill не найден" : r.statusText);
        return r.json();
      });
      document.title = (skill.title || skill.id) + " — ResearcherOS Hub";
      var html = "";
      if (typeof marked !== "undefined" && marked.parse) {
        html = marked.parse(skill.readme_md || "");
      } else {
        html = "<pre>" + esc(skill.readme_md) + "</pre>";
      }
      article.innerHTML =
        '<header class="hub-skill-header">' +
        '<p class="hub-skill-header__id"><code>' +
        esc(skill.id) +
        "</code></p>" +
        '<h1 class="hub-skill-header__title">' +
        esc(skill.title) +
        "</h1>" +
        (skill.summary
          ? '<p class="hub-skill-header__summary">' + esc(skill.summary) + "</p>"
          : "") +
        '<p class="hub-skill-header__meta">' +
        'из проекта <a href="' +
        esc(skill.project_url) +
        '">' +
        esc(skill.project_title || skill.project_slug) +
        "</a>" +
        (skill.owner_login ? " · @" + esc(skill.owner_login) : "") +
        (skill.repo_full_name
          ? ' · <a href="https://github.com/' +
            esc(skill.repo_full_name) +
            '" rel="noopener">' +
            esc(skill.repo_full_name) +
            "</a>"
          : "") +
        "</p>" +
        "</header>" +
        filesBlock(skill) +
        '<div class="hub-skill-body prose">' +
        html +
        "</div>";
    } catch (err) {
      article.innerHTML =
        '<p class="hub-status">' + esc(err.message || String(err)) + "</p>";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
