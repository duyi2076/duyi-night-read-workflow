#!/usr/bin/env python3
"""
Resolve and validate a WeRead web reader URL for a known book/chapter.

This script does not read WEREAD_API_KEY. It only uses the public WeRead web
search page to find the reader encodeId, then validates the reader page.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


SEARCH_BASE = "https://weread.qq.com/web/search/books"
READER_BASE = "https://weread.qq.com/web/reader"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)


@dataclass(frozen=True)
class ReaderCandidate:
    encode_id: str
    position: int
    score: int


def fetch_url(url: str, timeout: int = 15) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return response.status, raw.decode(charset, errors="replace")


def search_url(title: str) -> str:
    return f"{SEARCH_BASE}?keyword={urllib.parse.quote(title)}"


def reader_url(encode_id: str, chapter_uid: str) -> str:
    query = urllib.parse.urlencode({"progressChapterUid": chapter_uid})
    return f"{READER_BASE}/{encode_id}?{query}"


def label_forms(text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        text,
        html.escape(text),
        json.dumps(text, ensure_ascii=False)[1:-1],
        json.dumps(text, ensure_ascii=True)[1:-1],
    }


def contains_label(haystack: str, label: str | None) -> bool:
    if not label:
        return False
    return any(form and form in haystack for form in label_forms(label))


def reader_candidates(search_html: str, title: str, book_id: str, author: str | None = None) -> list[ReaderCandidate]:
    normalized = html.unescape(search_html).replace("\\/", "/")
    matches = list(re.finditer(r"/web/reader/([A-Za-z0-9]+)", normalized))
    candidates: dict[str, ReaderCandidate] = {}

    for match in matches:
        encode_id = match.group(1)
        anchor_end = normalized.find("</a>", match.end())
        item_start = normalized.rfind("<li", 0, match.start())
        item_end = normalized.find("</li>", match.end())
        if item_start >= 0 and item_end >= 0:
            start = item_start
            end = min(len(normalized), item_end + len("</li>"))
        elif anchor_end >= 0:
            start = max(0, match.start() - 300)
            end = min(len(normalized), anchor_end + len("</a>"))
        else:
            start = max(0, match.start() - 300)
            end = min(len(normalized), match.end() + 2000)
        context = normalized[start:end]

        score = 0
        if book_id and book_id in context:
            score += 10
        if contains_label(context, title):
            score += 6
        if contains_label(context, author):
            score += 2

        current = candidates.get(encode_id)
        candidate = ReaderCandidate(encode_id=encode_id, position=match.start(), score=score)
        if current is None or (candidate.score, -candidate.position) > (current.score, -current.position):
            candidates[encode_id] = candidate

    return sorted(candidates.values(), key=lambda item: (-item.score, item.position))


def choose_reader(search_html: str, title: str, book_id: str, author: str | None = None) -> ReaderCandidate | None:
    candidates = reader_candidates(search_html, title, book_id, author)
    if not candidates:
        return None
    scored = [candidate for candidate in candidates if candidate.score > 0]
    return scored[0] if scored else candidates[0]


def validate_reader(url: str, title: str, chapter_title: str | None) -> dict[str, object]:
    try:
        status, body = fetch_url(url)
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "title_found": False,
            "chapter_found": False,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "title_found": False,
            "chapter_found": False,
            "error": str(exc),
        }

    title_found = contains_label(body, title)
    chapter_found = True if not chapter_title else contains_label(body, chapter_title)
    return {
        "ok": status == 200 and title_found and chapter_found,
        "status": status,
        "title_found": title_found,
        "chapter_found": chapter_found,
        "error": "",
    }


def resolve(title: str, book_id: str, chapter_uid: str, chapter_title: str | None, author: str | None = None) -> dict[str, object]:
    url = search_url(title)
    status, body = fetch_url(url)
    candidate = choose_reader(body, title, book_id, author)
    if not candidate:
        return {
            "ok": False,
            "search_url": url,
            "search_status": status,
            "error": "No /web/reader/{encodeId} candidate found in search page",
        }

    resolved = reader_url(candidate.encode_id, chapter_uid)
    validation = validate_reader(resolved, title, chapter_title)
    return {
        "ok": bool(validation["ok"]),
        "search_url": url,
        "search_status": status,
        "reader_url": resolved,
        "encode_id": candidate.encode_id,
        "candidate_score": candidate.score,
        **validation,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve a verified WeRead web reader URL.")
    parser.add_argument("--title", required=True, help="Book title")
    parser.add_argument("--book-id", required=True, help="WeRead bookId from API")
    parser.add_argument("--chapter-uid", required=True, help="chapterUid from /book/chapterinfo")
    parser.add_argument("--chapter-title", default="", help="Chapter title to verify in reader HTML")
    parser.add_argument("--author", default="", help="Optional author name to disambiguate search results")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = resolve(
        title=args.title,
        book_id=args.book_id,
        chapter_uid=args.chapter_uid,
        chapter_title=args.chapter_title or None,
        author=args.author or None,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("ok"):
        print(f"OK 网页阅读：{result['reader_url']}")
        print(f"OK 搜索页：{result['search_url']}")
        print(f"OK App 章节直达：weread://reading?bId={args.book_id}&chapterUid={args.chapter_uid}")
    else:
        print("FAILED 未能验证网页阅读链接")
        for key in ("error", "reader_url", "search_url", "status", "title_found", "chapter_found"):
            if key in result:
                print(f"{key}: {result[key]}")

    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
