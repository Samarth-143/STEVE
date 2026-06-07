"""Test the health of the Gemini API key by making a simple API call."""

import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

TEST_PROMPT = "Say hello in exactly 3 words."
EXPECTED_MODEL = "gemini-2.5-flash"


def get_api_key() -> str:
    if not API_CONFIG_PATH.exists():
        print(f"[FAIL] Config file not found: {API_CONFIG_PATH}")
        sys.exit(1)
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    key = data.get("gemini_api_key", "")
    if not key:
        print("[FAIL] 'gemini_api_key' is empty or missing in config/api_keys.json")
        sys.exit(1)
    return key


def test_google_genai(api_key: str) -> tuple[bool, str]:
    """Test using the newer google-genai SDK."""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        start = time.time()
        response = client.models.generate_content(
            model=EXPECTED_MODEL,
            contents=TEST_PROMPT,
        )
        elapsed = time.time() - start
        text = response.text.strip()
        return True, f"Response ({elapsed:.2f}s): {text}"
    except Exception as e:
        return False, str(e)


def test_google_generativeai(api_key: str) -> tuple[bool, str]:
    """Test using the older google-generativeai SDK."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=EXPECTED_MODEL)
        start = time.time()
        response = model.generate_content(TEST_PROMPT)
        elapsed = time.time() - start
        text = response.text.strip()
        return True, f"Response ({elapsed:.2f}s): {text}"
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 50)
    print("  Gemini API Key Health Check")
    print("=" * 50)
    print(f"\nConfig : {API_CONFIG_PATH}")
    print(f"Model  : {EXPECTED_MODEL}")
    print(f"Prompt : \"{TEST_PROMPT}\"\n")

    api_key = get_api_key()
    masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print(f"API Key: {masked}\n")

    all_passed = True

    # Test 1: google-genai SDK
    print("-" * 50)
    print("[1/2] Testing google-genai SDK...")
    ok, msg = test_google_genai(api_key)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {msg}")
    if not ok:
        all_passed = False

    # Test 2: google-generativeai SDK
    print("-" * 50)
    print("[2/2] Testing google-generativeai SDK...")
    ok, msg = test_google_generativeai(api_key)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {msg}")
    if not ok:
        all_passed = False

    # Summary
    print("=" * 50)
    if all_passed:
        print("  Result: ALL CHECKS PASSED")
    else:
        print("  Result: SOME CHECKS FAILED")
    print("=" * 50)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
