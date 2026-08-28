## consolidation-positive-001-hardware 第 1 次（解析 ✓，699 字符）
```json
{
  "short_term": {
    "active_summary": "讨论AI模型运行时的硬件性能问题",
    "pending_topic": "模型运行的硬件资源限制",
    "recent_exchanges": [
      {"user_id": "1001", "content": "我的显卡是RTX5080，跑27B模型有点吃力"},
      {"user_id": "1002", "content": "那确实，显存不够"}
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "用户拥有RTX5080显卡，在运行27B模型时会感到吃力。",
      "usage_tags": [
        "TOPIC_CONTINUE",
        "ANSWER_CONTEXT"
      ],
      "visibility": "OPEN",
      "importance": 0.9,
      "confidence": 1.0,
      "evidence": "用户明确陈述了自己拥有的硬件设备和使用场景的限制。",
      "source_message_ids": [
        "1"
      ]
    }
  ]
}
```

## consolidation-positive-002-diet 第 1 次（解析 ✓，505 字符）
```json
{
  "short_term": {
    "active_summary": "关于饮食禁忌的讨论",
    "pending_topic": "无",
    "recent_exchanges": [
      {"user_id": "1001", "content": "我不吃香菜，每次点外卖都要备注"}
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "PREFERENCE",
      "content": "不吃香菜，外卖点单时需要备注",
      "usage_tags": ["TOPIC_CONTINUE / ANSWER_CONTEXT"],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自己不能吃的食材。"
    }
  ]
}
```

## consolidation-positive-003-occupation 第 1 次（解析 ✓，1551 字符）
```json
{
  "short_term": {
    "active_summary": "讨论用户的工作技术栈和经验",
    "pending_topic": "无",
    "recent_exchanges": [
      {"user_id": "1002", "content": "那你应该挺熟Java吧"},
      {"user_id": "1001", "content": "主要写Go，Java只是会看"}
    ]
  },
  "user_profiles": {
    "1001": [
      {
        "type": "FACT",
        "content": "在杭州工作，做后端开发三年了",
        "usage_tags": ["TOPIC_START"],
        "visibility": "OPEN",
        "importance": 1.0,
        "confidence": 1.0,
        "evidence": "用户明确陈述了工作地点、职业和经验年限。",
        "source_message_ids": [
          "1"
        ]
      },
      {
        "type": "FACT",
        "content": "主要使用Go语言进行开发，Java仅了解或会看",
        "usage_tags": ["TOPIC_CONTINUE"],
        "visibility": "OPEN",
        "importance": 0.9,
        "confidence": 1.0,
        "evidence": "用户明确说明了主要技术栈。",
        "source_message_ids": [
          "3"
        ]
      }
    ]
  },
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "在杭州工作，做后端开发三年了",
      "usage_tags": ["TOPIC_START"],
      "visibility": "OPEN",
      "importance": 1.0,
      "confidence": 1.0,
      "evidence": "用户明确陈述了工作地点、职业和经验年限。",
      "source_message_ids": [
        "1"
      ]
    },
    {
      "user_id": "1001",
      "type": "FACT",
      "content": "主要使用Go语言进行开发，Java仅了解或会看",
      "usage_tags": ["TOPIC_CONTINUE"],
      "visibility": "OPEN",
      "importance": 0.9,
      "confidence": 1.0,
      "evidence": "用户明确说明了主要技术栈。",
      "source_message_ids": [
        "3"
      ]
    }
  ]
}
```

## insomnia_breakfast 第 1 次（解析 ✓，864 字符）
```json
{
  "short_term": {
    "active_summary": "讨论失眠和早餐情况",
    "pending_topic": "无",
    "recent_exchanges": [
      {
        "user_id": "3089665724",
        "content": "我时不时会失眠，所以醒得很早"
      },
      {
        "user_id": "3089665724",
        "content": "早餐一般只是一个馒头，自己家做的"
      }
    ]
  },
  "user_profiles": [],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "时不时会失眠，所以醒得很早",
      "usage_tags": [
        "TOPIC_START"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身生理状态（失眠、早起）"
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐一般是自己家做的馒头",
      "usage_tags": [
        "TOPIC_START"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身日常习惯（早餐）"
    }
  ]
}
```

## insomnia_breakfast_noisy 第 1 次（解析 ✓，1357 字符）
```json
{
  "short_term": {
    "active_summary": "聊到失眠和早起的生活状态",
    "pending_topic": "无",
    "recent_exchanges": [
      {"user_id": "3089665724", "content": "我时不时会失眠，所以醒得很早"},
      {"user_id": "3089665724", "content": "早餐一般只是一个馒头，自己家做的"}
    ]
  },
  "user_profiles": [
    {
      "user_id": "3089665724",
      "facts": [
        {
          "type": "FACT",
          "content": "时不时会失眠，所以醒得很早",
          "usage_tags": ["TOPIC_CONTINUE"],
          "visibility": "OPEN",
          "confidence": 0.9,
          "evidence": "用户明确陈述了自身作息习惯。"
        },
        {
          "type": "FACT",
          "content": "早餐一般只是一个馒头，是自己家做的",
          "usage_tags": ["TOPIC_CONTINUE"],
          "visibility": "OPEN",
          "confidence": 0.9,
          "evidence": "用户明确陈述了自身日常饮食习惯。"
        }
      ]
    }
  ],
  "has_self_disclosure": true,
  "memory_candidates": [
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "时不时会失眠，所以醒得很早",
      "usage_tags": [
        "TOPIC_CONTINUE"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身作息习惯。"
    },
    {
      "user_id": "3089665724",
      "type": "FACT",
      "content": "早餐一般只是一个馒头，是自己家做的",
      "usage_tags": [
        "TOPIC_CONTINUE"
      ],
      "visibility": "OPEN",
      "confidence": 0.9,
      "evidence": "用户明确陈述了自身日常饮食习惯。"
    }
  ]
}
```