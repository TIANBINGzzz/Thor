"""Validate evidence-driven DOCX writing rules against the frozen 2025 run.

This is a mechanical policy/replay check. It does not invoke an Agent or claim
that a new report was generated; it records that limitation in its JSON output.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".claude/workflows/writing-docx/instructions.md"
GUIDE = ROOT / ".claude/workflows/writing-docx/templates/szpt-midterm/writing-guide.md"
RUN = ROOT / "scratch/report-2025-20260921"
OUTPUT = RUN / "optimization-comparison.json"


def contains(text: str, phrase: str) -> bool:
    return phrase in text


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    verification = json.loads((RUN / "verification-final5.json").read_text(encoding="utf-8"))
    audit = json.loads((RUN / "audit-final5.json").read_text(encoding="utf-8"))
    structure = json.loads((RUN / "structure-v1.json").read_text(encoding="utf-8"))
    evidence = json.loads((RUN / "evidence-map.json").read_text(encoding="utf-8"))

    checks = {
        "four_stage_flow": all(
            contains(workflow, phrase)
            for phrase in ("范围锁定", "证据就绪诊断", "分部分撰写、顺序写入", "全篇验收")
        ),
        "user_empty_policy_precedence": contains(workflow, "没有真实数据先不填")
        and contains(workflow, "不以黄色占位文字替代用户指定的空缺策略")
        and contains(workflow, "保留原单元格为空或模板原占位")
        and not contains(workflow, "不得填默认0、斜杠、空白或样例数掩盖缺口"),
        "old_sample_preflight": contains(workflow, "写入每个部分前先扫描")
        and contains(guide, "写入前先清理当前部分的旧模板样例"),
        "write_readback": contains(workflow, "写入→回读→标记完成")
        and contains(workflow, "正文回读"),
        "full_render_acceptance": contains(workflow, "PDF全文渲染")
        and contains(workflow, "真实目录字段与书签"),
        "alone_dictionary_guard": contains(guide, "alone 字段的含义以当前数据库业务字典为准")
        and not contains(guide, "学校自筹对应 alone 字段"),
        "historical_snapshot_guard": contains(guide, "历史绩效快照指标")
        and contains(guide, "不填写报告年度目标、完成值、完成率、得分或改善结论"),
        "guide_empty_policy_no_conflict": contains(guide, "保留原单元格为空或模板原占位")
        and not contains(guide, "不能留空、填默认0"),
        "baseline_xml_pdf_consistent": not verification.get("contentMissingFromPdf")
        and not verification.get("tableTextMissingFromPdf"),
        "baseline_structure_preserved": verification.get("sameTableRows")
        and verification.get("sameTableCells")
        and verification.get("sameAuthoredPageGeometry"),
        "baseline_audit_clean": not audit.get("forbiddenMarkers", []),
        "baseline_evidence_nonempty": bool(evidence),
    }

    result = {
        "baseline": {
            "run": "report-2025-20260921",
            "page_count": verification.get("pageCount"),
            "toc_fields": verification.get("tocFields", []),
            "table_count": structure.get("tables"),
            "known_failure_modes": [
                "经费正文可能被全局清理覆盖",
                "附件旧模板样例晚清理",
                "目录层级和真实字段在渲染后才发现",
                "表格XML文字与PDF文字可能不一致",
                "cantSplit导致合并单元格边框延伸",
            ],
        },
        "optimized_policy_checks": checks,
        "mechanically_verified": all(checks.values()),
        "actual_end_to_end_generation": "not_run",
        "limitations": [
            "本次对照复用了冻结证据和既有成稿验收结果，没有重新调用Agent生成第二份报告。",
            "因此只能证明规则和回放检查覆盖了基线问题，不能量化模型级A/B撰写质量提升。",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["mechanically_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
