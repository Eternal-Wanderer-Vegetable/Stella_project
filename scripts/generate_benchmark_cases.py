# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""确定性基准用例生成器（M1）：模板 × 实体池 → memory/benchmark/generated/。

设计约束：
- 同 seed 同输出（字节级）：实体池与噪音轮转全部用确定性索引运算，无随机数；
- 生成的用例带 ``generator`` 元数据（script/seed/template），与手写用例区分；
- 手写用例保持权威回归地位：生成器只写 generated/ 目录，绝不触碰其他类别；
- 产物进入主数据集（run_benchmark 会加载 generated/），其质量门槛与手写用例
  完全一致（ok 判定、forbidden/泄漏硬门禁一视同仁）。

用法：
    python scripts/generate_benchmark_cases.py            # 生成/覆盖 generated/
    python scripts/generate_benchmark_cases.py --check    # 校验现有产物与重生成一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "memory" / "benchmark" / "generated"
DEFAULT_SEED = 20261016
GENERATOR_NAME = "scripts/generate_benchmark_cases.py"

# 推荐模板：类别 × 物品（查询词=类别；期望=同类偏好；噪音=异类偏好，词面零重叠）
RECOMMEND_POOL: dict[str, tuple[str, ...]] = {
    "游戏": ("塞尔达传说", "星露谷物语", "双人成行"),
    "美食": ("麻婆豆腐", "红烧牛肉面", "手打柠檬茶"),
    "音乐": ("城市流行", "纯钢琴曲", "民谣"),
    "电影": ("科幻大片", "悬疑推理片", "治愈系动画"),
    "书籍": ("科幻小说", "历史纪实", "短篇散文"),
    "运动": ("羽毛球", "夜跑", "游泳"),
}
# 闲聊模板：话题 × 偏好（无模式关键词 → CASUAL_REPLY）
CASUAL_POOL: dict[str, tuple[str, ...]] = {
    "宠物": ("橘猫", "柯基犬", "仓鼠"),
    "旅行": ("海边度假", "古镇漫游", "山间徒步"),
    "日常": ("早睡早起", "周末烘焙", "下班夜骑"),
    "收藏": ("盲盒手办", "黑胶唱片", "绝版贴纸"),
    "天气": ("晴天出门", "雨天听歌", "雪天拍照"),
    "饮食": ("早餐吃包子", "下午喝茶", "夜宵吃面"),
}
# 技术模板：关键词（必须命中 _TECH_KEYWORDS）× 环境描述（→ TECH_HELP）
TECH_POOL: dict[str, tuple[str, ...]] = {
    "python": ("Python 3.12", "Python 3.10"),
    "pip": ("pip 24", "pip 23"),
    "conda": ("conda 默认环境", "conda 独立环境"),
    "cuda": ("CUDA 12", "CUDA 11"),
    "linux": ("Ubuntu 22.04", "Debian 12"),
    "配置": ("默认配置文件", "自定义配置文件"),
}

# 每条用例的噪音数量（异类偏好/事实，词面与查询零重叠）
NOISE_PER_CASE = 2


def _rotating_noise(pool: dict[str, tuple[str, ...]], key: str, seed: int) -> list[tuple[str, str]]:
    """确定性噪音选择：从其他类别按固定轮转取 NOISE_PER_CASE 条。

    seed 决定轮转起点（同 seed 同结果；改 seed 会改变噪音组合，用于验证确定性）。
    """
    keys = sorted(pool)
    others = [k for k in keys if k != key]
    items: list[tuple[str, str]] = []
    for i in range(NOISE_PER_CASE):
        cat = others[(seed + i) % len(others)]
        item = pool[cat][(seed + i) % len(pool[cat])]
        items.append((cat, item))
    return items


