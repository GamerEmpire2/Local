from ytmusicapi import YTMusic, OAuthCredentials

ytmusic = YTMusic("oauth.json", oauth_credentials=OAuthCredentials(client_id="", client_secret=""))

try:
    # This call requires authentication. If it works, you are logged in!
    user_info = ytmusic.get_account_info()
    print("Success! Logged in as:", user_info['accountName'])
except Exception as e:
    print("OAuth Failed. Error:", e)