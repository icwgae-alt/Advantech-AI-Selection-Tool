import argparse
import httpx
import json
import logging
import os
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path="configs/.env")

PRODUCT_API_URL = os.getenv("PRODUCT_API_URL")
PRODUCT_API_KEY = os.getenv("PRODUCT_API_KEY")
PRODUCT_API_TIMEOUT = float(os.getenv("PRODUCT_API_TIMEOUT", "120"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def ask_product_expert(query: str) -> dict:
    clean_query = " ".join(query.split()).strip()

    logger.info("Calling product expert API")
    logger.info("Query: %s", clean_query)

    if not PRODUCT_API_URL:
        raise RuntimeError("PRODUCT_API_URL is not set. Check environment variables.")
    if not PRODUCT_API_KEY:
        raise RuntimeError("PRODUCT_API_KEY is not set. Check environment variables.")

    payload = {
        "text": clean_query,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "x-api-key": PRODUCT_API_KEY,
    }
    try:
        response = httpx.post(
            PRODUCT_API_URL,
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(PRODUCT_API_TIMEOUT, connect=30.0),
        )
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Product expert API timed out after {PRODUCT_API_TIMEOUT}s. "
            "Increase PRODUCT_API_TIMEOUT if needed."
        ) from exc
    response.raise_for_status()
    result = response.json()
    logger.info("Product expert API completed (status %s)", response.status_code)
    return result


def main():
    parser = argparse.ArgumentParser(description="Query Advantech product expert API")
    parser.add_argument("--query", required=True, help="Product query text")
    args = parser.parse_args()

    try:
        result = ask_product_expert(args.query)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
