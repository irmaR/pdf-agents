import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from chargeback_bot.main import run_pipeline

GOLDEN_CASES = [
    {
        "input": {"po": "PO-8821", "code": "SS", "amount": 240},
        "expected_status": "auto_drafted",
        "expected_flags": [],
    },
    {
        "input": {"po": "PO-9034", "code": "LD", "amount": 180},
        "expected_status": "human_review",
        "expected_flags": ["Missing BOL"],
    },
]


def test_edge_case_detection():
    for case in GOLDEN_CASES:
        result = run_pipeline(case["input"])
        assert result["status"] == case["expected_status"]
        for flag in case["expected_flags"]:
            assert any(flag in f for f in result["flags"])


def test_full_pipeline_clean():
    result = run_pipeline("sample_clean.pdf")
    assert result["status"] == "auto_drafted"
