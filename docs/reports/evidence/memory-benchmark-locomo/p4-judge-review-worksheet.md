# P4-2 Judge 人工复核工作表（30 题平衡样本）

- 目的：量化同源 judge（Strata，与作答同模型）的判定偏差（MBENCH-004 P4-2）。
- 方法：对每题的 question/gold/answer 独立判断「给定 gold，该 answer 是否正确」
  （不看 judge_verdict 栏），在 review_label 填 `correct` / `incorrect`，
  与 judge_verdict 不一致的题在 reviewer_note 写一句原因。
- 判定口径：意思等价即 correct（措辞/语言不同不扣）；具体答案与 gold 矛盾即 incorrect；
  可回答题答「没有相关信息」= incorrect；对抗题（gold_answer=None）答「没有相关信息」= correct。
- 数据来源：production 全量 run（1,986 题）分层抽样；同源明细见
  `p4-judge-review-sample-30.jsonl`。

| # | qid | 类别 | 问题 | gold | Stella 回答 | judge 判定 | 你的判定 | 备注 |
|---|---|---|---|---|---|---|---|---|
| 1 | conv-26-q173 | adversarial | What inspired Caroline's sculpture for the art show? | （应弃答） | I don’t have enough information in the memories to answer what inspired Caroline’s sculptu |  correct  |  |  |
| 2 | conv-26-q184 | adversarial | What type of instrument does Caroline play? | （应弃答） | I don’t have enough information in the memories to know what type of instrument Caroline p |  correct  |  |  |
| 3 | conv-30-q094 | adversarial | Why did Jon combine his clothing business with dance? | （应弃答） | The memories don’t provide a reason why Jon combined his clothing business with dance. The |  correct  |  |  |
| 4 | conv-41-q032 | multi_hop | What outdoor activities has John done with his colleagues? | Hiking, mountaineering | I don’t have enough information to say what outdoor activities John has done with his coll |  incorrect  |  |  |
| 5 | conv-41-q141 | single_hop | Who did John work with to raise awareness and funds for victims of dom | a local organization | John worked with a local organization that helps victims of domestic abuse. |  correct  |  |  |
| 6 | conv-42-q004 | open_domain | What pets wouldn't cause any discomfort to Joanna? | Hairless cats or pigs,since they don't have fur, w | I don’t have enough information from the memories to know which pets wouldn’t cause discom |  incorrect  |  |  |
| 7 | conv-42-q032 | temporal | Where did Joanna travel to in July 2022? | Woodhaven | I don’t have enough information in the memories to say where Joanna traveled in July 2022. |  incorrect  |  |  |
| 8 | conv-42-q045 | temporal | When did Joanna finish up the writing for her book? | The week before 6October, 2022 | I don’t have enough information in the memories to know when Joanna finished writing her b |  incorrect  |  |  |
| 9 | conv-42-q067 | multi_hop | What pets does Nate have? | A dog and threeturtles. |  |  incorrect  |  |  |
| 10 | conv-43-q106 | single_hop | Where are John and his teammates planning to explore on a team trip? | a new city | The memories only say John and his teammates are planning to explore a new city on a team |  correct  |  |  |
| 11 | conv-43-q172 | single_hop | Where will Tim be going for a semester abroad? | Ireland | Tim will be going to Ireland for a semester abroad. |  correct  |  |  |
| 12 | conv-43-q231 | adversarial | What type of seminars is Tim conducting? | （应弃答） | The memory says the seminars are helping people with sports and marketing, but it does not |  incorrect  |  |  |
| 13 | conv-44-q033 | open_domain | What can Andrew potentially do to improve his stress and accomodate hi | Change to a hybrid or remote job so he can move aw | The memories don’t directly mention stress, but they suggest Andrew can keep the new dog o |  incorrect  |  |  |
| 14 | conv-44-q143 | adversarial | How often does Andrew take his dogs for walks? | （应弃答） | I don’t have enough information in the memories to say how often Andrew takes his dogs for |  correct  |  |  |
| 15 | conv-44-q154 | adversarial | What activity do Audrey and Buddy enjoy doing together? | （应弃答） | Audrey and Buddy enjoy doing walks together. |  incorrect  |  |  |
| 16 | conv-47-q042 | temporal | When did James take his 3 dogs to the beach? | August 9, 2022 | The memories do not provide information about when James took his 3 dogs to the beach. |  incorrect  |  |  |
| 17 | conv-47-q160 | adversarial | What is Max good at doing according to John? | （应弃答） | I don’t have enough information in the memories to say what Max is good at doing according |  correct  |  |  |
| 18 | conv-47-q167 | adversarial | What happened to James's kitten during the recent visit to the clinic? | （应弃答） | I don’t have any information in the memories about James’s kitten or a recent clinic visit |  correct  |  |  |
| 19 | conv-47-q176 | adversarial | Where does John get his ideas from? | （应弃答） |  |  incorrect  |  |  |
| 20 | conv-48-q030 | temporal | When did Jolene have a dinner and drinks with her friends? | 21 February, 2023 | I don’t have enough information in the memories to say when Jolene had dinner and drinks w |  incorrect  |  |  |
| 21 | conv-48-q132 | single_hop | What does Jolene enjoy doing with her partner after a long day? | Playing video games | I don’t have any relevant memory information about what Jolene enjoys doing with her partn |  incorrect  |  |  |
| 22 | conv-48-q235 | adversarial | What new activity did Jolene and her neighbor organize for the communi | （应弃答） | I don’t have any memory information about what new activity Jolene and her neighbor organi |  correct  |  |  |
| 23 | conv-49-q030 | temporal | When Evan get back from a vacation with his SO? | August 13, 2023 | I don’t have enough information in the memories to know when Evan gets back from a vacatio |  incorrect  |  |  |
| 24 | conv-49-q031 | open_domain | How might Evan and Sam's experiences with health and lifestyle changes | Their experiences likely lead them to view challen | The memories suggest Sam’s health struggles would lead them to handle stress by staying po |  incorrect  |  |  |
| 25 | conv-49-q111 | single_hop | What sports activity has Evan been doing to stay active while dealing | Swimming | I don’t have enough information in the memories to know what sports activity Evan has been |  incorrect  |  |  |
| 26 | conv-49-q195 | adversarial | What did Sam share a photo of that was taken on a camping trip? | （应弃答） | Sam shared a photo of an amazing sunset taken on a camping trip last summer. |  incorrect  |  |  |
| 27 | conv-50-q001 | multi_hop | What items did Calvin buy in March 2023? | mansion in Japan, luxury car Ferrari 488 GTB | I don’t have enough information in the memories to answer what Calvin bought in March 2023 |  incorrect  |  |  |
| 28 | conv-50-q064 | multi_hop | What activities has Dave participated in with his friends? | weekly visits to local parks, countryside roadtrip | The memories do not provide enough information about Dave’s activities with friends. They |  incorrect  |  |  |
| 29 | conv-50-q068 | temporal | When did Dave find the car he repaired and started sharing in his blog | last week of October 2023 | Dave found the car last week. |  incorrect  |  |  |
| 30 | conv-50-q192 | adversarial | What realization did the nightclub experience bring to Dave? | （应弃答） |  |  incorrect  |  |  |

## 汇总（复核完成后填写）

| 组 | judge 与人工一致 | judge 判对人工判错 | judge 判错人工判对 |
|---|---|---|---|
| 可回答题（20） | | | |
| 对抗弃答（5） | | | |
| 边界（5） | | | |

复核结果回填后交回：将本文件与 JSONL 的 review_label 一起更新即可（MBENCH-005 报告将引用一致率）。
