"""Shared tooltip coverage across every local application page."""
import asyncio, mimetypes, re
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
async def check():
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={"width":800,"height":600})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        async def serve(route):
            name=urlparse(route.request.url).path.lstrip('/') or 'index.html'
            file=ROOT/'web'/name
            if not file.is_file(): await route.abort();return
            body=file.read_bytes()
            if name.endswith('.html'):
                assert b'src="tooltips.js"' in body
                body=re.sub(rb'<script\b[^>]*>.*?</script>',b'',body,flags=re.S)
            await route.fulfill(body=body,content_type=mimetypes.guess_type(name)[0] or 'text/javascript')
        await page.route('http://tips.test/**',serve)
        await page.route('https://**/*',lambda route:route.abort())
        for name in ('index.html','literature.html','morphology.html','tour.html'):
            await page.goto('http://tips.test/'+name,wait_until='domcontentloaded')
            await page.evaluate("import('./tooltips.js')")
            assert await page.locator('[title]').count()==0
            await page.evaluate("""() => {
              const button=document.createElement('button');button.id='tip-test';button.title='Новый чат';
              button.style.cssText='position:fixed;top:8px;right:8px;width:40px;height:40px;z-index:999999';
              document.body.append(button);
            }""")
            button=page.locator('#tip-test')
            await button.hover()
            tip=page.locator('#researcheros-tooltip:popover-open')
            await tip.wait_for();assert await tip.inner_text()=='Новый чат'
            if name == 'index.html':
                out=ROOT/'.run/ui-screenshots/tooltips';out.mkdir(parents=True,exist_ok=True)
                await tip.screenshot(path=str(out/'tooltip-dark.png'))
                await page.evaluate("document.documentElement.dataset.theme='light'")
                await tip.screenshot(path=str(out/'tooltip-light.png'))
            assert await button.get_attribute('title') is None
            box=await tip.bounding_box();assert box['x']>=0 and box['x']+box['width']<=800
            await page.keyboard.press('Escape');await tip.wait_for(state='hidden')
            await button.focus();await tip.wait_for()
            assert 'researcheros-tooltip' in await button.get_attribute('aria-describedby')
            await page.evaluate("document.getElementById('tip-test').title='Остановить'")
            await page.wait_for_function("document.getElementById('researcheros-tooltip').textContent==='Остановить'")
            await page.evaluate("document.getElementById('tip-test').remove()")
            await tip.wait_for(state='hidden')
            await page.evaluate('''() => {
              const button=document.createElement('button');button.id='text-test';
              button.textContent='Новое дерево';button.title='Создать дерево исследований';
              button.style.cssText='position:fixed;top:100px;right:8px;z-index:999999';
              document.body.append(button);
            }''')
            await page.locator('#text-test').hover()
            await page.wait_for_timeout(400)
            assert await tip.count()==0
            await page.locator('#text-test').focus()
            await page.wait_for_timeout(30)
            assert await tip.count()==0
        assert not errors,errors
        await browser.close()
        print('PASS: shared tooltips on all four pages, dynamic labels, keyboard, Escape and viewport edges')
if __name__=='__main__':asyncio.run(check())
