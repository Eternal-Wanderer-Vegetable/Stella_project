## consolidation-positive-001-hardware 第 1 次（解析 ✓，1132 字符）
```json
{
  "short_term": {
    "active_summary": "讨论运行大型模型时显卡性能和显存不足的问题。",
    "pending_topic": "AI模型推理的硬件资源需求（显存/显卡型号）",
    "recent_exchanges": [
      {
        "user_id": "1001",
        "content": "我的显卡是RTX5080，跑27B模型有点吃力"
      },
      {
        "user_id": "1002",
        "content": "那确实，显存不够"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "拥有RTX5080显卡，在运行27B模型时会感到吃力。",
      "usage_tags": [
        "TOPIC_START",
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "importance": 0.9,
      "confidence": 1.0,
      "evidence": "用户明确陈述了自己拥有的硬件设备型号和使用场景下的性能感受。"
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "拥有一张RTX5080显卡，运行27B参数规模的模型时性能略显吃力",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.5,
      "confidence": 1.0,
      "evidence": "用户直接陈述了自己的硬件设备及使用该设备时的性能表现",
      "source_message_ids": [
        "1"
      ]
    }
  ]
}
```

## consolidation-positive-002-diet 第 1 次（解析 ✓，1086 字符）
```json
{
  "short_term": {
    "active_summary": "讨论了对香菜的个人饮食偏好。",
    "pending_topic": "无",
    "recent_exchanges": [
      {
        "user_id": "1001",
        "content": "我不吃香菜，每次点外卖都要备注"
      },
      {
        "user_id": "1003",
        "content": "哈哈同款"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "PREFERENCE",
      "content": "不吃香菜，每次点外卖都要备注。",
      "usage_tags": [
        "TOPIC_START",
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自己不能吃香菜的饮食习惯。"
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "PREFERENCE",
      "content": "不喜欢吃香菜，点外卖时需要备注",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "CONFLICT_AVOID"
      ],
      "visibility": "RESTRICTED",
      "behavior_rule": "在涉及饮食建议或点餐场景时，应避免推荐含香菜的食物",
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户直接陈述自己的饮食忌口",
      "source_message_ids": [
        "1"
      ]
    }
  ]
}
```

## consolidation-positive-003-occupation 第 1 次（解析 ✓，1861 字符）
```json
{
  "short_term": {
    "active_summary": "讨论后端开发技术栈，从Java到Go的侧重。",
    "pending_topic": "当前的技术栈偏好（Go vs Java）",
    "recent_exchanges": [
      {
        "user_id": "1002",
        "content": "那你应该挺熟Java吧"
      },
      {
        "user_id": "1001",
        "content": "主要写Go，Java只是会看"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "在杭州工作，后端开发有三年的经验。",
      "usage_tags": [
        "TOPIC_START",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户明确陈述了工作地点、职业和经验年限。",
      "source_message_ids": [
        "消息ID(1)"
      ]
    },
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "主要使用Go语言进行开发，Java仅停留在了解的层面。",
      "usage_tags": [
        "TOPIC_CONTINUE",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.9,
      "confidence": 1.0,
      "evidence": "用户明确说明了主要技术栈和次要技能。",
      "source_message_ids": [
        "消息ID(3)"
      ]
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "在杭州工作，从事后端开发工作三年",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.7,
      "confidence": 1.0,
      "evidence": "用户直接陈述了自己的工作地点、职业及从业年限",
      "source_message_ids": [
        "1"
      ]
    },
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "主要使用 Go 语言进行开发，了解 Java 但不作为主要开发语言",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.7,
      "confidence": 1.0,
      "evidence": "用户明确说明了自己的技术栈偏好与掌握程度",
      "source_message_ids": [
        "3"
      ]
    }
  ]
}
```

## insomnia_breakfast 第 1 次（解析 ✓，1847 字符）
```json
{
  "short_term": {
    "active_summary": "讨论失眠、早餐和一些网络感悟。",
    "pending_topic": "无",
    "recent_exchanges": [
      {
        "user_id": "3089665724",
        "content": "我时不时会失眠，所以醒得很早"
      },
      {
        "user_id": "3089665724",
        "content": "早餐一般只是一个馒头，自己家做的"
      },
      {
        "user_id": "1317175196",
        "content": "一花一叶一菩提👽轮回皆是场迷👿我带菩提落满地😫"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "偶尔会失眠，导致醒得很早。",
      "usage_tags": [
        "TOPIC_START"
      ],
      "visibility": "OPEN",
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户明确陈述了自身的作息习惯（失眠、早醒）。",
      "source_message_ids": [
        "消息ID(1)"
      ]
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐通常是自己家做的馒头。",
      "usage_tags": [
        "TOPIC_START"
      ],
      "visibility": "OPEN",
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户明确陈述了自身的日常饮食习惯（早餐）。",
      "source_message_ids": [
        "消息ID(3)"
      ]
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "有时会失眠，导致早醒",
      "usage_tags": [
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "importance": 0.6,
      "confidence": 0.9,
      "evidence": "用户直接陈述自己的作息与身体状况",
      "source_message_ids": [
        "1"
      ]
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐习惯吃一个自家做的馒头",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.5,
      "confidence": 0.9,
      "evidence": "用户直接陈述自己的饮食习惯",
      "source_message_ids": [
        "3"
      ]
    }
  ]
}
```

## insomnia_breakfast_noisy 第 1 次（解析 ✓，1346 字符）
```json
{
  "short_term": {
    "active_summary": "从祝福到失眠、早餐的日常闲聊。",
    "pending_topic": "无",
    "recent_exchanges": [
      {
        "user_id": "3089665724",
        "content": "早餐一般只是一个馒头，自己家做的"
      },
      {
        "user_id": "457548580",
        "content": "卡了"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "用户早餐一般是自己家做的馒头。",
      "usage_tags": [
        "TOPIC_CONTINUE"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确描述了自己日常的早餐情况。"
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "有时会失眠，导致早醒",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.6,
      "confidence": 0.9,
      "evidence": "用户直接陈述自己的睡眠状况与作息规律",
      "source_message_ids": [
        5
      ]
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐习惯吃自家做的馒头",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.5,
      "confidence": 0.9,
      "evidence": "用户直接陈述自己的饮食习惯",
      "source_message_ids": [
        9
      ]
    }
  ]
}
```