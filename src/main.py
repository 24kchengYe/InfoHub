"""InfoHub entry point."""

import uvicorn
from dotenv import load_dotenv
from src.config import load_global_config


def main():
    load_dotenv()
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
