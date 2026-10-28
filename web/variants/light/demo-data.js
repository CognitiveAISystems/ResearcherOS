/** Built-in demo project used by the standalone web preview. */
const DEMO = {
  id: "demo-aggregation",
  title: "Нестабильная экспрессия рекомбинантного белка",
  nodes: [
    { id: "n-problem", parent_id: null, node_type: "problem", title: "Низкий выход целевого белка в культуре HEK293", has_kanban: false },
    { id: "n-cause-misfold", parent_id: "n-problem", node_type: "cause", title: "Причина: агрегация из-за неправильного фолдинга", has_kanban: false },
    { id: "n-cause-toxic", parent_id: "n-problem", node_type: "cause", title: "Причина: токсичность для клеток", has_kanban: false },
    { id: "n-ev-viability", parent_id: "n-cause-toxic", node_type: "cause_evidence", title: "Доказательство: viability assay 72 ч", has_kanban: true, board_id: "board-ev-viability" },
    { id: "n-ev-fold", parent_id: "n-cause-misfold", node_type: "cause_evidence", title: "Доказательство: ThT-флуоресценция и TEM инклюзий", has_kanban: true, board_id: "board-ev-fold" },
    { id: "n-rem-chaperone", parent_id: "n-cause-misfold", node_type: "remediation", title: "Устранение: ко-экспрессия шаперонов HSP70/40", has_kanban: true, board_id: "board-rem-chaperone" },
    { id: "n-exp-tht", parent_id: "n-ev-fold", node_type: "experiment", title: "ThT assay на лизатах 24/48/72 ч", has_kanban: false },
  ],
  boards: {
    "board-ev-fold": {
      owner_node_id: "n-ev-fold",
      columns: [
        { id: "backlog", title: "Backlog" },
        { id: "running", title: "Running" },
        { id: "done", title: "Done" },
        { id: "successful", title: "Успешные" },
      ],
      cards: [
        { id: "c1", column_id: "backlog", title: "ThT time-course", description: "Сравнить с контрольным GFP." },
        { id: "c2", column_id: "backlog", title: "TEM инклюзий", description: "n=3 биологических повторности." },
      ],
    },
    "board-ev-viability": {
      owner_node_id: "n-ev-viability",
      columns: [
        { id: "backlog", title: "Backlog" },
        { id: "running", title: "Running" },
        { id: "done", title: "Done" },
        { id: "successful", title: "Успешные" },
      ],
      cards: [
        { id: "c4", column_id: "backlog", title: "MTT / Trypan blue", description: "Сравнить с пустым вектором." },
      ],
    },
    "board-rem-chaperone": {
      owner_node_id: "n-rem-chaperone",
      columns: [
        { id: "backlog", title: "Backlog" },
        { id: "running", title: "Running" },
        { id: "done", title: "Done" },
        { id: "successful", title: "Успешные" },
      ],
      cards: [
        { id: "c3", column_id: "running", title: "Ко-трансфекция HSP70", description: "Дозировка 1:1 и 1:2." },
      ],
    },
  },
};

const TYPE_LABELS = {
  problem: "Проблема",
  cause: "Причина",
  cause_evidence: "Доказательство",
  remediation: "Устранение",
  experiment: "Эксперимент",
};
