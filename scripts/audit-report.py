"""只读比较模板与成稿，定位待人工核验内容；统计结果不等同于验收通过。"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from collections import Counter

from docx import Document
from docx.oxml.ns import qn


def inspect(path):
    document = Document(path)
    # 转换后的正文可能包在内容控件/超链接中；python-docx的paragraph.text会漏读。
    def text(element):
        return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()
    paragraphs = [text(p) for p in document._element.body.iter(qn("w:p"))
                  if not any(a.tag == qn("w:tc") for a in p.iterancestors())]
    tables = []
    for index, table in enumerate(document.tables, 1):
        # 合并单元格只统计一次，避免把重复XML代理算作多个缺口。
        seen, cells = set(), []
        for row in table.rows:
            for cell in row.cells:
                if cell._tc in seen:
                    continue
                seen.add(cell._tc)
                cells.append(text(cell._tc))
        tables.append({"table": index, "rows": len(table.rows), "columns": len(table.columns),
                       "cells": cells})
    return paragraphs, tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("draft", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    baseline, baseline_tables = inspect(args.template)
    paragraphs, tables = inspect(args.draft)
    existing = set(baseline)
    markers = re.compile(r"深圳职业|深职[院大]|通信技术专业群|电子信息工程技术专业群|键入章标题|【[^】]*】|_{3,}")
    findings = []
    for index, text in enumerate(paragraphs):
        if markers.search(text):
            findings.append({"kind": "paragraph", "index": index, "text": text})
    for table in tables:
        for index, text in enumerate(table["cells"]):
            if markers.search(text):
                findings.append({"kind": "table", "table": table["table"], "cell": index, "text": text})
    unchanged = [{"index": i, "text": text} for i, text in enumerate(paragraphs)
                 if len(text) >= 60 and text in existing]
    repeats = [{"count": n, "text": text} for text, n in Counter(paragraphs).items()
               if n > 1 and len(text) >= 60]
    result = {"templateSha256": hashlib.sha256(args.template.read_bytes()).hexdigest(),
              "draftSha256": hashlib.sha256(args.draft.read_bytes()).hexdigest(),
              "templateParagraphs": len(baseline), "draftParagraphs": len(paragraphs),
              "templateTables": len(baseline_tables), "draftTables": len(tables),
              "newParagraphs": sum(bool(t) and t not in existing for t in paragraphs),
              "newCharacters": sum(len(t) for t in paragraphs if t not in existing),
              "unchangedLongParagraphs": unchanged, "repeatedLongParagraphs": repeats,
              "reviewMarkers": findings,
              "tableSummary": [{**{k: v for k, v in table.items() if k != "cells"},
                                "uniqueCells": len(table["cells"]),
                                "emptyCells": sum(not t for t in table["cells"])} for table in tables]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, list)}, ensure_ascii=False))
    print(json.dumps({"unchangedLongParagraphs": len(unchanged), "reviewMarkers": len(findings),
                      "repeatedLongParagraphs": len(repeats)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
