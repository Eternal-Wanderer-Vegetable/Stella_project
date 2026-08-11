# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""从真实库切消息窗口，按信号密度分层采样，供人工挑选标注素材（不进 CI）。

基准测试（memory/benchmark）覆盖的是“检索”这一环；被动摄入的风险点需要
从真实群消息里抽样跑 consolidator 观察。本脚本只做采集与分层，不做任何标注。
运行：``python scripts/sample_windows.py``（在项目根目录），输出 ``windows_raw.json``
（含真实数据，已加入 .gitignore）。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# 允许直接 `python scripts/sample_windows.py` 运行：把项目根加入 sys.path，
# 否则 `import config` 会命中 site-packages 里的第三方 config 包。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONSOLIDATION_LOCAL_BATCH_SIZE as B
from config import DB_PATH

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT group_id, user_id, content, timestamp FROM group_messages "
    "ORDER BY group_id, timestamp"
).fetchall()

windows, cur, gid = [], [], None
for r in rows:
    if r[0] != gid:
        gid, cur = r[0], []
    cur.append(r)
    if len(cur) == B:
        windows.append(cur)
        cur = []


def signal_score(w):
    """粗估可提取信息量：长句加分，图片/表情减分。"""
    texts = [(m[2] or "") for m in w]
    return sum(1 for t in texts if len(t) > 15) - sum(
        1 for t in texts if "[Image]" in t or "[图片]" in t or "[表情]" in t
    )


windows.sort(key=signal_score, reverse=True)
n = len(windows)
picked = windows[:12] + windows[n // 2 : n // 2 + 8] + windows[-10:]
#        ↑信息密集：该产候选   ↑中等             ↑刷屏：该产 0 条

print(f"# 共 {n} 个窗口，采样 {len(picked)} 个", file=sys.stderr)
Path("windows_raw.json").write_text(
    json.dumps(
        [[{"user": m[1], "content": m[2], "ts": m[3]} for m in w] for w in picked],
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
