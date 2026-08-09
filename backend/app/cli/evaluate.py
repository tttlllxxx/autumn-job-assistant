import json

from app.core.database import SessionLocal
from app.services.evaluation import evaluate_user_feedback


def main() -> int:
    with SessionLocal() as db:
        result = evaluate_user_feedback(db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1 if result["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
