"""Run the live reasoning pipeline against every public sample case and
compare the rubric-automated fields against the expected output.

Usage:  python scripts/check_sample_cases.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import _run_reasoning_pipeline  # noqa: E402
from app.schemas import AnalyzeTicketRequest  # noqa: E402

CASES_FILE = ROOT / "Should_Be_Hidden" / "SUST_Preli_Sample_Cases.json"
RUBRIC_FIELDS = (
    "relevant_transaction_id",
    "evidence_verdict",
    "case_type",
    "severity",
    "department",
    "human_review_required",
)


def main() -> int:
    cases = json.loads(CASES_FILE.read_text())["cases"]
    passed = 0
    for c in cases:
        req = AnalyzeTicketRequest.model_validate(c["input"])
        out = _run_reasoning_pipeline(req)
        eo = c["expected_output"]
        diffs = []
        for k in RUBRIC_FIELDS:
            if getattr(out, k) != eo[k]:
                diffs.append(f"{k}: got={getattr(out, k)!r} exp={eo[k]!r}")
        ok = not diffs
        if ok:
            passed += 1
        marker = "OK " if ok else "DIFF"
        print(f"[{marker}] {c['id']:10} {c['label'][:35]:35} :: {'; '.join(diffs)}")
    print(f"\nMatched {passed}/{len(cases)} on rubric-automated fields.")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())