"""Live MVP: chicken mains + explicitly named sugar-free drinks, pickup only.

Names/categories guide candidate selection; detail rounds provide real codes.
Complete baskets are always repriced. No membership purchase or coupon claiming.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import itertools

from .mcp import Client, MCPError, payload
from .planner import InputError, fingerprint, integer, text, validate_items


def food(code, name, slot, tags):
    return {"code": str(code), "name": name, "slot": slot, "tags": tags, "quantity": 1}


def business_data(result):
    value = payload(result)
    if not isinstance(value, dict) or value.get("success") is not True or "data" not in value:
        raise MCPError("官方业务查询未成功；请检查门店、时段与参数。")
    return value["data"]


def menu_price(entry):
    try:
        amount = Decimal(str(entry["currentPrice"]))
        return amount if amount.is_finite() and amount >= 0 else Decimal("Infinity")
    except (KeyError, InvalidOperation):
        return Decimal("Infinity")


def selected_round(round_info, choice):
    return {"round": str(round_info["id"]), "comboItemList": [{"code": choice["code"], "quantity": 1}]}


def build_candidates(call, store, main_name, drink_name):
    base = {"storeCode": store["storeCode"], "orderType": 1, "beType": 1}
    menu = business_data(call("query-meals", base))
    meals = menu.get("meals", {})
    categories = menu.get("categories", [])
    chicken_codes = {m["code"] for cat in categories if "鸡肉汉堡" in cat["name"] for m in cat["meals"]}
    beverage_codes = {m["code"] for cat in categories if "饮品" in cat["name"] for m in cat["meals"]}
    detail_cache = {}

    def detail(code):
        if code not in detail_cache:
            detail_cache[code] = business_data(call("query-meal-detail", {**base, "code": code}))
        return detail_cache[code]

    eligible = [(code, entry) for code, entry in meals.items()
                if code in chicken_codes and not entry.get("canWithOrder")]
    singles = sorted(((code, e) for code, e in eligible
                      if not any(word in e["name"] for word in ("套", "餐", "精选"))),
                     key=lambda pair: (pair[1]["name"] != main_name, menu_price(pair[1]), pair[0]))[:3]
    mains = []
    for code, entry in singles:
        if not detail(code).get("rounds"):
            mains.append((food(code, entry["name"], "main", ["chicken"]), {"productCode": code, "quantity": 1}))

    drinks = []
    # Bounded discovery avoids fetching every detail on a large menu.
    beverage_roots = [(code, e) for code, e in meals.items()
                      if code in beverage_codes and ("可乐" in e["name"] or "无糖" in e["name"])]
    for code, entry in beverage_roots[:3]:
        d = detail(code)
        if not d.get("rounds") and "无糖" in d["name"]:
            drinks.append((food(code, d["name"], "drink", ["sugar_free"]), {"productCode": code, "quantity": 1}))
        elif len(d.get("rounds", [])) == 1:
            r = d["rounds"][0]
            for choice in r["choices"]:
                if "无糖" in choice["name"]:
                    drinks.append((food(choice["code"], choice["name"], "drink", ["sugar_free"]),
                                   {"productCode": code, "quantity": 1, "roundList": [selected_round(r, choice)]}))
    drinks.sort(key=lambda pair: (pair[0]["name"] != drink_name, pair[0]["name"]))
    drinks = drinks[:2]
    candidates = []
    for main, drink in itertools.product(mains, drinks):
        candidates.append({"items": [main[0], drink[0]], "arguments": {**base, "items": [main[1], drink[1]]}})

    single_candidates = list(candidates)
    candidates = []
    packages = sorted(((code, e) for code, e in eligible if "套" in e["name"] or "餐" in e["name"]),
                      key=lambda pair: (menu_price(pair[1]), pair[0]))[:2]
    for code, entry in packages:
        d = detail(code)
        normalized, rounds = [], []
        valid = bool(d.get("rounds"))
        for r in d.get("rounds", []):
            # MVP only supports one required selection per round. Skip other layouts.
            if r.get("minQuantity") != 1 or r.get("maxQuantity") != 1:
                valid = False
                break
            if "饮料" in r["name"] or "饮品" in r["name"]:
                choices = [x for x in r["choices"] if "无糖" in x["name"]]
                choices.sort(key=lambda x: x["name"] != drink_name)
                slot, tags = "drink", ["sugar_free"]
            else:
                choices = [x for x in r["choices"] if x.get("isDefault") == 1]
                slot = "side" if "小食" in r["name"] else "main"
                tags = ["chicken"] if slot == "main" and choices and "鸡" in choices[0]["name"] else []
            if not choices:
                valid = False
                break
            chosen = choices[0]
            normalized.append(food(chosen["code"], chosen["name"], slot, tags))
            rounds.append(selected_round(r, chosen))
        if valid and any(x["slot"] == "main" and "chicken" in x["tags"] for x in normalized):
            candidates.append({"items": normalized, "arguments": {**base, "items": [
                {"productCode": code, "quantity": 1, "roundList": rounds}]}})

    # Include complete packages even when the pricing budget is small.
    candidates = single_candidates[:1] + single_candidates[2:3] + candidates + single_candidates[1:2] + single_candidates[3:]
    for index, candidate in enumerate(candidates):
        candidate.update(id=f"{store['storeCode']}-{index + 1}", store_code=store["storeCode"],
                         store_name=store["storeName"], available=True)
    return candidates, mains, drinks


def live_bundle(client: Client, *, city, keyword, budget_cents=3000, store_limit=2,
                max_quotes=12, allow_store_change=True,
                main_name="板烧鸡腿堡", drink_name="无糖可口可乐中杯", baseline_input=None, on_progress=None):
    integer(budget_cents, "budget_cents")
    if not 1 <= store_limit <= 3 or not 1 <= max_quotes <= 24:
        raise InputError("门店数须为 1–3，核价上限须为 1–24。")
    if baseline_input is not None:
        text(baseline_input.get("store_code"), "baseline store_code")
        validate_items(baseline_input.get("items"))
        main_name = next((x["name"] for x in baseline_input["items"] if x["slot"] == "main"), main_name)
        drink_name = next((x["name"] for x in baseline_input["items"] if x["slot"] == "drink"), drink_name)
    observations, failures = [], []

    def call(name, args):
        if on_progress:
            on_progress(name)
        response = client.call(name, args)
        observations.append({"tool": name, "arguments": args,
                             "observed_at": datetime.now(timezone.utc).isoformat(), "response": payload(response)})
        return response

    stores = business_data(call("query-nearby-stores", {"beType": 1, "searchType": 2,
                                                         "city": city, "keyword": keyword}))
    stores = [s for s in stores if s.get("businessStatus") is True]
    if not allow_store_change and baseline_input is not None:
        stores = [s for s in stores if s["storeCode"] == baseline_input["store_code"]]
    stores = stores[:store_limit if allow_store_change else 1]
    if not stores:
        raise InputError("本次查询未返回营业中的可用门店，请更换商圈或时段。")
    groups, baseline = [], baseline_input
    for store in stores:
        try:
            candidates, mains, drinks = build_candidates(call, store, main_name, drink_name)
            # Read available coupons; calculate-price remains the authority on actual discounts.
            call("query-store-coupons", {"storeCode": store["storeCode"], "orderType": 1, "beType": 1})
            groups.append(candidates)
            if baseline is None:
                main = next((x[0] for x in mains if x[0]["name"] == main_name), None)
                drink = next((x[0] for x in drinks if x[0]["name"] == drink_name), None)
                if main is None or drink is None:
                    raise InputError("原单餐品未能从首家门店菜单中完整确认；请用 --baseline-file 提供历史原单，或调整 --main、--drink。不会擅自更换原单。")
                baseline = {"store_code": store["storeCode"], "items": [main, drink]}
        except MCPError:
            failures.append({"store_code": store["storeCode"], "reason": "菜单、详情或优惠查询失败，该门店未用于推荐"})
    if baseline is None:
        raise InputError("未能获取可校验的原单与菜单，请稍后重试。")
    offers, attempted = [], 0
    # Interleave stores so the quote cap does not starve alternative stores.
    for row in itertools.zip_longest(*groups):
        for candidate in row:
            if candidate is None or attempted >= max_quotes:
                continue
            attempted += 1
            try:
                response = call("calculate-price", candidate["arguments"])
                result = payload(response)
                data = business_data(response)
                total = integer(data.get("price"), "官方应付总价（分）")
                candidate["total_cents"] = total
                candidate["quote"] = {"tool": "calculate-price", "observed_at": datetime.now(timezone.utc).isoformat(),
                                      "fingerprint": fingerprint(candidate), "response": result}
                offers.append(candidate)
            except (MCPError, InputError):
                failures.append({"candidate_id": candidate["id"], "reason": "官方核价失败，未用于推荐"})
    return {"mode": "live", "request": {"budget_cents": budget_cents, "allow_store_change": allow_store_change,
            "required_slots": [{"slot": "main", "tags": ["chicken"]}, {"slot": "drink", "tags": ["sugar_free"]}],
            "excluded_tags": []}, "baseline": baseline, "offers": offers,
            "failures": failures, "observations": observations,
            "scope": {"city": city, "keyword": keyword, "stores": len(stores), "attempted_quotes": attempted,
                      "candidate_count": sum(len(group) for group in groups), "max_quotes": max_quotes,
                      "note": "首版仅覆盖鸡肉主食与名称明确含无糖的饮品；不自动购卡、不宣称全局最低价。"}}
