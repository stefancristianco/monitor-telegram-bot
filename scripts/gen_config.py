#!/usr/bin/env python3

"""
Helper script to generate config template.
"""
import json

from data.constants import CONFIG_DB


def main() -> None:
    """
    This function will initiate and start script.
    :return: None
    """
    sample_config = {
        "bot": {
            "token": "bot_token",
            "allowed_users": ["000000000"],
        },
        "extensions": {
            "forta": {
                "scanner_pool_interval": "300",
                "wallet_pool_interval": "30",
                "db_path": "forta.json",
                "url": "https://api.forta.network/stats/sla/scanner/",
                "chains": {
                    "eth": {
                        "url": "wss://...",
                        "token": "0x41545f8b9472D758bB669ed8EaEEEcD7a9C4Ec29",
                    },
                    "matic": {
                        "url": "wss://...",
                        "token": "0x9ff62d1FC52A907B6DCbA8077c2DDCA6E6a9d3e1",
                    },
                },
                "description": "Scanner node monitoring and alerts extension.",
            },
            # "dummy": {"description": "Sample extension."},
        },
    }
    with open(CONFIG_DB, "w") as outfile:
        json.dump(sample_config, outfile)


if __name__ == "__main__":
    main()
