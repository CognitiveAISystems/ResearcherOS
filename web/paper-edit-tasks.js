/** Ordinary-file agent tasks, with a durable history and an explicit review step. */
export function createPaperEditPanel({ api, save, onReview }) {
  const panel = document.getElementById("paper-edit-panel");
  const form = document.getElementById("paper-edit-form");
  const status = document.getElementById("paper-edit-status");
  const list = document.getElementById("paper-edit-tasks");
  let project = null, slug = null, generation = 0, timer = null, loading = false, reviewSignature = "";
  const labels = {
    draft: "Копия готова", running: "Агент работает с копией…", waiting: "Ожидает рассмотрения предыдущей правки",
    review: "Правки готовы к проверке", resolved: "Предложение рассмотрено", unchanged: "Изменений нет",
    error: "Не удалось завершить", interrupted: "Запуск прерван", cancelled: "Задача отменена",
  };

  async function refresh() {
    if (!project || loading) return;
    const token = generation, pid = project, paper = slug;
    loading = true;
    try {
      const { tasks } = await api.paperEditTasks(pid, paper);
      if (token !== generation) return;
      list.replaceChildren();
      for (const task of tasks.slice(0, 5)) {
        const item = document.createElement("article");
        item.className = "paper-edit-task";
        const title = document.createElement("strong");
        title.textContent = task.title;
        const state = document.createElement("p");
        state.textContent = task.error || (task.conflict ? "Конфликт с изменениями человека" : labels[task.status]) || task.status;
        item.append(title, state);
        if (task.answer) {
          const answer = document.createElement("p");
          answer.textContent = task.answer;
          item.append(answer);
        }
        if (["draft", "waiting", "error", "interrupted"].includes(task.status)) {
          for (const [action, label] of [["submit", "Проверить сохранённые правки"], ["cancel", "Закрыть задачу"]]) {
            const button = document.createElement("button");
            button.type = "button"; button.className = "btn btn-small"; button.textContent = label;
            button.onclick = async () => {
              if (token !== generation) return;
              button.disabled = true;
              try {
                await api.resolvePaperEdit(pid, paper, task.id, action);
                await refresh();
                if (token === generation) await onReview(pid, paper);
              } catch (err) { if (token === generation) status.textContent = err.message; }
              finally { button.disabled = false; }
            };
            item.append(button);
          }
        }
        list.append(item);
      }
      form.querySelector('button[type="submit"]').disabled = tasks.some(t => ["draft", "running", "waiting", "review"].includes(t.status));
      const nextReview = tasks.filter(t => t.status === "review").map(t => `${t.id}:${Boolean(t.conflict)}`).join(",");
      if (nextReview && nextReview !== reviewSignature) await onReview(pid, paper);
      if (token === generation) reviewSignature = nextReview;
    } catch (err) { if (token === generation) status.textContent = err.message; }
    finally { if (token === generation) loading = false; }
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = document.getElementById("paper-edit-prompt").value.trim();
    const backend = document.getElementById("paper-edit-backend").value || null;
    if (!project || !prompt) return;
    const pid = project, paper = slug, token = generation;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      if (!(await save()) || token !== generation) return;
      await api.startPaperEdit(pid, paper, prompt, backend);
      if (token !== generation) return;
      status.textContent = "Задача отправлена. Готовые правки появятся в редакторе.";
      await refresh();
    } catch (err) { if (token === generation) status.textContent = err.message; }
    finally { if (token === generation) { button.disabled = false; await refresh(); } }
  });

  return {
    refresh,
    open(pid, paper) {
      if (project === pid && slug === paper) return;
      project = pid; slug = paper; generation++; loading = false; reviewSignature = "";
      status.textContent = ""; list.replaceChildren();
      document.getElementById("paper-edit-prompt").value = "";
      if (timer) clearInterval(timer);
      void refresh();
      timer = setInterval(() => {
        if (!panel?.closest(".hidden")) void refresh();
      }, 2500);
    },
  };
}
