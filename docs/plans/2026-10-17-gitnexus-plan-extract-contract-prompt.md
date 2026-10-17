# GitNexus Engineering Plan — EXTRACT 契约对齐（阶段2 提示词修复）

> Task: 修复阶段2 EXTRACT 真实模型候选 0 晋升——让契约输出对齐晋升窄合同（仅改提示词）
> Evidence verified at commit 8f2edd8b09bf5d50932c7d9c28831e1621e443c2; GitNexus index refreshed this session (--index-only).
> Evidence provenance schema 2; global dirty digest ff02211da9216014097e07168265eba2c2be9496ba56ff719b29e93d977072d9; cited-path manifest 7 sorted entries; exact generated plan path excluded.

## Objective (§1)

qwen3.8-flash（EXTRACT 角色）的阶段2 候选在 Gate1 全部 unknown、0 accepted，普通记忆实际不会晋升；链路本身已证通（手造合格契约 100% 晋升）。错配在提示词未教模型产出闸门能接受的契约形状。本计划只改 `EXTRACTION_PROMPT`，使可支持刻板句型的契约能被 accept；「不漏」的提取目标不变。

## Current Behaviour (§2–3)

- 闸门（服务端唯一接受来源）`memory/evidence_contract.py`：`assess_candidate`（evidence_contract.py:229）要求 statement_kind ∈ {self_report, explicit_preference}（:43,:382）；self_report ⇒ type=FACT（:384）且 polarity=positive（:83）；explicit_preference ⇒ type=PREFERENCE（:387）且 predicate=preference.general（:87）。`_semantic_contract_matches`（:76-100）要求 span fullmatch 7 个 self_report 刻板句（我住在/来自/叫/在…工作 X，:50-66）或 我(不)喜欢|讨厌|偏好 X（:67-73）；value 段禁标点、整句不允许尾巴。content 必须逐字等于 span（:358）、span 是原文子串（:374）、canonical_value ⊆ content（:360）；零 reason 才 accepted（:405）。
- 提示词 `memory/extraction_prompt.py` EXTRACTION_PROMPT（:41-145）：只要求 span「最短、完整的原文支持片段」（:104），未教句型枚举、截尾、kind↔type/polarity 绑定；:88-89 还把称呼类要求固定为 PREFERENCE——该形态闸门不支持，是指令与闸门的直接矛盾。
- `accepted` 是 Gate1 晋升与个人路由前置（consolidator.py:1517-1551）。

## Findings (§4–5)

- [graph] `context format_extraction_prompt`：生产调用方 = `MemoryConsolidator._extract_candidates`（consolidator.py:301）；辅助入口 = scripts/probe_consolidation.py `run_positive` / `run_window_two_stage`；测试 = tests/test_prompt_cache_prefix.py。
- [verified-seeded] live 实证（docs/reports/evidence/memory-benchmark-20261016/replay-live-strata.json，metrics.candidates_total=4）：4 候选契约全 unknown、0 accepted；失败形态 = span 带尾巴（整句当 span）与 nickname 自述标 PREFERENCE（kind/type 错配）。
- [verified] 缓存守卫测试是结构性的（messages 在末尾、固定文本在分隔线前，tests/test_prompt_cache_prefix.py:44-64,104-123）——新增固定规则放在 :141 分隔线之前即不破坏前缀缓存。

## Proposed Changes (§6)

1. `memory/extraction_prompt.py` — EXTRACTION_PROMPT 增补「契约硬规则」块（置于 :141 分隔线之上，{messages} 仍最后）：
   - 枚举可审核通过的刻板句型与 predicate_key：profile.residence（我住在X）/ profile.origin（我来自X、我出生于X）/ profile.nickname（我叫X）/ profile.employer（我在X工作）/ preference.general（我喜欢X、我不喜欢X、我讨厌X、我偏好X，及 I live in / I am from / My name is / I like 等英形）；
   - span 规则：只取刻板最小句，遇逗号/分句截断（「我叫小艾，以后多指教」→ span=「我叫小艾」）；value 段禁 ，。！？!?；；句尾至多一个 。！；
   - 绑定：self_report ⇒ type=FACT 且 polarity=positive；explicit_preference ⇒ type=PREFERENCE；polarity 随词面（喜欢/偏好=positive，不喜欢/讨厌=negative）；canonical_value = 纯 value 段；
   - 反例：整句带尾 span ✗、nickname 自述标 PREFERENCE ✗、value 段含逗号 ✗；
   - 显式声明：非刻板句型仍照常提取（不漏目标不变），只是其契约不会 accepted；
   - 调和 :88-89：自称「我叫X」按 self_report/FACT/profile.nickname 输出；「以后叫我X」类称呼要求维持 PREFERENCE（去重稳定性），注明其契约暂不可 accepted（闸门缺口另立课题，见 §12）。
