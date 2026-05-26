from bot.config import Config
from bot.runner import run_bot, setup_logging


def main() -> None:
    setup_logging()
    config = Config.from_env()
    run_bot(config)


if __name__ == "__main__":
    main()
