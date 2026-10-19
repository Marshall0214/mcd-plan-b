"""Explicitly fictional fixtures; no official product IDs or current prices."""
from importlib.resources import files
import json


def demo_bundle(scenario="budget"):
    bundle = json.loads(files("mcd_plan_b").joinpath("fixtures/demo.json").read_text(encoding="utf-8"))
    if scenario == "unavailable":
        bundle["request"]["budget_cents"] = 4500
        for offer in bundle["offers"]:
            if offer["store_code"] == "DEMO-A" and any(x["code"] == "DEMO-GRILL" for x in offer["items"]):
                offer["available"] = False
    elif scenario == "combo":
        bundle["request"]["budget_cents"] = 2800
        bundle["request"]["allow_store_change"] = False
    elif scenario == "impossible":
        bundle["request"]["budget_cents"] = 1000
    return bundle
