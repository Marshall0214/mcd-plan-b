"""Constraint solver over complete baskets; all prices are integer RMB cents."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json


class InputError(ValueError):
    pass


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise InputError(f"{label} 必须是大于等于 {minimum} 的整数。")
    return value


def strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise InputError(f"{label} 必须是非空字符串组成的列表。")
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} 必须是非空字符串。")
    return value


def validate_items(items):
    if not isinstance(items, list) or not items:
        raise InputError("items 必须包含至少一个餐品。")
    for item in items:
        for key in ("slot", "code", "name"):
            text(item.get(key), key)
        integer(item.get("quantity"), "quantity", 1)
        strings(item.get("tags"), "tags")


def fingerprint(offer):
    data = {key: offer[key] for key in ("store_code", "items", "arguments")}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_bundle(bundle):
    if bundle.get("mode") not in ("demo", "live"):
        raise InputError("mode 必须是 demo 或 live。")
    request = bundle["request"]
    integer(request.get("budget_cents"), "budget_cents")
    if type(request.get("allow_store_change")) is not bool:
        raise InputError("allow_store_change 必须是布尔值。")
    strings(request.get("excluded_tags", []), "excluded_tags")
    required = request.get("required_slots")
    if not isinstance(required, list) or not required:
        raise InputError("required_slots 不能为空。")
    slots = set()
    for rule in required:
        slot = text(rule.get("slot"), "slot")
        if slot in slots:
            raise InputError("required_slots 的 slot 不能重复。")
        slots.add(slot)
        strings(rule.get("tags", []), "required tags")
        integer(rule.get("quantity", 1), "required quantity", 1)
    text(bundle["baseline"].get("store_code"), "baseline store_code")
    validate_items(bundle["baseline"]["items"])
    if not isinstance(bundle.get("offers"), list):
        raise InputError("offers 必须是列表。")
    ids = set()
    for offer in bundle["offers"]:
        for field in ("id", "store_code", "store_name"):
            text(offer.get(field), field)
        if offer["id"] in ids:
            raise InputError("offer id 不能重复。")
        ids.add(offer["id"])
        validate_items(offer.get("items"))
        integer(offer.get("total_cents"), "total_cents")
        if type(offer.get("available")) is not bool:
            raise InputError("available 必须是布尔值。")


def quote_problem(offer, now):
    quote = offer.get("quote", {})
    try:
        arguments = offer["arguments"]
        if arguments.get("storeCode") != offer["store_code"] or not arguments.get("items"):
            return "报价门店或购物篮缺失"
        if quote.get("tool") != "calculate-price" or quote.get("fingerprint") != fingerprint(offer):
            return "报价与餐品选择不匹配"
        result = quote["response"]
        if result.get("success") is not True or result["data"]["price"] != offer["total_cents"]:
            return "缺少成功的官方应付价"
        integer(result["data"]["price"], "official price")
        observed = datetime.fromisoformat(quote["observed_at"])
        if observed.tzinfo is None:
            return "报价时间缺少时区"
        age = (now - observed).total_seconds()
        if age < -30 or age > 300:
            return "报价超过五分钟或时间异常，请重新核价"
    except (KeyError, TypeError, ValueError):
        return "报价凭据不完整"
    return None


def violations(offer, bundle, now):
    request, issues = bundle["request"], []
    def add(code, message):
        issues.append({"constraint": code, "message": message})
    if not offer["available"]:
        add("availability", "餐品不可用或套餐组合未通过校验")
    if bundle["mode"] == "live":
        problem = quote_problem(offer, now)
        if problem:
            add("quote", problem)
    if offer["total_cents"] > request["budget_cents"]:
        excess = offer["total_cents"] - request["budget_cents"]
        add("budget", f"超出预算 ¥{excess / 100:.2f}")
    if not request["allow_store_change"] and offer["store_code"] != bundle["baseline"]["store_code"]:
        add("store", "需要更换门店，但当前未允许换店")
    excluded = set(request.get("excluded_tags", []))
    if any(excluded.intersection(item["tags"]) for item in offer["items"]):
        add("excluded_tags", "含有明确排除的餐品标签")
    for rule in request["required_slots"]:
        matches = sum(item["quantity"] for item in offer["items"]
                      if item["slot"] == rule["slot"] and set(rule.get("tags", [])).issubset(item["tags"]))
        if matches < rule.get("quantity", 1):
            add("slot:" + rule["slot"], f"未满足 {rule['slot']} 的标签或数量要求")
    return issues


def counts(items):
    result = Counter()
    for item in items:
        result[(item["slot"], item["code"])] += item["quantity"]
    return result


def similarity(offer, baseline):
    wanted, actual = counts(baseline["items"]), counts(offer["items"])
    weights = {"main": 5, "drink": 3, "side": 1}
    return sum(min(qty, actual[key]) * weights.get(key[0], 1) for key, qty in wanted.items())


def explanation(offer, baseline):
    before, after = counts(baseline["items"]), counts(offer["items"])
    kept, changed = [], []
    names = {(x["slot"], x["code"]): x["name"] for x in baseline["items"] + offer["items"]}
    for key, qty in before.items():
        same = min(qty, after[key])
        if same:
            kept.append(f"{names[key]} ×{same}")
        if qty > same:
            changed.append(f"减少 {names[key]} ×{qty - same}")
    for key, qty in after.items():
        if qty > before[key]:
            changed.append(f"增加 {names[key]} ×{qty - before[key]}")
    if offer["store_code"] != baseline["store_code"]:
        changed.append("更换门店为" + offer["store_name"])
    return kept, changed


def plan(bundle, now=None):
    validate_bundle(bundle)
    now = now or datetime.now(timezone.utc)
    feasible, rejected = [], []
    for offer in bundle["offers"]:
        issues = violations(offer, bundle, now)
        if issues:
            rejected.append({"id": offer["id"], "issues": issues})
        else:
            feasible.append(offer)
    baseline = bundle["baseline"]
    # Three perspectives; never pad the result with duplicate baskets.
    same = lambda o: o["store_code"] == baseline["store_code"]
    rankings = [
        ("最接近原单（原店优先）", sorted(feasible, key=lambda o: (not same(o), -similarity(o, baseline), o["total_cents"], o["id"]))),
        ("预算优先", sorted(feasible, key=lambda o: (o["total_cents"], not same(o), -similarity(o, baseline), o["id"]))),
        ("换店备选", sorted((o for o in feasible if not same(o)), key=lambda o: (-similarity(o, baseline), o["total_cents"], o["id"]))),
    ]
    selected, seen = [], set()
    for label, candidates in rankings:
        if not candidates:
            continue
        offer = candidates[0]
        signature = (offer["store_code"], json.dumps(offer.get("arguments", {}).get("items", offer["items"]), sort_keys=True))
        if signature in seen:
            continue
        seen.add(signature)
        kept, changed = explanation(offer, baseline)
        selected.append({**offer, "label": label, "kept": kept, "changed": changed,
                         "remaining_cents": bundle["request"]["budget_cents"] - offer["total_cents"]})
    # Only user-adjustable conflicts are suggested; bad availability/quotes are never relaxable.
    relaxations = []
    if not feasible:
        viable = [r for r in rejected if not any(x["constraint"] in ("availability", "quote") for x in r["issues"])]
        if viable:
            minimum = min(len(r["issues"]) for r in viable)
            relaxations = [r for r in viable if len(r["issues"]) == minimum][:3]
    return {"mode": bundle["mode"], "status": "ok" if selected else "no_solution",
            "budget_cents": bundle["request"]["budget_cents"], "plans": selected,
            "rejected": rejected, "relaxations": relaxations,
            "checked_count": len(bundle["offers"]), "feasible_count": len(feasible)}


def render(result):
    lines = ["# 麦麦补位", "", "演示数据 · 非实时价格" if result["mode"] == "demo" else "实时 MCP 核价 · 仅比较本次查询的候选组合",
             f"预算 ¥{result['budget_cents'] / 100:.2f}；检查 {result['checked_count']} 个组合，{result['feasible_count']} 个满足全部条件。", ""]
    for p in result["plans"]:
        lines += [f"## {p['label']} · ¥{p['total_cents'] / 100:.2f}", p["store_name"],
                  "餐品：" + "、".join(f"{x['name']} ×{x['quantity']}" for x in p["items"]),
                  "保留：" + ("、".join(p["kept"]) or "保留硬性需求，原单餐品均已替换"),
                  "调整：" + ("；".join(p["changed"]) or "餐品与门店均与原单一致"),
                  f"预算余量：¥{p['remaining_cents'] / 100:.2f}", ""]
    if not result["plans"]:
        lines += ["当前没有满足全部条件的方案。未自动放宽任何需求。", ""]
        for r in result["relaxations"]:
            lines.append("可讨论的调整（需用户选择）：" + "；".join(x["message"] for x in r["issues"]))
    if result["rejected"]:
        lines += ["", "未入选原因："]
        lines += [r["id"] + "：" + "；".join(x["message"] for x in r["issues"]) for r in result["rejected"]]
    lines += ["", "尚未创建订单。选定方案后需再次核价；实际价格及供应以官方渠道为准。"]
    return "\n".join(lines)
