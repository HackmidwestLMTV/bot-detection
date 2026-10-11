"""Fixed evidence gate. An approval here is only permission for human review."""

from engine.scorer import score_features, validate_variant


def gate(candidate: dict, baseline: dict, humans: list, forgeries: list):
    validate_variant(candidate)
    validate_variant(baseline)
    groups = {}
    reasons = []
    if not humans:
        reasons.append("no human evidence")
    if not forgeries:
        reasons.append("no forgery evidence")
    for row in humans:
        device = row.get("device")
        if device not in ("mouse", "trackpad", "touch"):
            raise ValueError("human evidence requires mouse, trackpad, or touch device")
        group = groups.setdefault(device, {"total": 0, "candidate": 0, "baseline": 0})
        group["total"] += 1
        for name, variant in (("candidate", candidate), ("baseline", baseline)):
            group[name] += int(not score_features(row["features"], variant)["pass"])
    for device, group in sorted(groups.items()):
        if group["candidate"] > group["baseline"]:
            reasons.append(f"rejects {group['candidate']} of {group['total']} {device} users (baseline {group['baseline']})")
    passed = {"candidate": 0, "baseline": 0, "total": len(forgeries)}
    for row in forgeries:
        for name, variant in (("candidate", candidate), ("baseline", baseline)):
            passed[name] += int(score_features(row["features"], variant)["pass"])
    if forgeries and passed["candidate"] >= passed["baseline"]:
        reasons.append(f"forgeries passed did not decrease ({passed['candidate']} vs baseline {passed['baseline']})")
    return {"candidate": candidate["id"], "baseline": baseline["id"],
            "verdict": "reject" if reasons else "approve_for_review", "humans_rejected": groups,
            "forgeries_passed": passed, "reasons": reasons}
