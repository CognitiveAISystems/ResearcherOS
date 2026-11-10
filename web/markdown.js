import { marked } from "./vendor-marked.mjs";
import katex from "./vendor/katex.mjs";

// Tokenize before Markdown can consume TeX backslashes, underscores and pipes.
function mathToken(source, block) {
  const pattern = block
    ? /^(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\])(?:[ \t]*\n|$)/
    : /^(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([^\n]+?)\\\)|\$(?!\s)([^\n$]*?\S)\$(?!\d))/;
  const match = pattern.exec(source);
  if (!match) return;
  return {
    type: block ? "blockMath" : "inlineMath",
    raw: match[0],
    text: match.slice(1).find(value => value !== undefined),
    display: block || source.startsWith("$$") || source.startsWith("\\["),
  };
}

function renderMathToken(token) {
  const math = katex.renderToString(token.text, {
    displayMode: token.display,
    output: "mathml",
    throwOnError: false,
    trust: false,
  });
  return token.display
    ? `<div class="md-math-display" style="overflow-x:auto;margin:1em 0;padding:.25em 0">${math}</div>\n`
    : math;
}

marked.use({ extensions: [
  {
    name: "blockMath", level: "block",
    tokenizer(source) { return mathToken(source, true); },
    renderer: renderMathToken,
  },
  {
    name: "inlineMath", level: "inline",
    start(source) { return source.search(/\$|\\[([]/); },
    tokenizer(source) { return mathToken(source, false); },
    renderer: renderMathToken,
  },
] });

marked.setOptions({
  breaks: true,
  gfm: true,
});

/** Resolve assets/… URLs for report preview (paths are relative to report folder). */
export function linkReportAssets(source, assetUrlFn) {
  if (!source || !assetUrlFn) return source;
  return source
    .replace(
      /(!?\[[^\]]*\]\()(assets\/[^)\s]+)(\))/gi,
      (_, open, path, close) => `${open}${assetUrlFn(path)}${close}`
    )
    .replace(
      /(src=["'])(assets\/[^"']+)(["'])/gi,
      (_, open, path, close) => `${open}${assetUrlFn(path)}${close}`
    );
}

const VIDEO_EXT_RE = /\.(mp4|webm|mov|m4v)(\?.*)?$/i;

/** Inline media: <img> with video extension and <a> links to videos become <video> players. */
export function embedInlineMedia(html) {
  if (!html?.trim() || typeof document === "undefined") return html;
  const root = document.createElement("div");
  root.innerHTML = html;

  const makeVideo = (src) => {
    const video = document.createElement("video");
    video.className = "md-media md-media--video";
    video.src = src;
    video.controls = true;
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    return video;
  };

  for (const img of root.querySelectorAll("img")) {
    if (VIDEO_EXT_RE.test(img.getAttribute("src") || "")) {
      img.replaceWith(makeVideo(img.getAttribute("src")));
    } else {
      img.classList.add("md-media");
    }
  }

  for (const a of root.querySelectorAll("a")) {
    const href = a.getAttribute("href") || "";
    if (!VIDEO_EXT_RE.test(href)) continue;
    const figure = document.createElement("figure");
    figure.className = "md-media-figure";
    const caption = document.createElement("figcaption");
    caption.className = "md-media-caption";
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = a.textContent || href.split("/").pop();
    caption.appendChild(link);
    figure.append(makeVideo(href), caption);
    a.replaceWith(figure);
  }

  for (const video of root.querySelectorAll("video:not(.md-media)")) {
    video.classList.add("md-media", "md-media--video");
    video.controls = true;
  }

  return root.innerHTML;
}

/**
 * Wrap each top-level section (e.g. ##) in <details> for collapse in preview.
 * Content before the first matching heading stays outside any block.
 */
export function wrapCollapsibleSections(html, headingLevels = [2]) {
  if (!html?.trim() || typeof document === "undefined") return html;
  const levels = new Set(headingLevels);
  const root = document.createElement("div");
  root.innerHTML = html;
  const nodes = [...root.childNodes];
  root.replaceChildren();

  const out = document.createDocumentFragment();
  let lead = document.createDocumentFragment();

  const flushLead = () => {
    if (lead.childNodes.length) {
      out.appendChild(lead);
      lead = document.createDocumentFragment();
    }
  };

  const isSectionHeading = (node) => {
    if (node.nodeType !== Node.ELEMENT_NODE) return 0;
    const m = /^H([1-6])$/i.exec(node.tagName);
    if (!m) return 0;
    const level = Number(m[1]);
    return levels.has(level) ? level : 0;
  };

  let i = 0;
  while (i < nodes.length) {
    const node = nodes[i];
    const level = isSectionHeading(node);
    if (!level) {
      lead.appendChild(node);
      i += 1;
      continue;
    }

    flushLead();

    const details = document.createElement("details");
    details.className = `md-section md-section--h${level}`;
    details.open = true;

    const summary = document.createElement("summary");
    summary.className = "md-section-summary";
    if (node.childNodes.length) {
      for (const child of node.childNodes) {
        summary.appendChild(child.cloneNode(true));
      }
    } else {
      summary.textContent = node.textContent;
    }

    const body = document.createElement("div");
    body.className = "md-section-body";

    i += 1;
    while (i < nodes.length && !isSectionHeading(nodes[i])) {
      body.appendChild(nodes[i]);
      i += 1;
    }

    details.append(summary, body);
    out.appendChild(details);
  }

  flushLead();
  root.appendChild(out);
  return root.innerHTML;
}

/** Task lists and HOW-TODO blockquotes — classes for report preview styling. */
export function enhanceReportPreview(html) {
  if (!html?.trim() || typeof document === "undefined") return html;
  const root = document.createElement("div");
  root.innerHTML = html;

  for (const bq of root.querySelectorAll("blockquote")) {
    const text = bq.textContent?.trim() ?? "";
    if (/^HOW-TODO\b/i.test(text)) {
      bq.classList.add("md-how-todo");
    }
  }

  for (const li of root.querySelectorAll("li")) {
    if (li.querySelector(':scope > input[type="checkbox"]')) {
      li.classList.add("md-task-item");
    }
  }

  return root.innerHTML;
}

export function renderMarkdown(source, options = {}) {
  if (!source?.trim()) {
    return '<p class="md-empty">Пустой отчёт — напишите Markdown слева</p>';
  }
  const md = options.assetUrlFn
    ? linkReportAssets(source, options.assetUrlFn)
    : source;
  let html = marked.parse(md);
  if (options.collapsibleSections !== false) {
    const levels = options.collapsibleHeadingLevels ?? [2];
    html = wrapCollapsibleSections(html, levels);
  }
  if (options.embedInlineMedia !== false) {
    html = embedInlineMedia(html);
  }
  if (options.enhanceReportPreview !== false) {
    html = enhanceReportPreview(html);
  }
  return html;
}
