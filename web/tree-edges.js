/** Incoming edge metadata belongs to the child; old trees retain their nodes. */
export const EDGE_LABELS = { direction: "Направление", hypothesis: "Гипотеза", evidence: "Доказательство" };

export function edgeKind(node) {
  if (node.edge_type && node.edge_type !== "direction") return node.edge_type;
  if (node.node_type === "remediation") return "hypothesis";
  if (node.node_type === "cause_evidence") return "evidence";
  return "direction";
}

export function edgeCaption(node) {
  if (edgeKind(node) !== "hypothesis") return "";
  const label = (node.edge_label || "").trim();
  return label || (node.edge_type && node.edge_type !== "direction" ? EDGE_LABELS[node.edge_type] : "");
}

export function edgeLabelHeight(node) {
  const text = edgeCaption(node);
  return text ? Math.max(44, Math.ceil(text.length / 23) * 14 + 28) : 0;
}

export function treeEdgeDefs(prefix) {
  return `<defs>${Object.keys(EDGE_LABELS).map(kind => `<marker id="${prefix}-${kind}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" orient="auto"><path class="tree-arrow-${kind}" d="${kind === 'hypothesis' ? 'M0 0 L10 5 L0 10 Z' : 'M1 1 L9 5 L1 9'}"/></marker>`).join("")}</defs>`;
}

export function appendTreeEdge(group, start, end, node, prefix, onEdit) {
  const ns = "http://www.w3.org/2000/svg";
  const kind = edgeKind(node);
  const path = document.createElementNS(ns, "path");
  const middle = (start.y + end.y) / 2;
  path.setAttribute("d", `M${start.x} ${start.y} C${start.x} ${middle},${end.x} ${middle},${end.x} ${end.y}`);
  path.setAttribute("class", `edge tree-edge tree-edge-${kind}`);
  path.setAttribute("marker-end", `url(#${prefix}-${kind})`);
  group.append(path);
  const caption = edgeCaption(node);
  if (!caption) return;
  const label = document.createElementNS(ns, "foreignObject");
  const height = edgeLabelHeight(node);
  label.setAttribute("x", String(end.x - 90));
  label.setAttribute("y", String(end.y - height - 12));
  label.setAttribute("width", "180");
  label.setAttribute("height", String(height));
  label.classList.add("tree-edge-label");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tree-edge-caption";
  button.setAttribute("aria-label", `${EDGE_LABELS[kind]}: ${caption}`);
  const heading = document.createElement("span");
  heading.className = "tree-edge-kind";
  heading.textContent = EDGE_LABELS[kind];
  const comment = document.createElement("span");
  comment.className = "tree-edge-comment";
  comment.textContent = caption;
  button.append(heading, comment);
  button.addEventListener("pointerdown", event => event.stopPropagation());
  button.addEventListener("click", event => event.stopPropagation());
  button.addEventListener("dblclick", event => {
    event.preventDefault();
    event.stopPropagation();
    onEdit(node, label);
  });
  label.append(button);
  group.append(label);
}
