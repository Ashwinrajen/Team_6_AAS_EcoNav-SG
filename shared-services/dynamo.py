# shared-services/dynamo.py
import os
from dotenv import load_dotenv
load_dotenv()

print("USE_DDB =", os.getenv("USE_DDB"))
print("AWS_DDB_ENDPOINT =", os.getenv("AWS_DDB_ENDPOINT"))
print("AWS_REGION =", os.getenv("AWS_REGION"), "AWS_DEFAULT_REGION =", os.getenv("AWS_DEFAULT_REGION"))
print("DDB_SESSIONS_TABLE =", os.getenv("DDB_SESSIONS_TABLE"))
print("DDB_MEMORY_TABLE =", os.getenv("DDB_MEMORY_TABLE"))

from typing import Any, Dict, Optional

USE_DDB = os.getenv("USE_DDB")
DDB_SESSIONS_TABLE = os.getenv("DDB_SESSIONS_TABLE")
DDB_MEMORY_TABLE = os.getenv("DDB_MEMORY_TABLE")  # not used here but kept for symmetry
AWS_DDB_ENDPOINT = os.getenv("AWS_DDB_ENDPOINT")
AWS_REGION = os.getenv("AWS_REGION")

print(AWS_REGION)

# ---------------- In-memory fallback stores ----------------
_memory_store: Dict[str, Dict[str, Dict[str, Any]]] = {
    "sessions": {},
    "memory": {}
}

# ---------------- Optional DynamoDB client ----------------
if USE_DDB:
    import boto3
    from botocore.exceptions import ClientError
    from decimal import Decimal

    _ddb = boto3.resource(
        "dynamodb",
        region_name=AWS_REGION,
        endpoint_url=AWS_DDB_ENDPOINT if AWS_DDB_ENDPOINT else None
    )
    sessions_table = _ddb.Table(DDB_SESSIONS_TABLE)

    def _to_ddb(v: Any) -> Any:
        """Recursively convert floats to Decimal for DynamoDB."""
        if isinstance(v, float):
            return Decimal(str(v))
        if isinstance(v, dict):
            return {k: _to_ddb(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_to_ddb(x) for x in v]
        return v


# ---------------------- SESSIONS API ----------------------
def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    if not USE_DDB:
        return _memory_store["sessions"].get(session_id)

    try:
        resp = sessions_table.get_item(Key={"session_id": session_id})
        return resp.get("Item")
    except Exception as e:
        print(f"DDB get_session error: {e}")
        return None


def put_session(session: Dict[str, Any]) -> None:
    if not USE_DDB:
        _memory_store["sessions"][session["session_id"]] = session
        return

    try:
        item = _to_ddb(session)  # type: ignore[name-defined]
        sessions_table.put_item(Item=item)
    except Exception as e:
        print(f"DDB put_session error: {e}")


def update_session(session_id: str, updates: Dict[str, Any]) -> None:
    """
    Partial update. Uses UpdateExpression in DDB; plain dict .update() in memory mode.
    """
    if not USE_DDB:
        if session_id in _memory_store["sessions"]:
            _memory_store["sessions"][session_id].update(updates)
        else:
            # upsert for safety
            _memory_store["sessions"][session_id] = {"session_id": session_id, **updates}
        return

    try:
        # Build UpdateExpression
        expr_parts = []
        names = {}
        values = {}
        idx = 0
        for k, v in updates.items():
            idx += 1
            nk = f"#k{idx}"
            nv = f":v{idx}"
            names[nk] = k
            values[nv] = _to_ddb(v)  # type: ignore[name-defined]
            expr_parts.append(f"{nk} = {nv}")

        if not expr_parts:
            return

        sessions_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=dict(names),
            ExpressionAttributeValues=dict(values),
        )
    except Exception as e:
        print(f"DDB update_session error: {e}")


def delete_session(session_id: str) -> None:
    if not USE_DDB:
        _memory_store["sessions"].pop(session_id, None)
        return

    try:
        sessions_table.delete_item(Key={"session_id": session_id})
    except Exception as e:
        print(f"DDB delete_session error: {e}")


# ---------------------- MEMORY (unused here) ----------------------
# Kept intentionally to mirror interface; not used by shared-services/main.py
def get_memory(session_id: str) -> Optional[Dict[str, Any]]:
    return _memory_store["memory"].get(session_id)

def put_memory(memory: Dict[str, Any]) -> None:
    _memory_store["memory"][memory["session_id"]] = memory

def delete_memory(session_id: str) -> None:
    _memory_store["memory"].pop(session_id, None)
