"""CLI over the shared verify(). Same code path as the API/UI.

  python verify.py --input ../inputs.json
  python verify.py --brand "Lulu and Georgia" --url https://www.luluandgeorgia.com/products/carson-sofa \
                   --variant '{"Color": "Ivory Modern Boucle", "Size": "103\\"W"}' --qty 1 [--no-cache]
Exit code 0 = all resolved, 2 = at least one unresolved.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from pricecheck import db
from pricecheck.core import Request, dumps, new_run_id
from pricecheck.service import verify

DEFAULT_INPUTS = Path(os.environ.get("INPUTS_FILE", Path(__file__).resolve().parent.parent / "inputs.json"))


def main():
    ap = argparse.ArgumentParser(description="Verify the current public US/USD unit price of a product variant.")
    ap.add_argument("--input", type=Path, nargs="?", const=DEFAULT_INPUTS,
                    help=f"JSON list of {{brand, url, variant, quantity}} (bare --input = {DEFAULT_INPUTS})")
    ap.add_argument("--brand"); ap.add_argument("--url")
    ap.add_argument("--variant", help='JSON object of option name -> value')
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--no-cache", action="store_true", help="force a fresh observation")
    a = ap.parse_args()

    if a.input:
        reqs = [Request(x["brand"], x["url"], x["variant"], x.get("quantity", 1)) for x in json.loads(a.input.read_text())]
    elif a.brand and a.url and a.variant:
        reqs = [Request(a.brand, a.url, json.loads(a.variant), a.qty)]
    else:
        ap.error("give --input, or --brand --url --variant")

    db.init()
    run_id = new_run_id()
    results = [verify(r, no_cache=a.no_cache, run_id=run_id) for r in reqs]
    print(dumps(results if len(results) > 1 else results[0]))
    for r in results:
        o = r["outcome"]
        line = f"[{o['status'].upper()}] {r['brand']} {r['requested_variant']['options']}"
        line += f" -> {r['currency']} {r['current_amount']}" if r["current_amount"] else f" -> {o['reason']}: {o['detail']}"
        print(line, file=sys.stderr)
        if o["status"] == "unresolved":
            v = json.dumps(r["requested_variant"]["options"]).replace("'", "'\\''")
            print(f"  rerun: python verify.py --brand '{r['brand']}' --url '{r['product'].get('url')}'"
                  f" --variant '{v}' --qty {r['requested_variant']['quantity']} --no-cache", file=sys.stderr)
    sys.exit(0 if all(r["outcome"]["status"] == "resolved" for r in results) else 2)


if __name__ == "__main__":
    main()
