# astrbot_plugin_stella_template

Stella 插件接入规范的**模板插件**。它同时是三样东西：

1. 一份能直接拷走改名的骨架（两条接入通路各一个示例）；
2. `docs/plugin-spec.md` 的可执行注脚——规范里每条容易写错的约定，这里都有对应的一行代码或一段注释；
3. `deploy plugin-check` 的回归夹具——`tests/test_plugin_check.py` 拿它跑一遍校验器并断言**零 error、零 warn**。规范与校验器一旦漂移，那个测试先失败。

它在 AstrBot 上也能原样运行：导入路径全部是 `astrbot.api.*`，Stella 侧由 `astrbot_compat/shim.py` 把这些模块伪装进 `sys.modules`。

## 文件清单

| 文件 | 必需 | 作用 | AstrBot 是否也读 |
|---|---|---|---|
| `main.py` | 是 | 插件入口，加载器按它判定一个目录是不是插件 | 是 |
| `metadata.yaml` | 建议 | 名称 / 版本 / 作者；本模板还带 Stella 扩展字段 `stella.egress` | 是（`stella.*` 除外，多写不影响） |
| `capability.toml` | 有 `@llm_tool` 就必需 | 能力声明：**没有它，工具在聊天里永远不会被触发** | 否 |
| `_conf_schema.json` | 可选 | 配置项 schema，展开成 `self.config` 的默认值 | 是 |
| `requirements.txt` | 有第三方依赖才要 | 依赖清单 | 是 |

## 试一遍

```bash
python -m deploy plugin-check docs/examples/astrbot_plugin_stella_template
```

会执行该插件代码（与启动时相同的动作，校验器会在输出里明说这一点），然后打印 16 项检查的结论。

想真的装上去跑，把这个目录拷到 `data/plugins/` 下、改个自己的名字即可：

```
/模板                  # 指令通路：确定性触发
这段话有多少字         # 工具通路：经 Router 语义路由（靠 capability.toml 的 examples）
```

## 拷走之后要改什么

- `metadata.yaml` 的 `name` 要与目录名一致；`stella.egress` 按实际出网目标写，不出网就整段删掉
- `capability.toml` 的 `id` / `domain` / `description` / `examples` 全都要重写。**`examples` 写「用户会怎么问」**，4~6 句，每句一种问法——写成工具描述那种「当用户询问 X 时调用」会让同域工具之间几乎没有区分度（实测负样本余量 −0.024，换成问句 +0.141）。不想手写就跑 `python -m deploy plugin-scaffold <目录>` 生成草稿再人审
- `keywords` 默认别写。它是 Level 0 的字面命中、**命中即执行且不抽参数**，工具有必填参数时写它只是让 Comes 去猜那个值
- `_conf_schema.json` 里没被代码读到的键要删掉——留着它只会让用户以为改了有用

## 这里刻意演示的四件事

| # | 做法 | 不这么做会怎样 |
|---|---|---|
| 1 | 两条通路各写一个：`@filter.command` 指令 / `@filter.llm_tool` 工具 | 会发消息、下单、改外部状态的功能做成可路由工具，就会在**没有用户确认**的情况下被 Comes 调用 |
| 2 | 工具是只读、幂等的 | 同上 |
| 3 | 后台任务走 `self.context.register_task` | 裸 `asyncio.create_task` 起的任务在卸载与热重载后**残留并继续跑**，而这不报错 |
| 4 | 失败**抛异常**，不 `return "查询失败……"` | 那串字不以 `error:` 开头 → 被当成成功输出 → 贴上「真实数据」进 Stella 的 prompt，于是失败文案被当事实转述，而 provider 退避永远不触发（见 `docs/plugin-spec.md` §6.6） |

完整规范见 [`docs/plugin-spec.md`](../../plugin-spec.md)。
