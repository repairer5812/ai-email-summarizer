from __future__ import annotations

import webmail_summary.llm.local_models as lm
import webmail_summary.llm.provider as prov


def test_standard_tier_budget_is_not_smaller_than_fast():
    fast_budget = prov._local_tier_budget("fast")
    standard_budget = prov._local_tier_budget("standard")

    assert standard_budget.max_tokens > fast_budget.max_tokens
    assert standard_budget.request_timeout_s >= fast_budget.request_timeout_s
    assert standard_budget.total_request_budget_s >= fast_budget.total_request_budget_s


def test_performance_tier_gets_largest_local_budget():
    standard_budget = prov._local_tier_budget("standard")
    performance_budget = prov._local_tier_budget("performance")

    assert performance_budget.max_tokens > standard_budget.max_tokens
    assert performance_budget.request_timeout_s >= standard_budget.request_timeout_s
    assert (
        performance_budget.total_request_budget_s
        >= standard_budget.total_request_budget_s
    )


def test_qwen_performance_model_maps_to_performance_budget():
    model = lm.get_local_model("qwen35_4b")
    budget = prov._local_tier_budget(model.tier)

    assert model.tier == "performance"
    assert budget.max_tokens == 512
    assert budget.request_timeout_s == 210.0
