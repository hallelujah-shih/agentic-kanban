"""AC harness 入口。运行: uv run python tests/run_ac.py [--only ac1,ac6,...]

全绿后 exit 0；任一 FAIL exit 1。红跑：AGENT_KANBAN_SRC 指向空目录对"空实现"全红留档。
"""

from __future__ import annotations

import sys
import traceback

from ac_lib import RESULTS, ok
from ac_cases_a import ac1, ac2, ac3, ac4, ac5
from ac_cases_b import ac6, ac7, ac8, ac9, ac16, extras, matrix
from ac_cases_c import ac11, ac12, ac13, ac15, ac17, cli_m0, payload, readlock, rest_api, security
from ac_cases_d import p1_id_normalization, p2_decomposition_signal, p2_payload_8kb
from ac_cases_e import ac10, reconcile_ac

TESTS: dict[str, object] = {
    "ac1": ac1, "ac2": ac2, "ac3": ac3, "ac4": ac4, "ac5": ac5,
    "ac6": ac6, "ac7": ac7, "ac8": ac8, "ac9": ac9, "ac16": ac16,
    "ac10": ac10, "ac11": ac11, "ac12": ac12, "ac13": ac13, "ac15": ac15, "ac17": ac17,
    "security": security, "readlock": readlock, "payload": payload,
    "rest_api": rest_api, "cli_m0": cli_m0,
    "matrix": matrix, "extras": extras,
    "p1_ids": p1_id_normalization, "p2_payload": p2_payload_8kb, "p2_decomp": p2_decomposition_signal,
    "reconcile": reconcile_ac,
}


def main() -> int:
    only: set[str] | None = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        only = {s.strip().lower() for s in sys.argv[i + 1].split(",")}
    names = [n for n in TESTS if not only or n in only]
    for name in names:
        print(f"## {name}")
        try:
            TESTS[name]()
        except Exception as exc:
            ok(name, False, f"exception: {type(exc).__name__}: {exc}")
            traceback.print_exc()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n== 结果: {len(RESULTS) - len(fails)}/{len(RESULTS)} PASS")
    for name, _, detail in fails:
        print(f"FAIL {name}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
