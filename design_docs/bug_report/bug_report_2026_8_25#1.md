# #1.手机端卡片解析测试（失败）
21:10:38
SUCCESS
nonebot
OneBot V11 1694717255 | [message.group.normal]: Message 1342409926 from 3089665724@[群:263402786] '[json:data={"ver":"1.0.0.19","prompt":"[QQ小程序]WEAVERS-编织者，超级混响官方MV改编版+中英歌词字幕",...]'
21:10:38
INFO
nonebot
Event will be handled by Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291)
21:10:38
INFO
nonebot
Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291) running complete
21:10:38
INFO
bot_main
[chat_debug] is_chat_trigger gid=263402786 gid_ok=True is_tome=False text='' self_id=1694717255 raw=[MessageSegment(type='json', data={'data': '{"ver":"1.0.0.19","prompt":"[QQ小程序]WEAVERS-编织者，超级混响官方MV改编版+中英歌词字幕","config":{"type":"normal","width":0,"height":0,"forward":1,"autoSize":0,"ctime":1787663428,"token":"980a389e68cb921a116580980eff2d0a"},"needShareCallBack":false,"app":"com.tencent.miniapp_01","view":"view_8C8E89B49BE609866298ADDFF2DBABA4","meta":{"detail_1":{"appid":"1109937557","appType"

# #2.电脑链接解析测试（成功渲染封面）

21:16:21
SUCCESS
nonebot
OneBot V11 1694717255 | [message.group.normal]: Message 815578929 from 3089665724@[群:263402786] 'https://www.bilibili.com/video/BV1jxuE66EbM/?spm_id_from=333.1391.0.0&vd_source=1a58774ee505bcff5551ecb84d3ed862'
21:16:21
INFO
nonebot
Event will be handled by Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291)
21:16:21
INFO
nonebot
Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291) running complete
21:16:21
INFO
nonebot
Event will be handled by Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=353)
21:16:21
INFO
bot_main
[plugin_debug] handle_plugin event='https://www.bilibili.com/video/BV1jxuE66EbM/?spm_id_from=333.1391.0.0&vd_source=1a58774ee505bcff5551ecb84d3ed862' msg_id=815578929
21:16:22
INFO
logging
127.0.0.1:52299 - "GET /stella/status HTTP/1.1" 200
21:16:24
INFO
logging
127.0.0.1:52300 - "GET /stella/status HTTP/1.1" 200
21:16:25
SUCCESS
nonebot
OneBot V11 1694717255 | [message.group.normal]: Message 1970372443 from 1809238591@[群:950238216] '绿泰坦的设计很完美'
21:16:25
INFO
nonebot
Event will be handled by Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291)
21:16:25
INFO
nonebot
Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=291) running complete
21:16:25
INFO
bot_main
[chat_debug] is_chat_trigger gid=950238216 gid_ok=False is_tome=False text='绿泰坦的设计很完美' self_id=1694717255 raw=[MessageSegment(type='text', data={'text': '绿泰坦的设计很完美'})]
21:16:25
INFO
logging
127.0.0.1:57695 - "GET /stella/status HTTP/1.1" 200
21:16:26
INFO
bot_main
[plugin_debug] dispatch handled=True msg_id=815578929
21:16:26
INFO
nonebot
Matcher(type='message', module=stella_project.plugins.bot_main.ai_gateway, lineno=353) running complete
21:16:26
SUCCESS
nonebot
OneBot V11 1694717255 | [message_sent]: {'time': 1787663785, 'self_id': 1694717255, 'post_type': 'message_sent', 'user_id': 1694717255, 'message_id': 965468302, 'message_seq': 965468302, 'real_id': 965468302, 'real_seq': '256493', 'message_type': 'group', 'sender': {'user_id': 1694717255, 'nickname': 'Stella', 'card': 'Stella', 'role': 'member'}, 'raw_message': '渲染图片失败了 (´;ω;`)UP 主: Aceasion\n播放量: 1157\n点赞: 63\n投币: 14\n总共 1 人正在观看[CQ:image,file=2ACB75FBF1942080409E8F8D26FE25D8.jpg,sub_type=0,url=
21:16:26
INFO
bot_main
[chat_debug] is_chat_trigger gid=263402786 gid_ok=True is_tome=False text='https://www.bilibili.com/video/BV1jxuE66EbM/?spm_id_from=333.1391.0.0&vd_source=1a58774ee505bcff5551ecb84d3ed862' self_id=1694717255 raw=[MessageSegment(type='text', data={'text': 'https://www.bilibili.com/video/BV1jxuE66EbM/?spm_id_from=333.1391.0.0&vd_source=1a58774ee505bcff5551ecb84d3ed862'})]
21:16:27
INFO
logging
127.0.0.1:54980 - "GET /stella/status HTTP/1.1" 200

# #3.主动注入指令测试

### 🕒 [2026-08-25 19:50:35] @回复触发 | 群: `263402786` | 用户: `3089665724`
- **🖥 模型**: `lm_studio / google/gemma-4-26b-a4b-qat`（耗时 11.44s，系统提示词 759 字符）
- **📥 用户输入**: 可以给我推荐一些好看的番剧吗？
- **🧭 路由判定**: `chat+memory+tool` via `semantic`（能力: anime.recommend=0.87，最高分 0.868，468ms）—— 语义命中 ['anime.recommend=0.87']
- **🔧 工具执行**: anime.recommend → `success`（1 次工具调用，直调，0.891s）
  > 近期热门条目（近 3 个月，按热度）: 1. 无职转生 第三季 ～到了异世界就拿出真本事～ (ID: 501963) 评分: 7.9 排名: 286 日期: 2026-07-04 链接: https://bgm.tv/subject/501963  2. 尼古喵喵 (ID: 622206) 评分: 7.3 排名: 1552 日期: 2026-07-02 链接: https://bgm.tv/subject/622206  3. 在超市后门吸烟的二人 (ID: 571784) 评分: 7.0 排名: 2550 日期: 2026-07-09 链接: https://bgm.tv/subject/5…
- **📤 完整 Prompt（发给 LLM）**:
  > 现在是 2026-08-25 19:50，星期二。
  > 
  > 当前与你对话的用户 QQ 号：3089665724。注意：上下文里标注了用户QQ号的内容属于对应的人，只有明确写着当前用户 3089665724 的才归 TA；不要把别人的发言当成 TA 说的。
  > 
  > 当前对话摘要：
  > 之前的话题（约 23.8 小时前）: 讨论了看什么放松，后转入AI和角色扮演的互动。
  > 最近的对话（时间正序，「我」是你自己说过的话）:
  > 用户(3636097627): 手机搞JAVA
  > 用户(3089665724): 可以给我推荐一些好看的番剧吗？
  > 
  > 【刚刚查到的信息（真实数据，回答时以此为准）】
  > 近期热门条目（近 3 个月，按热度）:
  > 1. 无职转生 第三季 ～到了异世界就拿出真本事～ (ID: 501963)
  > 评分: 7.9
  > 排名: 286
  > 日期: 2026-07-04
  > 链接: https://bgm.tv/subject/501963
  > 
  > 2. 尼古喵喵 (ID: 622206)
  > 评分: 7.3
  > 排名: 1552
  > 日期: 2026-07-02
  > 链接: https://bgm.tv/subject/622206
  > 
  > 3. 在超市后门吸烟的二人 (ID: 571784)
  > 评分: 7.0
  > 排名: 2550
  > 日期: 2026-07-09
  > 链接: https://bgm.tv/subject/5…
  > 
  > 【现在 用户(3089665724) 对你说】可以给我推荐一些好看的番剧吗？
  > 请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。
- **📥 原始 LLM 输出（完整）**:
  > <thought>哎呀，终于等到这个话题了，这就去翻翻最近啥比较火。</thought>
  > <action>NONE</action>
  > <reply>看你最近是想看那种正经一点的吗？
  > 要是看异世界题材的话，无职转生第三季应该还不错。
  > 或者看那种比较日常轻松的呀？</reply>
- **🧠 内部思考**:
  > 哎呀，终于等到这个话题了，这就去翻翻最近啥比较火。
- **⚙️ 判定动作**: `NONE`
- **💬 最终台词**: 看你最近是想看那种正经一点的吗？ <br> 要是看异世界题材的话，无职转生第三季应该还不错。 <br> 或者看那种比较日常轻松的呀？


### 🕒 [2026-08-25 21:33:32] @回复触发 | 群: `263402786` | 用户: `3089665724`
- **🖥 模型**: `lm_studio / google/gemma-4-26b-a4b-qat`（耗时 12.52s，系统提示词 759 字符）
- **📥 用户输入**: 最近B站的热门视频是什么呢
- **🧭 路由判定**: `chat+memory+tool` via `semantic`（能力: video.hot=0.92，最高分 0.924，1390ms）—— 语义命中 ['video.hot=0.92']
- **🔧 工具执行**: video.hot → `success`（1 次工具调用，直调，0.375s）
  > B站全站热门视频（第 1 页）: 1. 贱谍过家家（8） BV号: BV1gLhK6LEcb 链接: https://www.bilibili.com/video/BV1gLhK6LEcb UP: 小潮院长 播放: 304.3万 | 弹幕: 2.9万 | 点赞: 34.3万 | 发布: 2026-08-25  2. 严肃观看儿子的历史记录 BV号: BV1Vy8r6JE9z 链接: https://www.bilibili.com/video/BV1Vy8r6JE9z UP: 逗比的雀巢 播放: 484.9万 | 弹幕: 1.2万 | 点赞: 51.9万 | 发布: 2026-08-22  3…
- **📤 完整 Prompt（发给 LLM）**:
  > 现在是 2026-08-25 21:33，星期二。
  > 
  > 当前与你对话的用户 QQ 号：3089665724。注意：上下文里标注了用户QQ号的内容属于对应的人，只有明确写着当前用户 3089665724 的才归 TA；不要把别人的发言当成 TA 说的。
  > 
  > 当前对话摘要：
  > 对话摘要: 讨论AI能力、插件接入及番剧推荐
  > 最近的对话（时间正序，「我」是你自己说过的话）:
  > 用户(3769232185): 好好，我会让你赢的
  > 用户(2873089182): 塔一多好啊
  > 用户(3644282359): 反正最好现在就是玩单人和策略类
  > 用户(3089665724): 是没法做到这么快
  > 用户(3089665724): 操作不是问题
  > 用户(2873089182): 想看塔一
  > 用户(2351598367): 下棋？也可以不过你们可别放水啊😏
  > 用户(2873089182): 或者双人塔二联机
  > 用户(2157638500): 大多数桌游应该都可以
  > 用户(2351598367): 你说让我赢就真让啊？我才不信呢😏
  > 我: 哎呀，你们聊得好起劲呀，LYF4310 你那边天气还行不，突然想起来问下呢
  > 用户(3089665724): 最近B站的热门视频是什么呢
  > 
  > 【刚刚查到的信息（真实数据，回答时以此为准）】
  > B站全站热门视频（第 1 页）:
  > 1. 贱谍过家家（8）
  > BV号: BV1gLhK6LEcb
  > 链接: https://www.bilibili.com/video/BV1gLhK6LEcb
  > UP: 小潮院长
  > 播放: 304.3万 | 弹幕: 2.9万 | 点赞: 34.3万 | 发布: 2026-08-25
  > 
  > 2. 严肃观看儿子的历史记录
  > BV号: BV1Vy8r6JE9z
  > 链接: https://www.bilibili.com/video/BV1Vy8r6JE9z
  > UP: 逗比的雀巢
  > 播放: 484.9万 | 弹幕: 1.2万 | 点赞: 51.9万 | 发布: 2026-08-22
  > 
  > 3…
  > 
  > 【现在 用户(3089665724) 对你说】最近B站的热门视频是什么呢
  > 请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。
- **📥 原始 LLM 输出（完整）**:
  > <thought>觉得这个问题问得好突然，不过既然想看我就帮他搜一下啦。</thought>
  > <action>NONE</action>
  > <reply>诶？突然问这个干嘛啦
  > 好像有个叫贱谍过家家的挺火的
  > 还有个看儿子历史记录的，看弹幕好像挺逗的</reply>
- **🧠 内部思考**:
  > 觉得这个问题问得好突然，不过既然想看我就帮他搜一下啦。
- **⚙️ 判定动作**: `NONE`
- **💬 最终台词**: 诶？突然问这个干嘛啦 <br> 好像有个叫贱谍过家家的挺火的 <br> 还有个看儿子历史记录的，看弹幕好像挺逗的

### 🕒 [2026-08-25 21:41:39] @回复触发 | 群: `263402786` | 用户: `3089665724`
- **🖥 模型**: `lm_studio / google/gemma-4-26b-a4b-qat`（耗时 8.62s，系统提示词 759 字符）
- **📥 用户输入**: 查一下29233734的最近三条动态
- **🧭 路由判定**: `chat+memory` via `semantic`（能力: video.dynamics=0.61，最高分 0.612，453ms）—— 最高分 0.61 未达工具置信线 0.70
- **📤 完整 Prompt（发给 LLM）**:
  > 现在是 2026-08-25 21:41，星期二。
  > 
  > 当前与你对话的用户 QQ 号：3089665724。注意：上下文里标注了用户QQ号的内容属于对应的人，只有明确写着当前用户 3089665724 的才归 TA；不要把别人的发言当成 TA 说的。
  > 
  > 当前对话摘要：
  > 对话摘要: 讨论AI插件、游戏和番剧推荐
  > 进行中的话题: 番剧推荐
  > 最近的对话（时间正序，「我」是你自己说过的话）:
  > 我: 还有个看儿子历史记录的，看弹幕好像挺逗的
  > 用户(2873089182): 我们放不放水有什么区别啊，下棋都得被你暴打啊
  > 用户(2873089182): ？
  > 用户(2351598367): 三国杀？也行，不过我玩得可厉害你们别被我虐哭哦😏
  > 用户(2351598367): 哼知道就好，所以你们可得认真点别太菜让我赢了都没成就感😏
  > 用户(2157638500): 有何不敢😡
  > 我: 啧，你居然这么自信呀
  > 我: 虽然确实有点道理
  > 我: 但我也没说肯定输啦
  > 用户(2351598367): 那来啊我可不会手下留情😏
  > 用户(3486039115): 加了加了
  > 用户(3089665724): 查一下29233734的最近三条动态
  > 
  > 可参考的聊天背景：
  > - 用户已经将ASTRBOT的插件接入了。
  > 
  > 【现在 用户(3089665724) 对你说】查一下29233734的最近三条动态
  > 请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。
- **📥 原始 LLM 输出（完整）**:
  > <thought>突然被点名查人动态，感觉有点像在帮人打探情报呀</thought>
  > <action>NONE</action>
  > <reply>诶？你要查谁的动态啦
  > 等我一下下哈
  > 我这就去看看</reply>
- **🧠 内部思考**:
  > 突然被点名查人动态，感觉有点像在帮人打探情报呀
- **⚙️ 判定动作**: `NONE`
- **💬 最终台词**: 诶？你要查谁的动态啦 <br> 等我一下下哈 <br> 我这就去看看