import pandas as pd


def apply_cleaning(df, opts):
    original_len = len(df)
    log = []

    if opts.get("remove_sponsored"):
        before = len(df)
        if "sponsored" in df.columns:
            mask = df["sponsored"].fillna(False).astype(bool)
        else:
            mask = df["product_name"].str.strip().str.lower().str.startswith(
                "sponsored", na=False
            )
        df   = df[~mask]
        log.append(f"Removed **{before - len(df)}** sponsored listings")

    if opts.get("remove_no_price"):
        before = len(df)
        df     = df[df["price_usd"].notna() & (df["price_usd"] > 0)]
        log.append(f"Removed **{before - len(df)}** rows with missing/zero price")

    if opts.get("remove_no_rating"):
        before = len(df)
        df     = df[df["rating"].notna()]
        log.append(f"Removed **{before - len(df)}** rows with no rating")

    if opts.get("remove_outliers"):
        before = len(df)
        pct    = opts.get("outlier_pct", 99) / 100
        cap    = df["price_usd"].quantile(pct)
        if pd.notna(cap):
            df = df[df["price_usd"].isna() | (df["price_usd"] <= cap)]
            log.append(
                f"Removed **{before - len(df)}** price outliers "
                f"(above {opts['outlier_pct']}th pct = ${cap:.0f})"
            )
        else:
            log.append("Skipped price outliers because no numeric prices were available")

    if opts.get("remove_duplicates"):
        before = len(df)
        df     = df.drop_duplicates(subset=["product_name", "origin_country", "price_usd"])
        log.append(f"Removed **{before - len(df)}** duplicate rows")

    log.append(f"**{len(df):,}** rows remain (from {original_len:,})")
    return df.reset_index(drop=True), log
