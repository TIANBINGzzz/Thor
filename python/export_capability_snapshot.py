"""将 MySQL 管理的 Capability 和 Skill 文本导出为本地审阅快照。"""

import argparse
from pathlib import Path

from runtime.bootstrap import initialize_runtime
from runtime.capability_snapshots import export_capability_snapshot
from capability_packs.registry import PACK_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capability_ref')
    args = parser.parse_args()
    initialize_runtime()
    files = export_capability_snapshot(args.capability_ref)
    root = Path(PACK_ROOT) / args.capability_ref
    print(f'已导出 {len(files)} 个数据库内容文件到 {root}')


if __name__ == '__main__':
    main()
