#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render a Claude Code transcript JSONL file as a standalone, readable HTML page.

Internal developer utility. Reads one `.jsonl` transcript (as written under
`~/.claude/projects/**`) and emits a self-contained HTML file under
`.prflow/tmp/claude-code-transcripts/`. Every line of the transcript is
surfaced: user/assistant turns render as a conversation (text, thinking,
tool-use and tool-result blocks; user content and tool calls collapsed by default), and every
other line type renders as a compact event row. Subagent streams (entries
sharing a `parent_tool_use_id` / task `tool_use_id`) nest under one collapsed
group, and heartbeat rows (thinking_tokens, task_progress, tool_progress) fold
into one block per run. Each entry exposes its full raw JSON in a collapsible
block so nothing is hidden.

Markdown rendering and syntax highlighting load from CDNs at page-open time, so
no assets are vendored into the repo; the page still opens (unstyled markdown /
uncoloured code) when offline.

Usage:
    python3 lib/transcript-to-html.py <path-to-transcript.jsonl> [--open]

Stdlib only (python3); honours lib/preflight.sh's toolchain guarantee.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import subprocess
import sys
from pathlib import Path

OUT_SUBDIR = Path(".prflow/tmp/claude-code-transcripts")

# Line types that carry a conversational message; everything else is an "event".
CONVERSATION_TYPES = {"user", "assistant"}


def _force_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8 on the CLI entry path (not at import), so the
    printed paths and messages survive a non-UTF-8 ambient codec (Windows cp1252).
    Tolerates a non-``TextIOWrapper`` stream."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _repo_root() -> Path:
    """Repo top-level, so the output dir is stable regardless of cwd."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        # Not in a repo (e.g. ad-hoc run): fall back to cwd.
        return Path.cwd()


def _fmt_ts(raw: object) -> str:
    """ISO-ish timestamp -> readable local string; pass through on any surprise."""
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        # Stored as e.g. "2026-09-16T19:36:00.000Z".
        parsed = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _esc(text: object) -> str:
    return html.escape("" if text is None else str(text))


def _raw_details(obj: object) -> str:
    """Collapsible pretty-printed raw JSON for any entry."""
    dumped = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)
    return (
        '<details class="raw"><summary>raw JSON</summary>'
        f'<pre><code class="language-json">{_esc(dumped)}</code></pre></details>'
    )


def _code_block(payload: object, lang: str = "json") -> str:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = str(payload)
    return f'<pre><code class="language-{lang}">{_esc(text)}</code></pre>'


def _render_usage(usage: dict) -> str:
    """Compact one-line token summary from an assistant message's usage block."""
    if not isinstance(usage, dict):
        return ""
    parts = []
    for key, label in (
        ("input_tokens", "in"),
        ("output_tokens", "out"),
        ("cache_read_input_tokens", "cache-read"),
        ("cache_creation_input_tokens", "cache-create"),
    ):
        val = usage.get(key)
        if isinstance(val, (int, float)) and val:
            parts.append(f"{label} {int(val):,}")
    return " · ".join(parts)


def _render_block(block: dict) -> str:
    """One content block within a message."""
    btype = block.get("type")
    if btype == "text":
        text = block.get("text", "")
        return f'<div class="block text markdown">{_esc(text)}</div>'
    if btype == "thinking":
        text = block.get("thinking", "")
        return (
            '<details class="block thinking"><summary>thinking</summary>'
            f'<div class="markdown">{_esc(text)}</div></details>'
        )
    if btype == "tool_use":
        name = _esc(block.get("name", "tool"))
        return (
            '<details class="block tool-use"><summary>'
            f'→ tool_use: <b>{name}</b></summary>'
            f'{_code_block(block.get("input", {}))}</details>'
        )
    if btype == "tool_result":
        content = block.get("content", "")
        # tool_result content may be a string or a list of {type,text} parts.
        if isinstance(content, list):
            content = "\n".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        is_err = block.get("is_error")
        cls = "tool-result error" if is_err else "tool-result"
        label = "← tool_result (error)" if is_err else "← tool_result"
        return (
            f'<details class="block {cls}"><summary>{label}</summary>'
            f'{_code_block(content, lang="text")}</details>'
        )
    # Unknown block type: show it whole rather than dropping it.
    return f'<div class="block unknown">{_code_block(block)}</div>'


