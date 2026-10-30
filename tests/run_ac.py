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
from ac_cases_f import http_mcp, http_mcp_equiv, http_mcp_sec
from ac_cases_g import board_terminal_fields, board_view, sse_stream, web_shell
from ac_cases_h import (months_ago, prune_confirm, prune_cross, prune_export, prune_export_fail,
                        prune_terminal, prune_zombie, renew_events)
from ac_cases_i import (retry_board, retry_cross_window, retry_edge1, retry_edge2, retry_edge3,
                        retry_edge4, retry_edge5, retry_ex5, retry_s1, retry_s2, retry_s3)
from ac_cases_j import export_csv
from ac_cases_dispatch import (k_bg_claim_binding, k_bg_heartbeat, k_bg_note_basis,
                               k_bg_renew_binding, k_dispatch_authfail, k_dispatch_badstate,
                               k_dispatch_failnote, k_dispatch_main, k_dispatch_reuse,
                               k_dispatch_placement, k_dispatch_timeout, k_history_assembly,
                               k_resume, k_resume_errcase, k_resume_model_204,
                               k_resume_model_err)
from ac_cases_k import k_state, k_archive, k_delete, k_web, k_g12
from ac_cases_l import (l_audience, l_blocked_reason_chain, l_blocked_reason_empty,
                        l_export_stable, l_headline, l_latest_first, l_record_title,
                        l_summary_line, l_tool_self_desc)
from ac_cases_m import (m_echo, m_full_id, m_cross_surface, m_normalization,
                        m_lease_return, m_lease_seq, m_prefix_ambiguous, m_prefix_invalid,
                        m_prefix_trunc, m_prefix_unique, m_prefix_zero)
from ac_cases_n import (n1, n10, n11, n12, n13, n14, n15, n16, n17, n17b, n18,
                        n19, n2, n20, n21, n22, n23, n24, n26, n27, n28, n29,
                        n3, n4, n5, n6, n7, n8, n9, n_parse)
from ac_cases_o import (sa_added, sa_blankacc, sa_coverage, sa_dup, sa_empty,
                        sa_foreign, sa_form, sa_happy, sa_omit, sa_reason,
                        sa_size, sa_stracc)

TESTS: dict[str, object] = {
    "ac1": ac1, "ac2": ac2, "ac3": ac3, "ac4": ac4, "ac5": ac5,
    "ac6": ac6, "ac7": ac7, "ac8": ac8, "ac9": ac9, "ac16": ac16,
    "ac10": ac10, "ac11": ac11, "ac12": ac12, "ac13": ac13, "ac15": ac15, "ac17": ac17,
    "security": security, "readlock": readlock, "payload": payload,
    "rest_api": rest_api, "cli_m0": cli_m0,
    "matrix": matrix, "extras": extras,
    "p1_ids": p1_id_normalization, "p2_payload": p2_payload_8kb, "p2_decomp": p2_decomposition_signal,
    "reconcile": reconcile_ac,
    "http_mcp": http_mcp, "http_mcp_sec": http_mcp_sec, "http_mcp_equiv": http_mcp_equiv,
    "board": board_view, "board_term": board_terminal_fields, "sse": sse_stream, "web": web_shell,
    "renew": renew_events,
    "prune_terminal": prune_terminal, "prune_cross": prune_cross,
    "prune_confirm": prune_confirm, "prune_export": prune_export,
    "prune_export_fail": prune_export_fail,
    "prune_zombie": prune_zombie, "months_ago": months_ago,
    "retry_s1": retry_s1, "retry_s2": retry_s2, "retry_s3": retry_s3,
    "retry_edge1": retry_edge1, "retry_edge2": retry_edge2, "retry_edge3": retry_edge3,
    "retry_edge4": retry_edge4, "retry_edge5": retry_edge5,
    "retry_ex5": retry_ex5, "retry_cross_window": retry_cross_window,
    "retry_board": retry_board,
    "export_csv": export_csv,
    "k_state": k_state,
    "k_archive": k_archive,
    "k_delete": k_delete,
    "k_web": k_web,
    "k_g12": k_g12,
    "k_bg_heartbeat": k_bg_heartbeat,
    "k_bg_claim_binding": k_bg_claim_binding,
    "k_bg_note_basis": k_bg_note_basis,
    "k_bg_renew_binding": k_bg_renew_binding,
    "k_dispatch_main": k_dispatch_main,
    "k_dispatch_badstate": k_dispatch_badstate,
    "k_dispatch_authfail": k_dispatch_authfail,
    "k_dispatch_reuse": k_dispatch_reuse,
    "k_dispatch_timeout": k_dispatch_timeout,
    "k_history_assembly": k_history_assembly,
    "k_dispatch_placement": k_dispatch_placement,
    "k_dispatch_failnote": k_dispatch_failnote,
    "k_resume": k_resume,
    "k_resume_errcase": k_resume_errcase,
    "k_resume_model_204": k_resume_model_204,
    "k_resume_model_err": k_resume_model_err,
    "l_headline": l_headline, "l_summary_line": l_summary_line, "l_record_title": l_record_title,
    "l_blocked_reason_chain": l_blocked_reason_chain, "l_blocked_reason_empty": l_blocked_reason_empty,
    "l_tool_self_desc": l_tool_self_desc,
    "l_latest_first": l_latest_first, "l_audience": l_audience, "l_export_stable": l_export_stable,
    "m_prefix_unique": m_prefix_unique, "m_prefix_ambiguous": m_prefix_ambiguous,
    "m_prefix_trunc": m_prefix_trunc, "m_prefix_zero": m_prefix_zero, "m_prefix_invalid": m_prefix_invalid,
    "m_full_id": m_full_id, "m_normalization": m_normalization, "m_cross_surface": m_cross_surface,
    "m_echo": m_echo,
    "m_lease_return": m_lease_return, "m_lease_seq": m_lease_seq,
    "n_parse": n_parse,
    "n1": n1, "n2": n2, "n3": n3, "n4": n4, "n5": n5, "n6": n6, "n7": n7, "n8": n8,
    "n9": n9, "n10": n10, "n11": n11, "n28": n28,
    "n12": n12, "n13": n13, "n14": n14, "n15": n15, "n16": n16,
    "n17": n17, "n17b": n17b, "n18": n18,
    "n19": n19, "n20": n20, "n21": n21, "n22": n22, "n23": n23, "n24": n24,
    "n26": n26, "n27": n27, "n29": n29,
    "sa_happy": sa_happy, "sa_form": sa_form, "sa_foreign": sa_foreign,
    "sa_coverage": sa_coverage, "sa_added": sa_added, "sa_empty": sa_empty,
    "sa_omit": sa_omit, "sa_dup": sa_dup, "sa_reason": sa_reason,
    "sa_stracc": sa_stracc, "sa_size": sa_size, "sa_blankacc": sa_blankacc,
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