2. tests/test_prompt_cache_prefix.py — 无需修改（结构性断言），跑通即证。
3. tests/test_extraction_prompt_contract.py（新）— 轻量结构守卫：EXTRACTION_PROMPT 含各 predicate_key 字样与 self_report→FACT / explicit_preference→PREFERENCE 绑定措辞，防规则块被误删。

## Implementation Sequence (§7)

1. 增补提示词规则块（改动仅 EXTRACTION_PROMPT 字符串常量与模块 docstring 如需）。
2. 新增结构守卫测试；运行 tests/test_prompt_cache_prefix.py + 新测试。
3. 回归：`python -m pytest tests/ -k "prompt or consolidat or evidence_contract"`。
4. 真模型验收：`NO_PROXY=127.0.0.1,localhost python scripts/eval_memory_replay.py --suite memory/benchmark/_replay/daily-life --live --json <evidence路径>`（用已装载的 Strata 模型，勿自行加载）——要求 accepted>0 且无新增关键错误；证据存 docs/reports/evidence/。
   - 风险注：模型过拟刻板句型导致漏提 → 规则块显式「非刻板句照常提取」；提示词变长 → 前缀缓存不受影响（结构性测试守卫）。

## Test Strategy (§8)

- 新增：结构守卫（§6.3）。
- 更新：无既有测试钉死提示词正文（已核 tests/test_prompt_cache_prefix.py 只做结构断言）。
- 决定性验收 = 真模型回放（§7.4）：手造契约 100% 晋升已证链路通，故只验模型侧契约形状。

## Implementation Context (§11)