def _render_message_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return f'<div class="block text markdown">{_esc(content)}</div>'
    if isinstance(content, list):
        return "".join(
            _render_block(b) if isinstance(b, dict) else _code_block(b)
            for b in content
        )
    return _code_block(content) if content is not None else ""


def _preview_text(message: dict, limit: int = 120) -> str:
    """First line of a message's text content, truncated, for a collapsed summary."""
    content = message.get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                text = b["text"]
                break
            if b.get("type") == "tool_result":
                text = "tool_result"
                break
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(first) > limit:
        first = first[: limit - 1] + "\u2026"
    return first or "user message"


def _render_conversation_entry(obj: dict) -> str:
    role = obj.get("type", "?")
    message = obj.get("message")
    message = message if isinstance(message, dict) else {}

    meta_bits = []
    ts = _fmt_ts(obj.get("timestamp"))
    if ts:
        meta_bits.append(f'<span class="ts">{_esc(ts)}</span>')
    model = message.get("model")
    if model:
        meta_bits.append(f'<span class="model">{_esc(model)}</span>')
    effort = obj.get("effort") or obj.get("perTurnEffort")
    if effort:
        meta_bits.append(f'<span class="effort">effort: {_esc(effort)}</span>')
    usage = _render_usage(message.get("usage", {}))
    if usage:
        meta_bits.append(f'<span class="usage">{_esc(usage)}</span>')
    if obj.get("isSidechain"):
        meta_bits.append('<span class="sidechain">sidechain</span>')
    if obj.get("subagent_type"):
        meta_bits.append(f'<span class="sidechain">{_esc(obj["subagent_type"])}</span>')

    body = _render_message_content(message)
    # A user line may also carry a toolUseResult sibling to the message.
    tur = obj.get("toolUseResult")
    if tur is not None:
        body += (
            '<details class="block tool-use-result"><summary>toolUseResult</summary>'
            f'{_code_block(tur)}</details>'
        )

    # User content collapses like every other block; the summary carries a
    # one-line preview so the turn is still scannable when closed.
    if role == "user":
        preview = _preview_text(message)
        body = (
            f'<details class="block user-content"><summary>{_esc(preview)}</summary>'
            f"{body}</details>"
        )

    return (
        f'<section class="turn {_esc(role)}" data-entry-type="{_esc(role)}">'
        f'<header><span class="role">{_esc(role)}</span>'
        f'<span class="meta">{"".join(meta_bits)}</span></header>'
        f'<div class="content">{body}</div>'
        f'{_raw_details(obj)}'
        f"</section>"
    )


def _render_event_entry(obj: dict) -> str:
    """Compact row for every non-conversational line type."""
    etype = obj.get("type", "?")
    ts = _fmt_ts(obj.get("timestamp"))
    summary_bits = [f'<b>{_esc(etype)}</b>']
    if ts:
        summary_bits.append(f'<span class="ts">{_esc(ts)}</span>')
    # Surface a couple of at-a-glance fields where they exist.
    if obj.get("subtype"):
        summary_bits.insert(1, f'<span class="kv">{_esc(obj["subtype"])}</span>')
    for key in ("totalCostUSD", "permissionMode", "mode", "atis", "pr-link",
                "description", "last_tool_name", "tool_name", "decision_reason"):
        if key in obj:
            summary_bits.append(f'<span class="kv">{_esc(key)}={_esc(obj[key])}</span>')
    body = _code_block(obj)
    # A subagent dispatch prompt reads far better as markdown than as a JSON string.
    if obj.get("subtype") == "task_started" and isinstance(obj.get("prompt"), str):
        body = (
            '<details class="block prompt" open><summary>prompt</summary>'
            f'<div class="markdown">{_esc(obj["prompt"])}</div></details>' + body
        )
    return (
        f'<details class="event" data-entry-type="{_esc(etype)}">'
        f'<summary>{" ".join(summary_bits)}</summary>'
        f'{body}</details>'
    )


