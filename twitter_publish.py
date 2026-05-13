# twitter_publish.py (v2)
import os
import tweepy

def twitter_configured() -> bool:
    required = [
        "TWITTER_API_KEY",
        "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_TOKEN_SECRET",
    ]
    return all(os.environ.get(key) for key in required)

def publish_to_twitter(content: str) -> str:
    if not twitter_configured():
        raise RuntimeError("Twitter credentials missing.")

    client = tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )

    if len(content) > 280:
        content = content[:277] + "..."

    response = client.create_tweet(text=content)
    tweet_id = response.data['id']
    
    # Username nikaalne ke liye ek extra call (optional)
    me = client.get_me()
    username = me.data.username
    tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
    return tweet_url