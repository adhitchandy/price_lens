from dataclasses import dataclass

import pandas as pd

from .schemas import ScrapeReport


@dataclass
class ScrapeOutcome:
    raw_products: pd.DataFrame
    report: ScrapeReport
