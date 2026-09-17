"""Export the local API contract without opening a database or RPC connection."""

import json

from .app import create_app


if __name__ == "__main__":
    print(json.dumps(create_app().openapi(), sort_keys=True))
