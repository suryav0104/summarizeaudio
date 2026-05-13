def main() -> None:
    import logging
    import os
    import warnings
    from summarizeaudio.config import LOG_PATH

    # faster-whisper/ctranslate2 can leave a multiprocessing semaphore for
    # Python's resource_tracker to clean up at shutdown. The warning is noisy
    # when the tray app is launched from Terminal, and it is emitted from a
    # helper process, so use PYTHONWARNINGS in addition to the local filter.
    warning_filter = "ignore:resource_tracker:UserWarning:multiprocessing.resource_tracker"
    existing_filters = os.environ.get("PYTHONWARNINGS")
    if existing_filters:
        if warning_filter not in existing_filters:
            os.environ["PYTHONWARNINGS"] = f"{existing_filters},{warning_filter}"
    else:
        os.environ["PYTHONWARNINGS"] = warning_filter

    warnings.filterwarnings(
        "ignore",
        message=r"resource_tracker: There appear to be .* leaked semaphore objects",
        category=UserWarning,
    )

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if os.environ.get("SUMMARIZEAUDIO_CONSOLE_LOG"):
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
    )
    from summarizeaudio.tray import run
    run()

if __name__ == "__main__":
    main()
