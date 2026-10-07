(function () {
  var nav = document.getElementById("todo-sidebar");
  if (!nav) return;

  var links = Array.from(nav.querySelectorAll("[data-todo-nav]"));
  var targets = links
    .map(function (link) {
      return {
        link: link,
        section: document.querySelector(link.getAttribute("href")),
      };
    })
    .filter(function (item) {
      return item.section;
    });

  function setActive(activeLink) {
    links.forEach(function (link) {
      var active = link === activeLink;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  var scheduled = false;

  function updateActive() {
    scheduled = false;
    var marker = window.scrollY + 120;
    var current = targets[0];

    targets.forEach(function (item) {
      if (item.section.offsetTop <= marker) current = item;
    });

    if (current) setActive(current.link);
  }

  function requestUpdate() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateActive);
  }

  window.addEventListener("scroll", requestUpdate, { passive: true });
  window.addEventListener("resize", requestUpdate);
  window.addEventListener("hashchange", requestUpdate);
  updateActive();
})();
