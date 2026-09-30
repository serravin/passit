import argparse

from .config import Settings
from .db import Database
from .seed import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed"])
    parser.parse_args()
    settings = Settings()
    settings.validate()
    initialize(Database(settings.database_url), demo=settings.mode == "demo")


if __name__ == "__main__":
    main()
