def main() -> None:
    import logging
    from summarizeaudio.config import LOG_PATH
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    from summarizeaudio.tray import run
    run()

if __name__ == "__main__":
    main()
