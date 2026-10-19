from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from mcd_plan_b.demo import demo_bundle
from mcd_plan_b.planner import InputError, fingerprint, plan, render, similarity


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.bundle = demo_bundle()
        self.now = datetime(2026, 10, 19, 5, tzinfo=timezone.utc)

    def live(self):
        self.bundle["mode"] = "live"
        for offer in self.bundle["offers"]:
            offer["arguments"] = {"storeCode": offer["store_code"], "orderType": 1, "beType": 1,
                                  "items": [{"productCode": x["code"], "quantity": x["quantity"]} for x in offer["items"]]}
            offer["quote"] = {"tool": "calculate-price", "observed_at": self.now.isoformat(),
                              "fingerprint": fingerprint(offer),
                              "response": {"success": True, "data": {"price": offer["total_cents"]}}}

    def test_three_meaningfully_different_choices(self):
        result = plan(self.bundle)
        self.assertEqual([x["id"] for x in result["plans"]], ["keep-main", "replace-main", "other-store"])
        self.assertTrue(all(p["total_cents"] <= 3000 for p in result["plans"]))

    def test_sugar_free_is_hard_requirement(self):
        result = plan(self.bundle)
        rejected = {r["id"]: r for r in result["rejected"]}
        self.assertEqual(rejected["sugary-cheap"]["issues"][0]["constraint"], "slot:drink")

    def test_unavailable_food_is_never_recommended(self):
        result = plan(demo_bundle("unavailable"))
        self.assertTrue(all(p["id"] not in ("original", "keep-main") for p in result["plans"]))

    def test_same_store_is_hard_requirement(self):
        self.bundle["request"]["allow_store_change"] = False
        result = plan(self.bundle)
        self.assertTrue(all(p["store_code"] == "DEMO-A" for p in result["plans"]))

    def test_exclusions_check_sides_too(self):
        self.bundle["offers"][1]["items"][0]["tags"].append("excluded")
        self.bundle["request"]["excluded_tags"] = ["excluded"]
        self.assertNotIn("keep-main", [x["id"] for x in plan(self.bundle)["plans"]])

    def test_no_solution_does_not_relax_requirements(self):
        bundle = demo_bundle("impossible")
        before = deepcopy(bundle)
        result = plan(bundle)
        self.assertEqual(result["status"], "no_solution")
        self.assertEqual(result["plans"], [])
        self.assertTrue(result["relaxations"])
        self.assertEqual(bundle, before)

    def test_unknown_tags_do_not_pass(self):
        self.bundle["offers"] = [self.bundle["offers"][1]]
        self.bundle["offers"][0]["items"][1]["tags"] = []
        self.assertEqual(plan(self.bundle)["status"], "no_solution")

    def test_quantity_is_not_inferred_from_presence(self):
        self.bundle["request"]["required_slots"][0]["quantity"] = 2
        self.assertEqual(plan(self.bundle)["status"], "no_solution")

    def test_similarity_counts_duplicate_lines_correctly(self):
        offer = self.bundle["offers"][1]
        before = similarity(offer, self.bundle["baseline"])
        offer["items"].append(deepcopy(offer["items"][0]))
        self.assertEqual(similarity(offer, self.bundle["baseline"]), before)

    def test_bad_money_and_boolean_quantities_rejected(self):
        for value in (-1, 3000.0, True, "3000"):
            with self.subTest(value=value):
                b = deepcopy(self.bundle)
                b["request"]["budget_cents"] = value
                with self.assertRaises(InputError):
                    plan(b)
        self.bundle["offers"][0]["items"][0]["quantity"] = True
        with self.assertRaises(InputError):
            plan(self.bundle)

    def test_duplicate_offer_ids_rejected(self):
        self.bundle["offers"][1]["id"] = "original"
        with self.assertRaises(InputError):
            plan(self.bundle)

    def test_best_price_already_selected_is_merged_not_replaced(self):
        self.bundle["offers"] = [self.bundle["offers"][1], self.bundle["offers"][2]]
        self.bundle["offers"][0]["total_cents"] = 2000
        self.assertEqual([p["id"] for p in plan(self.bundle)["plans"]], ["keep-main"])

    def test_zero_budget_is_a_valid_request(self):
        self.bundle["request"]["budget_cents"] = 0
        self.assertEqual(plan(self.bundle)["status"], "no_solution")

    def test_valid_bound_live_quotes(self):
        self.live()
        self.assertEqual(plan(self.bundle, self.now)["status"], "ok")

    def test_stale_quotes_never_become_relaxation_suggestions(self):
        self.live()
        result = plan(self.bundle, self.now + timedelta(minutes=6))
        self.assertEqual(result["status"], "no_solution")
        self.assertEqual(result["relaxations"], [])

    def test_changed_basket_or_tag_invalidates_quote(self):
        self.live()
        for offer in self.bundle["offers"]:
            offer["arguments"]["items"][0]["quantity"] += 1
        self.assertEqual(plan(self.bundle, self.now)["status"], "no_solution")

    def test_fabricated_total_rejected(self):
        self.live()
        for offer in self.bundle["offers"]:
            offer["total_cents"] = 1
        self.assertEqual(plan(self.bundle, self.now)["status"], "no_solution")

    def test_missing_or_naive_quote_time_rejected(self):
        self.live()
        for timestamp in ("invalid", "2026-10-19T05:00:00", "2026-10-20T05:00:00+00:00"):
            with self.subTest(timestamp=timestamp):
                b = deepcopy(self.bundle)
                for offer in b["offers"]:
                    offer["quote"]["observed_at"] = timestamp
                self.assertEqual(plan(b, self.now)["status"], "no_solution")

    def test_demo_is_visibly_labelled(self):
        self.assertIn("演示数据 · 非实时价格", render(plan(self.bundle)))


if __name__ == "__main__":
    unittest.main()
