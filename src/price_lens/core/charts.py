import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]


def make_chart_avg_price_country(df):
    data = (df[df["price_usd"].notna()]
            .groupby("origin_country")["price_usd"]
            .agg(avg_price="mean", listings="count")
            .reset_index()
            .sort_values("avg_price", ascending=True))
    if data.empty:
        return None
    overall = data["avg_price"].mean()
    colors  = [PALETTE[0] if v >= overall else PALETTE[1] for v in data["avg_price"]]
    fig, ax = plt.subplots(figsize=(9, max(4, len(data) * 0.38)))
    bars = ax.barh(data["origin_country"], data["avg_price"], color=colors, edgecolor="white")
    for bar, n in zip(bars, data["listings"]):
        w = bar.get_width()
        ax.text(w + overall * 0.01, bar.get_y() + bar.get_height() / 2,
                f"${w:,.0f}  (n={n})", va="center", fontsize=8.5)
    ax.axvline(overall, color="grey", linestyle="--", lw=1.4, label=f"Overall avg ${overall:.0f}")
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=PALETTE[0], label="Above avg"),
        Patch(facecolor=PALETTE[1], label="Below avg"),
        plt.Line2D([0],[0], color="grey", linestyle="--", lw=1.4, label=f"Avg ${overall:.0f}"),
    ], fontsize=9)
    ax.set_title("Average Price per Unit by Country (USD)", fontweight="bold", pad=10)
    ax.set_xlabel("Avg Price (USD)")
    ax.set_xlim(0, data["avg_price"].max() * 1.3)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_price_distribution(df):
    data = df["price_usd"].dropna()
    if data.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    ax.hist(data, bins=35, color=PALETTE[0], edgecolor="white", alpha=0.85)
    ax.axvline(data.mean(),   color="red",   linestyle="--", lw=1.6, label=f"Mean ${data.mean():.0f}")
    ax.axvline(data.median(), color="green", linestyle="--", lw=1.6, label=f"Median ${data.median():.0f}")
    ax.set_title("Price Distribution (USD)", fontweight="bold")
    ax.set_xlabel("Price (USD)"); ax.set_ylabel("Count")
    ax.legend(fontsize=9); ax.spines[["top","right"]].set_visible(False)

    ax2 = axes[1]
    if "product_type" in df.columns:
        order = (df[df["price_usd"].notna()]
                 .groupby("product_type")["price_usd"]
                 .median().sort_values(ascending=False).index)
        sns.boxplot(data=df[df["product_type"].isin(order)],
                    x="price_usd", y="product_type", order=order,
                    palette=PALETTE, ax=ax2, fliersize=2)
        ax2.set_title("Price by Product Type (USD)", fontweight="bold")
        ax2.set_xlabel("Price (USD)"); ax2.set_ylabel("")
        ax2.spines[["top","right"]].set_visible(False)

    plt.tight_layout()
    return fig

def make_chart_ratings(df):
    data = df["rating"].dropna()
    if data.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    ax.hist(data, bins=20, color=PALETTE[1], edgecolor="white", alpha=0.85)
    ax.axvline(data.mean(),   color="red",   linestyle="--", lw=1.6, label=f"Mean {data.mean():.2f}")
    ax.axvline(data.median(), color="green", linestyle="--", lw=1.6, label=f"Median {data.median():.2f}")
    ax.set_title("Rating Distribution", fontweight="bold")
    ax.set_xlabel("Rating (out of 5)"); ax.set_ylabel("Count")
    ax.legend(fontsize=9); ax.spines[["top","right"]].set_visible(False)

    ax2 = axes[1]
    if "product_type" in df.columns:
        avg_r = (df.dropna(subset=["rating"])
                 .groupby("product_type")["rating"]
                 .mean().sort_values(ascending=True))
        bars  = ax2.barh(avg_r.index, avg_r.values, color=PALETTE[2])
        for bar in bars:
            w = bar.get_width()
            ax2.text(w + 0.02, bar.get_y() + bar.get_height() / 2,
                     f"{w:.2f}", va="center", fontsize=9)
        ax2.axvline(4.0, color="grey", linestyle=":", lw=1.2, label="4.0 line")
        ax2.set_xlim(0, 5.5)
        ax2.set_title("Avg Rating by Product Type", fontweight="bold")
        ax2.set_xlabel("Avg Rating"); ax2.legend(fontsize=9)
        ax2.spines[["top","right"]].set_visible(False)

    plt.tight_layout()
    return fig

def make_chart_listings_by_country(df):
    data = df["origin_country"].value_counts().head(15)
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(9, max(4, len(data) * 0.38)))
    bars = ax.barh(data.index[::-1], data.values[::-1], color=PALETTE[0], edgecolor="white")
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{w:,.0f}", va="center", fontsize=9)
    ax.set_title("Listings per Country (Top 15)", fontweight="bold", pad=10)
    ax.set_xlabel("Number of Listings")
    ax.set_xlim(0, data.max() * 1.15)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_price_vs_rating(df):
    data = df.dropna(subset=["price_usd","rating"])
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    types   = data["product_type"].unique() if "product_type" in data.columns else ["All"]
    cmap    = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)}
    if "product_type" in data.columns:
        for pt, grp in data.groupby("product_type"):
            ax.scatter(grp["price_usd"], grp["rating"], label=pt,
                       color=cmap[pt], alpha=0.5, s=35, edgecolors="white", lw=0.3)
    else:
        ax.scatter(data["price_usd"], data["rating"], color=PALETTE[0], alpha=0.5, s=35)
    z  = np.polyfit(data["price_usd"], data["rating"], 1)
    xs = np.linspace(data["price_usd"].min(), data["price_usd"].max(), 200)
    ax.plot(xs, np.poly1d(z)(xs), "k--", lw=1.4, alpha=0.6, label="Trend")
    ax.set_title("Price vs. Rating", fontweight="bold", pad=10)
    ax.set_xlabel("Price (USD)"); ax.set_ylabel("Rating")
    ax.legend(fontsize=9, loc="lower right")
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_product_type_dist(df):
    if "product_type" not in df.columns:
        return None
    data = df["product_type"].value_counts()
    fig, ax = plt.subplots(figsize=(9, max(3, len(data) * 0.4)))
    bars = ax.barh(data.index[::-1], data.values[::-1],
                   color=PALETTE[:len(data)][::-1], edgecolor="white")
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{w:,.0f}", va="center", fontsize=9)
    ax.set_title("Listings by Product Type", fontweight="bold", pad=10)
    ax.set_xlabel("Count")
    ax.set_xlim(0, data.max() * 1.15)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig
