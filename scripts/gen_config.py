import json

from constants import CONFIG_DB

sample_config = {"token": "secret:bot_token", "allowed_users": ["000000000"]}

with open(CONFIG_DB, "w") as outfile:
    json.dump(sample_config, outfile)
