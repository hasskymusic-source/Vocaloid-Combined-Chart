import os
import json
from pathlib import Path
import tweepy

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_LATEST = BASE_DIR / "public" / "data" / "latest_ranking.json"

def get_twitter_client():
    consumer_key = os.environ.get("X_API_KEY")
    consumer_secret = os.environ.get("X_API_SECRET")
    access_token = os.environ.get("X_ACCESS_TOKEN")
    access_token_secret = os.environ.get("X_ACCESS_SECRET")
    
    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        print("[WARN] X API keys are missing. Skipping X post.")
        return None

    client = tweepy.Client(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=access_token,
        access_token_secret=access_token_secret
    )
    return client

def main():
    if not PUBLIC_LATEST.exists():
        print("[ERROR] Ranking data not found. Cannot post to X.")
        return

    with open(PUBLIC_LATEST, "r", encoding="utf-8") as f:
        data = json.load(f)

    period = data.get("period", "")
    songs = data.get("songs", [])[:3]

    tweet_lines = [
        "🏆【週刊VOCALOID複合ランキング】",
        f"集計期間: {period}",
        ""
    ]

    for s in songs:
        rank = s.get("rank")
        title = s.get("title", "")
        producer = s.get("producer", "")
        
        # 文字数制限対策：曲名とボカロP名を合わせて最大22文字に制限（超える場合は末尾を…にする）
        max_str_len = 22
        combined = f"{title} / {producer}"
        if len(combined) > max_str_len:
            combined = combined[:max_str_len-1] + "…"
            
        tweet_lines.append(f"{rank}位: {combined}")

    tweet_lines.extend([
        "",
        "🔽4位以降・詳細分析はこちら",
        "https://weekly-vocaloid-combined-chart.com",
        "#複合ボカラン #ボカロ #vocanew"
    ])

    tweet_text = "\n".join(tweet_lines)
    print("--- 投稿予定のテキスト ---")
    print(tweet_text)
    print("--------------------------")

    client = get_twitter_client()
    if client:
        try:
            response = client.create_tweet(text=tweet_text)
            print(f"[OK] Successfully posted to X: {response}")
        except Exception as e:
            print(f"[ERROR] Failed to post to X: {e}")

if __name__ == "__main__":
    main()