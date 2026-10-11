"""Read-only compatibility check against a separate Person 1 source checkout."""
import argparse
import importlib
import json
from pathlib import Path
import sys

from engine.forger import forge_trail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", type=Path)
    args = parser.parse_args(argv)
    root = args.platform.resolve()
    sys.path.insert(0, str(root))
    app = importlib.import_module("web.app").app
    adapter = importlib.import_module("web.engine_adapter")
    expected = {"/v1/challenges": "post", "/v1/challenges/{cid}/attempt": "post",
                "/v1/variants/active": "get", "/v1/variants": "post", "/v1/variants/{variant_id}/activate": "post",
                "/v1/lab/human-features": "get", "/v1/lab/forgeries": "get", "/v1/lab/gate": "post",
                "/v1/lab/approvals": "post", "/v1/lab/approvals/{approval_id}": "get",
                "/v1/lab/commands/next": "get", "/v1/lab/events": "post"}
    paths = app.openapi()["paths"]
    missing = [path for path, method in expected.items() if method not in paths.get(path, {})]
    variant = json.loads((root / "contracts/fixtures/variant_v1.json").read_text())
    scored = adapter.score(forge_trail(42), 42, variant)
    result = {"routes_present": not missing, "missing": missing, "using_real_engine": not adapter.USING_STUBS,
              "naive_forgery_passed": scored["pass"], "database_integration_tested": False,
              "deployment_branch_fix_needed": "origin/p2-engine" in (root / "deploy.sh").read_text()}
    print(json.dumps(result))
    return 0 if not missing and not adapter.USING_STUBS and not scored["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
