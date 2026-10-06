(function () {
  var STORAGE_KEY = "koi-theme";
  var MEDIA_EXTS = {
    image: ["png", "jpg", "jpeg", "webp", "gif"],
    video: ["mp4", "webm"],
  };

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function syncSchemaTheme(root) {
    var theme = currentTheme();
    (root || document).querySelectorAll('iframe[src*="full_schema.html"]').forEach(function (frame) {
      try {
        var url = new URL(frame.getAttribute("src"), location.href);
        url.searchParams.set("embed", "1");
        url.searchParams.set("theme", theme);
        var next = url.pathname.replace(/^\//, "") === url.pathname
          ? url.pathname.split("/").pop() + url.search
          : url.pathname + url.search;
        // Keep relative src when possible
        var rel = frame.getAttribute("src").split("?")[0];
        next = rel + "?" + url.searchParams.toString();
        if (frame.getAttribute("src") !== next) frame.setAttribute("src", next);
      } catch (e) {}
    });
    sizeSchemaFrames(root);
  }

  function sizeSchemaFrames(root) {
    var DIAG_W = 1360;
    var DIAG_H = 930;
    (root || document).querySelectorAll(".schema-frame--embed iframe").forEach(function (frame) {
      var w = frame.getBoundingClientRect().width || frame.parentElement?.clientWidth || 0;
      if (!w) return;
      var h = Math.min((w * DIAG_H) / DIAG_W, window.innerHeight * 0.85, DIAG_H);
      frame.style.height = Math.round(h) + "px";
    });
  }

  function setTheme(theme) {
    var t = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", t);
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch (e) {}
    var btn = document.getElementById("btn-theme");
    if (btn) {
      btn.setAttribute("aria-label", t === "dark" ? "Светлая тема" : "Тёмная тема");
      btn.title = t === "dark" ? "Светлая тема" : "Тёмная тема";
    }
    syncSchemaTheme(document.getElementById("features-content"));
  }

  function bindThemeToggle() {
    var btn = document.getElementById("btn-theme");
    if (!btn) return;
    btn.addEventListener("click", function () {
      setTheme(currentTheme() === "dark" ? "light" : "dark");
    });
    setTheme(currentTheme());
  }

  function slugifyHeading(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^\w\u0400-\u04ff\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-");
  }

  function addHeadingIds(root) {
    root.querySelectorAll("h2, h3").forEach(function (el) {
      if (el.id) return;
      var id = slugifyHeading(el.textContent);
      if (!id) return;
      el.id = id;
      // Stable anchors used in nav
      if (/три слоя|тр[её]х слоях/i.test(el.textContent)) el.id = "three-layers";
      if (/^(общая )?схема$/i.test(el.textContent.trim()) || /схема целиком/i.test(el.textContent)) el.id = "schema";
      if (/каталог локальных (фич|возможностей)/i.test(el.textContent) || /локальные фичи/i.test(el.textContent)) el.id = "feature-catalog";
      if (/^(синхронизация|три механизма согласования состояния)$/i.test(el.textContent.trim())) el.id = "sync";
      if (/^как работает$/i.test(el.textContent.trim())) el.id = "how-it-works";
      if (/как человек работает/i.test(el.textContent)) el.id = "ui";
      if (/какие (скиллы|сценарии)/i.test(el.textContent)) el.id = "skills";
      if (/как устроено технически/i.test(el.textContent)) el.id = "tech";
    });
  }

  function probeMedia(basePath, exts) {
    return new Promise(function (resolve) {
      var i = 0;
      function next() {
        if (i >= exts.length) {
          resolve(null);
          return;
        }
        var ext = exts[i++];
        var url = basePath + "." + ext;
        fetch(url, { method: "HEAD" })
          .then(function (res) {
            if (res.ok) resolve({ url: url, ext: ext });
            else next();
          })
          .catch(next);
      }
      next();
    });
  }

  function fillMediaSlots(root) {
    root.querySelectorAll(".media-slot[data-media]").forEach(function (slot) {
      var name = slot.getAttribute("data-media");
      if (!name) return;
      var base = "media/" + name;
      var accept = (slot.getAttribute("data-accept") || "png,jpg,webp,mp4,webm")
        .split(",")
        .map(function (s) {
          return s.trim().toLowerCase();
        })
        .filter(Boolean);

      probeMedia(base, accept).then(function (hit) {
        if (!hit) return;
        slot.setAttribute("data-filled", "true");
        slot.innerHTML = "";
        var isVideo = MEDIA_EXTS.video.indexOf(hit.ext) !== -1;
        if (isVideo) {
          var video = document.createElement("video");
          video.controls = true;
          video.src = hit.url;
          video.setAttribute("playsinline", "");
          slot.appendChild(video);
        } else {
          var img = document.createElement("img");
          img.src = hit.url;
          img.alt = name.replace(/-/g, " ");
          slot.appendChild(img);
        }
      });
    });
  }

  function renderMarkdown(md) {
    // Strip HTML comment lead hint if present
    md = md.replace(/^<!--\s*lead:[^>]*-->\s*/i, "");
    if (window.marked && typeof marked.parse === "function") {
      marked.setOptions({ gfm: true, breaks: false });
      return marked.parse(md);
    }
    // Fallback: show raw if CDN blocked
    return "<pre>" + md.replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    }) + "</pre>";
  }

  function loadPage() {
    var mount = document.getElementById("features-content");
    if (!mount) return;
    if (mount.getAttribute("data-rendered") === "true") {
      addHeadingIds(mount);
      syncSchemaTheme(mount);
      requestAnimationFrame(function () { sizeSchemaFrames(mount); });
      return;
    }
    var src = mount.getAttribute("data-md");
    if (!src) return;

    fetch(src)
      .then(function (res) {
        if (!res.ok) throw new Error("Не удалось загрузить " + src);
        return res.text();
      })
      .then(function (md) {
        mount.innerHTML = renderMarkdown(md);
        addHeadingIds(mount);
        fillMediaSlots(mount);
        syncSchemaTheme(mount);
        sizeSchemaFrames(mount);
        requestAnimationFrame(function () {
          sizeSchemaFrames(mount);
        });
      })
      .catch(function (err) {
        mount.innerHTML =
          '<p class="error">Не удалось открыть страницу. Запустите локальный сервер из <code>docs-site</code> (см. README) — браузер блокирует <code>fetch</code> с <code>file://</code>.</p><p class="error">' +
          String(err.message || err) +
          "</p>";
      });
  }

  function boot() {
    bindThemeToggle();
    loadPage();
    window.addEventListener("resize", function () {
      sizeSchemaFrames(document.getElementById("features-content"));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
