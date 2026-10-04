from agenteval.rubric.pipeline import validate_partial_order

def test_partial_order_keeps_only_discriminative_items():
    strong = [{"R1": 1, "R2": 1, "R3": 0}, {"R1": 1, "R2": 1, "R3": 1}]
    weak = [{"R1": 0, "R2": 1, "R3": 0}, {"R1": 0, "R2": 1, "R3": 1}]
    v = validate_partial_order(strong, weak)
    assert v["R1"]["valid"] and not v["R2"]["valid"]   # R2 两侧都满足 → 不区分 → 丢
    assert not v["R3"]["valid"]                          # R3 两侧一样 → 丢
