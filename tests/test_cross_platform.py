#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


extract_today = load_module("extract_today", REPO / "scripts/extract_today.py")
check_dependencies = load_module("check_dependencies", REPO / "scripts/check_dependencies.py")
resolve_weread_link = load_module("resolve_weread_link", REPO / "scripts/resolve_weread_link.py")


class EnvPatch:
    def __init__(self, **values):
        self.values = values
        self.old = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.old[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)

    def __exit__(self, *_):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class CrossPlatformPathTests(unittest.TestCase):
    def test_codex_sessions_are_found_under_windows_appdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            appdata = base / "AppData" / "Roaming"
            localappdata = base / "AppData" / "Local"
            session_dir = appdata / "Codex" / "sessions" / "2026" / "05" / "18"
            session_dir.mkdir(parents=True)
            rollout = session_dir / "rollout-test.jsonl"
            rollout.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:00:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": "Windows Codex 用户问题",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            old_home = extract_today.HOME
            extract_today.HOME = home
            try:
                with EnvPatch(
                    USERPROFILE=home,
                    APPDATA=appdata,
                    LOCALAPPDATA=localappdata,
                    NIGHT_READ_CODEX_ROOT=None,
                    NIGHT_READ_CODEX_ROOTS=None,
                ):
                    messages = extract_today.collect_codex(0)
            finally:
                extract_today.HOME = old_home

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].source, "Codex")
            self.assertIn("Windows Codex", messages[0].text)

    def test_codex_custom_root_env_override_is_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            custom_root = base / "custom-codex"
            session_dir = custom_root / "sessions" / "2026" / "05" / "18"
            session_dir.mkdir(parents=True)
            rollout = session_dir / "rollout-test.jsonl"
            rollout.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:00:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": "自定义 Codex 路径里的用户问题",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            old_home = extract_today.HOME
            extract_today.HOME = home
            try:
                with EnvPatch(
                    USERPROFILE=home,
                    APPDATA=base / "empty-roaming",
                    LOCALAPPDATA=base / "empty-local",
                    NIGHT_READ_CODEX_ROOT=custom_root,
                    NIGHT_READ_CODEX_ROOTS=None,
                ):
                    messages = extract_today.collect_codex(0)
            finally:
                extract_today.HOME = old_home

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].source, "Codex")
            self.assertIn("自定义 Codex 路径", messages[0].text)

    def test_weread_skill_is_found_under_windows_style_skill_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            appdata = base / "AppData" / "Roaming"
            skill = appdata / ".agents" / "skills" / "weread-skills" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: 微信读书\n---\n", encoding="utf-8")

            old_home = check_dependencies.HOME
            check_dependencies.HOME = home
            try:
                with EnvPatch(USERPROFILE=home, APPDATA=appdata, LOCALAPPDATA=base / "Local"):
                    found = check_dependencies.find_weread_skill()
            finally:
                check_dependencies.HOME = old_home

            self.assertEqual(found, skill)

    def test_qclaw_windows_style_root_is_collected_as_claw_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            appdata = base / "AppData" / "Roaming"
            project_dir = appdata / "QClaw" / "projects" / "demo"
            project_dir.mkdir(parents=True)
            log = project_dir / "session.jsonl"
            log.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-18T12:00:00Z",
                        "type": "message",
                        "role": "user",
                        "content": "QClaw 里的用户问题",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            old_home = extract_today.HOME
            extract_today.HOME = home
            try:
                with EnvPatch(
                    USERPROFILE=home,
                    APPDATA=appdata,
                    LOCALAPPDATA=base / "Local",
                    NIGHT_READ_QCLAW_ROOT=None,
                    NIGHT_READ_QCLAW_ROOTS=None,
                ):
                    messages = extract_today.collect_openclaw(0)
            finally:
                extract_today.HOME = old_home

            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].source, "QClaw")
            self.assertIn("QClaw 里的用户问题", messages[0].text)


class WeReadLinkResolverTests(unittest.TestCase):
    def test_reader_candidate_prefers_matching_book_id_and_title(self):
        html = """
        <a href="/web/reader/notthisone">别的书</a>
        <a href="/web/reader/sampleReader001">
          样例之书
          <img src="https://cdn.weread.qq.com/weread/cover/23/99000123/x.jpg">
        </a>
        """

        candidate = resolve_weread_link.choose_reader(
            html,
            title="样例之书",
            book_id="99000123",
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.encode_id, "sampleReader001")

    def test_reader_url_uses_progress_chapter_uid_not_book_id(self):
        url = resolve_weread_link.reader_url("sampleReader001", "chapter-42")

        self.assertEqual(url, "https://weread.qq.com/web/reader/sampleReader001?progressChapterUid=chapter-42")

    def test_contains_label_accepts_json_escaped_chinese(self):
        escaped = '{"title":"\\u6837\\u4f8b\\u4e4b\\u4e66"}'

        self.assertTrue(resolve_weread_link.contains_label(escaped, "样例之书"))


if __name__ == "__main__":
    unittest.main()
