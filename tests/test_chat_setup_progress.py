"""Offline browser check: .venv/bin/python tests/test_chat_setup_progress.py."""
import asyncio
import mimetypes
import re
from pathlib import Path

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


async def check(variant="chats"):
    view_root = ROOT / "web" if variant == "chats" else ROOT / "web/variants/light"
    source = (view_root / "app.js").read_text()
    formatter = source[source.index("function formatAgentChatInline("):source.index("/** Drop redundant")]
    output = ROOT / ".run/ui-screenshots/setup-progress"
    if variant != "chats":
        output /= variant
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        async def serve(route):
            from urllib.parse import urlparse
            name = urlparse(route.request.url).path.lstrip("/") or "index.html"
            path = ROOT / "web" / name
            if (view_root / name).is_file():
                path = view_root / name
            if not path.is_file():
                await route.abort()
                return
            content = path.read_bytes()
            if name == "index.html":
                content = re.sub(rb"<script\b[^>]*>.*?</script>", b"", content, flags=re.S)
            await route.fulfill(body=content, content_type=mimetypes.guess_type(name)[0] or "text/javascript")

        await page.route("http://progress.test/**", serve)
        await page.goto("http://progress.test/", wait_until="domcontentloaded")
        await page.add_script_tag(content=formatter)
        stages = ["Предложил черновик постановки — 1", "Уточняю детали и исправляю стиль", "Обновил черновик постановки — 2"]
        transcript = "\n\n".join(f"```setup-progress\n{stage}\n```" for stage in stages)

        async def render(text):
            await page.evaluate("""text => {
                for (const id of ['agent-chat-log', 'report-interview-log']) {
                    const reply = document.createElement('div');
                    reply.className = 'agent-chat-reply';
                    reply.innerHTML = formatAgentChatReply(text);
                    document.getElementById(id).replaceChildren(reply);
                }
            }""", text)

        # An unfinished streamed block is visible before the agent completes its answer.
        await render("```setup-progress\n" + stages[0])
        await expect(page.locator("#agent-chat-log .agent-chat-progress")).to_have_text(stages[0])
        await render(transcript + "\n\n**Готово.** Откройте `отчёт`.")
        for log in ("agent-chat-log", "report-interview-log"):
            await expect(page.locator(f"#{log} .agent-chat-progress")).to_have_text(stages)
            await expect(page.locator(f"#{log} strong")).to_have_text("Готово.")
            await expect(page.locator(f"#{log} code")).to_have_text("отчёт")
            assert "setup-progress" not in await page.locator(f"#{log}").text_content()

        await render('```setup-progress\n<img src=x onerror="window.injected=true">\n```')
        assert await page.locator(".agent-chat-progress img").count() == 0
        assert not await page.evaluate("Boolean(window.injected)")
        await render(transcript + "\n\nПостановка готова к проверке.")

        for width in (1440, 390):
            await page.set_viewport_size({"width": width, "height": 900})
            for theme in ("light", "dark"):
                await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                for surface in ("main", "card"):
                    await page.evaluate("""surface => {
                        document.getElementById('agent-chat-panel').classList.toggle('hidden', surface !== 'main');
                        document.getElementById('card-report-modal').classList.toggle('hidden', surface !== 'card');
                        document.getElementById('report-interview').hidden = false;
                        document.getElementById('card-report-card-title').textContent = 'Постановка эксперимента';
                    }""", surface)
                    panel = page.locator("#agent-chat-panel" if surface == "main" else "#report-interview")
                    await expect(panel).to_be_visible()
                    for stage in await panel.locator(".agent-chat-progress").all():
                        assert await stage.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
                    await panel.screenshot(path=str(output / f"{surface}-{width}-{theme}.png"))
        await browser.close()
    print("PASS: streamed and saved stages, order, text formatting, HTML escaping; both chats, themes and widths")


if __name__ == "__main__":
    asyncio.run(check())
    asyncio.run(check("light"))
