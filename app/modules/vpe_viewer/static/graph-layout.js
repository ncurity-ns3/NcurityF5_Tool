(function (root) {
  function nodeSize(kind) {
    if (kind === "start" || kind === "entry") return { w: 72, h: 30 };
    if (kind.startsWith("ending") || kind === "terminal") return { w: 128, h: 30 };
    return { w: 148, h: 40 };
  }

  function pruneGraph(graph) {
    const incoming = new Set((graph.edges || []).map((e) => e.to));
    const start = graph.start_item;
    const nodes = (graph.nodes || []).filter((n) => {
      if (n.id === start || n.kind === "start" || n.kind === "entry") return true;
      if (n.kind === "terminal" && !incoming.has(n.id)) return false;
      return true;
    });
    const keep = new Set(nodes.map((n) => n.id));
    const edges = (graph.edges || []).filter((e) => keep.has(e.from) && keep.has(e.to));
    return { ...graph, nodes, edges };
  }

  function isExceptEdge(e) {
    return /^except$/i.test(e.caption || "");
  }

  function isEarlyExitTerminal(node, incoming, outgoing) {
    if (node.kind !== "terminal") return false;
    const ins = incoming[node.id] || [];
    if (ins.length !== 1) return false;
    const src = ins[0];
    if (!isExceptEdge(src) && !/^except$/i.test(node.caption || "")) return false;
    return (outgoing[src.from] || []).some((e) => e.to !== node.id);
  }

  function edgeKey(e) {
    return `${e.from}\0${e.to}\0${e.caption || ""}`;
  }

  function boxesOverlap(a, b, pad) {
    const g = pad || 8;
    const ax1 = a.x - a.width / 2;
    const ay1 = a.y - a.height / 2;
    const ax2 = a.x + a.width / 2;
    const ay2 = a.y + a.height / 2;
    const bx1 = b.x - b.width / 2;
    const by1 = b.y - b.height / 2;
    const bx2 = b.x + b.width / 2;
    const by2 = b.y + b.height / 2;
    return ax1 < bx2 - g && bx1 < ax2 - g && ay1 < by2 - g && by1 < ay2 - g;
  }

  function layoutGraph(rawGraph) {
    const graph = pruneGraph(rawGraph);
    const nodeMap = Object.fromEntries(graph.nodes.map((n) => [n.id, { ...n, ...nodeSize(n.kind) }]));
    const outgoing = {};
    const incoming = {};
    (graph.edges || []).forEach((e) => {
      if (!nodeMap[e.from] || !nodeMap[e.to]) return;
      (outgoing[e.from] ||= []).push(e);
      (incoming[e.to] ||= []).push(e);
    });
    const rank = {};
    const start = graph.start_item && nodeMap[graph.start_item] ? graph.start_item : graph.nodes[0]?.id;
    if (start) rank[start] = 0;
    const limit = graph.nodes.length + 2;
    for (let i = 0; i < limit; i += 1) {
      let changed = false;
      (graph.edges || []).forEach((e) => {
        if (rank[e.from] == null) return;
        const nextRank = rank[e.from] + 1;
        if (rank[e.to] == null || nextRank > rank[e.to]) {
          rank[e.to] = nextRank;
          changed = true;
        }
      });
      if (!changed) break;
    }
    graph.nodes.forEach((n) => {
      if (rank[n.id] == null) rank[n.id] = 0;
    });
    const naturalMax = Math.max(0, ...Object.values(rank));
    graph.nodes.forEach((n) => {
      if (n.kind.startsWith("ending")) rank[n.id] = naturalMax;
      else if (n.kind === "terminal" && !isEarlyExitTerminal(n, incoming, outgoing)) rank[n.id] = naturalMax;
    });

    const incomingTrack = {};
    const edgeTrack = {};
    const widthMemo = {};
    const visiting = {};

    function restEdges(id) {
      return (outgoing[id] || []).filter((e) => !isExceptEdge(e));
    }
    function exceptEdges(id) {
      return (outgoing[id] || []).filter(isExceptEdge);
    }
    function subtreeWidth(id) {
      if (widthMemo[id] != null) return widthMemo[id];
      if (visiting[id]) return 1;
      visiting[id] = true;
      const rest = restEdges(id);
      let width = 0;
      rest.forEach((e) => {
        width += subtreeWidth(e.to);
      });
      visiting[id] = false;
      widthMemo[id] = Math.max(1, width || 1);
      return widthMemo[id];
    }

    const placed = new Set();
    function assignTracks(id, t0) {
      if (incomingTrack[id] == null) incomingTrack[id] = t0;
      if (placed.has(id)) return;
      placed.add(id);
      exceptEdges(id).forEach((e) => {
        const w = subtreeWidth(e.to);
        const t = nextAbove - (w - 1);
        nextAbove = t - 1;
        edgeTrack[edgeKey(e)] = incomingTrack[e.to] != null ? incomingTrack[e.to] : t;
        if (incomingTrack[e.to] == null) incomingTrack[e.to] = t;
        assignTracks(e.to, incomingTrack[e.to]);
      });
      let t = incomingTrack[id] ?? t0;
      restEdges(id).forEach((e) => {
        if (incomingTrack[e.to] != null) {
          edgeTrack[edgeKey(e)] = t;
          assignTracks(e.to, incomingTrack[e.to]);
          t += 1;
          return;
        }
        edgeTrack[edgeKey(e)] = t;
        incomingTrack[e.to] = t;
        const w = subtreeWidth(e.to);
        assignTracks(e.to, t);
        t += w;
      });
    }

    let nextAbove = -1;
    if (start) assignTracks(start, 0);
    graph.nodes.forEach((n, i) => {
      if (incomingTrack[n.id] == null) incomingTrack[n.id] = i + 1;
    });
    (graph.edges || []).forEach((e) => {
      if (edgeTrack[edgeKey(e)] == null) {
        edgeTrack[edgeKey(e)] = incomingTrack[e.to] ?? incomingTrack[e.from] ?? 0;
      }
    });

    function trackSpan(id) {
      const ts = [...new Set(tracksOf(id))].sort((a, b) => a - b);
      if (!ts.length) return { tMin: 0, tMax: 0 };
      return { tMin: ts[0], tMax: ts[ts.length - 1] };
    }

    function trackHits(e) {
      const t = edgeTrack[edgeKey(e)];
      if (t == null || rank[e.from] == null || rank[e.to] == null) return [];
      const hits = [];
      graph.nodes.forEach((n) => {
        if (n.id === e.from || n.id === e.to) return;
        const rn = rank[n.id];
        if (rn <= rank[e.from] || rn >= rank[e.to]) return;
        const { tMin, tMax } = trackSpan(n.id);
        if (t >= tMin && t <= tMax) hits.push(n.id);
      });
      return hits;
    }

    for (let step = 0; step < 24; step += 1) {
      let moved = false;
      (graph.edges || []).forEach((e) => {
        const hits = trackHits(e);
        if (!hits.length) return;
        let top = Infinity;
        hits.forEach((id) => {
          top = Math.min(top, trackSpan(id).tMin);
        });
        const used = new Set(Object.values(edgeTrack));
        let next = top - 1;
        while (used.has(next)) next -= 1;
        edgeTrack[edgeKey(e)] = next;
        moved = true;
      });
      if (!moved) break;
    }

    const allTracks = [...Object.values(incomingTrack), ...Object.values(edgeTrack)];
    const minT = allTracks.length ? Math.min(...allTracks) : 0;
    Object.keys(incomingTrack).forEach((k) => {
      incomingTrack[k] -= minT;
    });
    Object.keys(edgeTrack).forEach((k) => {
      edgeTrack[k] -= minT;
    });

    function tracksOf(id) {
      const ts = [incomingTrack[id]];
      (outgoing[id] || []).forEach((e) => ts.push(edgeTrack[edgeKey(e)]));
      (incoming[id] || []).forEach((e) => ts.push(edgeTrack[edgeKey(e)]));
      return ts.filter((t) => t != null && !Number.isNaN(t));
    }

    const TRACK = 58;
    const COL = 248;
    const originY = 36;

    const nodes = [];
    graph.nodes.forEach((n) => {
      const size = nodeMap[n.id];
      const ts = [...new Set(tracksOf(n.id))].sort((a, b) => a - b);
      const tMin = ts[0];
      const tMax = ts[ts.length - 1];
      const isEnd = n.kind.startsWith("ending") || n.kind === "terminal";
      const tracks = isEnd && ts.length > 1 ? ts : [null];
      tracks.forEach((track) => {
        const multi = !isEnd && tMax > tMin;
        const width = multi ? 96 : size.w;
        const topLine = originY + tMin * TRACK;
        const botLine = originY + tMax * TRACK;
        const height = multi ? botLine - topLine + 36 : size.h;
        const line = track == null ? incomingTrack[n.id] : track;
        const y = multi ? (topLine + botLine) / 2 : originY + line * TRACK;
        nodes.push({
          ...n,
          width,
          height,
          x: 64 + rank[n.id] * COL + width / 2,
          y,
          cy: originY + (incomingTrack[n.id] ?? 0) * TRACK,
          track: line,
          rank: rank[n.id],
        });
      });
    });

    function pickPlaced(id, y) {
      const cands = nodes.filter((n) => n.id === id);
      if (!cands.length) return null;
      if (cands.length === 1) return cands[0];
      return cands.reduce((best, n) => {
        const d = Math.abs(n.y - y);
        return !best || d < Math.abs(best.y - y) ? n : best;
      }, null);
    }

    const edges = (graph.edges || [])
      .map((e) => {
        const y = originY + (edgeTrack[edgeKey(e)] ?? incomingTrack[e.to] ?? 0) * TRACK;
        const a = pickPlaced(e.from, y);
        const b = pickPlaced(e.to, y);
        if (!a || !b) return null;
        const x1 = a.x + a.width / 2;
        const x2 = b.x - b.width / 2;
        return {
          ...e,
          points: [
            { x: x1, y },
            { x: x2, y },
          ],
          labelAt: { x: x1 + 10, y: y - 6, anchor: "start" },
        };
      })
      .filter(Boolean);
    const width = Math.max(400, ...nodes.map((n) => n.x + n.width / 2 + 48));
    const height = Math.max(
      180,
      ...nodes.map((n) => n.y + n.height / 2 + 36),
      ...edges.flatMap((e) => e.points.map((p) => p.y + 20))
    );
    return { nodes, edges, width, height };
  }

  function edgeCrossesForeignBoxes(laid, pad) {
    const gap = pad == null ? 3 : pad;
    const hits = [];
    (laid.edges || []).forEach((e) => {
      const pts = e.points || [];
      for (let i = 1; i < pts.length; i += 1) {
        const a = pts[i - 1];
        const b = pts[i];
        if (Math.abs(a.y - b.y) > 1) continue;
        const y = a.y;
        const lo = Math.min(a.x, b.x);
        const hi = Math.max(a.x, b.x);
        (laid.nodes || []).forEach((n) => {
          if (n.id === e.from || n.id === e.to) return;
          const left = n.x - n.width / 2;
          const right = n.x + n.width / 2;
          const top = n.y - n.height / 2;
          const bot = n.y + n.height / 2;
          if (right <= lo + gap || left >= hi - gap) return;
          if (y > top + gap && y < bot - gap) hits.push({ edge: e, node: n.id });
        });
      }
    });
    return hits;
  }

  const api = { layoutGraph, pruneGraph, nodeSize, boxesOverlap, edgeCrossesForeignBoxes };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof globalThis !== "undefined" ? globalThis : this);
