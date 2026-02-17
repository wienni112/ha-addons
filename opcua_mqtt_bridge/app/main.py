import asyncio
from bridge import run_bridge_forever


def main():
    asyncio.run(run_bridge_forever())


if __name__ == "__main__":
    main()
