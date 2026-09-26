"""Live end-to-end verification of the /api/prompt-templates surface.

Run against a live backend:  python scripts/verify_prompt_api.py
Creates records with a verify-<ts> code prefix so they are easy to spot.
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"
STAMP = int(time.time())
CODE = f"verify-{STAMP}"

results: list[tuple[bool, str, str]] = []


def call(method: str, path: str, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("content-type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""))
    return ok


# --- 1. list ---------------------------------------------------------------
status, payload = call("GET", "/api/prompt-templates")
check("GET /api/prompt-templates returns 200 with data list",
      status == 200 and isinstance(payload.get("data"), list), f"status={status}")
check("list response carries requestId", bool(payload.get("requestId")))
orphans = [t["code"] for t in payload["data"] if t["versionCount"] == 0]
print(f"      note: existing templates={len(payload['data'])}, orphans(versionCount=0)={orphans}")

# --- 2. create ------------------------------------------------------------
key = str(uuid.uuid4())
new_body = {
    "code": CODE,
    "name": "验证用提示词",
    "kind": "planner",
    "stage": "plan",
    "executionTarget": "llm",
    "body": "你是一个用于接口验证的规划器。",
    "userPromptTemplate": "输入：{{input}}",
    "changeNote": "api verification",
}
status, payload = call("POST", "/api/prompt-templates", new_body, {"Idempotency-Key": key})
created_ok = check("POST create returns 201", status == 201, f"status={status} body={str(payload)[:200]}")
if not created_ok:
    print("\ncannot continue without a created template")
    sys.exit(1)
tpl = payload["data"]["template"]
ver = payload["data"]["version"]
tpl_id, ver_id = tpl["id"], ver["id"]
check("created template has defaultVersionId set", tpl["defaultVersionId"] == ver_id,
      f"defaultVersionId={tpl['defaultVersionId']} versionId={ver_id}")
check("created version is versionNo=1", ver["versionNo"] == 1, f"versionNo={ver['versionNo']}")
check("created version keeps body verbatim", ver["body"] == new_body["body"])
check("created version keeps chinese name intact", ver["name"] == new_body["name"], repr(ver["name"]))
check("created version has contentSha256", len(ver["contentSha256"]) == 64)
check("response body has data key (frontend contract)", "data" in payload)
print(f"      note: fileSyncStatus={ver['fileSyncStatus']} fileSyncError={ver['fileSyncError']}")

# --- 3. idempotency replay -------------------------------------------------
status, payload2 = call("POST", "/api/prompt-templates", new_body, {"Idempotency-Key": key})
same = status in (200, 201) and payload2["data"]["template"]["id"] == tpl_id
check("POST replay with same Idempotency-Key returns the SAME template (no duplicate)",
      same, f"status={status} id={payload2.get('data', {}).get('template', {}).get('id')}")

# --- 4. code conflict ------------------------------------------------------
status, payload3 = call("POST", "/api/prompt-templates", new_body, {"Idempotency-Key": str(uuid.uuid4())})
check("POST duplicate code with a NEW key returns 409 PROMPT_CODE_CONFLICT",
      status == 409, f"status={status} err={payload3.get('error', {}).get('code')}")

# --- 5. validation --------------------------------------------------------
status, payload4 = call("POST", "/api/prompt-templates", {"code": f"{CODE}-x", "name": "n"})
check("POST missing required field returns 400 INVALID_PROMPT",
      status == 400, f"status={status} err={payload4.get('error', {}).get('code')}")

# a rejected request must NOT consume its idempotency key
reuse_key = str(uuid.uuid4())
status, _ = call("POST", "/api/prompt-templates", {"code": f"{CODE}-r"}, {"Idempotency-Key": reuse_key})
rejected = status == 400
status, payload5 = call("POST", "/api/prompt-templates",
                        {**new_body, "code": f"{CODE}-r"}, {"Idempotency-Key": reuse_key})
check("a rejected request does not consume its Idempotency-Key (retry succeeds)",
      rejected and status == 201, f"reject={rejected} retry={status}")
retry_tpl_id = payload5.get("data", {}).get("template", {}).get("id")

# --- 6. detail / versions / version ---------------------------------------
status, payload = call("GET", f"/api/prompt-templates/{tpl_id}")
check("GET detail returns 200 with versions array",
      status == 200 and isinstance(payload["data"].get("versions"), list), f"status={status}")
check("detail versionCount is 1", payload["data"]["versionCount"] == 1, f"got={payload['data']['versionCount']}")

status, payload = call("GET", f"/api/prompt-templates/{tpl_id}/versions")
check("GET versions returns the single version", status == 200 and len(payload["data"]) == 1,
      f"status={status} n={len(payload.get('data', []))}")

status, payload = call("GET", f"/api/prompt-versions/{ver_id}")
check("GET version by id returns 200", status == 200 and payload["data"]["id"] == ver_id, f"status={status}")

# --- 7. resolve -----------------------------------------------------------
status, payload = call("GET", f"/api/prompt-templates/{tpl_id}/resolve")
check("GET resolve (no versionId) returns the default version",
      status == 200 and payload["data"]["id"] == ver_id, f"status={status}")

status, payload = call("GET", f"/api/prompt-templates/{tpl_id}/resolve?versionId={ver_id}")
check("GET resolve with explicit versionId returns that version",
      status == 200 and payload["data"]["id"] == ver_id, f"status={status}")

if retry_tpl_id:
    foreign = payload5["data"]["version"]["id"]
    status, payload = call("GET", f"/api/prompt-templates/{tpl_id}/resolve?versionId={foreign}")
    check("GET resolve with a version from ANOTHER template returns 409 PROMPT_VERSION_OWNERSHIP",
          status == 409, f"status={status} err={payload.get('error', {}).get('code')}")

# --- 8. create version ----------------------------------------------------
vkey = str(uuid.uuid4())
vbody = {"baseVersionId": ver_id, "body": "你是一个用于接口验证的规划器。第二版。",
         "changeNote": "v2 via api verification"}
status, payload = call("POST", f"/api/prompt-templates/{tpl_id}/versions", vbody, {"Idempotency-Key": vkey})
v2_ok = check("POST create version returns 201 with versionNo=2",
              status == 201 and payload["data"]["version"]["versionNo"] == 2,
              f"status={status} body={str(payload)[:200]}")
if v2_ok:
    v2 = payload["data"]["version"]
    check("new version becomes the template default",
          payload["data"]["template"]["defaultVersionId"] == v2["id"])
    check("new version sha differs from v1", v2["contentSha256"] != ver["contentSha256"])

    status, payload = call("POST", f"/api/prompt-templates/{tpl_id}/versions", vbody, {"Idempotency-Key": vkey})
    check("POST version replay with same key returns the SAME version (no versionNo bump)",
          payload.get("data", {}).get("version", {}).get("id") == v2["id"],
          f"status={status} id={payload.get('data', {}).get('version', {}).get('id')}")

    status, payload = call("POST", f"/api/prompt-templates/{tpl_id}/versions", vbody, {"Idempotency-Key": str(uuid.uuid4())})
    check("POST identical content with a NEW key returns 409 PROMPT_VERSION_DUPLICATE",
          status == 409, f"status={status} err={payload.get('error', {}).get('code')}")

status, payload = call("POST", f"/api/prompt-templates/{tpl_id}/versions", {"body": "no base"})
check("POST version without baseVersionId returns 400", status == 400, f"status={status}")

# --- 9. not found ---------------------------------------------------------
ghost = str(uuid.uuid4())
status, _ = call("GET", f"/api/prompt-templates/{ghost}")
check("GET unknown template returns 404", status == 404, f"status={status}")
status, _ = call("GET", f"/api/prompt-versions/{ghost}")
check("GET unknown version returns 404", status == 404, f"status={status}")
status, payload = call("GET", "/api/prompt-templates/not-a-uuid")
# main.py maps RequestValidationError to 400 INVALID_REQUEST app-wide (not FastAPI's default 422)
check("GET malformed uuid returns 400 INVALID_REQUEST (app-wide convention)",
      status == 400 and payload.get("error", {}).get("code") == "INVALID_REQUEST",
      f"status={status} err={payload.get('error', {}).get('code')}")

# --- 10. final list state -------------------------------------------------
status, payload = call("GET", "/api/prompt-templates")
mine = [t for t in payload["data"] if t["code"].startswith(f"verify-{STAMP}")]
check("created templates appear in the list with versionCount>=1",
      len(mine) == 2 and all(t["versionCount"] >= 1 for t in mine),
      f"found={[(t['code'], t['versionCount']) for t in mine]}")

failed = [r for r in results if not r[0]]
print(f"\n{'=' * 62}")
print(f"total={len(results)}  passed={len(results) - len(failed)}  failed={len(failed)}")
if failed:
    for _, name, detail in failed:
        print(f"  FAIL {name}  {detail}")
print(f"cleanup: templates with code prefix verify-{STAMP} were left in the DB")
sys.exit(1 if failed else 0)
