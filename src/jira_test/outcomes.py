"""Final test outcomes shared by CLI and desktop reporting."""


def final_result(previous: dict, reports: list[dict], canceled: bool = False) -> dict:
    """Merge pytest phases without letting a successful call hide teardown failure."""
    result = dict(previous)
    failures = [report for report in reports if report["outcome"] == "failed"]
    failed = next(
        (report for report in failures if report["when"] != "call"),
        failures[0] if failures else None,
    )
    skipped = next((report for report in reports if report["outcome"] == "skipped"), None)
    call = next((report for report in reports if report["when"] == "call"), None)
    teardown_complete = any(report["when"] == "teardown" for report in reports)
    if failed:
        if result.get("outcome") != "blocked" or failed["when"] != "call":
            result.update(outcome="failed", reason=failed["longrepr"])
        for key in ("screenshot", "evidence_error"):
            if key in failed:
                result[key] = failed[key]
        if canceled and "JobCancelled" in failed["longrepr"]:
            result["outcome"] = "canceled"
    elif not teardown_complete:
        result["outcome"] = "canceled" if canceled else "incomplete"
    elif skipped:
        result.update(outcome="skipped", reason=skipped["longrepr"])
    elif call:
        result["outcome"] = call["outcome"]
    else:
        result["outcome"] = "canceled" if canceled else "incomplete"
    return result