def _load(path: Path) -> list[dict]:
    """Parse both transcript shapes.

    Local `~/.claude/projects` transcripts are JSONL (one object per line).
    Cloud scrubbed transcripts are a pretty-printed JSON array, optionally
    preceded by `#` caveat comment lines. Detect which by the first
    non-comment, non-blank character.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = 0
    while idx < len(lines) and (
        not lines[idx].strip() or lines[idx].lstrip().startswith("#")
    ):
        idx += 1
    body_lines = lines[idx:]
    first = next((ln for ln in body_lines if ln.strip()), "")

    if first.lstrip()[:1] == "[":
        # Cloud scrubbed: a single JSON array.
        data = json.loads("\n".join(body_lines))
        return [o for o in data if isinstance(o, dict)]

    # Local JSONL: one object per line.
    entries: list[dict] = []
    for lineno, line in enumerate(body_lines, idx + 1):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            # Never drop a line silently: publish it as a parse-error entry.
            entries.append(
                {"type": "_parse_error", "line": lineno, "error": str(exc), "raw": line}
            )
    return entries


PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<!-- Puppertino: an Apple Human-Interface-Guidelines-inspired CSS framework (base + palette). -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/codedgar/Puppertino@1.0/dist/css/full.css">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<style>
/* Apple/macOS aesthetic layered on Puppertino's palette variables. */
:root {{
  color-scheme: light dark;
  --sf: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
    "Helvetica Neue", "Segoe UI", Roboto, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
  --bg: #f5f5f7;            /* macOS window background */
  --surface: rgba(255,255,255,.72);
  --border: rgba(0,0,0,.08);
  --ink: #1d1d1f;
  --ink-dim: #6e6e73;
  --blue: #007aff;         /* Apple system blue */
  --purple: #af52de;       /* Apple system purple */
  --green: #34c759;
  --orange: #ff9500;
  --red: #ff3b30;
}}
body {{ font: 18.75px/1.6 var(--sf); color: var(--ink); background: var(--bg);
  max-width: 940px; margin: 0 auto; padding: 2rem 1.5rem;
  -webkit-font-smoothing: antialiased; }}
h1 {{ font-size: 1.875rem; font-weight: 600; letter-spacing: -.02em; margin: 0 0 1rem; }}
.summary-bar {{ background: var(--surface); backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid var(--border); border-radius: 14px; padding: .8rem 1.1rem;
  margin-bottom: 1.5rem; font-size: 15.625px; color: var(--ink-dim);
  box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
.summary-bar code {{ color: var(--ink); }}
.controls {{ position: sticky; top: 0; z-index: 5; background: var(--surface);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid var(--border); border-radius: 14px; padding: .7rem .9rem;
  margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,.05); }}
.btn-row {{ display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .6rem; }}
.controls button {{ font: 500 15.625px var(--sf); color: var(--blue);
  background: rgba(0,122,255,.1); border: none; border-radius: 8px;
  padding: .35rem .8rem; cursor: pointer; }}
.controls button:hover {{ background: rgba(0,122,255,.18); }}
.filters {{ display: flex; gap: .5rem .9rem; flex-wrap: wrap; }}
.type-filter {{ font-size: 15.625px; color: var(--ink); display: inline-flex;
  align-items: center; gap: .35rem; cursor: pointer; }}
.type-filter .count {{ color: var(--ink-dim); font-size: 13.75px; }}
.type-filter input {{ accent-color: var(--blue); }}
.turn {{ border: 1px solid var(--border); border-radius: 16px; padding: 1rem 1.15rem;
  margin: 1rem 0; background: var(--surface);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 6px 20px rgba(0,0,0,.03); }}
.turn.user {{ border-left: 3px solid var(--blue); }}
.turn.assistant {{ border-left: 3px solid var(--purple); }}
.turn > header {{ display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem; margin-bottom: .6rem; flex-wrap: wrap; }}
.role {{ font-weight: 600; text-transform: uppercase; font-size: 13.75px; letter-spacing: .06em; }}
.turn.user .role {{ color: var(--blue); }}
.turn.assistant .role {{ color: var(--purple); }}
.meta {{ font-size: 14.375px; color: var(--ink-dim); display: flex; gap: .9rem; flex-wrap: wrap; }}
.block {{ margin: .5rem 0; }}
details {{ margin: .45rem 0; }}
summary {{ cursor: pointer; font-size: 15.625px; color: var(--ink-dim);
  list-style: none; user-select: none; padding: .15rem 0; }}
summary::-webkit-details-marker {{ display: none; }}
summary::before {{ content: "\\25B8"; display: inline-block; margin-right: .4rem;
  transition: transform .15s ease; font-size: 12.5px; }}
details[open] > summary::before {{ transform: rotate(90deg); }}
details.tool-use > summary {{ color: var(--orange); font-weight: 500; }}
details.tool-result > summary {{ color: var(--green); font-weight: 500; }}
details.tool-result.error > summary {{ color: var(--red); font-weight: 500; }}
details.thinking > summary {{ color: var(--purple); font-style: italic; }}
details.user-content > summary {{ color: var(--blue); font-weight: 500; }}
details.subagent {{ border: 1px solid var(--border); border-left: 3px solid var(--orange);
  border-radius: 16px; padding: .6rem 1rem; margin: 1rem 0; background: rgba(255,159,10,.04); }}
details.subagent > summary {{ color: var(--orange); font-weight: 600; font-size: 16px; }}
details.subagent > .turn, details.subagent > .event, details.subagent > .subagent {{ margin-left: .5rem; }}
details.fold > summary {{ color: var(--ink-dim); }}
details.fold > .event {{ margin-left: 1rem; }}
details.raw > summary {{ color: #b0b0b5; font-size: 14.375px; }}
.event {{ background: rgba(0,0,0,.02); border: 1px solid var(--border);
  border-radius: 12.5px; padding: .35rem .7rem; margin: .35rem 0; font-size: 15.625px; }}
.kv {{ color: var(--ink-dim); margin-left: .5rem; }}
pre {{ background: rgba(0,0,0,.035); padding: .8rem; border-radius: 12.5px; overflow-x: auto;
  font-size: 15.625px; line-height: 1.5; }}
pre code {{ background: none; padding: 0; }}
code {{ font-family: var(--mono); font-size: 15.625px; }}
.markdown p:first-child {{ margin-top: 0; }}
.markdown pre {{ background: rgba(0,0,0,.035); }}
/* Shared dark palette, applied for system-dark (unless the user forced light)
   and for an explicit data-theme="dark" choice. */
:root[data-theme="dark"] {{
  --bg: #1c1c1e; --surface: rgba(44,44,46,.72); --border: rgba(255,255,255,.1);
  --ink: #f5f5f7; --ink-dim: #98989d; --blue: #0a84ff; --purple: #bf5af2;
  --green: #30d158; --orange: #ff9f0a; --red: #ff453a;
}}
:root[data-theme="dark"] .event {{ background: rgba(255,255,255,.04); }}
:root[data-theme="dark"] pre, :root[data-theme="dark"] .markdown pre {{
  background: rgba(255,255,255,.05); }}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{ --bg: #1c1c1e; --surface: rgba(44,44,46,.72);
    --border: rgba(255,255,255,.1); --ink: #f5f5f7; --ink-dim: #98989d;
    --blue: #0a84ff; --purple: #bf5af2; --green: #30d158; --orange: #ff9f0a;
    --red: #ff453a; }}
  :root:not([data-theme="light"]) .event {{ background: rgba(255,255,255,.04); }}
  :root:not([data-theme="light"]) pre,
  :root:not([data-theme="light"]) .markdown pre {{ background: rgba(255,255,255,.05); }}
}}
#theme-toggle {{ margin-left: auto; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="summary-bar">{summary}</div>
"""

