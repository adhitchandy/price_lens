from argparse import Namespace
from pathlib import Path

import pandas as pd

from price_lens import cli
from price_lens.orchestrator.runner import ResearchRunResult


def test_health_subset_reports_batch_counts(monkeypatch, tmp_path):
    def run(plan, log):
        assert plan.marketplaces == {"mediamarkt": ("mediamarkt.de",)}
        rows = pd.DataFrame([{
            "marketplace": "mediamarkt.de", "product_id": "123", "currency_code": "EUR",
        }])
        report = {"platform_reports": {"mediamarkt": {
            "failures": [], "events": [
                {"marketplace": "mediamarkt.de", "status": "succeeded"},
                {"marketplace": "mediamarkt.de", "status": "no_next_control"},
            ],
        }}}
        return ResearchRunResult(tmp_path, rows, rows, report)

    monkeypatch.setattr(cli, "run_research", run)
    request = Path(__file__).parents[1] / "examples/mediamarkt_international_research_plan.json"
    assert cli.check_mediamarkt_marketplaces(Namespace(
        request=request, marketplaces=["mediamarkt.de"],
    )) == 0
    health = pd.read_csv(tmp_path / "marketplace_health.csv")
    assert health.iloc[0]["batches_succeeded"] == 1
    assert health.iloc[0]["pagination_stops"] == 1
