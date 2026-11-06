"""Place access-policy nodes the same way the previous viewer did."""

from __future__ import annotations

import math
import re


def _node_size(kind: str) -> tuple[int, int]:
    if kind in {"start", "entry"}:
        return 72, 30
    if kind.startswith("ending") or kind == "terminal":
        return 128, 30
    return 148, 40


def _text_px(text: str) -> int:
    width = 0
    for char in text:
        width += 16 if ord(char) > 127 else 9
    return width


def _wrap_caption(caption: str) -> list[str]:
    text = str(caption or "").strip()
    if not text:
        return [""]
    words = [word for word in re.split(r"[_\-]+", text) if word]
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current}_{word}"
        if current and _text_px(trial) > 150:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) > 3:
        lines = lines[:2] + ["_".join(lines[2:])]
    return lines


def _caption_box(kind: str, caption: str) -> tuple[int, int, list[str]]:
    base_w, base_h = _node_size(kind)
    lines = _wrap_caption(caption)
    text_w = max((_text_px(line) for line in lines), default=0)
    width = max(base_w, text_w + 28)
    height = max(base_h, 14 + 16 * len(lines))
    return width, height, lines


def _is_except_edge(edge: dict) -> bool:
    return bool(re.fullmatch(r"except", str(edge.get("caption") or ""), flags=re.IGNORECASE))


def _edge_key(edge: dict) -> str:
    return f"{edge.get('from')}\0{edge.get('to')}\0{edge.get('caption') or ''}"


def _prune_graph(graph: dict) -> dict:
    incoming = {edge.get("to") for edge in (graph.get("edges") or [])}
    start = graph.get("start_item")
    nodes = []
    for node in graph.get("nodes") or []:
        if node.get("id") == start or node.get("kind") in {"start", "entry"}:
            nodes.append(node)
            continue
        if node.get("kind") == "terminal" and node.get("id") not in incoming:
            continue
        nodes.append(node)
    keep = {node.get("id") for node in nodes}
    edges = [
        edge
        for edge in (graph.get("edges") or [])
        if edge.get("from") in keep and edge.get("to") in keep
    ]
    return {**graph, "nodes": nodes, "edges": edges}


