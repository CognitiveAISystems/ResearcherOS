(function () {
  var STORAGE_KEY = "koi-theme";

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
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
    initMermaid(true);
  }

  function bindThemeToggle() {
    var btn = document.getElementById("btn-theme");
    if (!btn) return;
    btn.addEventListener("click", function () {
      setTheme(currentTheme() === "dark" ? "light" : "dark");
    });
  }

  function setCurrentNav() {
    var path = location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll(".nav a[href]").forEach(function (a) {
      var href = a.getAttribute("href");
      if (!href || href.startsWith("http") || href.startsWith("#")) return;
      var resolved = new URL(href, location.href).pathname.replace(/\/$/, "") || "/";
      if (path === resolved || (resolved !== "/" && path.indexOf(resolved) === 0)) {
        a.setAttribute("aria-current", "page");
      }
    });
  }

  function mermaidVars(theme) {
    if (document.querySelector('link[href*="airi-theme.css"]')) {
      return {
        primaryColor: "#2fbead", primaryTextColor: "#ffffff",
        nodeTextColor: "#ffffff", textColor: "#161c27",
        primaryBorderColor: "#2fbead", lineColor: "#161c27",
        edgeLabelBackground: "#ffffff",
        secondaryColor: "#e8d5c4", tertiaryColor: "#ffffff",
        fontFamily: "Inter, sans-serif",
      };
    }
    if (theme === "dark") {
      return {
        primaryColor: "#2a1848",
        primaryTextColor: "#f4f4ff",
        primaryBorderColor: "#9b5cff",
        lineColor: "#8b8ca8",
        secondaryColor: "#0e0e14",
        tertiaryColor: "#1a1228",
        fontFamily: "Inter, sans-serif",
      };
    }
    return {
      primaryColor: "#efe8ff",
      primaryTextColor: "#1a1d26",
      primaryBorderColor: "#6b42d4",
      lineColor: "#5c6370",
      secondaryColor: "#f6f8fc",
      tertiaryColor: "#ffffff",
      fontFamily: "Inter, sans-serif",
    };
  }

  var mermaidReady = false;

  function initMermaid(rerender) {
    if (!window.mermaid) return;
    var theme = currentTheme();
    window.mermaid.initialize({
      startOnLoad: !rerender,
      theme: "base",
      themeVariables: mermaidVars(theme),
      flowchart: { curve: "basis", padding: 12 },
    });
    if (!rerender || !mermaidReady) {
      mermaidReady = true;
      return;
    }
    document.querySelectorAll(".graph .mermaid").forEach(function (el) {
      var src = el.getAttribute("data-src");
      if (!src) {
        src = el.textContent;
        el.setAttribute("data-src", src);
      }
      el.removeAttribute("data-processed");
      el.textContent = src;
    });
    window.mermaid.run({ querySelector: ".graph .mermaid" });
  }

  function initReveal() {
    var nodes = document.querySelectorAll(".reveal");
    if (!nodes.length) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      nodes.forEach(function (n) {
        n.classList.add("is-in");
      });
      return;
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" }
    );
    nodes.forEach(function (n) {
      io.observe(n);
    });
  }

  function initChapterNav() {
    var nav = document.getElementById("chapter-nav");
    if (!nav) return;
    var links = nav.querySelectorAll("[data-nav]");
    var chapters = document.querySelectorAll("[data-chapter]");
    var hero = document.getElementById("top");
    if (!chapters.length) return;

    function setActive(id) {
      links.forEach(function (a) {
        a.classList.toggle("is-active", id && a.getAttribute("data-nav") === id);
      });
    }

    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return;
          if (e.target.id === "top") {
            setActive(null);
            return;
          }
          setActive(e.target.getAttribute("data-chapter"));
        });
      },
      { rootMargin: "-40% 0px -45% 0px", threshold: 0.01 }
    );
    if (hero) io.observe(hero);
    chapters.forEach(function (c) {
      io.observe(c);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function loadSkillsGrid() {
    var grid = document.getElementById("skill-grid");
    if (!grid) return;
    var url = new URL("skills.json", location.href).href;
    fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("skills.json");
        return r.json();
      })
      .then(function (skills) {
        grid.innerHTML = skills
          .map(function (s) {
            return (
              '<a class="skill-link" href="skills/' +
              encodeURIComponent(s.id) +
              '.html">' +
              '<p class="skill-link__id">' +
              escapeHtml(s.id) +
              "</p>" +
              '<h3 class="skill-link__name">' +
              escapeHtml(s.title) +
              "</h3>" +
              (s.when
                ? '<p class="skill-link__when">' + escapeHtml(s.when) + "</p>"
                : "") +
              '<p class="skill-link__desc">' +
              escapeHtml(s.summary) +
              "</p>" +
              "</a>"
            );
          })
          .join("");
      })
      .catch(function () {
        grid.innerHTML =
          '<p class="chapter__lead">Не удалось загрузить каталог. Откройте <a href="skills/index.html">skills/</a>.</p>';
      });
  }

  function initScrollHint() {
    var hint = document.getElementById("hero-scroll");
    var hero = document.getElementById("top");
    if (!hint || !hero) return;

    function update() {
      var past = window.scrollY > Math.max(80, hero.offsetHeight * 0.22);
      hint.classList.toggle("is-hidden", past);
    }

    window.addEventListener("scroll", update, { passive: true });
    update();
  }

  document.querySelectorAll(".graph .mermaid").forEach(function (el) {
    if (!el.getAttribute("data-src")) {
      el.setAttribute("data-src", el.textContent);
    }
  });

  setCurrentNav();
  bindThemeToggle();
  initReveal();
  initChapterNav();
  initScrollHint();
  loadSkillsGrid();
  initMermaid(false);
})();
