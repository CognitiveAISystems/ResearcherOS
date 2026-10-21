"""Run: .venv/bin/python tests/test_mindmap_zoom.py (Playwright Chromium)."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        await page.set_content('''<html data-theme="light"><body>
          <div class="mindmap-viewport" id="viewport">
            <div class="mindmap-canvas" id="canvas" style="width:1000px;height:800px">
              <div class="node-wrap" style="left:160px;top:100px">
                <div class="map-node method" style="width:240px">Чёткий текст дерева</div>
                <div class="node-kanban-below"></div>
              </div>
            </div>
          </div></body></html>''')
        await page.add_style_tag(path=str(ROOT / "web/styles.css"))
        for name in ("lab-canvas", "method-activity"):
            source = (ROOT / f"web/{name}.js").read_text().replace("export ", "")
            await page.add_script_tag(content=source)
        await page.evaluate('''() => {
          window.cam = new MindmapCamera(document.querySelector('#viewport'), document.querySelector('#canvas'));
          cam.minScale = .1; cam.maxScale = 6; cam.methodMaxScale = 6;
          document.querySelector('.node-kanban-below').innerHTML = methodActivityHtml(
            {running: [{id:'test', title:'Проверка масштаба'}], bubbles: []}, {id:'method'});
        }''')
        sizes = []
        for scale in (.25, 1, 2, 4):
            result = await page.evaluate('''scale => {
              cam.scale = scale; cam._apply();
              syncMethodActivityZoomMode(cam.viewport, cam);
              const icon = document.querySelector('.method-activity-svg');
              return {overlay: shouldUseActivityOverlay(cam), width: icon.getBoundingClientRect().width,
                visibility: getComputedStyle(icon).visibility,
                willChange: getComputedStyle(cam.canvas).willChange};
            }''', scale)
            assert result["overlay"] == (scale < 1), result
            assert result["willChange"] == "auto", result
            if scale >= 1:
                assert result["visibility"] == "visible", result
                sizes.append(result["width"])
        assert abs(sizes[1] / sizes[0] - 2) < .01, sizes
        assert abs(sizes[2] / sizes[0] - 4) < .01, sizes
        # Zoom around the pointer must preserve the world point beneath it.
        await page.evaluate('''() => {
          const wx = (500-cam.x)/cam.scale, wy = (350-cam.y)/cam.scale;
          cam.zoomAt(500, 350, 2);
          if (Math.abs((500-cam.x)/cam.scale-wx) > 1e-8 ||
              Math.abs((350-cam.y)/cam.scale-wy) > 1e-8) throw Error('zoom anchor moved');
          cam.x=0; cam.y=0; cam.scale=3; cam._apply();
        }''')
        output = ROOT / ".run/ui-screenshots"
        output.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output / "mindmap-zoom.png"))
        await browser.close()
        print("PASS: overview beacon, proportional 1×/2×/4× icon, zoom anchor, rasterization CSS")


if __name__ == "__main__":
    asyncio.run(check())
