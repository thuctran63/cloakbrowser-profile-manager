"""Smoke test: open a visible CloakBrowser window and load example.com."""

import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from cloakbrowser import launch


def main() -> None:
    browser = launch(headless=False)
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded", timeout=60_000)
        print(f"Title: {page.title()}")
        print(f"URL: {page.url}")
        print("Browser opened successfully. Keeping it visible for 10 seconds...")
        time.sleep(10)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
