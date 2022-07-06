import json

from data.constants import CONFIG_DB

sample_config = {
    "bot": {
        "token": "bot_token",
        "allowed_users": ["000000000"],
    },
    "extensions": {
        "forta": {
            "pooling_interval": "300",
            "db_path": "forta.db",
            "url": "https://api.forta.network/stats/sla/scanner/",
        },
        "dummy": "",
    },
}

with open(CONFIG_DB, "w") as outfile:
    json.dump(sample_config, outfile)
