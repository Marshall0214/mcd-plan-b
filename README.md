# 麦麦补位 · McDonald's Plan B

**想吃的没了、套餐需要换、预算超了？保留你最在意的需求，重新搭出一份合适的餐。**

这是一个基于麦当劳中国 MCP 的点餐替代方案 Skill，包含可执行的 Python 规划器、真实 MCP 只读查询流程，以及无需 Token 的离线演示。面向经常复购、需要控制单餐预算、有明确餐品偏好的用户。

## 先看效果

用户：

> 照上次那份点，最多 30 元。鸡肉主食和无糖饮料必须保留，其他可以换，也可以看看附近另一家。

麦麦补位将预算、饮品偏好、换店许可作为约束，给出至多三种方案：

| 视角 | 如何选择 | 解释什么 |
|---|---|---|
| 最接近原单 | 优先原店，再尽量保留原单餐品 | 保留了什么、替换了什么 |
| 预算优先 | 已成功核价的候选中整单应付价最低 | 金额与预算余量 |
| 换店备选 | 其他已查询门店中尽量保留原单 | 换店与餐品变化 |

同一个篮子不重复推荐。多个目标对应同一个方案时合并，因此可能只有一到两个方案。没有满足全部条件的方案时，会展示冲突并等待用户选择，不会自动把“无糖”换成“含糖”或放宽预算。

## 30 秒运行演示

需要 Python 3.11 或更新版本；核心、演示和 MCP 查询均无第三方运行依赖。

先进入项目目录（如果当前就在此 README 所在目录，可跳过 `cd`）：

```powershell
cd mcd-plan-b
```

然后执行：

```powershell
python -m mcd_plan_b demo --scenario budget
python -m mcd_plan_b demo --scenario unavailable
python -m mcd_plan_b demo --scenario combo
python -m mcd_plan_b demo --scenario impossible
```

四个场景分别展示超预算、原店餐品不可用、套餐组合调整、没有可行方案。演示使用虚构餐品、虚构编码和虚构价格，输出明确标注。`impossible` 返回退出码 2，表示正常完成查询但无解。

预算演示会输出：原店去掉非必需小食的 ¥29.00 方案、替换主食与饮料规格的 ¥22.00 方案，以及换店保留原单的 ¥29.80 方案。均为演示金额。

也可安装命令行入口：

```powershell
python -m pip install -e .
mcd-plan-b demo
```

## 连接真实麦当劳 MCP

