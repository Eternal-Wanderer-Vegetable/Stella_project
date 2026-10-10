# 插件接入规范 v1.0

此路径保留以兼容旧链接。当前正文请读[插件接入规范 v1.0](reference/plugin-spec.md).

下方保留原章节锚点并指向新位置；维护时修改目标正文。

<a id="0-适用范围与兼容性承诺"></a>

- [0. 适用范围与兼容性承诺](reference/plugin-spec.md#0-适用范围与兼容性承诺)

<a id="1-最小可跑插件"></a>

- [1. 最小可跑插件](reference/plugin-spec.md#1-最小可跑插件)

<a id="2-目录结构清单"></a>

- [2. 目录结构清单](reference/plugin-spec.md#2-目录结构清单)

<a id="3-两条接入通路怎么选"></a>

- [3. 两条接入通路怎么选](reference/plugin-spec.md#3-两条接入通路怎么选)

<a id="4-生命周期与加载时机"></a>

- [4. 生命周期与加载时机](reference/plugin-spec.md#4-生命周期与加载时机)

<a id="5-指令通路规范"></a>

- [5. 指令通路规范](reference/plugin-spec.md#5-指令通路规范)

<a id="6-工具通路规范核心"></a>

- [6. 工具通路规范（核心）](reference/plugin-spec.md#6-工具通路规范核心)

<a id="61-签名与-docstring-契约"></a>

- [6.1 签名与 docstring 契约](reference/plugin-spec.md#61-签名与-docstring-契约)

<a id="62-capabilitytoml-与三层优先级"></a>

- [6.2 `capability.toml` 与三层优先级](reference/plugin-spec.md#62-capabilitytoml-与三层优先级)

<a id="63-怎么写-examples"></a>

- [6.3 怎么写 `examples`](reference/plugin-spec.md#63-怎么写-examples)

<a id="64-怎么写-keywords"></a>

- [6.4 怎么写 `keywords`](reference/plugin-spec.md#64-怎么写-keywords)

<a id="65-返回值契约"></a>

- [6.5 返回值契约](reference/plugin-spec.md#65-返回值契约)

<a id="66-失败契约最容易写错的一条"></a>

- [6.6 失败契约（最容易写错的一条）](reference/plugin-spec.md#66-失败契约最容易写错的一条)

<a id="67-超时"></a>

- [6.7 超时](reference/plugin-spec.md#67-超时)

<a id="68-无参直调"></a>

- [6.8 无参直调](reference/plugin-spec.md#68-无参直调)

<a id="69-无聊天模型时的能力边界"></a>

- [6.9 无聊天模型时的能力边界](reference/plugin-spec.md#69-无聊天模型时的能力边界)

<a id="610-一个能力多个实现"></a>

- [6.10 一个能力多个实现](reference/plugin-spec.md#610-一个能力多个实现)

<a id="7-上下文预算契约8k"></a>

- [7. 上下文预算契约（8K）](reference/plugin-spec.md#7-上下文预算契约8k)

<a id="8-渲染契约"></a>

- [8. 渲染契约](reference/plugin-spec.md#8-渲染契约)

<a id="9-配置与数据"></a>

- [9. 配置与数据](reference/plugin-spec.md#9-配置与数据)

<a id="10-隐私与出网声明"></a>

- [10. 隐私与出网声明](reference/plugin-spec.md#10-隐私与出网声明)

<a id="11-兼容性矩阵"></a>

- [11. 兼容性矩阵](reference/plugin-spec.md#11-兼容性矩阵)

<a id="12-自检生成与发布"></a>

- [12. 自检、生成与发布](reference/plugin-spec.md#12-自检生成与发布)

<a id="13-调试"></a>

- [13. 调试](reference/plugin-spec.md#13-调试)

<a id="14-能力查询"></a>

- [14. 能力查询](reference/plugin-spec.md#14-能力查询)

<a id="15-版本与兼容策略"></a>

- [15. 版本与兼容策略](reference/plugin-spec.md#15-版本与兼容策略)

<a id="相关文档"></a>

- [相关文档](reference/plugin-spec.md#相关文档)

<a id="610-会话接入注意事项"></a>

- [6.1.0 会话接入注意事项](reference/plugin-spec.md#610-会话接入注意事项)
