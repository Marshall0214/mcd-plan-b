import unittest

from mcd_plan_b.live import live_bundle
from mcd_plan_b.planner import InputError, plan


class FakeMCP:
    """Fictional products with the same field shapes as discovered official tools."""
    def __init__(self):
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "query-nearby-stores":
            data = [{"storeCode": s, "storeName": "演示" + s, "businessStatus": True} for s in ["A", "B"]]
        elif name == "query-meals":
            data = {"categories": [
                {"name": "鸡肉汉堡/卷", "meals": [{"code": "main"}, {"code": "cheap"}, {"code": "combo"}]},
                {"name": "饮品", "meals": [{"code": "cola"}]}],
                "meals": {"main": {"name": "板烧鸡腿堡", "currentPrice": "24"},
                          "cheap": {"name": "麦香鸡", "currentPrice": "17"},
                          "cola": {"name": "可乐", "currentPrice": "9.5"},
                          "combo": {"name": "鸡腿堡三件套", "currentPrice": "26.9"}}}
        elif name == "query-meal-detail":
            code = args["code"]
            data = {"code": code, "name": code, "rounds": []}
            if code == "cola":
                data["rounds"] = [{"id": 1, "minQuantity": 1, "maxQuantity": 1, "choices": [
                    {"code": "sweet", "name": "可乐中杯", "isDefault": 1},
                    {"code": "zero", "name": "无糖可口可乐中杯", "isDefault": 0}]}]
            if code == "combo":
                data["rounds"] = [{"id": 1, "name": "鸡腿堡", "minQuantity": 1, "maxQuantity": 1,
                                   "choices": [{"code": "chicken", "name": "鸡腿堡", "isDefault": 1}]},
                                  {"id": 2, "name": "选择套餐内饮料", "minQuantity": 1, "maxQuantity": 1,
                                   "choices": [{"code": "sweet", "name": "可乐中杯", "isDefault": 1},
                                               {"code": "zero", "name": "无糖可口可乐中杯", "isDefault": 0}]}]
        elif name == "query-store-coupons":
            data = []
        elif name == "calculate-price":
            root = args["items"][0]["productCode"]
            data = {"price": {"main": 3300, "cheap": 2400, "combo": 2390}[root]}
        else:
            raise AssertionError("Unexpected tool: " + name)
        return {"structuredContent": {"success": True, "data": data}}


class LiveTests(unittest.TestCase):
    def test_end_to_end_real_shape_and_price_authority(self):
        c = FakeMCP()
        bundle = live_bundle(c, city="演示", keyword="演示", max_quotes=6)
        result = plan(bundle)
        self.assertEqual(bundle["scope"]["attempted_quotes"], 6)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["plans"][0]["total_cents"], 2390)
        self.assertTrue(any(x["tool"] == "query-store-coupons" for x in bundle["observations"]))
        priced_combos = [args for name, args in c.calls if name == "calculate-price" and args["items"][0]["productCode"] == "combo"]
        self.assertEqual(priced_combos[0]["items"][0]["roundList"][1]["comboItemList"][0]["code"], "zero")

    def test_quote_cap_is_honored_and_alternative_store_included(self):
        c = FakeMCP()
        live_bundle(c, city="演示", keyword="演示", max_quotes=2)
        calls = [args for name, args in c.calls if name == "calculate-price"]
        self.assertEqual(len(calls), 2)
        self.assertEqual({x["storeCode"] for x in calls}, {"A", "B"})

    def test_same_store_does_not_query_second_menu(self):
        c = FakeMCP()
        live_bundle(c, city="演示", keyword="演示", allow_store_change=False)
        self.assertEqual({args["storeCode"] for name, args in c.calls if name == "query-meals"}, {"A"})

    def test_unknown_original_is_not_silently_replaced(self):
        with self.assertRaises(InputError):
            live_bundle(FakeMCP(), city="演示", keyword="演示", main_name="不存在的原单")

    def test_historical_unavailable_original_can_find_replacement(self):
        baseline = {"store_code": "A", "items": [
            {"code": "retired", "name": "已下架鸡肉堡", "slot": "main", "tags": ["chicken"], "quantity": 1},
            {"code": "zero", "name": "无糖可口可乐中杯", "slot": "drink", "tags": ["sugar_free"], "quantity": 1}]}
        bundle = live_bundle(FakeMCP(), city="演示", keyword="演示", baseline_input=baseline)
        result = plan(bundle)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(any("已下架鸡肉堡" in change for change in result["plans"][0]["changed"]))

    def test_bounds_are_checked_before_network(self):
        c = FakeMCP()
        with self.assertRaises(InputError):
            live_bundle(c, city="演示", keyword="演示", max_quotes=25)
        self.assertEqual(c.calls, [])


if __name__ == "__main__":
    unittest.main()
