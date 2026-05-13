"""
Post-installation verification script.
Run before air-gapping to confirm everything is in place.

Usage:
    python verify.py
    python verify.py --model llama3.1:8b
"""

import argparse
import json
import sys

def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "\033[32m[PASS]\033[0m" if ok else "\033[31m[FAIL]\033[0m"
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="llama3.1:8b")
    args = parser.parse_args()

    all_ok = True
    print("\nOffline interview analyser — installation verification\n")

    # 1. Python version
    import sys as _sys
    v = _sys.version_info
    all_ok &= check("Python >= 3.11", v.major == 3 and v.minor >= 11,
                    f"found {v.major}.{v.minor}.{v.micro}")

    # 2. Required packages
    for pkg in ["ollama", "pydantic", "yaml", "rich"]:
        try:
            __import__(pkg)
            all_ok &= check(f"Package: {pkg}", True)
        except ImportError:
            all_ok &= check(f"Package: {pkg}", False, "not installed — run: pip install -r requirements.txt")

    # 3. Ollama server reachable on localhost
    try:
        import ollama as _ollama
        client = _ollama.Client(host="http://127.0.0.1:11434")
        models = client.list()
        all_ok &= check("Ollama server (localhost:11434)", True, "reachable")

        # 4. Requested model available
        model_names = [m.model for m in models.models]
        model_ok = any(args.model in n for n in model_names)
        all_ok &= check(f"Model: {args.model}", model_ok,
                        "not found — run: ollama pull " + args.model if not model_ok else "loaded")
    except Exception as exc:
        all_ok &= check("Ollama server (localhost:11434)", False, str(exc))
        all_ok &= check(f"Model: {args.model}", False, "cannot check (server unavailable)")

    # 5. Prompt files present
    from pathlib import Path
    base = Path(__file__).parent
    for prompt in ["anonymise", "summary", "themes", "sentiment", "compare"]:
        p = base.parent / "prompts" / f"{prompt}.txt"
        all_ok &= check(f"Prompt file: {prompt}.txt", p.exists())

    # 6. Config file
    cfg_path = base / "config.yaml"
    all_ok &= check("config.yaml", cfg_path.exists())

    # 7. No outbound network (spot check — cannot be guaranteed programmatically)
    import socket
    try:
        socket.setdefaulttimeout(2)
        socket.socket().connect(("8.8.8.8", 53))
        all_ok &= check("Network isolation", False,
                        "machine can reach internet — disconnect before processing PII data")
    except OSError:
        all_ok &= check("Network isolation", True, "no outbound connection detected")

    # 8. Quick inference test
    try:
        import ollama as _ollama
        client = _ollama.Client(host="http://127.0.0.1:11434")
        resp = client.chat(
            model=args.model,
            messages=[{"role": "user", "content": 'Reply with valid JSON: {"status":"ok"}'}],
            format="json",
            options={"temperature": 0.0, "num_predict": 20},
        )
        parsed = json.loads(resp.message.content)
        all_ok &= check("Inference test (JSON output)", parsed.get("status") == "ok")
    except Exception as exc:
        all_ok &= check("Inference test (JSON output)", False, str(exc))

    print()
    if all_ok:
        print("\033[32mAll checks passed. Safe to air-gap.\033[0m\n")
    else:
        print("\033[31mSome checks failed. Fix issues above before air-gapping.\033[0m\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
