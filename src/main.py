"""InfoHub entry point."""

import logging
import uvicorn
from dotenv import load_dotenv
from src.config import load_global_config


def main():
    load_dotenv()

    # Configure root logger so all infohub/apscheduler logs go to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = load_global_config()
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
