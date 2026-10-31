"""Quick navigation through the real API with isolated research and chat data."""
import os
from pathlib import Path

from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    from koi.adapters import agent_chat_queue as queue, project_mount
    from koi.agent_chat import conversations as chats

    third = Path(os.environ['KOI_WORKSPACE']) / 'third/koi-structure'
    third.mkdir(parents=True)
    (third / 'project.md').write_text('---\nid: third\ntitle: Пустое дерево\nprograms:\n- id: language\n  title: SLM\n---\n\n# problem: third-root\n\nНовое исследование\n')
    (third / 'research.json').write_text('{"version":1,"questions":[]}')
    project_mount.rescan_projects()
    for index in range(10):
        chats.create('demo', title=f'Предыдущее обсуждение {index + 1}', program_id='agents')
    first = chats.create('demo', title='Результаты эксперимента', program_id='agents')
    other = chats.create('comparison', title='Обсуждение другого дерева', program_id='agents')
    general = chats.create(None, title='Общий разговор программы', program_id='agents')
    general_answer = queue.enqueue_question(None, 'Какие планы?', conversation_id=general['id'])
    queue.submit_answer(general_answer['id'], 'Обсудим планы по всем исследованиям.')
    answer = queue.enqueue_question('demo', 'Что получилось?', conversation_id=first['id'])
    queue.submit_answer(answer['id'], 'Эксперимент завершён. Новый результат.')
    work = queue.enqueue_question('comparison', 'Продолжи проверку', conversation_id=other['id'])
    queue.mark_processing(work['id'])
    screenshots = Path(__file__).resolve().parents[1] / '.run/ui-screenshots/quick-navigation'
    screenshots.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 900})
        page.set_default_timeout(12000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('https://**/*', lambda route: route.abort())
        await page.goto(url + '?desktop=1&project=demo', wait_until='networkidle')
        await page.locator('#btn-app-variant').click()
        await page.evaluate("localStorage.setItem('koi-theme', 'dark')")
        await page.locator('input[value=quick]').check()
        await page.locator('#app-variant-dialog button[type=submit]').click()
        await page.wait_for_function("document.documentElement.dataset.appVariant === 'quick'")
        assert await page.locator('html').get_attribute('data-theme') == 'light'
        await page.locator('#btn-app-variant').click()
        await page.locator('[data-manage-trees]').click()
        assert await page.locator('.workspace').evaluate("el => el.classList.contains('is-managing-trees')")
        dots = page.locator('.research-quick-tree')
        demo = page.locator('.research-quick-tree[data-tree-id=demo]')
        comparison = page.locator('.research-quick-tree[data-tree-id=comparison]')
        empty = page.locator('.research-quick-tree[data-tree-id=third]')
        general_button = page.locator('.research-quick-tree[data-program-id=global]')
        add_chat = page.locator('[data-research-add-chat]')
        await demo.wait_for()
        await demo.click()
        assert await dots.count() == 4
        assert await general_button.count() == 1
        assert await page.locator('.research-quick-group h3').first.inner_text() == 'General'
        heading = page.locator('.research-chat-heading h2')
        original_heading = await heading.inner_text()
        await page.evaluate("document.fonts.load('500 18px Inter', 'Принятие решений')")
        assert await heading.evaluate("el => getComputedStyle(el).fontFamily.startsWith('Inter')")
        assert await page.evaluate("document.fonts.check('500 18px Inter', 'Принятие решений')")
        assert await heading.evaluate("el => getComputedStyle(el).fontWeight") == '500'

        short_height = (await heading.bounding_box())['height']
        await heading.evaluate("el => el.textContent = 'Принятие решений в средах с неизвестной механикой'")
        assert await heading.evaluate('el => el.scrollHeight <= el.clientHeight')
        assert (await heading.bounding_box())['height'] > short_height
        await page.screenshot(path=str(screenshots / 'header-long-title.png'), animations='disabled')
        await heading.evaluate('(el, label) => el.textContent = label', original_heading)
        assert await page.locator('.research-chat-search').count() == 0
        assert await page.locator('.research-quick-legend').count() == 0
        assert await page.locator('.research-program').count() == 0
        assert await page.locator('.research-quick-utility').count() == 0
        assert not await page.locator('#btn-theme').is_visible()
        assert not await page.locator('.research-manage').is_visible()
        assert await page.locator('.conversation-rail [data-research-create]').is_visible()
        assert not await page.locator('[data-research-collapse]').is_visible()
        panel_toggle = page.locator('.conversation-rail #btn-agent-chat')
        assert await panel_toggle.is_visible()
        resize = page.locator('#agent-chat-panel .main-chat-resize')
        assert await resize.is_visible()
        assert await resize.evaluate("el => getComputedStyle(el, '::before').display") == 'none'
        assert await page.locator('#agent-chat-panel').evaluate("el => getComputedStyle(el).borderInlineEndColor === 'rgba(0, 0, 0, 0)' && getComputedStyle(el).boxShadow === 'none'")
        await page.mouse.move(1000, 50)
        assert await resize.evaluate("el => getComputedStyle(el, '::after').opacity") == '0'
        await resize.hover()
        assert await resize.evaluate("el => getComputedStyle(el, '::after').opacity") == '1'
        await page.mouse.move(1000, 50)
        panel = page.locator('#agent-chat-panel')
        width_before = (await panel.bounding_box())['width']
        grip = await resize.bounding_box()
        await page.mouse.move(grip['x'] + grip['width'] / 2, grip['y'] + grip['height'] / 2)
        await page.mouse.down()
        await page.mouse.move(grip['x'] + grip['width'] / 2 + 80, grip['y'] + grip['height'] / 2)
        await page.mouse.up()
        assert (await panel.bounding_box())['width'] >= width_before + 70
        await resize.dblclick()

        assert await page.locator('.research-quick-tree-list').count() == 3
        assert await page.locator('.research-chat-meta').first.inner_text() == 'Эксперимент завершён. Новый результат.'
        assert await page.locator('.research-chat-unread').first.inner_text() == '1'
        assert await page.locator('[data-research-add-chat]').is_visible()
        # Expanding and scrolling a long list must not move its creation action off screen.
        add_before = await add_chat.bounding_box()
        assert add_before['y'] >= (await page.locator('.research-chat-heading').bounding_box())['y']
        more = page.locator('.research-chat-show-all')
        more_before = await more.bounding_box()
        await page.locator('.research-chat-show-all').click()
        entries = page.locator('.research-chat-entries')
        assert await more.get_attribute('aria-expanded') == 'true'
        assert (await more.bounding_box())['y'] == more_before['y']
        assert await more.evaluate("el => [...el.parentElement.children].slice(0, 3).every(row => row.classList.contains('conversation-entry-row')) && el.nextElementSibling.classList.contains('conversation-entry-row')")
        await more.focus()
        await page.keyboard.press('Enter')
        assert await entries.locator('[data-conversation]').count() == 3
        assert await more.get_attribute('aria-expanded') == 'false'
        assert await more.evaluate('el => el === document.activeElement')
        await page.keyboard.press('Enter')
        await entries.evaluate('el => el.scrollTop = el.scrollHeight')
        assert await entries.evaluate('el => el.scrollTop > 0')
        assert await add_chat.bounding_box() == add_before
        history_bounds = await entries.bounding_box()
        assert history_bounds['y'] + history_bounds['height'] <= add_before['y'], 'Expanded history must stop above the footer action'
        last_chat_bounds = await entries.locator('.conversation-entry-row').last.bounding_box()
        assert last_chat_bounds['y'] + last_chat_bounds['height'] <= add_before['y'], 'The last chat must remain readable above the footer'
        assert await add_chat.evaluate('el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }')
        await page.screenshot(path=str(screenshots / 'expanded-list.png'), animations='disabled')
        await page.locator('.research-chat-show-all').click()
        await entries.evaluate('el => el.scrollTop = 0')
        # Menu actions do not select/read a chat; hover must not reflow its title or time.
        first_entry = page.locator(f'.research-chat-entries [data-conversation="{first["id"]}"]')
        first_menu = first_entry
        await page.mouse.move(800, 80)
        title_before = await first_entry.locator('.research-chat-title-line').bounding_box()
        await first_entry.hover()
        assert await first_entry.locator('.research-chat-title-line').bounding_box() == title_before
        await first_entry.click(button='right')
        actions = page.locator('.conversation-actions-popover:popover-open')
        await actions.wait_for()
        assert await actions.get_by_role('button').count() == 1
        assert await actions.get_by_text('мигание', exact=False).count() == 0
        assert await first_menu.get_attribute('aria-expanded') == 'true'
        assert await first_menu.evaluate("el => getComputedStyle(el).backgroundColor") == 'rgba(0, 0, 0, 0)'
        assert chats.find(first['id'])['unread']
        await page.screenshot(path=str(screenshots / 'chat-menu.png'), animations='disabled')
        row_colors = await first_entry.evaluate('''el => ({
            background: getComputedStyle(el.parentElement).backgroundColor,
            title: getComputedStyle(el.querySelector('.conversation-entry-title')).color,
            preview: getComputedStyle(el.querySelector('.research-chat-meta')).color,
            trigger: getComputedStyle(el).color
        })''')
        await actions.get_by_role('button', name='Удалить чат').hover()
        # Measure computed foreground/background pairs (including color-mix) in the browser.
        contrast = await actions.get_by_role('button', name='Удалить чат').evaluate('''(el, rowColors) => {
            const style = getComputedStyle(el), canvas = document.createElement('canvas');
            canvas.width = canvas.height = 1;
            const ctx = canvas.getContext('2d');
            const rgb = color => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3); };
            const luminance = color => rgb(color).map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [.2126, .7152, .0722][i], 0);
            const ratio = (foreground, background) => { const a = luminance(foreground), b = luminance(background); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); };
            return {foreground: style.color, background: style.backgroundColor, ratio: ratio(style.color, style.backgroundColor),
                title_ratio: ratio(rowColors.title, rowColors.background),
                preview_ratio: ratio(rowColors.preview, rowColors.background),
                trigger_ratio: ratio(rowColors.trigger, rowColors.background)};
        }''', row_colors)
        assert contrast['ratio'] >= 4.5, contrast
        assert contrast['title_ratio'] >= 4.5 and contrast['preview_ratio'] >= 4.5 and contrast['trigger_ratio'] >= 3, contrast
        print('Delete action contrast:', contrast)
        await page.screenshot(path=str(screenshots / 'chat-menu-hover.png'), animations='disabled')
        await page.keyboard.press('Escape')
        assert await first_menu.evaluate('el => el === document.activeElement')
        await page.keyboard.press('Shift+F10')
        await actions.wait_for()
        await page.wait_for_function("document.activeElement.matches('.conversation-actions-popover')")
        await page.keyboard.press('Tab')
        assert await actions.get_by_role('button', name='Удалить чат').evaluate('el => el === document.activeElement')
        await page.keyboard.press('Enter')
        await page.locator('.conversation-delete-dialog[open]').wait_for()
        await page.locator('.conversation-delete-dialog [data-dismiss]').click()
        assert chats.find(first['id']) is not None
        # The rail reuses the real project creation flow, with its existing fields.
        await page.locator('.conversation-rail #btn-new-project').click()
        await page.locator('#create-project-modal:not(.hidden)').wait_for()
        assert await page.locator('#create-project-description').is_visible()
        assert await page.locator('#create-project-tag').is_visible()
        await page.locator('#create-project-modal > .modal-panel > .modal-close').click()
        # One stable rail control collapses and reopens the panel from the keyboard.
        selected_dot = demo.locator('.research-quick-dot')
        selected_fill = await selected_dot.evaluate('el => getComputedStyle(el).backgroundImage')
        assert selected_fill.count('linear-gradient') == 2
        other_dot = comparison.locator('.research-quick-dot')
        assert 'linear-gradient' in await other_dot.evaluate('el => getComputedStyle(el).backgroundImage')
        shared_gradient = await other_dot.evaluate("""el => {
            const style = getComputedStyle(el);
            const list = el.closest('.research-quick-tree-list');
            const edge = getComputedStyle(list, '::before');
            return {
                sameImage: style.backgroundImage === edge.backgroundImage,
                sameSize: style.backgroundSize === edge.backgroundSize,
                nodeOrigin: el.getBoundingClientRect().top + parseFloat(style.backgroundPositionY),
                edgeOrigin: list.getBoundingClientRect().top + 22 + parseFloat(edge.backgroundPositionY),
            };
        }""")
        assert shared_gradient['sameImage'] and shared_gradient['sameSize']
        assert abs(shared_gradient['nodeOrigin'] - shared_gradient['edgeOrigin']) < 1

        assert await first_entry.evaluate('el => el.getBoundingClientRect().height') >= 92
        toggle_before = await panel_toggle.bounding_box()
        await panel_toggle.focus()
        await page.keyboard.press('Enter')
        assert not await page.locator('.research-chat-search input').is_visible()
        assert await panel_toggle.get_attribute('aria-expanded') == 'false'
        assert await selected_dot.evaluate('el => getComputedStyle(el).backgroundImage') == selected_fill
        assert await other_dot.evaluate('el => getComputedStyle(el).backgroundImage') == 'none'
        assert await panel_toggle.bounding_box() == toggle_before
        assert await panel_toggle.evaluate('el => el === document.activeElement')
        await page.keyboard.press('Enter')
        assert await panel_toggle.get_attribute('aria-expanded') == 'true'
        assert await selected_dot.evaluate('el => getComputedStyle(el).backgroundImage') == selected_fill
        assert 'linear-gradient' in await other_dot.evaluate('el => getComputedStyle(el).backgroundImage')
        assert await panel_toggle.bounding_box() == toggle_before
        # General lists unassigned chats, creates them without a tree and is searchable everywhere.
        await general_button.click()
        assert await page.locator('.research-chat-heading h2').inner_text() == 'Общие чаты'
        assert await general_button.get_attribute('aria-pressed') == 'true'
        assert 'has-unread' in await general_button.get_attribute('class')
        assert chats.find(general['id'])['unread'], 'Opening General must not read its chats'
        assert await page.locator(f'.research-chat-entries [data-conversation="{general["id"]}"]').is_visible()
        assert await page.locator(f'.research-chat-entries [data-conversation="{first["id"]}"]').count() == 0
        await page.screenshot(path=str(screenshots / 'general.png'), animations='disabled')
        async with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/agent-conversations')) as general_created:
            await page.locator('[data-research-add-chat]').click()
        general_row = (await (await general_created.value).json())['item']
        assert general_row['project_id'] is None and general_row.get('program_id') is None
        await general_button.click()
        await page.locator(f'.research-chat-entries [data-conversation="{general["id"]}"]').click()
        await page.wait_for_function("document.querySelector('.research-quick-tree[data-program-id=global]').getAttribute('aria-pressed') === 'true'")
        await page.wait_for_function("!document.querySelector('.research-quick-tree[data-program-id=global]').classList.contains('has-unread')")
        assert not chats.find(general['id'])['unread']
        await general_button.click()
        order = await dots.evaluate_all('els => els.map(el => el.dataset.treeId)')
        await demo.click()
        await page.wait_for_function("document.querySelector('.research-quick-tree[data-tree-id=demo]').getAttribute('aria-pressed') === 'true'")
        assert await page.locator('.research-chat-section').count() == 1
        assert await page.locator('.research-chat-section').get_attribute('data-section-id') == 'demo'
        assert await page.locator('.research-chat-entries').get_by_text('Общий разговор программы').count() == 0
        assert 'has-unread' in await demo.get_attribute('class')
        assert 'has-activity' not in await comparison.get_attribute('class')
        assert chats.find(first['id'])['unread'], 'Opening the tree list must not read its chats'
        await demo.evaluate('el => window.originalQuickDot = el')
        await demo.focus()
        await page.locator('#researcheros-tooltip:popover-open').wait_for()
        assert 'Результаты' not in await page.locator('#researcheros-tooltip').inner_text()
        assert 'Текущее' in await page.locator('#researcheros-tooltip').inner_text()
        assert (await page.locator('#researcheros-tooltip').bounding_box())['x'] >= (await demo.bounding_box())['x'] + 44
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(2200)
        assert await demo.evaluate('el => el === window.originalQuickDot'), 'Polling must preserve focus and dot identity'
        assert await dots.evaluate_all('els => els.map(el => el.dataset.treeId)') == order
        assert await comparison.locator('.research-quick-dot').evaluate('el => getComputedStyle(el).animationName') == 'none'
        assert await demo.locator('.research-quick-dot').evaluate('el => getComputedStyle(el).animationName') == 'none'
        await page.emulate_media(reduced_motion='reduce')
        assert await comparison.locator('.research-quick-dot').evaluate('el => getComputedStyle(el).animationName') == 'none'
        assert await demo.locator('.research-quick-dot').evaluate('el => getComputedStyle(el).borderRadius') == '5px'
        await page.emulate_media(reduced_motion='no-preference')
        for theme in ('light',):
            await page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
            await page.screenshot(path=str(screenshots / f'{theme}.png'), animations='disabled')
        await comparison.focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.querySelector('.research-chat-section').dataset.sectionId === 'comparison'")
        assert await comparison.get_attribute('aria-pressed') == 'true'
        assert await page.locator(f'.research-chat-entries [data-conversation="{first["id"]}"]').count() == 0
        assert chats.find(first['id'])['unread']
        await page.locator(f'.research-chat-entries [data-conversation="{other["id"]}"]').click(button="right")
        assert await actions.get_by_role('button', name='Удалить чат').is_disabled()
        assert await actions.get_by_text('Пока агент отвечает, чат нельзя удалить.').is_visible()
        await page.screenshot(path=str(screenshots / 'chat-menu-pending.png'), animations='disabled')
        await page.keyboard.press('Escape')
        # Open a chat, preserve its draft when selecting another tree, return explicitly.
        await page.locator(f'.research-chat-entries [data-conversation="{other["id"]}"]').click()
        await page.locator('#agent-chat-input').fill('Неотправленный черновик')
        await demo.click()
        assert await page.locator('#agent-chat-conversations').is_visible()
        await comparison.click()
        await page.locator(f'.research-chat-entries [data-conversation="{other["id"]}"]').click()
        assert await page.locator('#agent-chat-input').input_value() == 'Неотправленный черновик'
        await empty.click()
        assert await page.locator('.research-chat-section').get_attribute('data-section-id') == 'third'
        assert await page.locator('.research-chat-entries').get_by_text('Пока нет чатов').is_visible()
        await page.screenshot(path=str(screenshots / 'empty-tree.png'), animations='disabled')
        async with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/agent-conversations')) as created:
            await page.locator('[data-research-add-chat]').focus()
            await page.keyboard.press('Enter')
        row = (await (await created.value).json())['item']
        assert row['project_id'] == 'third' and row['program_id'] == 'language'
        assert await page.locator('#agent-chat-input').is_visible()
        assert await page.locator('#agent-chat-form [data-cli-agent]').is_visible()
        await page.screenshot(path=str(screenshots / 'composer.png'), animations='disabled')
        await demo.click()
        # Read status clears only after the answer itself has been opened.
        await page.locator(f'.research-chat-entries [data-conversation="{first["id"]}"]').click()
        await page.wait_for_function("!document.querySelector('.research-quick-tree[data-tree-id=demo]').classList.contains('has-unread')")
        assert not chats.find(first['id'])['unread']
        await demo.click()
        await page.locator('#agent-chat-panel .conversation-content').wait_for(state='hidden')
        await page.mouse.move(800, 80)
        assert await first_entry.get_attribute('aria-pressed') == 'true'
        assert await first_entry.evaluate('el => getComputedStyle(el.parentElement).backgroundColor') == 'rgba(0, 0, 0, 0)'
        await first_entry.hover()
        hover_color = await first_entry.evaluate('el => getComputedStyle(el.parentElement).backgroundColor')
        assert hover_color == 'rgb(249, 248, 253)', 'Match the user-provided hover reference'
        assert await first_entry.evaluate('el => getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
        await page.screenshot(path=str(screenshots / 'chat-hover-selected.png'), animations='disabled')
        unselected_entry = page.locator('.research-chat-entries .conversation-entry[aria-pressed="false"]').first
        await unselected_entry.hover()
        assert await unselected_entry.evaluate('el => getComputedStyle(el.parentElement).backgroundColor') == hover_color
        assert await unselected_entry.evaluate('el => getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
        assert await first_entry.evaluate('el => getComputedStyle(el.parentElement).backgroundColor') == 'rgba(0, 0, 0, 0)'
        await page.screenshot(path=str(screenshots / 'chat-hover-unselected.png'), animations='disabled')
        await first_entry.hover()
        await first_entry.click(button='right')
        await page.mouse.move(800, 80)
        assert await first_entry.evaluate('el => getComputedStyle(el.parentElement).backgroundColor') == 'rgba(0, 0, 0, 0)'
        await page.screenshot(path=str(screenshots / 'chat-menu-selected.png'), animations='disabled')
        await page.keyboard.press('Escape')
        for width in (320, 900, 1440):
            await page.set_viewport_size({'width': width, 'height': 900})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert await page.locator('.research-quick-create-tree').evaluate('el => { const r = el.getBoundingClientRect(); return r.bottom <= innerHeight && el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }'), 'Create-tree action must not be covered by the notification bell'
            assert await dots.evaluate_all('els => els.every(el => { const r = el.getBoundingClientRect(); return r.width >= 44 && r.height >= 44; })')
            await page.wait_for_function("() => { const r = document.querySelector('[data-research-add-chat]').getBoundingClientRect(); return r.width >= 44 && r.height >= 44 && r.top >= 0 && r.bottom <= innerHeight; }")
            assert await add_chat.evaluate('el => el.previousElementSibling.getBoundingClientRect().bottom <= el.getBoundingClientRect().top'), 'History and footer must not overlap'
            await page.screenshot(path=str(screenshots / f'width-{width}.png'), animations='disabled')
        # Keep the toolbar usable with 200% CSS zoom, RTL and a much longer translated label.
        await page.evaluate("document.documentElement.style.zoom = '2'")
        assert await add_chat.evaluate('el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; }')
        grip = await resize.bounding_box()
        width_before = (await panel.bounding_box())['width']
        await page.mouse.move(grip['x'] + grip['width'] / 2, grip['y'] + 100)
        await page.mouse.down()
        await page.mouse.move(grip['x'] + grip['width'] / 2 + 40, grip['y'] + 100)
        await page.mouse.up()
        assert abs((await panel.bounding_box())['width'] - width_before - 40) <= 3
        await resize.dblclick()
        await page.screenshot(path=str(screenshots / 'zoom-200.png'), animations='disabled')
        await page.evaluate("document.documentElement.style.zoom = ''; document.documentElement.dir = 'rtl'")
        assert await add_chat.locator('svg').evaluate('el => el.getBoundingClientRect().x > el.nextElementSibling.getBoundingClientRect().x')
        await page.screenshot(path=str(screenshots / 'rtl.png'), animations='disabled')
        await page.evaluate("document.documentElement.dir = 'ltr'")
        await page.set_viewport_size({'width': 320, 'height': 900})
        await add_chat.locator('span').evaluate("el => el.textContent = 'Neuen Chat in diesem Forschungsbaum beginnen'")
        assert await add_chat.evaluate('el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().bottom <= innerHeight')
        await page.screenshot(path=str(screenshots / 'long-label.png'), animations='disabled')
        await add_chat.locator('span').evaluate("el => el.textContent = 'Новый чат'")
        await page.set_viewport_size({'width': 1440, 'height': 900})
        await page.emulate_media(reduced_motion='reduce')
        assert await add_chat.evaluate("el => !getComputedStyle(el).transitionProperty.includes('scale')")
        await page.emulate_media(reduced_motion='no-preference')
        # Expanded tree history must not expand the board/card histories or leak other scopes.
        board_chats = [chats.create('demo', board_id='board', title=f'Метод: обсуждение {i}') for i in range(5)]
        card_chats = [chats.create('demo', board_id='board', card_id='card', title=f'Карточка: обсуждение {i}') for i in range(5)]
        sibling = chats.create('demo', board_id='board', title='Еще одно обсуждение метода')
        unrelated = chats.create('demo', title='Обсуждение всего дерева')
        await page.wait_for_function("id => !!document.querySelector('[data-conversation=\"' + id + '\"]')", arg=unrelated['id'])
        await more.click()
        assert await entries.locator('[data-conversation]').count() > 3
        await page.locator('.map-node.method').click()
        await page.wait_for_function("document.querySelectorAll('.research-chat-entries [data-conversation]').length === 3")
        expected_board = {row['id'] for row in board_chats + card_chats + [sibling]}
        assert set(await entries.locator('[data-conversation]').evaluate_all('els => els.map(el => el.dataset.conversation)')) <= expected_board
        assert await more.get_attribute('aria-expanded') == 'false'
        await more.click()
        assert set(await entries.locator('[data-conversation]').evaluate_all('els => els.map(el => el.dataset.conversation)')) == expected_board
        await page.screenshot(path=str(screenshots / 'kanban-history.png'), animations='disabled')
        await page.locator('#kanban-board [data-card-id=card] .card-expand-report').focus()
        await page.keyboard.press('Enter')
        await page.locator('#card-report-modal:not(.hidden)').wait_for()
        await page.wait_for_function("() => document.querySelectorAll('.research-chat-entries [data-conversation]').length === 3")
        expected_card = {row['id'] for row in card_chats}
        assert set(await entries.locator('[data-conversation]').evaluate_all('els => els.map(el => el.dataset.conversation)')) <= expected_card
        assert await more.get_attribute('aria-expanded') == 'false'
        await more.click()
        assert set(await entries.locator('[data-conversation]').evaluate_all('els => els.map(el => el.dataset.conversation)')) == expected_card
        await more.click()
        assert await entries.locator('[data-conversation]').count() == 3
        await page.screenshot(path=str(screenshots / 'card-history.png'), animations='disabled')
        assert not await comparison.is_disabled() and not await empty.is_disabled()
        assert not await general_button.is_disabled()
        assert not await demo.is_disabled()
        assert await page.locator('.conversation-rail #btn-new-project').is_disabled()
        await comparison.click()
        assert not await page.locator('#card-report-modal').is_visible()
        assert not await page.locator('#kanban-modal').is_visible()
        assert await comparison.get_attribute('aria-pressed') == 'true'
        await demo.click()
        await page.locator('.map-node.method').click()
        await page.locator('#kanban-modal:not(.hidden)').wait_for()
        await demo.click()
        assert not await page.locator('#kanban-modal').is_visible()
        assert await demo.get_attribute('aria-pressed') == 'true'
        # General must also exit both board and card context.
        for from_card in (False, True):
            await demo.click()
            await page.locator('.map-node.method').click()
            await page.locator('#kanban-modal:not(.hidden)').wait_for()
            if from_card:
                await page.locator('#kanban-board [data-card-id=card] .card-expand-report').focus()
                await page.keyboard.press('Enter')
                await page.locator('#card-report-modal:not(.hidden)').wait_for()
            await general_button.click()
            assert not await page.locator('#card-report-modal').is_visible()
            assert not await page.locator('#kanban-modal').is_visible()
            assert await general_button.get_attribute('aria-pressed') == 'true'
            assert await heading.inner_text() == 'Общие чаты'
        # Re-selecting the current tree restores its fitted zoom in every view mode.
        for mode in ('chief', 'teamlead', 'researcher'):
            await page.locator(f'button[data-view-mode={mode}]').click()
            await demo.click()
            await page.wait_for_timeout(450)
            fitted = await page.locator('#mindmap-canvas').evaluate('el => new DOMMatrix(getComputedStyle(el).transform).a')
            await page.locator('#mindmap-viewport').evaluate("el => el.dispatchEvent(new WheelEvent('wheel', {deltaY: 100, clientX: 900, clientY: 400, bubbles: true, cancelable: true}))")
            zoomed_out = await page.locator('#mindmap-canvas').evaluate('el => new DOMMatrix(getComputedStyle(el).transform).a')
            assert zoomed_out < fitted
            await demo.click()
            await page.wait_for_function("scale => Math.abs(new DOMMatrix(getComputedStyle(document.getElementById('mindmap-canvas')).transform).a - scale) < 0.001", arg=fitted)
        await page.screenshot(path=str(screenshots / 'header-tree-zoom.png'), animations='disabled')
        await page.evaluate("document.documentElement.dataset.theme = 'dark'")
        await page.screenshot(path=str(screenshots / 'header-dark.png'), animations='disabled')
        await page.evaluate("document.documentElement.dataset.theme = 'light'")
        # The option persists on the server, including for a fresh browser context.
        second = await browser.new_context()
        fresh = await second.new_page()
        await fresh.route('https://**/*', lambda route: route.abort())
        await fresh.goto(url + '?desktop=1', wait_until='networkidle')
        assert await fresh.locator('html').get_attribute('data-app-variant') == 'quick'
        await second.close()
        await page.locator('#btn-app-variant').click()
        await page.locator('input[value=chats]').check()
        await page.locator('#app-variant-dialog button[type=submit]').click()
        await page.wait_for_function("document.documentElement.dataset.appVariant === 'chats'")
        await page.locator('.research-program').first.wait_for()
        assert await dots.count() == 0
        assert not errors, errors
        await browser.close()
    print('PASS: General and tree selection/creation, search removed, tree navigation closes card/kanban, unread/work states, keyboard, stable dots, drafts, card context, responsive themes, persistence and opt-out')


if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
