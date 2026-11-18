let pending;

export function installedAgentStatus(readStatus) {
  if (!pending) pending = check().finally(() => { pending = null; });
  return pending;

  async function check() {
    let status = await readStatus();
    if (status.cli.some(agent => agent.available)) return status;

    const dialog = document.createElement("dialog");
    dialog.className = "cli-install-dialog";
    dialog.setAttribute("aria-labelledby", "cli-install-title");
    dialog.innerHTML = `
      <svg viewBox="0 0 100 80" width="100" height="80" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round">
        <path d="M50 20V10 M10 38v16 M90 38v16"/><circle cx="50" cy="7" r="4"/>
        <rect x="18" y="19" width="64" height="51" rx="14"/>
        <path d="M32 38h5 M63 38h5"/><path data-mouth d="M39 58Q50 44 61 58"/>
      </svg>
      <h2 id="cli-install-title">Установите CLI-агента</h2>
      <p>Для работы нужен хотя бы один CLI-агент: Claude Code, Cursor, Codex или OpenCode.</p>
      <p role="status"></p>
      <button class="btn btn-primary" type="button">Проверить установку</button>`;
    document.body.append(dialog);
    dialog.addEventListener("cancel", event => event.preventDefault());
    const button = dialog.querySelector("button");
    const message = dialog.querySelector('[role="status"]');
    let ready = false;
    dialog.showModal();
    await new Promise(resolve => {
      button.onclick = async () => {
        if (ready) { resolve(); return; }
        button.disabled = true;
        dialog.classList.add("checking");
        message.textContent = "Проверяем установку…";
        try {
          [status] = await Promise.all([readStatus(), new Promise(done => setTimeout(done, 450))]);
          const agents = status.cli.filter(agent => agent.available);
          ready = agents.length > 0;
          message.textContent = ready ? agents.map(agent => agent.label).join(", ") : "CLI всё ещё не установлен.";
          if (ready) {
            dialog.querySelector("h2").textContent = "Агент готов к работе";
            dialog.querySelector("p").hidden = true;
            dialog.querySelector("[data-mouth]").setAttribute("d", "M38 51Q50 67 62 51");
            button.textContent = "Продолжить";
          }
        } catch {
          message.textContent = "Не удалось проверить установку. Попробуйте ещё раз.";
        } finally {
          dialog.classList.remove("checking");
          button.disabled = false;
          button.focus();
        }
      };
    });
    dialog.close();
    dialog.remove();
    return status;
  }
}
