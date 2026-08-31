# AIsa Go-to-Market（市场进入情报）

**作者：** aisa-team
**版本：** 0.1.0
**类型：** tool（工具）

为你的 Dify 智能体提供高级 GTM（市场进入）数据——竞品流量情报、关键词研究、社交聆听、B2B 客户开发、创作者发现、AI 答案引擎可见度——全部通过**一个 AIsa API 密钥**完成。

[English documentation / 英文文档](README.md)

## 为什么选择这个插件

自建 GTM 自动化通常意味着分别注册、签约并支付 Similarweb、Semrush、Ahrefs、DataForSEO、Apollo、Tavily、Oxylabs 以及多个社交 API——直接采购成本相当于**每月 $4,859 以上**。[AIsa Go-to-Market 套餐](https://aisa.one/solutions/go-to-market)将它们整合到一个密钥之后，**每月 $39，内含 $50 API 额度**。本插件把这些能力封装为七个专用工具，供 Dify 智能体与工作流直接调用。

## 工具列表

| 工具 | 数据来源 | 智能体能做什么 |
|---|---|---|
| **网络研究** | Tavily | 搜索实时网页、提取页面内容、爬取网站、生成站点 URL 地图 |
| **流量情报** | Similarweb + Ahrefs | 域名流量、互动、受众地域与人群画像、相似网站、技术栈、域名权重 |
| **关键词与 SEO** | Semrush + DataForSEO | 关键词搜索量、难度、建议，域名的自然关键词与竞争对手，外链概况 |
| **社交聆听** | X、Reddit、Instagram、Pinterest、YouTube | 搜索品牌提及与讨论、查询公开主页（只读） |
| **客户开发** | Apollo | 按职位/地区/公司规模搜索联系人、搜索公司、按域名补全公司信息 |
| **创作者发现** | WaveInflu | 基于种子 YouTube/TikTok 账号发现相似创作者、查询创作者联系邮箱 |
| **AI 可见度** | Oxylabs | 查看 ChatGPT、Gemini、Perplexity、Google AI Mode 如何回答买家式问题（GEO/AEO） |

### 示例提示词

- "拆解 linear.app——他们规模多大，和谁竞争？"
- "AI 会议纪要产品在德国应该优先做哪些关键词？"
- "这周 X 和 Reddit 上大家怎么讨论我们的品牌？"
- "找出美国 11-50 人 SaaS 公司的增长负责人名单。"
- "找到与这个频道相似的 YouTube 创作者，并拿到前 3 位的联系邮箱。"
- "当用户问 ChatGPT'最适合初创公司的 CRM'时，会提到我们吗？"

## 安装配置

1. **获取 AIsa API 密钥** —— 订阅 [Go-to-Market 套餐](https://aisa.one/solutions/go-to-market)（每月 $39，含 $50 API 额度；超出部分按用量计费）。
2. 在 Dify 中**安装本插件**，打开提供商设置并粘贴密钥。密钥校验是免费的——插件通过 AIsa 账户余额接口验证，不消耗额度。
3. 在 Agent 应用或工作流中**挂载工具**。七个工具共享同一个凭据。

### 连接要求

插件仅向 **`api.aisa.one`** 发起出站 HTTPS（443 端口）请求——不访问其他主机、无入站连接、无遥测。运行在 Dify 标准插件运行时中，使用默认权限（无需存储、模型或端点权限）。

## 使用须知

- **计费**按调用量通过你的 AIsa 账户结算（例如 Semrush 关键词查询每次成功调用 $0.09；失败调用不计费）。额度用尽时，工具会返回带充值链接的明确错误，而不是静默失败。
- **流量数据延迟**：Similarweb 月度指标约滞后当前日期两个月。日期参数留空即可，工具会自动选择有效的时间窗口。
- **分隔符**：关键词难度最多 20 个关键词，用 `;` 分隔；搜索量最多 100 个，用 `,` 分隔。
- **国家定位**：支持两位代码或全名（"de"、"Germany"），已映射 30+ 市场的本地化关键词数据。
- **TikTok** 内容搜索上游暂不可用；但仍可通过"创作者发现"找到 TikTok 创作者。
- **AI 可见度**查询会在上游渲染真实答案引擎会话，最长约需 2 分钟。
- 所有工具均为**只读**：不会代表你发布、发送或联系任何人。

## 隐私

工具输入（查询词、域名、关键词、URL）会转发至 AIsa API 以完成请求；插件本身不存储任何数据。详见 [PRIVACY.md](PRIVACY.md)。

## 支持

- 源码仓库：[github.com/AIsa-team/dify-gtm-plugin-source](https://github.com/AIsa-team/dify-gtm-plugin-source)
- AIsa 文档：[aisa.one/docs](https://aisa.one/docs)
- 套餐与定价：[aisa.one/solutions/go-to-market](https://aisa.one/solutions/go-to-market)
- 联系方式：haoyang@aisa.one