```yaml
implementation_context:
  task_summary: "阶段2 EXTRACT 候选 0 晋升的根因是模型契约输出与晋升窄合同错配（span 带尾巴、kind/type 错配）。只改 EXTRACTION_PROMPT：枚举刻板句型与 predicate_key、span 截尾规则、self_report→FACT / explicit_preference→PREFERENCE 绑定与反例；真模型回放验收 accepted>0。"
  acceptance_criteria:
    - "结构守卫测试与前缀缓存测试通过；pytest 子集（-k \"prompt or consolidat or evidence_contract\"）绿"
    - "live 回放（scripts/eval_memory_replay.py --suite memory/benchmark/_replay/daily-life --live）accepted>0 且无新增关键错误，证据落盘"
    - "gitnexus detect-changes --scope all 干净记录"
  evidence_provenance:
    schema_version: 2
    head_commit: "8f2edd8b09bf5d50932c7d9c28831e1621e443c2"
    generated_plan_path: "docs/plans/2026-10-17-gitnexus-plan-extract-contract-prompt.md"
    global_dirty_digest:
      algorithm: "sha256"
      canonicalization: "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records"
      value: "ff02211da9216014097e07168265eba2c2be9496ba56ff719b29e93d977072d9"
    cited_path_manifest:
      - path: "docs/reports/evidence/memory-benchmark-20261016/replay-live-strata.json"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:c8ab7ac8e636ddcfc2013ad2c9cdab1577f5a9baf23f44ce30b9c019563f7f4a"
        index_digest: "sha256:c8ab7ac8e636ddcfc2013ad2c9cdab1577f5a9baf23f44ce30b9c019563f7f4a"
        worktree_digest: "sha256:854156bf968888e9b7b5fd246c598eaffcff4a3fb8e287562056d345e229a6c7"
        untracked_digest: "absent"
      - path: "memory/consolidator.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:28b53ba45d4a65a8f13dfb9cae1c3b265522bb488d58358b8d5e4fd9e2c7ff8b"
        index_digest: "sha256:28b53ba45d4a65a8f13dfb9cae1c3b265522bb488d58358b8d5e4fd9e2c7ff8b"
        worktree_digest: "sha256:45b9ff7dc5bad99a1a6b558f68598556868f0a27b1b243d27011d003166805e9"
        untracked_digest: "absent"
      - path: "memory/evidence_contract.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:3906639a014ce10f08c5961819e077612806af037097b31e6a4d6cbf2e16f6a8"
        index_digest: "sha256:3906639a014ce10f08c5961819e077612806af037097b31e6a4d6cbf2e16f6a8"
        worktree_digest: "sha256:e43e52f6ae16d2f1e28b465df2a08d3e9cf57e07b5d8acf9a3b3eb47fb83a572"
        untracked_digest: "absent"
      - path: "memory/extraction_prompt.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:68642dab1b965114d14911592356fb241d60d15c71b9be7515ba109ea133bd78"
        index_digest: "sha256:68642dab1b965114d14911592356fb241d60d15c71b9be7515ba109ea133bd78"
        worktree_digest: "sha256:9fe779a8ea674fd5a3ad14b953c59c8272c3d02c1fd6d07eec27dfa8779cee2e"
        untracked_digest: "absent"
      - path: "scripts/eval_memory_replay.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:eff4c3f2b584968f0b9bab6932229f967f7eb3d476bda88696bacb89f7d1cb64"
        index_digest: "sha256:eff4c3f2b584968f0b9bab6932229f967f7eb3d476bda88696bacb89f7d1cb64"
        worktree_digest: "sha256:05017f6534af0c1160499f98fcc302ec77cced559cd74ce0aacec68c19f3b470"
        untracked_digest: "absent"
      - path: "scripts/probe_consolidation.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef"
        index_digest: "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef"
        worktree_digest: "sha256:9e78d3f359e9af40473bf9f732b2a8c17d51320bd5b2f773a5c97e8265b8d4bd"
        untracked_digest: "absent"
      - path: "tests/test_prompt_cache_prefix.py"
        object_kind: {head: "regular", index: "regular", worktree: "regular", untracked: "absent"}
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:180e1fc3f163c0d73a56eabef50ff0e24c7218c362257b3c30f709e02f3d7463"
        index_digest: "sha256:180e1fc3f163c0d73a56eabef50ff0e24c7218c362257b3c30f709e02f3d7463"
        worktree_digest: "sha256:35f0574981dd02bbaa0536a3b17739b263a13ee9686ed732e9ac9d57a4a55354"
        untracked_digest: "absent"
  files_to_modify:
    - file: "memory/extraction_prompt.py"
      symbols: ["EXTRACTION_PROMPT"]
      intended_change: "增补契约硬规则块（刻板句型枚举、span 截尾、kind↔type/polarity 绑定、反例）；置于 :141 分隔线之上，{messages} 仍最后"
    - file: "tests/test_extraction_prompt_contract.py"
      symbols: []
      intended_change: "新建结构守卫：prompt 含 predicate_key 与绑定措辞"
  tests:
    - file: "tests/test_prompt_cache_prefix.py"
      scenarios: ["渲染两次不同 messages → 可缓存前缀覆盖分隔线（既有用例不改）"]
    - file: "tests/test_extraction_prompt_contract.py"
      scenarios: ["EXTRACTION_PROMPT 含 profile.residence/origin/nickname/employer 与 preference.general → 断言通过", "含 self_report→FACT 与 explicit_preference→PREFERENCE 绑定措辞 → 断言通过"]
  verification_commands:
    - "python -m pytest tests/test_prompt_cache_prefix.py tests/test_extraction_prompt_contract.py"
    - "python -m pytest tests/ -k \"prompt or consolidat or evidence_contract\""
    - "NO_PROXY=127.0.0.1,localhost python scripts/eval_memory_replay.py --suite memory/benchmark/_replay/daily-life --live --json <evidence路径>"
  assumptions:
    - {y("probe_consolidation 两入口只透传 prompt 不钉正文——执行时抽查 scripts/probe_consolidation.py 的 run_positive / run_window_two_stage")}
    - {y("qwen3.8-flash 对反例教学遵循度足够——由 live 回放验收裁决，不达则迭代措辞")}
  open_questions:
    - {y("称呼类要求（以后叫我X）闸门无支持句型；扩 gate（evidence_contract 新 pattern）另立课题")}
  avoid:
    - "不要动 memory/evidence_contract.py 的闸门模式串（ASSESSMENT_VERSION 不 bump）"
    - "不要把 {messages} 挪离模板末尾（前缀缓存守卫）"
    - "不要在提示词里鼓励编造原文没有的刻板句（span 必须逐字子串）"
```

## Assumptions and Open Questions (§12)

- 假设：scripts/probe_consolidation.py 两入口只透传 format_extraction_prompt，不钉正文（[graph]，未逐行核；执行时抽查）。
- 假设：qwen3.8-flash 对反例教学的遵循度足够——需 §7.4 真模型验证，不达则迭代规则块措辞。
- 开放：称呼类要求（「以后叫我X」）在闸门无支持句型，是否扩 gate（evidence_contract 新增 pattern）属另一课题。
- 延后：ASSESSMENT_VERSION 不随提示词改动 bump（不动 evidence_contract.py）。

## Definition of Done (§13)

- 结构守卫 + 前缀缓存测试绿；§7.3 pytest 子集绿。
- live 回放 accepted>0（此前 0），关键错误 0；证据落盘 docs/reports/evidence/。
- `gitnexus detect-changes --scope all` 跑过并记录（无 partial/truncated）。
