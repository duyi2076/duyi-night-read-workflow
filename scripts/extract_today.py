#!/usr/bin/env python3
"""
抽取最近 N 小时使用者在本机 agent 里发出的用户消息。

覆盖范围：
- Claude Code: .claude / Claude 常见目录下的 projects/**/*.jsonl
- Codex: .codex / Codex 常见目录下的 state_5.sqlite + sessions/**/*.jsonl
- Hermes: .hermes / Hermes 常见目录下的 state.db
- Claw 系: OpenClaw / QClaw / ClawX / Claw / WorkBuddy 常见目录下的 projects/**/*.jsonl

默认只保留用户主动提问，跳过系统提醒、工具结果、命令回显和 agent 长回答。

如本机 agent 记录不在常见目录，可用环境变量覆盖根目录：
    NIGHT_READ_CLAUDE_ROOT=/path/to/.claude
    NIGHT_READ_CODEX_ROOT=/path/to/.codex
    NIGHT_READ_HERMES_ROOT=/path/to/.hermes
    NIGHT_READ_OPENCLAW_ROOT=/path/to/openclaw
    NIGHT_READ_QCLAW_ROOT=/path/to/qclaw
    NIGHT_READ_CLAWX_ROOT=/path/to/clawx
    NIGHT_READ_CLAW_ROOT=/path/to/claw
    NIGHT_READ_WORKBUDDY_ROOT=/path/to/.workbuddy
多个根目录可用系统路径分隔符连接（macOS/Linux 用 :，Windows 用 ;）。

用法：
    python3 extract_today.py [daily|24h|24] [max_per_session=40]
    python3 extract_today.py [deep|240h|240] [max_per_session=40]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import glob
import html
import json
import os
import re
import sqlite3
import sys
import time


HOME = Path.home()
RECENT_FILE_GRACE_SECONDS = 24 * 3600
HOUR_ALIASES = {
    "daily": 24,
    "day": 24,
    "24h": 24,
    "today": 24,
    "deep": 240,
    "long": 240,
    "week": 240,
    "weekly": 240,
    "240h": 240,
}

ROOT_NAMES = {
    "claude": (".claude", "Claude", "claude"),
    "codex": (".codex", "Codex", "codex"),
    "hermes": (".hermes", "Hermes", "hermes"),
    "workbuddy": (
        ".workbuddy",
        "WorkBuddy",
        "workbuddy",
        ".openclaw",
        "OpenClaw",
        "openclaw",
        ".qclaw",
        "QClaw",
        "qclaw",
        ".clawx",
        "ClawX",
        "clawx",
        ".claw",
        "Claw",
        "claw",
    ),
}
ROOT_ENV_VARS = {
    "claude": ("NIGHT_READ_CLAUDE_ROOT", "NIGHT_READ_CLAUDE_ROOTS"),
    "codex": ("NIGHT_READ_CODEX_ROOT", "NIGHT_READ_CODEX_ROOTS"),
    "hermes": ("NIGHT_READ_HERMES_ROOT", "NIGHT_READ_HERMES_ROOTS"),
    "workbuddy": (
        "NIGHT_READ_WORKBUDDY_ROOT",
        "NIGHT_READ_WORKBUDDY_ROOTS",
        "NIGHT_READ_OPENCLAW_ROOT",
        "NIGHT_READ_OPENCLAW_ROOTS",
        "NIGHT_READ_QCLAW_ROOT",
        "NIGHT_READ_QCLAW_ROOTS",
        "NIGHT_READ_CLAWX_ROOT",
        "NIGHT_READ_CLAWX_ROOTS",
        "NIGHT_READ_CLAW_ROOT",
        "NIGHT_READ_CLAW_ROOTS",
    ),
}


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def env_paths(name: str) -> list[Path]:
    value = os.environ.get(name)
    if not value:
        return []
    return [Path(part).expanduser() for part in value.split(os.pathsep) if part.strip()]


def base_dirs() -> list[Path]:
    bases = [HOME]
    for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        value = env_path(name)
        if value:
            bases.append(value)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in bases:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def agent_roots(kind: str) -> list[Path]:
    roots: list[Path] = []
    for env_name in ROOT_ENV_VARS.get(kind, ()):
        roots.extend(env_paths(env_name))

    for base in base_dirs():
        for name in ROOT_NAMES[kind]:
            roots.append(base / name)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        key = (str(path.resolve()) if path.exists() else str(path)).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


@dataclass
class UserMessage:
    source: str
    session: str
    ts: float
    text: str
    path: str


def parse_ts(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1_000_000_000_000:
            return number / 1000.0
        if number > 1_000_000_000:
            return number
        return 0.0
    if not isinstance(value, str):
        return 0.0

    text = value.strip()
    if not text:
        return 0.0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return parse_ts(float(text))

    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def parse_hours_arg(value: str | None) -> tuple[int, str]:
    if not value:
        return 24, "daily"
    text = value.strip().lower()
    if text in HOUR_ALIASES:
        hours = HOUR_ALIASES[text]
    elif text.endswith("h") and text[:-1].isdigit():
        hours = int(text[:-1])
    else:
        hours = int(text)

    mode = "deep" if hours >= 240 else "daily"
    return hours, mode


def short_ts(ts: float) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def iter_recent_files(root: Path, pattern: str, cutoff: float):
    for name in glob.glob(str(root / pattern), recursive=True):
        path = Path(name)
        try:
            if path.stat().st_mtime < cutoff - RECENT_FILE_GRACE_SECONDS:
                continue
        except OSError:
            continue
        yield path


def read_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception:
        return


def content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        return ""
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return " ".join(parts)


def pull_user_query(text: str) -> str:
    match = re.search(r"<user_query>(.*?)</user_query>", text, flags=re.S)
    if match:
        return html.unescape(match.group(1)).strip()
    return text


def redact_secrets(text: str) -> str:
    replacements = [
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", "Bearer [REDACTED]"),
        (r"\bsk-[A-Za-z0-9_-]{20,}", "[REDACTED_KEY]"),
        (
            r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]{12,}",
            r"\1=[REDACTED]",
        ),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def clean_text(text: str) -> str:
    text = pull_user_query(text or "")
    for marker in ("## My request for Codex:", "## My request for Claude:", "## My request:"):
        if marker in text:
            text = text.split(marker, 1)[1]
            break
    text = re.sub(
        r"<(editor_selection|canvas_selection|current_note)[^>]*>.*?</\1>",
        "",
        text,
        flags=re.S,
    )
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = redact_secrets(text.strip())
    return text


def should_keep(text: str) -> bool:
    if len(text) < 10:
        return False

    head = text[:500].strip().lower()
    skip_prefixes = (
        "# agents.md instructions",
        "<system-reminder",
        "<command-name>",
        "<local-command",
        "<environment_context>",
        "<skill>",
        "[request interrupted",
        "base directory for this skill",
    )
    if head.startswith(skip_prefixes):
        return False
    if "system-reminder" in head:
        return False
    if "<instructions>" in head:
        return False
    if head.startswith("user:") and "assistant:" in head:
        return False
    if head in {"/clear", "/compact"}:
        return False
    return True


def add_message(messages: list[UserMessage], source: str, session: str, ts: float, text: str, path: Path):
    text = clean_text(text)
    if not should_keep(text):
        return
    messages.append(UserMessage(source, session, ts, text[:600], str(path)))


def collect_claude(cutoff: float) -> list[UserMessage]:
    messages: list[UserMessage] = []
    for root in agent_roots("claude"):
        for path in iter_recent_files(root, "projects/**/*.jsonl", cutoff):
            if "subagents" in path.parts:
                continue
            session = path.name
            for row in read_jsonl(path):
                if row.get("type") != "user" or row.get("isSidechain"):
                    continue
                message = row.get("message", {})
                text = content_to_text(message.get("content"))
                ts = parse_ts(row.get("timestamp"))
                if ts and ts < cutoff:
                    continue
                add_message(messages, "Claude Code", session, ts, text, path)
    return messages


def codex_paths(cutoff: float) -> set[Path]:
    paths: set[Path] = set()
    for root in agent_roots("codex"):
        db = root / "state_5.sqlite"
        if db.exists():
            try:
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                rows = conn.execute("SELECT rollout_path, created_at, updated_at FROM threads").fetchall()
                conn.close()
                for rollout_path, created_at, updated_at in rows:
                    if not rollout_path:
                        continue
                    path = Path(rollout_path).expanduser()
                    row_ts = max(parse_ts(created_at), parse_ts(updated_at))
                    try:
                        file_recent = path.exists() and path.stat().st_mtime >= cutoff - RECENT_FILE_GRACE_SECONDS
                    except OSError:
                        file_recent = False
                    if row_ts >= cutoff - RECENT_FILE_GRACE_SECONDS or file_recent:
                        paths.add(path)
            except Exception:
                pass

        for pattern in ("sessions/**/*.jsonl", "archived_sessions/*.jsonl"):
            paths.update(iter_recent_files(root, pattern, cutoff))
    return paths


def collect_codex(cutoff: float) -> list[UserMessage]:
    messages: list[UserMessage] = []
    for path in codex_paths(cutoff):
        if not path.exists():
            continue
        session = path.name
        for row in read_jsonl(path):
            if row.get("type") != "response_item":
                continue
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "message" or payload.get("role") != "user":
                continue
            text = content_to_text(payload.get("content"))
            ts = parse_ts(row.get("timestamp"))
            if ts and ts < cutoff:
                continue
            add_message(messages, "Codex", session, ts, text, path)
    return messages


def collect_hermes(cutoff: float) -> list[UserMessage]:
    messages: list[UserMessage] = []
    for root in agent_roots("hermes"):
        db = root / "state.db"
        if not db.exists():
            continue

        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = conn.execute(
                """
                SELECT session_id, timestamp, content
                FROM messages
                WHERE role = 'user' AND timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (cutoff,),
            ).fetchall()
            conn.close()
        except Exception:
            continue

        for session_id, ts, content in rows:
            add_message(messages, "Hermes", str(session_id), parse_ts(ts), content or "", db)
    return messages


