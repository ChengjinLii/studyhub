from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("bots.qq_studyhub_bot.server:app", host="0.0.0.0", port=8321)


if __name__ == "__main__":
    main()