从 [官方开放平台](https://open.mcd.cn/mcp) 申请 Token，将其配置为当前进程的 `MCD_MCP_TOKEN` 环境变量。程序从环境读取，不加载 `.env` 文件，也不接收命令行 Token 参数。

PowerShell 可以这样读取输入，避免把 Token 字面量写进命令历史：

```powershell
$mcdSecureToken = Read-Host 'MCP Token' -AsSecureString
$env:MCD_MCP_TOKEN = [System.Net.NetworkCredential]::new('', $mcdSecureToken).Password
python -m mcd_plan_b mcp tools
python -m mcd_plan_b live --city 苏州 --keyword 仁恒仓街 --budget 30
Remove-Item Env:MCD_MCP_TOKEN
```

`live` 默认以“板烧鸡腿堡＋无糖可口可乐中杯”为原单，查询最多两家营业门店、尝试核价最多 12 个组合。原单名称可由 `--main` 和 `--drink` 指定。默认值是演示这个工作流的参考原单，不代表已读取用户历史订单。

```powershell
python -m mcd_plan_b live --city 苏州 --keyword 仁恒仓街 --budget 28 --same-store
python -m mcd_plan_b live --city 苏州 --keyword 仁恒仓街 --budget 30 --stores 2 --max-quotes 12 --json
```

真实执行过的核验摘要见 [真实接入记录](docs/live-verification.md)。核价结果只对查询当时与当前账号有效，不能作为永久报价。

### 原单餐品已经下架

由 Skill 宿主查询 `order-list`，确认用户要复刻的订单后，标准化保存原单。例如以下结构中的编码必须替换为真实历史订单返回的编码：

```json
{
  "store_code": "历史门店编码",
  "items": [
    {"slot": "main", "code": "历史主食编码", "name": "历史主食名称", "quantity": 1, "tags": ["chicken"]},
    {"slot": "drink", "code": "历史饮品编码", "name": "历史无糖饮品名称", "quantity": 1, "tags": ["sugar_free"]}
  ]
}
```

保存到 `private/baseline.json`，然后：

```powershell
python -m mcd_plan_b live --city 苏州 --keyword 仁恒仓街 --budget 30 --baseline-file private/baseline.json
```

历史原单不要求当前仍在售；候选餐品则必须来自本次查询并成功核价。没有历史原单文件且无法在菜单中确认指定的原单时，会明确停止，不会偷偷更换原单。

### 在智能体中作为 Skill 使用

将本项目完整目录导入支持文件型 Skill 的宿主。Codex 可把整个 `mcd-plan-b` 目录复制到个人 Skills 目录；不要只复制 `SKILL.md`，它需要同目录的 Python 包、脚本和参考文件。也可以让智能体在当前项目中读取 [SKILL.md](SKILL.md)。

宿主自行管理麦当劳 MCP 连接时，参考 [mcp-config.example.json](mcp-config.example.json)。`${MCD_MCP_TOKEN}` 是环境变量占位符，是否展开取决于宿主；应在宿主的本地凭据配置中完成设置，不能将真实值保存进公开文件。

Skill 负责理解“照上次点”“薯条能换但饮料必须无糖”等自然语言；规划器负责校验标准化需求和候选。CLI 本身不包含语言模型，也不自动猜测自然语言意图。

## 可解释、可核验的实现

- **硬性需求先过滤：** 预算、必需槽位、已知标签、数量、排除项和换店许可全部满足后才能推荐。
- **整单核价：** 使用 `calculate-price` 的 `data.price`，不把菜单价相加，不自己推测券叠加，也不自动购买会员卡。
- **套餐保留真实选择：** 查询详情后提交实际 `roundList`，例如将套餐默认含糖饮料替换为明确可选的无糖饮料。
- **防止报价误配：** 指纹绑定门店、组成项和完整调用参数；五分钟后必须重新核价。指纹是本地一致性校验，不是官方签名。
- **不擅自下单：** CLI 仅允许只读工具。用户选定并授权后，可由宿主按 Skill 指引重新核价并创建订单。

原始查询、参数、时间与报价保存在 `private/live-bundle.json`，该目录被 Git 忽略。它可能包含个人优惠信息，公开项目或提交比赛前不要上传。程序不会把 Token 写入这些文件。

标准化协议与扩展方法见 [输入格式](references/input-format.md)，工具与业务链路见 [MCP_INTEGRATION.md](MCP_INTEGRATION.md)。

## 当前覆盖范围

自动实时流程优先覆盖**到店场景的鸡肉主食＋名称明确含“无糖”的饮品**，以及每轮必选一项的鸡肉套餐。不覆盖全部菜单、外送、营养优化、任意复杂套餐或自动历史订单解析。未知结构会跳过；不保证全局最低价或取餐时间。

规划器支持其他明确标签、数量和槽位，宿主可依照当前 MCP Schema 构造输入扩展场景。名称与类别用于普通口味偏好，不构成过敏原或营养安全保证。

## 验证与打包

```powershell
python -m unittest discover -s tests -v
python scripts/package.py
python scripts/check_release.py
```

测试均使用虚构数据和模拟传输，不消耗用户权益。打包输出 `dist/mcd-plan-b.zip`，使用白名单收集项目文件，不包含 `private/`、`.env`、缓存或本地凭据。

退出码：`0` 有可行方案或查询成功，`1` 输入/接口错误，`2` 查询成功但无可行方案。

## 参赛材料

本仓库包含 README、原样复制的官方 `CONTEST_DECLARATION.md`、MCP 接入说明、配置示例、Skill 和源代码。报名规则及官方入口见 [麦当劳程序员创意开发大赛](https://github.com/M-China/mcd-developer-innovation-challenge)。未提供 `workbuddy.md`，因为本次开发没有真实使用 WorkBuddy。

本项目由参赛者独立开发，非麦当劳官方产品。价格、供应和优惠以官方渠道的实时结果为准。

## 开源许可

本项目原创代码和文档采用 [MIT License](LICENSE)。官方参赛声明保留原文，其权利及适用条款以官方发布为准；麦当劳名称、商标及第三方内容不属于本项目的许可授权范围。
