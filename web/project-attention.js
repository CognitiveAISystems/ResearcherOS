/** Session-only attention estimates. Learning stays in shadow mode. */
export class ProjectAttention {
  constructor() {
    this.history = [];
    this.candidate = null;
    this.weights = [0.65, 0.35];
    this.metrics = { samples: 0, baselineMatches: 0, learnedMatches: 0 };
  }

  features(proximity, now) {
    return Object.entries(proximity).map(([id, focus]) => {
      const recent = this.history.reduce((sum, event, index) => sum + (
        event.id === id
          ? Math.pow(0.5, Math.max(0, now - event.time) / 30000) * Math.pow(0.75, index)
          : 0
      ), 0);
      return { id, x: [Math.min(1, recent / 2), focus] };
    });
  }

  rank(rows, weights = [0.65, 0.35]) {
    return rows.map(({ id, x }) => ({ id, score: x[0] * weights[0] + x[1] * weights[1] }))
      .sort((a, b) => b.score - a.score);
  }

  interact(id, proximity, now) {
    // Score before recording the action: the target must not leak into its features.
    const rows = this.features(proximity, now);
    const target = rows.find(row => row.id === id);
    if (target && rows.length > 1) {
      const baseline = this.rank(rows)[0];
      const learned = this.rank(rows, this.weights)[0];
      this.metrics.samples++;
      this.metrics.baselineMatches += Number(baseline.id === id);
      this.metrics.learnedMatches += Number(learned.id === id);
      if (learned.id !== id) {
        const other = rows.find(row => row.id === learned.id);
        this.weights = this.weights.map((weight, i) =>
          Math.max(0.05, weight + 0.05 * (target.x[i] - other.x[i])));
        const total = this.weights.reduce((a, b) => a + b, 0);
        this.weights = this.weights.map(weight => weight / total);
      }
    }
    this.history.unshift({ id, time: now });
    this.history.length = Math.min(this.history.length, 8);
    this.reset();
  }

  reset() { this.candidate = null; }

  choose(currentId, proximity, now) {
    // A clear spatial focus is stronger evidence than previous work elsewhere.
    const spatial = Object.entries(proximity).sort((a, b) => b[1] - a[1]);
    if (spatial[0]?.[1] >= 0.6 && spatial[0][1] - (spatial[1]?.[1] || 0) >= 0.3) {
      this.reset();
      return spatial[0][0];
    }
    const ranked = this.rank(this.features(proximity, now));
    const best = ranked[0];
    const current = ranked.find(row => row.id === currentId);
    if (!best || best.id === currentId || best.score < 0.2 ||
        best.score - (current?.score || 0) < 0.15 ||
        (this.history[0] && now - this.history[0].time < 1500)) {
      this.reset();
      return currentId;
    }
    if (this.candidate?.id !== best.id) this.candidate = { id: best.id, since: now };
    if (now - this.candidate.since < 800) return currentId;
    return best.id;
  }
}

/** Distance to visible node rectangles, not to a potentially offscreen tree root. */
export function projectProximity(nodes, viewport) {
  const result = {};
  if (viewport.width <= 0 || viewport.height <= 0) return result;
  const cx = viewport.left + viewport.width / 2;
  const cy = viewport.top + viewport.height / 2;
  for (const { id, rect } of nodes) {
    if (rect.width <= 0 || rect.height <= 0 || rect.right <= viewport.left ||
        rect.left >= viewport.right || rect.bottom <= viewport.top || rect.top >= viewport.bottom) continue;
    const dx = Math.max(rect.left - cx, 0, cx - rect.right) / (viewport.width / 2);
    const dy = Math.max(rect.top - cy, 0, cy - rect.bottom) / (viewport.height / 2);
    const score = Math.exp(-3 * (dx * dx + dy * dy));
    result[id] = Math.max(result[id] || 0, score);
  }
  return result;
}
