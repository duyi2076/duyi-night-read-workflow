#!/usr/bin/env python3
"""
检查 duyi-night-read 工作流的本机依赖。

只做自检和引导，不自动安装第三方 skill，也不写入用户配置。
"""

from __future__ import annotations

from pathlib import Path
import os
import platform


HOME = Path.home()
WEREAD_CANDIDATES = [
    "weread-skills",
    "微信读书",
]
WEREAD_INSTALL_URL = "https://weread.qq.com/r/weread-skills"
ROOT_NAMES = {
    "Claude Code": (".claude", "Claude", "claude"),
    "Codex": (".codex", "Codex", "codex"),
    "Hermes": (".hermes", "Hermes", "hermes"),
    "Claw 系": (
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
    "Claude Code": ("NIGHT_READ_CLAUDE_ROOT", "NIGHT_READ_CLAUDE_ROOTS"),
    "Codex": ("NIGHT_READ_CODEX_ROOT", "NIGHT_READ_CODEX_ROOTS"),
    "Hermes": ("NIGHT_READ_HERMES_ROOT", "NIGHT_READ_HERMES_ROOTS"),
    "Claw 系": (
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


def skill_roots() -> list[Path]:
    roots: list[Path] = []
    for base in base_dirs():
        roots.extend(
            [
                base / ".agents/skills",
                base / ".claude/skills",
                base / ".codex/skills",
                base / "agents/skills",
                base / "Claude/skills",
                base / "Codex/skills",
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
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


def root_has_data(kind: str, root: Path) -> bool:
    if kind == "Claude Code":
        return (root / "projects").exists()
    if kind == "Codex":
        return (root / "state_5.sqlite").exists() or (root / "sessions").exists()
    if kind == "Hermes":
        return (root / "state.db").exists() or (root / "sessions").exists()
    if kind == "Claw 系":
        return (root / "projects").exists()
    return False


def find_weread_skill() -> Path | None:
    for root in skill_roots():
        for name in WEREAD_CANDIDATES:
            path = root / name / "SKILL.md"
            if path.exists():
                return path
    return None


def main() -> int:
    missing = False
    weread_skill = find_weread_skill()

    print("# duyi-night-read dependency check")
    print(f"系统: {platform.system() or 'unknown'}")
    print()

    print("## 本机 agent 记录")
    for kind in ROOT_NAMES:
        found = [root for root in agent_roots(kind) if root_has_data(kind, root)]
        if found:
            print(f"OK {kind}: {found[0]}")
        else:
            print(f"WARN {kind}: 未发现记录目录，没用过这个 agent 可以忽略")
            env_hint = ROOT_ENV_VARS.get(kind, ("NIGHT_READ_<AGENT>_ROOT",))[0]
            print(f"     如果记录在自定义路径，可设置 {env_hint}=<记录根目录>")
    print()

    if weread_skill:
        print(f"OK 微信读书 skill: {weread_skill}")
    else:
        missing = True
        print("MISSING 微信读书 skill")
        print(f"安装入口：{WEREAD_INSTALL_URL}")
        print("打开后复制页面里的 Skill 安装指令，发送给你的 AI 助手安装。")
        print("请先安装微信读书 skill，并确保它的 SKILL.md 位于以下任一位置：")
        for root in skill_roots():
            print(f"- {root}/weread-skills/SKILL.md")
            print(f"- {root}/微信读书/SKILL.md")

    if os.environ.get("WEREAD_API_KEY"):
        print("OK WEREAD_API_KEY is set")
    else:
        missing = True
        print("MISSING WEREAD_API_KEY")
        print(f"获取入口：{WEREAD_INSTALL_URL}")
        print("请先在页面登录微信读书获取 API Key，再按你的系统配置：")
        print("export WEREAD_API_KEY=<你的微信读书 Agent API Key>")
        print('PowerShell: $env:WEREAD_API_KEY="<你的微信读书 Agent API Key>"')
        print("CMD: set WEREAD_API_KEY=<你的微信读书 Agent API Key>")

    print()
    if missing:
        print("依赖未就绪。先补齐上面的项，再运行夜读工作流。")
        return 1

    print("依赖已就绪，可以运行：")
    print("python3 scripts/extract_today.py daily 40")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