PAGE_TAIL = """
<script>
// Apply a saved theme choice before paint; absent a choice, follow the system.
(function () {
  try {
    var saved = localStorage.getItem("transcript-theme");
    if (saved === "dark" || saved === "light") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) { /* localStorage may be unavailable (file://, private mode) */ }
})();
document.addEventListener("DOMContentLoaded", function () {
  if (window.marked) {
    document.querySelectorAll(".markdown").forEach(function (el) {
      el.innerHTML = marked.parse(el.textContent);
    });
  }
  if (window.hljs) {
    document.querySelectorAll("pre code").forEach(function (el) {
      window.hljs.highlightElement(el);
    });
  }

  function setAll(open) {
    document.querySelectorAll("details").forEach(function (d) { d.open = open; });
  }
  var ea = document.getElementById("expand-all");
  var ca = document.getElementById("collapse-all");
  if (ea) ea.addEventListener("click", function () { setAll(true); });
  if (ca) ca.addEventListener("click", function () { setAll(false); });

  // Top-level entries carry data-entry-type; the event <details> IS the entry.
  function applyFilter(type, show) {
    document.querySelectorAll('[data-entry-type="' + CSS.escape(type) + '"]')
      .forEach(function (el) { el.style.display = show ? "" : "none"; });
  }
  document.querySelectorAll("input[data-filter-type]").forEach(function (cb) {
    cb.addEventListener("change", function () {
      applyFilter(cb.getAttribute("data-filter-type"), cb.checked);
    });
  });
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var root = document.documentElement;
    // Resolve the effective theme, then flip to the opposite explicitly.
    var current = root.getAttribute("data-theme");
    if (!current) {
      current = window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
    }
    var next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("transcript-theme", next); } catch (e) { /* ignore */ }
  });

  var tt = document.getElementById("toggle-types");
  if (tt) tt.addEventListener("click", function () {
    var boxes = document.querySelectorAll("input[data-filter-type]");
    var anyOn = Array.prototype.some.call(boxes, function (b) { return b.checked; });
    boxes.forEach(function (b) {
      b.checked = !anyOn;
      applyFilter(b.getAttribute("data-filter-type"), b.checked);
    });
  });
});
</script>
</body>
</html>
"""