def build_cases(seed: int) -> list[dict]:
    """按模板 × 实体池构建全部生成用例（顺序稳定）。"""
    cases: list[dict] = []

    for cat in sorted(RECOMMEND_POOL):
        for item in RECOMMEND_POOL[cat]:
            memories = {
                "PREF": {"content": f"用户喜欢的{cat}是{item}", "type": "PREFERENCE",
                         "usage_tags": ["RECOMMEND"], "visibility": "OPEN",
                         "confidence": 0.9, "importance": 0.8},
            }
            for i, (ncat, nitem) in enumerate(_rotating_noise(RECOMMEND_POOL, cat, seed)):
                memories[f"N{i + 1}"] = {"content": f"用户喜欢的{ncat}是{nitem}", "type": "PREFERENCE",
                                         "usage_tags": ["RECOMMEND"], "visibility": "OPEN",
                                         "confidence": 0.5, "importance": 0.4}
            cases.append({
                "id": f"gen-recommend-{len(cases) + 1:03d}",
                "scenario": {"group_id": 20, "user_id": 2000},
                "input": f"有什么{cat}推荐吗",
                "mode": "RECOMMEND",
                "trigger": "reply",
                "memories": memories,
                "expected_memory": ["PREF"],
                "max_retrieved": 3,
                "generator": {"script": GENERATOR_NAME, "seed": seed, "template": "recommend"},
                "notes": "生成用例：同类偏好（高分）必须被召回，异类偏好允许进但不得顶掉期望。",
            })

    for cat in sorted(CASUAL_POOL):
        for item in CASUAL_POOL[cat]:
            memories = {
                "PREF": {"content": f"用户喜欢聊{item}相关的话题", "type": "PREFERENCE",
                         "usage_tags": ["TOPIC_CONTINUE"], "visibility": "OPEN",
                         "confidence": 0.9, "importance": 0.8},
            }
            for i, (ncat, _nitem) in enumerate(_rotating_noise(CASUAL_POOL, cat, seed)):
                memories[f"N{i + 1}"] = {"content": f"用户平时关注{ncat}", "type": "PREFERENCE",
                                         "usage_tags": ["TOPIC_CONTINUE"], "visibility": "OPEN",
                                         "confidence": 0.5, "importance": 0.4}
            cases.append({
                "id": f"gen-casual-{len(cases) + 1:03d}",
                "scenario": {"group_id": 21, "user_id": 2100},
                "input": f"今天想随便聊聊{cat}",
                "mode": "CASUAL_REPLY",
                "trigger": "reply",
                "memories": memories,
                "expected_memory": ["PREF"],
                "max_retrieved": 3,
                "generator": {"script": GENERATOR_NAME, "seed": seed, "template": "casual"},
                "notes": "生成用例：闲聊延续话题时同类偏好必须可召回。",
            })

    for kw in sorted(TECH_POOL):
        for env in TECH_POOL[kw]:
            memories = {
                "ENV": {"content": f"用户的{kw}环境是{env}", "type": "FACT",
                        "usage_tags": ["ANSWER_CONTEXT"], "visibility": "OPEN",
                        "confidence": 0.9, "importance": 0.8},
            }
            for i, (nkw, nenv) in enumerate(_rotating_noise(TECH_POOL, kw, seed)):
                memories[f"N{i + 1}"] = {"content": f"用户的{nkw}环境是{nenv}", "type": "FACT",
                                         "usage_tags": ["ANSWER_CONTEXT"], "visibility": "OPEN",
                                         "confidence": 0.5, "importance": 0.4}
            cases.append({
                "id": f"gen-tech-{len(cases) + 1:03d}",
                "scenario": {"group_id": 22, "user_id": 2200},
                "input": f"{kw}报错了帮我看看",
                "mode": "TECH_HELP",
                "trigger": "reply",
                "memories": memories,
                "expected_memory": ["ENV"],
                "max_retrieved": 3,
                "generator": {"script": GENERATOR_NAME, "seed": seed, "template": "tech"},
                "notes": "生成用例：技术求助时用户环境事实必须可召回（词面含关键词命中）。",
            })

    return cases


def write_cases(out_dir: Path, seed: int) -> str:
    """写 generated/ 目录（每用例一个文件），返回产物摘要（排序 path+bytes sha256）。"""
    if out_dir.exists():
        for p in sorted(out_dir.rglob("*.json")):
            p.unlink(missing_ok=True)
    cases = build_cases(seed)
    for case in cases:
        template = case["generator"]["template"]
        d = out_dir / template
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{case['id']}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return digest_dir(out_dir)


def digest_dir(out_dir: Path) -> str:
    """产物目录摘要：排序（相对路径, sha256）规范 JSON 的 sha256（冻结断言用）。"""
    entries = []
    for p in sorted(out_dir.rglob("*.json")):
        entries.append({
            "path": p.relative_to(out_dir).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        })
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stella benchmark 生成用例（确定性）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="确定性种子")
    parser.add_argument("--check", action="store_true",
                        help="不写盘：校验现有产物与重新生成完全一致，不一致非零退出")
    args = parser.parse_args(argv)

    if args.check:
        if not args.out.exists():
            print(f"❌ 产物目录不存在：{args.out}", file=sys.stderr)
            return 1
        current = digest_dir(args.out)
        expected = write_cases(args.out.parent / "__regen_check__", args.seed)
        import shutil

        shutil.rmtree(args.out.parent / "__regen_check__", ignore_errors=True)
        if current != expected:
            print(f"❌ generated/ 与 seed={args.seed} 的重生成结果不一致（"
                  f"current={current[:12]} expected={expected[:12]}）——"
                  f"若为有意变更，请同步更新冻结断言", file=sys.stderr)
            return 1
        print(f"✅ generated/ 一致（seed={args.seed}, digest={current[:12]}…, "
              f"{len(build_cases(args.seed))} cases）")
        return 0

    digest = write_cases(args.out, args.seed)
    cases = build_cases(args.seed)
    print(f"✅ 生成 {len(cases)} 条用例 → {args.out}（seed={args.seed}, digest={digest[:12]}…）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
