## consolidation-positive-001-hardware 第 1 次（解析 ✓，1116 字符）
```json
{
  "short_term": {
    "active_summary": "讨论运行大型模型时显卡和显存的性能问题",
    "pending_topic": "模型运行的硬件配置与资源需求",
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
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户明确陈述了自己拥有的硬件和使用场景带来的性能问题。"
    }
  ]
}

──── 阶段2 提取 ────
{
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "拥有一张RTX5080显卡，运行27B规模的模型时性能略显吃力",
      "usage_tags": [
        "ANSWER_CONTEXT",
        "PERSONALIZE"
      ],
      "visibility": "OPEN",
      "importance": 0.5,
      "confidence": 0.9,
      "evidence": "用户直接陈述了自己的硬件设备及使用该设备时的性能表现",
      "source_message_ids": [
        "1"
      ]
    }
  ]
}
```

## consolidation-positive-002-diet 第 1 次（解析 ✓，1156 字符）
```json
{
  "short_term": {
    "active_summary": "讨论外卖备注的个人口味偏好",
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
      "content": "不吃香菜，点外卖时需要备注。",
      "usage_tags": [
        "TOPIC_START",
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自己不能接受的食材（香菜）并采取了应对措施（备注）。",
      "source_message_ids": [
        1
      ]
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
      "importance": 0.7,
      "confidence": 1.0,
      "evidence": "用户明确表示“我不吃香菜，每次点外卖都要备注”",
      "source_message_ids": [
        "1"
      ]
    }
  ]
}
```

## consolidation-positive-003-occupation 第 1 次（解析 ✓，1785 字符）
```json
{
  "short_term": {
    "active_summary": "讨论开发语言，用户自述主要使用Go语言",
    "pending_topic": "技术栈/编程语言偏好",
    "recent_exchanges": [
      {"user_id": "1001", "content": "我在杭州工作，做后端开发三年了"},
      {"user_id": "1002", "content": "那你应该挺熟Java吧"},
      {"user_id": "1001", "content": "主要写Go，Java只是会看"}
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "在杭州工作，后端开发三年经验",
      "usage_tags": ["TOPIC_START", "PERSONALIZE"],
      "visibility": "OPEN",
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户明确说明了工作地点、职业和经验年限。",
      "source_message_ids": [
        1
      ]
    },
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "主要使用Go语言进行开发，Java仅了解或会看。",
      "usage_tags": ["TOPIC_CONTINUE", "PERSONALIZE"],
      "visibility": "OPEN",
      "importance": 0.9,
      "confidence": 1.0,
      "evidence": "用户明确说明了主要的开发语言和对其他语言的掌握程度。",
      "source_message_ids": [
        3
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
      "evidence": "用户直接陈述自己的工作地点与职业资历",
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
      "importance": 0.8,
      "confidence": 1.0,
      "evidence": "用户直接陈述自己的技术栈情况",
      "source_message_ids": [
        "3"
      ]
    }
  ]
}
```

## insomnia_breakfast 第 1 次（解析 ✓，1834 字符）
```json
{
  "short_term": {
    "active_summary": "讨论失眠、早餐和一些网络迷因。",
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
      "content": "时不时会失眠，所以醒得很早。",
      "usage_tags": [
        "TOPIC_START",
        "EMOTIONAL_SUPPORT"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身的作息习惯（失眠早醒）。",
      "source_message_ids": [
        1
      ]
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐一般只是一个馒头，是自己家做的。",
      "usage_tags": [
        "TOPIC_START",
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身的早餐习惯和来源。",
      "source_message_ids": [
        3
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
        1
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
        3
      ]
    }
  ]
}
```