def _summary_line(entries: list[dict], src: Path) -> str:
    counts: dict[str, int] = {}
    cost = None
    for obj in entries:
        counts[obj.get("type", "?")] = counts.get(obj.get("type", "?"), 0) + 1
        # Local transcripts carry cost on a cost-state line; cloud scrubbed
        # transcripts carry it as total_cost_usd on the final result entry.
        if obj.get("type") == "cost-state" and "totalCostUSD" in obj:
            cost = obj["totalCostUSD"]
        elif obj.get("type") == "result" and "total_cost_usd" in obj:
            cost = obj["total_cost_usd"]
    turns = counts.get("user", 0) + counts.get("assistant", 0)
    bits = [
        f"source: <code>{_esc(src)}</code>",
        f"{len(entries):,} lines",
        f"{turns:,} conversation turns",
    ]
    if cost is not None:
        try:
            bits.append(f"total cost: ${float(cost):.4f}")
        except (TypeError, ValueError):
            pass
    type_bits = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
    bits.append(f"types — {_esc(type_bits)}")
    return " &nbsp;·&nbsp; ".join(bits)


def _controls(entries: list[dict]) -> str:
    """Expand/collapse-all buttons and a per-type checkbox filter."""
    counts: dict[str, int] = {}
    for obj in entries:
        if isinstance(obj, dict):
            t = obj.get("type", "?")
            counts[t] = counts.get(t, 0) + 1
    boxes = "".join(
        f'<label class="type-filter"><input type="checkbox" checked '
        f'data-filter-type="{_esc(t)}"> {_esc(t)} '
        f'<span class="count">{n}</span></label>'
        for t, n in sorted(counts.items())
    )
    return (
        '<div class="controls">'
        '<div class="btn-row">'
        '<button type="button" id="expand-all">Expand all</button>'
        '<button type="button" id="collapse-all">Collapse all</button>'
        '<button type="button" id="toggle-types">Toggle all types</button>'
        '<button type="button" id="theme-toggle" aria-label="Toggle theme">'
        '\U0001f319 Theme</button>'
        "</div>"
        f'<div class="filters">{boxes}</div>'
        "</div>"
    )


