#!/usr/bin/env python3
"""飞书需求解析 dry-run 工具。

第一版只做关键词提取，不调用外部 AI，不访问飞书 API。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


DEFAULT_VOCAB_PATH = Path(__file__).with_name("vocabulary.json")


def load_vocabulary(path: Path = DEFAULT_VOCAB_PATH) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def extract_city(text: str, city_aliases: Dict[str, str]) -> str:
    hits = []
    for alias, city in city_aliases.items():
        if alias in text:
            hits.append(city)
    hits = unique_keep_order(hits)
    return hits[0] if len(hits) == 1 else ""


def extract_districts(text: str, city: str, districts_by_city: Dict[str, List[str]]) -> List[str]:
    candidates = []
    if city:
        candidates.extend(districts_by_city.get(city, []))
    for values in districts_by_city.values():
        candidates.extend(values)
    return unique_keep_order([name for name in candidates if name in text])


def extract_categories(text: str, category_aliases: Dict[str, str]) -> List[str]:
    hits = []
    for alias, category in sorted(category_aliases.items(), key=lambda x: len(x[0]), reverse=True):
        start = text.find(alias)
        if start >= 0:
            hits.append((start, -len(alias), category))
    return unique_keep_order([item[2] for item in sorted(hits)])


def extract_dates(text: str) -> List[str]:
    patterns = [
        r"\d{4}年\d{1,2}月\d{1,2}日",
        r"\d{1,2}月\d{1,2}日",
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{1,2}\.\d{1,2}",
        r"今天|明天|昨天|当日|本月|当月",
    ]
    hits = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, text))
    return unique_keep_order(hits)


def parse_requirement(text: str, vocabulary: Dict[str, object] | None = None) -> Dict[str, object]:
    vocabulary = vocabulary or load_vocabulary()
    city_aliases = vocabulary.get("cities", {})
    districts_by_city = vocabulary.get("districts_by_city", {})
    category_aliases = vocabulary.get("categories", {})
    vague_words = vocabulary.get("vague_terms", [])

    text = text.strip()
    city = extract_city(text, city_aliases)
    districts = extract_districts(text, city, districts_by_city)
    categories = extract_categories(text, category_aliases)
    dates = extract_dates(text)

    missing_fields = []
    questions = []
    if not city:
        missing_fields.append("城市")
        questions.append("城市未指定，请确认需要处理哪个城市。")
    if not districts:
        missing_fields.append("区县")
        questions.append("区县未指定，请确认区县范围，或确认是否使用默认区县范围。")
    if not categories:
        missing_fields.append("品类")
        questions.append("品类未指定，请确认需要处理哪些品类。")

    vague_hits = [word for word in vague_words if word in text]
    if vague_hits:
        questions.append(f"需求包含模糊表达：{', '.join(vague_hits)}，请确认具体执行范围。")

    return {
        "raw_text": text,
        "city": city,
        "districts": districts,
        "categories": categories,
        "dates": dates,
        "missing_fields": missing_fields,
        "vague_terms": vague_hits,
        "needs_human_review": bool(missing_fields or vague_hits),
        "questions": questions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="解析飞书需求文本。")
    parser.add_argument("--text", help="需求文本。")
    parser.add_argument("--file", help="包含需求文本的文件。")
    parser.add_argument("--out", help="输出 JSON 文件。")
    parser.add_argument("--vocab", default=str(DEFAULT_VOCAB_PATH), help="词库 JSON 文件。")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise SystemExit("必须提供 --text 或 --file。")

    result = parse_requirement(text, load_vocabulary(Path(args.vocab)))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