def collect_openclaw(cutoff: float) -> list[UserMessage]:
    messages: list[UserMessage] = []
    for root in agent_roots("workbuddy"):
        for path in iter_recent_files(root, "projects/**/*.jsonl", cutoff):
            session = f"{path.parent.name}/{path.name}"
            for row in read_jsonl(path):
                if row.get("type") != "message" or row.get("role") != "user":
                    continue
                provider_data = row.get("providerData")
                if isinstance(provider_data, dict) and provider_data.get("skipRun"):
                    continue
                text = content_to_text(row.get("content"))
                ts = parse_ts(row.get("timestamp"))
                if ts and ts < cutoff:
                    continue
                add_message(messages, claw_source_name(root), session, ts, text, path)
    return messages


def claw_source_name(root: Path) -> str:
    name = root.name.casefold().lstrip(".")
    if name == "qclaw":
        return "QClaw"
    if name == "clawx":
        return "ClawX"
    if name == "claw":
        return "Claw"
    if name == "workbuddy":
        return "WorkBuddy"
    return "OpenClaw"


def dedupe(messages: list[UserMessage]) -> list[UserMessage]:
    seen: set[str] = set()
    output: list[UserMessage] = []
    for msg in sorted(messages, key=lambda item: (item.ts or 0, item.source, item.session)):
        key = re.sub(r"\s+", " ", msg.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(msg)
    return output


def group_messages(messages: list[UserMessage], max_per_session: int):
    groups: dict[tuple[str, str], list[UserMessage]] = {}
    for msg in messages:
        groups.setdefault((msg.source, msg.session), []).append(msg)

    grouped = []
    for key, items in groups.items():
        items.sort(key=lambda item: item.ts or 0)
        if max_per_session > 0 and len(items) > max_per_session:
            items = items[-max_per_session:]
        grouped.append((key, items))

    grouped.sort(key=lambda group: (group[1][0].ts or 0, group[0][0], group[0][1]))
    return grouped


def main():
    hours, mode = parse_hours_arg(sys.argv[1] if len(sys.argv) > 1 else None)
    max_per_session = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    cutoff = time.time() - hours * 3600

    collectors = (
        collect_claude,
        collect_codex,
        collect_hermes,
        collect_openclaw,
    )

    messages: list[UserMessage] = []
    for collector in collectors:
        messages.extend(collector(cutoff))
    messages = dedupe(messages)
    grouped = group_messages(messages, max_per_session)

    shown_messages = [msg for _, items in grouped for msg in items]
    source_counts: dict[str, int] = {}
    for msg in shown_messages:
        source_counts[msg.source] = source_counts.get(msg.source, 0) + 1
    source_summary = " · ".join(f"{name}: {count}" for name, count in sorted(source_counts.items()))

    print(f"# 今日对话抽取（最近 {hours}h）")
    print(f"# 模式: {mode}")
    print(f"# 覆盖来源: Claude Code / Codex / Hermes / OpenClaw / QClaw / ClawX / Claw / WorkBuddy")
    print(f"# 会话数: {len(grouped)}  用户提问总数: {sum(len(items) for _, items in grouped)}")
    if source_summary:
        print(f"# 来源计数: {source_summary}")
    print()

    for (source, session), items in grouped:
        print(f"## [{source}] {session} ({len(items)} 条)")
        for msg in items:
            single_line = msg.text.replace("\n", " ⏎ ")
            print(f"[{short_ts(msg.ts)}] {single_line}")
        print()


if __name__ == "__main__":
    main()
