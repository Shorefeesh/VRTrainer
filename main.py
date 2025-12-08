from ui.main import main
import coloredlogs
import logging

if __name__ == "__main__":

    log_level = logging.DEBUG
    coloredlogs.install(level=log_level,
        fmt='%(asctime)s %(hostname)s %(programname)s %(name)s[%(process)d] %(levelname)s %(message)s')
    logging.getLogger().setLevel(log_level)
    main()
