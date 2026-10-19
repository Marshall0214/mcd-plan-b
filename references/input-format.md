# 标准化输入协议

执行 `python -m mcd_plan_b plan --input path.json`；输入使用 UTF-8 JSON。
完整离线范例见 `mcd_plan_b/fixtures/demo.json`。可从该文件修改需求与候选，保持 `mode: demo`。

| 字段 | 含义 |
|---|---|
| mode | `demo` 或 `live`，输出明确标识 |
| request.budget_cents | 非负整数，人民币分，含优惠后整单费用 |
| request.allow_store_change | 布尔值 |
| request.required_slots | 至少一个 `{slot, tags, quantity?}`，quantity 默认为 1 |
| request.excluded_tags | 全购物篮排除标签列表 |
| baseline | `{store_code, items}`，原单可以当前不可用，但须基于已知原单 |
| offers | 完整购物篮列表，不是单品价格表 |
| offers[].id | 非空、唯一的候选 ID |
| offers[].store_code / store_name | 门店编码与名称 |
| offers[].available | 布尔值；明确不可用时为 false |
| offers[].items | `{slot, code, name, quantity, tags}` 列表；套餐展开为实际选中的组成项 |
| offers[].total_cents | 官方整单最终应付价，不是菜单展示价；演示使用虚构金额 |

`slot` 常用 `main`、`drink`、`side`，也支持其他槽位；`tags` 是已核实的字符串列表。数量必须为正整数。同槽位同时符合全部要求标签的餐品数量之和须达到所需数量。排除标签检查所有组成项。未知信息不满足必需标签。

匹配排序：先同门店，再最大化与原单一致的餐品数量权重（主食 5、饮品 3、小食 1、其他 1），同分时选低价。预算方案按候选中的最低价，平价优先原店，再考虑原单相似度。换店方案按相似度与价格排序。每类只取其真实第一名，重复篮子合并，所以可能只有 1–2 个方案。

## 真实报价附加字段

`live` 模式每个 offer 还需要：

```json
{
  "arguments": {
    "storeCode": "来自实时查询",
    "orderType": 1,
    "beType": 1,
    "items": [{"productCode": "真实商品编码", "quantity": 1}]
  },
  "quote": {
    "tool": "calculate-price",
    "observed_at": "带时区的 ISO 8601 时间",
    "fingerprint": "planner.fingerprint(offer) 的结果",
    "response": {"success": true, "data": {"price": 2500}}
  }
}
```

`quote.response` 应存放实际工具返回解码后的完整业务对象，以上仅为字段结构示意。实测到店业务 `data.price` 为人民币分。未来字段或单位变化时，适配代码后再使用；不能回退到猜测字段或展示价。

`fingerprint` 绑定门店、标准化组成项、完整请求参数（包括套餐选项、优惠券、预约时间等）。核价后任何这些信息变化都需要重算。指纹是本地防误配机制，不是服务端签名，不能证明手动编辑文件的真实性；不得把它用于对外审计认证。宿主从菜单到标准化标签和实际请求的映射仍需核实。

有效报价须成功、金额相同、带时区且在五分钟内。过期或失败的报价、不可用的餐品不出现在放宽需求建议中；它们需要重新查询。

无解时 `relaxations` 只列出与某个已核价候选有关的、条数最少的需求冲突，不是数学意义上的不可满足核，也不自动放宽任何条件。