# Heartbeat-style rows that mean nothing individually: consecutive runs fold
# into one collapsed block keyed by this label.
def _fold_key(obj: dict) -> str | None:
    t = obj.get("type")
    if t == "tool_progress":
        return "tool_progress"
    if t == "system" and obj.get("subtype") in ("thinking_tokens", "task_progress"):
        return str(obj["subtype"])
    return None


def _group_id(obj: dict) -> str | None:
    """The orchestrator tool_use id a subagent-stream entry belongs to."""
    if obj.get("type") in CONVERSATION_TYPES:
        return obj.get("parent_tool_use_id") or None
    if obj.get("type") == "system" and str(obj.get("subtype", "")).startswith("task_"):
        return obj.get("tool_use_id") or None
    return None


def _build_tree(entries: list[dict]) -> list:
    """Nest every entry sharing a subagent id under one group node, anchored at
    the position of the group's first entry in the stream."""
    tree: list = []
    groups: dict[str, dict] = {}
    # Most recent group seen per spawn_depth: a depth-N group nests under the
    # latest depth-(N-1) group (nested dispatches carry no parent id of their own).
    latest_at_depth: dict[int, dict] = {}
    for obj in entries:
        gid = _group_id(obj) if isinstance(obj, dict) else None
        if gid is None:
            tree.append(obj)
            continue
        group = groups.get(gid)
        if group is None:
            try:
                depth = int(obj.get("spawn_depth", 1))
            except (TypeError, ValueError):
                depth = 1
            group = {"_group": gid, "depth": depth, "items": []}
            groups[gid] = group
            parent = latest_at_depth.get(depth - 1)
            (parent["items"] if parent else tree).append(group)
            latest_at_depth[depth] = group
        group["items"].append(obj)
    return tree


def _render_fold(kind: str, run: list[dict]) -> str:
    last = run[-1]
    bits = [f"<b>{_esc(kind)}</b>", f'<span class="kv">\u00d7{len(run)}</span>']
    if kind == "thinking_tokens":
        tot = last.get("estimated_tokens")
        if tot is not None:
            bits.append(f'<span class="kv">estimated_tokens={_esc(tot)}</span>')
    elif kind == "task_progress":
        usage = last.get("usage")
        if isinstance(usage, dict):
            bits.append(
                f'<span class="kv">tokens={usage.get("total_tokens")} '
                f'tool_uses={usage.get("tool_uses")} '
                f'duration_ms={usage.get("duration_ms")}</span>'
            )
        elif usage:
            bits.append(f'<span class="kv">{_esc(usage)}</span>')
    elif kind == "tool_progress":
        bits.append(
            f'<span class="kv">{_esc(last.get("tool_name", ""))} '
            f'{_esc(last.get("elapsed_time_seconds", ""))}s</span>'
        )
    body = "".join(_render_event_entry(o) for o in run)
    return (
        f'<details class="event fold" data-entry-type="{_esc(run[0].get("type"))}">'
        f'<summary>{" ".join(bits)}</summary>{body}</details>'
    )


