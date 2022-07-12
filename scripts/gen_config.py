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
                "pooling_interval": "300",
                "db_path": "forta.db",
                "url": "https://api.forta.network/stats/sla/scanner/",
                "description": "Scanner node monitoring and alerts extension.",
            },
            "dummy": {"description": "Sample extension."},
            "erc20": {
                "pooling_interval": "300",
                "db_path": "erc20.db",
                "description": "ERC20 monitor and alert on new transfers.",
            },
        },
    }
    with open(CONFIG_DB, "w") as outfile:
        json.dump(sample_config, outfile)


if __name__ == "__main__":
    main()
