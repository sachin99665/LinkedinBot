import os
import tweepy
from dotenv import load_dotenv
load_dotenv()

print("API Key starts with:", os.environ.get("TWITTER_API_KEY", "")[:10])
print("API Secret starts with:", os.environ.get("TWITTER_API_SECRET", "")[:10])
print("Access Token starts with:", os.environ.get("TWITTER_ACCESS_TOKEN", "")[:15])
print("Access Token Secret starts with:", os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")[:10])

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

try:
    r = client.create_tweet(text="Hello from bot test 🚀")
    print("✅ Success! Tweet ID:", r.data['id'])
except Exception as e:
    print("❌ Error:", e)