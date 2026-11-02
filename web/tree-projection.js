/** Display legacy relation nodes as edges without migrating research records. */
export function projectTreeNodes(nodes) {
  const result = nodes.map(node => ({ ...node }));
  for (const source of nodes) {
    const node = result.find(item => item.id === source.id);
    if (!['remediation', 'cause_evidence'].includes(source.node_type) || !source.parent_id) continue;
    const children = result.filter(item => item.parent_id === source.id && item.node_type !== 'experiment');
    const edge = {
      edge_type: source.node_type === 'remediation' ? 'hypothesis' : 'evidence',
      edge_label: source.title,
      edge_source: source,
    };
    if (children.length === 1 && children[0].node_type === 'method') {
      Object.assign(children[0], edge, { parent_id: source.parent_id });
      result.splice(result.indexOf(node), 1);
    } else {
      // Empty branches remain accessible and can receive their first method.
      Object.assign(node, edge, {
        node_type: 'program',
        title: source.node_type === 'remediation' ? 'Проверка гипотезы' : 'Проверка проблемы',
        source_node: source,
      });
    }
  }
  const sources = new Map(nodes.map(node => [node.id, node]));
  for (const node of result) {
    let parent = sources.get(node.parent_id);
    const visited = new Set();
    while (parent?.node_type === 'cause' && parent.parent_id && !visited.has(parent.id)) {
      visited.add(parent.id);
      node.parent_id = parent.parent_id;
      parent = sources.get(parent.parent_id);
    }
  }
  return result.filter(node => node.node_type !== 'cause' || !node.parent_id);
}
