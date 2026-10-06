"""Build offline-ready documentation HTML. Requires Python Markdown."""
from pathlib import Path
import re
import html
import markdown

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / 'features'

def media(match):
    attrs, fallback = match.groups()
    name = re.search(r'data-media="([^"]+)"', attrs).group(1)
    accept = re.search(r'data-accept="([^"]+)"', attrs)
    for ext in (accept.group(1) if accept else 'png,jpg,webp,mp4,webm').split(','):
        path = FEATURES / 'media' / (name + '.' + ext)
        if not path.exists():
            continue
        url = 'media/' + path.name
        title = re.search(r'<strong>(.*?)</strong>', fallback, re.S)
        alt = html.escape(title.group(1) if title else name.replace('-', ' '), quote=True)
        tag = (f'<video controls playsinline src="{url}"></video>' if ext in ['mp4', 'webm']
               else f'<img src="{url}" alt="{alt}" loading="lazy">')
        return '<div class="media-slot" data-filled="true">' + tag + '</div>'
    return '<div class="media-slot">' + fallback + '</div>'

for page in FEATURES.glob('*.html'):
    source = page.read_text()
    match = re.search(r'<article id="features-content"[^>]*data-md="([^"]+)"[^>]*>', source)
    if not match:
        continue
    md = (FEATURES / match.group(1)).read_text()
    md = re.sub(r'^<!--\s*lead:[^>]*-->\s*', '', md)
    body = markdown.markdown(md, extensions=['tables', 'fenced_code', 'sane_lists'])
    body = re.sub(r'<div\s+([^>]*data-media="[^"]+"[^>]*)>(.*?)</div>', media, body, flags=re.S)
    # The outer article closes immediately before the main container.
    end = re.search(r'</article>\s*</main>', source[match.end():])
    assert end, page
    stop = match.end() + end.start()
    opening = match.group(0).replace(' data-rendered="true"', '').replace('>', ' data-rendered="true">')
    source = source[:match.start()] + opening + '\n' + body + '\n      ' + source[stop:]
    source = re.sub(r'\s*<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>', '', source)
    source = source.replace('js/features.js?v=8', 'js/features.js?v=airi-static-1')
    page.write_text(source)
    print(page.name)
