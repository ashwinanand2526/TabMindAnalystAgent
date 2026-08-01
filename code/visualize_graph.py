"""DAG visualizer for Session 8 graph runs.

Reads the ``graph.json`` written by SessionStore and renders a labelled
DiGraph PNG into the same session directory.  Called after every node
batch so the file updates as the run progresses.

Usage (standalone — render a finished session):
    uv run python visualize_graph.py <session_id>
    uv run python visualize_graph.py s8-5e41160c

Output files:
    state/sessions/<sid>/dag.png              ← overwritten each batch
    state/sessions/<sid>/dag_step_NNN.png     ← permanent snapshot per step
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── colour palette ─────────────────────────────────────────────────────────────
# Status → (node fill hex, text hex)
STATUS_COLOURS: dict[str, tuple[str, str]] = {
    "complete": ("#2ecc71", "#0a3d1f"),
    "failed":   ("#e74c3c", "#fff5f5"),
    "skipped":  ("#7f8c8d", "#ecf0f1"),
    "running":  ("#f39c12", "#1a0900"),
    "pending":  ("#3498db", "#0d2137"),
}
DEFAULT_COLOUR = ("#546e7a", "#ecf0f1")

# Skill → short badge text (ASCII only — safe with any mpl font)
SKILL_BADGE: dict[str, str] = {
    "planner":   "PLN",
    "researcher": "RES",
    "analyst":   "ANL",
    "coder":     "COD",
    "critic":    "CRT",
    "formatter": "FMT",
}

BG_DARK   = "#12121e"
BG_PANEL  = "#1a1a2e"
EDGE_COL  = "#546e7a"


def _layered_pos(g) -> dict:  # type: ignore[type-arg]
    """Left-to-right layout via topological generations."""
    import networkx as nx

    try:
        gens = list(nx.topological_generations(g))
    except nx.NetworkXUnfeasible:
        return nx.spring_layout(g, seed=42)

    pos: dict = {}
    x_gap, y_gap = 3.5, 2.2
    for li, layer in enumerate(gens):
        nodes = sorted(layer)
        n = len(nodes)
        for ri, node in enumerate(nodes):
            x = li * x_gap
            y = (ri - (n - 1) / 2.0) * y_gap
            pos[node] = (x, y)
    return pos


def render(session_id: str) -> Path | None:
    """Render the DAG for *session_id* and save it as ``dag.png``.

    Overwrites the same file each time — no per-step snapshots are kept.
    Returns the written Path, or None if graph.json is missing/empty.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import networkx as nx
    except ImportError as e:
        print(f"[visualize_graph] missing dependency: {e}. "
              "Run: uv add matplotlib", file=sys.stderr)
        return None

    sessions_root = Path(__file__).parent / "state" / "sessions"
    session_dir   = sessions_root / session_id
    json_path     = session_dir / "graph.json"

    if not json_path.exists():
        print(f"[visualize_graph] {json_path} not found", file=sys.stderr)
        return None

    payload = json.loads(json_path.read_text())
    g: nx.DiGraph = nx.node_link_graph(payload, edges="edges", directed=True)

    if g.number_of_nodes() == 0:
        return None

    # ── Ensure edges exist ────────────────────────────────────────────────────
    # Reconstruct edges from inputs and from planner/successor relationships.
    # The 'say hello' run has inputs=["USER_QUERY"] on both nodes so the
    # serialised graph has no edges. We synthesise them in two passes:
    #   1. Explicit n:X input references
    #   2. result.successors list on each node (planner emits these)
    if g.number_of_edges() == 0:
        for nid, data in g.nodes(data=True):
            for inp in data.get("inputs", []):
                if inp.startswith("n:") and inp in g.nodes:
                    g.add_edge(inp, nid)
        # Pass 2: walk every node's result.successors to find who spawned whom.
        # We match by skill+label against the node list.
        nid_list = list(g.nodes())  # insertion-order (Python 3.7+)
        for i, src_nid in enumerate(nid_list):
            result = g.nodes[src_nid].get("result") or {}
            if isinstance(result, dict):
                for succ_spec in result.get("successors", []):
                    succ_skill = succ_spec.get("skill")
                    succ_label = (succ_spec.get("metadata") or {}).get("label")
                    # Find the matching child node
                    for child_nid in nid_list[i + 1:]:
                        cd = g.nodes[child_nid]
                        skill_match = cd.get("skill") == succ_skill
                        label_match = (cd.get("metadata") or {}).get("label") == succ_label
                        if skill_match and (label_match or succ_label is None):
                            if not g.has_edge(src_nid, child_nid):
                                g.add_edge(src_nid, child_nid)
                            break

    pos  = _layered_pos(g)
    nids = list(g.nodes())

    # ── Figure sizing ─────────────────────────────────────────────────────────
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    x_span = (max(xs) - min(xs)) if len(xs) > 1 else 1
    y_span = (max(ys) - min(ys)) if len(ys) > 1 else 1
    fig_w = max(9, x_span * 1.6 + 4)
    fig_h = max(5, y_span * 1.6 + 3)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_PANEL)
    ax.set_aspect("equal")
    ax.axis("off")

    # ── Edges ─────────────────────────────────────────────────────────────────
    if g.number_of_edges() > 0:
        nx.draw_networkx_edges(
            g, pos, ax=ax,
            edge_color=EDGE_COL,
            width=2.2,
            arrows=True,
            arrowstyle="-|>",
            arrowsize=20,
            connectionstyle="arc3,rad=0.08",
            min_source_margin=45,
            min_target_margin=45,
        )

    # ── Nodes (draw via networkx so size is in display pt²) ───────────────────
    # Group by status for colouring
    status_groups: dict[str, list] = {}
    for nid in nids:
        s = g.nodes[nid].get("status", "pending")
        status_groups.setdefault(s, []).append(nid)

    for status, group in status_groups.items():
        fill, _ = STATUS_COLOURS.get(status, DEFAULT_COLOUR)
        nx.draw_networkx_nodes(
            g, pos, nodelist=group, ax=ax,
            node_color=fill,
            node_size=3200,
            node_shape="o",
            linewidths=2.0,
            edgecolors="#ecf0f1",
            alpha=0.95,
        )

    # ── Node labels (multi-line text rendered manually) ────────────────────────
    for nid, data in g.nodes(data=True):
        status = data.get("status", "pending")
        skill  = data.get("skill", "?")
        fill, text_col = STATUS_COLOURS.get(status, DEFAULT_COLOUR)
        x, y = pos[nid]

        badge = SKILL_BADGE.get(skill, "???")

        # Line 1: node id  (bold)
        ax.text(x, y + 0.28, nid,
                ha="center", va="center",
                fontsize=8.5, fontweight="bold",
                color=text_col, zorder=5)

        # Line 2: [badge] skill
        ax.text(x, y + 0.02, f"[{badge}] {skill}",
                ha="center", va="center",
                fontsize=7.5, color=text_col, zorder=5)

        # Line 3: status + elapsed (just below the circle)
        result  = data.get("result")
        elapsed = ""
        if isinstance(result, dict) and result.get("elapsed_s") is not None:
            elapsed = f" {result['elapsed_s']:.1f}s"

        ax.text(x, y - 0.72,
                f"[ {status}{elapsed} ]",
                ha="center", va="center",
                fontsize=7, color=fill,
                fontweight="bold", zorder=5)

    # ── Legend ────────────────────────────────────────────────────────────────
    patches = [
        mpatches.Patch(facecolor=c, edgecolor="#ecf0f1", linewidth=0.5,
                       label=s.capitalize())
        for s, (c, _) in STATUS_COLOURS.items()
    ]
    legend = ax.legend(
        handles=patches, loc="upper right",
        framealpha=0.4, facecolor=BG_PANEL,
        labelcolor="white", fontsize=8.5,
        edgecolor=EDGE_COL, borderpad=0.8,
        handlelength=1.2, handleheight=1.2,
    )
    legend.get_frame().set_linewidth(1.2)

    # ── Title ─────────────────────────────────────────────────────────────────
    query_path = session_dir / "query.txt"
    query_text = query_path.read_text().strip()[:70] if query_path.exists() else ""
    ax.set_title(
        f"Session  {session_id}\n\"{query_text}\"",
        color="white", fontsize=10, pad=14,
        fontweight="bold", loc="center",
    )

    # Pad the axis so labels aren't clipped
    margin = 1.5
    ax.set_xlim(min(xs) - margin, max(xs) + margin)
    ax.set_ylim(min(ys) - margin * 1.5, max(ys) + margin * 1.5)

    fig.subplots_adjust(left=0.04, right=0.96, top=0.90, bottom=0.04)

    # ── Save (single file, overwritten each step) ────────────────────────────
    out_path = session_dir / "dag.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())

    plt.close(fig)
    rel = out_path.relative_to(Path(__file__).parent)
    print(f"[visualize_graph] wrote {rel}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python visualize_graph.py <session_id>")
        sys.exit(1)
    p = render(sys.argv[1])
    print(f"Saved: {p}" if p else "Nothing to render.")