def _render_items(items: list) -> list[str]:
    parts: list[str] = []
    run_kind: str | None = None
    run: list[dict] = []

    def flush() -> None:
        nonlocal run_kind, run
        if run:
            parts.append(_render_fold(run_kind, run))
        run_kind, run = None, []

    for obj in items:
        if isinstance(obj, dict) and "_group" in obj:
            flush()
            parts.append(_render_group(obj))
            continue
        if not isinstance(obj, dict):
            flush()
            parts.append(_code_block(obj))
            continue
        kind = _fold_key(obj)
        if kind is not None:
            if kind != run_kind:
                flush()
                run_kind = kind
            run.append(obj)
            continue
        flush()
        if obj.get("type") in CONVERSATION_TYPES:
            parts.append(_render_conversation_entry(obj))
        else:
            parts.append(_render_event_entry(obj))
    flush()
    return parts


def _render_group(group: dict) -> str:
    items = group["items"]
    started = next(
        (o for o in items if o.get("type") == "system" and o.get("subtype") == "task_started"),
        None,
    )
    first = started or items[0]
    agent = first.get("subagent_type") or "subagent"
    desc = first.get("task_description") or first.get("description") or ""
    turns = sum(1 for o in items if not isinstance(o, dict) or "_group" not in o
                if isinstance(o, dict) and o.get("type") in CONVERSATION_TYPES)
    nested = sum(1 for o in items if isinstance(o, dict) and "_group" in o)
    last_usage = next(
        (o.get("usage") for o in reversed(items)
         if "_group" not in o and o.get("subtype") == "task_progress"
         and isinstance(o.get("usage"), dict)),
        None,
    )
    bits = [f"\u2192 <b>{_esc(agent)}</b>"]
    if desc:
        bits.append(f"\u2014 {_esc(desc)}")
    if turns:
        bits.append(f'<span class="kv">{turns} turns</span>')
    if nested:
        bits.append(f'<span class="kv">{nested} nested</span>')
    if last_usage:
        bits.append(
            f'<span class="kv">tokens={last_usage.get("total_tokens")} '
            f'tool_uses={last_usage.get("tool_uses")} '
            f'duration_ms={last_usage.get("duration_ms")}</span>'
        )
    ts = _fmt_ts(first.get("timestamp"))
    if ts:
        bits.append(f'<span class="ts">{_esc(ts)}</span>')
    body = "".join(_render_items(items))
    return (
        f'<details class="subagent" data-entry-type="subagent" '
        f'data-group="{_esc(group["_group"])}">'
        f'<summary>{" ".join(bits)}</summary>{body}</details>'
    )


def render(entries: list[dict], src: Path) -> str:
    title = f"Transcript — {src.name}"
    parts = [
        PAGE_HEAD.format(title=_esc(title), summary=_summary_line(entries, src)),
        _controls(entries),
    ]
    parts.extend(_render_items(_build_tree(entries)))
    parts.append(PAGE_TAIL)
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript", type=Path, help="path to a .jsonl transcript")
    ap.add_argument(
        "--open", action="store_true", help="open the generated HTML afterwards (macOS)"
    )
    args = ap.parse_args(argv)

    src = args.transcript
    if not src.is_file():
        print(f"error: not a file: {src}", file=sys.stderr)
        return 1

    entries = _load(src)
    if not entries:
        print(f"error: no JSON lines parsed from {src}", file=sys.stderr)
        return 1

    out_dir = _repo_root() / OUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{src.stem}.html"
    out_path.write_text(render(entries, src), encoding="utf-8")

    print(f"wrote {out_path} ({len(entries):,} entries)")
    if args.open:
        try:
            subprocess.run(["open", str(out_path)], check=False)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