def layout_graph(raw_graph: dict) -> dict:
    graph = _prune_graph(raw_graph)
    node_map = {}
    for node in graph["nodes"]:
        kind = str(node.get("kind") or "")
        caption = str(node.get("caption") or "")
        width, height, lines = _caption_box(kind, caption)
        node_map[node["id"]] = {**node, "w": width, "h": height, "lines": lines}
    outgoing: dict[str, list] = {}
    incoming: dict[str, list] = {}
    for edge in graph["edges"]:
        if edge.get("from") not in node_map or edge.get("to") not in node_map:
            continue
        outgoing.setdefault(edge["from"], []).append(edge)
        incoming.setdefault(edge["to"], []).append(edge)

    rank: dict[str, int] = {}
    start = graph.get("start_item") if graph.get("start_item") in node_map else None
    if start is None and graph["nodes"]:
        start = graph["nodes"][0].get("id")
    if start:
        rank[start] = 0
    limit = len(graph["nodes"]) + 2
    for _ in range(limit):
        changed = False
        for edge in graph["edges"]:
            if rank.get(edge.get("from")) is None:
                continue
            next_rank = rank[edge["from"]] + 1
            if rank.get(edge.get("to")) is None or next_rank > rank[edge["to"]]:
                rank[edge["to"]] = next_rank
                changed = True
        if not changed:
            break
    for node in graph["nodes"]:
        rank.setdefault(node["id"], 0)

    natural_max = max(rank.values(), default=0)

    def _early_exit(node: dict) -> bool:
        if node.get("kind") != "terminal":
            return False
        ins = incoming.get(node["id"]) or []
        if len(ins) != 1:
            return False
        src = ins[0]
        caption = str(node.get("caption") or "")
        if not _is_except_edge(src) and not re.fullmatch(r"except", caption, flags=re.IGNORECASE):
            return False
        return any(edge.get("to") != node["id"] for edge in (outgoing.get(src.get("from")) or []))

    for node in graph["nodes"]:
        kind = str(node.get("kind") or "")
        if kind.startswith("ending") or (kind == "terminal" and not _early_exit(node)):
            rank[node["id"]] = natural_max

    incoming_track: dict[str, float] = {}
    edge_track: dict[str, float] = {}
    width_memo: dict[str, int] = {}
    visiting: dict[str, bool] = {}
    next_above = -1

    def rest_edges(node_id: str) -> list:
        return [edge for edge in (outgoing.get(node_id) or []) if not _is_except_edge(edge)]

    def except_edges(node_id: str) -> list:
        return [edge for edge in (outgoing.get(node_id) or []) if _is_except_edge(edge)]

    def subtree_width(node_id: str) -> int:
        if node_id in width_memo:
            return width_memo[node_id]
        if visiting.get(node_id):
            return 1
        visiting[node_id] = True
        width = sum(subtree_width(edge["to"]) for edge in rest_edges(node_id))
        visiting[node_id] = False
        width_memo[node_id] = max(1, width or 1)
        return width_memo[node_id]

    placed: set[str] = set()

    def assign_tracks(node_id: str, track0: float) -> None:
        nonlocal next_above
        if node_id not in incoming_track:
            incoming_track[node_id] = track0
        if node_id in placed:
            return
        placed.add(node_id)
        for edge in except_edges(node_id):
            width = subtree_width(edge["to"])
            track = next_above - (width - 1)
            next_above = track - 1
            edge_track[_edge_key(edge)] = incoming_track.get(edge["to"], track)
            incoming_track.setdefault(edge["to"], track)
            assign_tracks(edge["to"], incoming_track[edge["to"]])
        track = incoming_track.get(node_id, track0)
        for edge in rest_edges(node_id):
            if edge["to"] in incoming_track:
                edge_track[_edge_key(edge)] = track
                assign_tracks(edge["to"], incoming_track[edge["to"]])
                track += 1
                continue
            edge_track[_edge_key(edge)] = track
            incoming_track[edge["to"]] = track
            width = subtree_width(edge["to"])
            assign_tracks(edge["to"], track)
            track += width

    if start:
        assign_tracks(start, 0)
    for index, node in enumerate(graph["nodes"]):
        incoming_track.setdefault(node["id"], index + 1)
    for edge in graph["edges"]:
        edge_track.setdefault(
            _edge_key(edge),
            incoming_track.get(edge.get("to"), incoming_track.get(edge.get("from"), 0)),
        )

    def tracks_of(node_id: str) -> list[float]:
        values = [incoming_track.get(node_id)]
        for edge in outgoing.get(node_id) or []:
            values.append(edge_track.get(_edge_key(edge)))
        for edge in incoming.get(node_id) or []:
            values.append(edge_track.get(_edge_key(edge)))
        return [value for value in values if value is not None and not math.isnan(value)]

    def track_span(node_id: str) -> tuple[float, float]:
        values = sorted(set(tracks_of(node_id)))
        if not values:
            return 0, 0
        return values[0], values[-1]

    def track_hits(edge: dict) -> list[str]:
        track = edge_track.get(_edge_key(edge))
        if track is None or rank.get(edge.get("from")) is None or rank.get(edge.get("to")) is None:
            return []
        hits = []
        for node in graph["nodes"]:
            if node["id"] in {edge.get("from"), edge.get("to")}:
                continue
            node_rank = rank.get(node["id"])
            if node_rank is None or node_rank <= rank[edge["from"]] or node_rank >= rank[edge["to"]]:
                continue
            low, high = track_span(node["id"])
            if low <= track <= high:
                hits.append(node["id"])
        return hits

    for _ in range(24):
        moved = False
        for edge in graph["edges"]:
            hits = track_hits(edge)
            if not hits:
                continue
            top = min(track_span(node_id)[0] for node_id in hits)
            used = set(edge_track.values())
            nxt = top - 1
            while nxt in used:
                nxt -= 1
            edge_track[_edge_key(edge)] = nxt
            moved = True
        if not moved:
            break

    all_tracks = [*incoming_track.values(), *edge_track.values()]
    min_track = min(all_tracks) if all_tracks else 0
    for key in list(incoming_track):
        incoming_track[key] -= min_track
    for key in list(edge_track):
        edge_track[key] -= min_track

    widths = [item["w"] for item in node_map.values()] or [148]
    heights = [item["h"] for item in node_map.values()] or [40]
    track_gap = max(76, max(heights) + 30)
    column = max(260, max(widths) + 128)
    origin_y = 44
    nodes: list[dict] = []
    for node in graph["nodes"]:
        size = node_map[node["id"]]
        values = sorted(set(tracks_of(node["id"])))
        low = values[0] if values else 0
        high = values[-1] if values else 0
        kind = str(node.get("kind") or "")
        is_end = kind.startswith("ending") or kind == "terminal"
        tracks = values if is_end and len(values) > 1 else [None]
        for track in tracks:
            multi = (not is_end) and high > low
            width = size["w"]
            top_line = origin_y + low * track_gap
            bot_line = origin_y + high * track_gap
            height = max(size["h"], bot_line - top_line + 28) if multi else size["h"]
            line = incoming_track.get(node["id"], 0) if track is None else track
            y = (top_line + bot_line) / 2 if multi else origin_y + line * track_gap
            nodes.append(
                {
                    **node,
                    "width": width,
                    "height": height,
                    "lines": size.get("lines") or [str(node.get("caption") or "")],
                    "x": 64 + rank[node["id"]] * column + width / 2,
                    "y": y,
                    "rank": rank[node["id"]],
                }
            )

    def pick_placed(node_id: str, y: float) -> dict | None:
        found = [node for node in nodes if node["id"] == node_id]
        if not found:
            return None
        if len(found) == 1:
            return found[0]
        return min(found, key=lambda node: abs(node["y"] - y))

    edges = []
    for edge in graph["edges"]:
        y = origin_y + (edge_track.get(_edge_key(edge), incoming_track.get(edge.get("to"), 0))) * track_gap
        start_node = pick_placed(edge.get("from"), y)
        end_node = pick_placed(edge.get("to"), y)
        if start_node is None or end_node is None:
            continue
        x1 = start_node["x"] + start_node["width"] / 2
        x2 = end_node["x"] - end_node["width"] / 2
        edges.append({**edge, "x1": x1, "y": y, "x2": x2})

    width = 400
    height = 180
    if nodes:
        width = max(width, max(node["x"] + node["width"] / 2 + 48 for node in nodes))
        height = max(height, max(node["y"] + node["height"] / 2 + 36 for node in nodes))
    if edges:
        height = max(height, max(edge["y"] + 20 for edge in edges))
    return {"nodes": nodes, "edges": edges, "width": width, "height": height}
