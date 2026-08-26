from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def normaliser_code(value: object) -> str:
    code = str(value or "").strip().upper()
    return code.zfill(8) if code else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.source.read_text(encoding="utf-8"))
    stack = [data]
    articles: dict[str, Counter[str]] = defaultdict(Counter)
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            code = normaliser_code(item.get("code"))
            label = str(item.get("produit") or "").strip()
            if code and label:
                articles[code][label] += 1
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)

    payload = [
        {
            "code_article": code,
            "libelle_article": labels.most_common(1)[0][0],
        }
        for code, labels in sorted(articles.items())
    ]
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"articles={len(payload)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
