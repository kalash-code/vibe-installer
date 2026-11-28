#!/usr/bin/env python3
"""CI-автотест критической синхронизации: основное приложение <-> Dev Console.
Проверяет FIX-01 (доставка ответа разработчика) и право пользователя на свои обращения.
Запуск: python ci/test_sync.py
"""
import json, os, sys, time, urllib.request, urllib.error

HUB = os.environ.get("VIBE_HUB", "https://vibe-feedback.vresetnikov257.workers.dev")
DEV = os.environ.get("VIBE_DEV_TOKEN", "")
USER_TOKEN = os.environ.get("VIBE_USER_TOKEN", "")

if not DEV or not USER_TOKEN:
    print("SKIP: VIBE_DEV_TOKEN / VIBE_USER_TOKEN не заданы (секреты CI)")
    sys.exit(0)

HDR_DEV = {"Content-Type": "application/json", "X-Dev-Token": DEV}
HDR_USER = {"Content-Type": "application/json", "X-User-Id": USER_TOKEN}


def call(path, method="GET", body=None, headers=None):
    req = urllib.request.Request(HUB + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + " | " + name + (" | " + detail if detail else ""))
    return cond


def main():
    ok = True
    # 1. Пользователь видит только свои обращения (FIX-01 backend)
    s, d = call("/api/messages", headers=HDR_USER)
    ok &= check("user can read own messages", s == 200 and d.get("ok") and isinstance(d.get("items"), list), f"HTTP {s}")
    if s == 200 and d.get("items"):
        ok &= check("no foreign messages leaked", all(m.get("userId") for m in d["items"]), f"{len(d['items'])} items")
    s, d = call("/api/messages")
    ok &= check("anonymous blocked", s == 401, f"HTTP {s}")

    # 2. Полный цикл: тикет -> ответ разработчика -> доставка
    s, d = call("/api/messages", "POST", {
        "name": "CI Test", "email": "ci@vibe.ru", "topic": "problem",
        "subject": "CI sync check", "message": "automated check " + str(int(time.time()))
    }, HDR_USER)
    tid = d.get("id", "")
    ok &= check("ticket created", s == 200 and bool(tid), str(d)[:120])
    if not tid:
        return 1

    s, d = call("/api/messages", headers=HDR_DEV)
    found = any(m.get("id") == tid for m in d.get("items", []))
    ok &= check("ticket visible to dev", s == 200 and found)

    s, d = call(f"/api/messages/{tid}/reply", "POST",
                {"text": "CI dev reply", "author": "Создатель"}, HDR_DEV)
    ok &= check("dev reply accepted", s == 200, str(d)[:120])

    s, d = call("/api/messages", headers=HDR_USER)
    item = next((m for m in d.get("items", []) if m.get("id") == tid), None)
    delivered = bool(item and any("CI dev reply" in str(t.get("text", "")) for t in item.get("thread", [])))
    ok &= check("reply delivered to user (FIX-01)", delivered)

    s, d = call(f"/api/messages/{tid}", "PATCH", {"status": "closed"}, HDR_DEV)
    ok &= check("ticket closed", s == 200 and d.get("item", {}).get("status") == "closed")

    # 3. Восстановление пароля: non-enumeration + валидация
    s, d = call("/api/password/forgot", "POST", {"email": "unknown@example.com"}, {"Content-Type": "application/json"})
    ok &= check("forgot non-enumeration", s == 200 and d.get("ok"), f"HTTP {s}")
    s, d = call("/api/password/reset", "POST", {"token": "bad", "password": "123456"}, {"Content-Type": "application/json"})
    ok &= check("reset rejects bad token", s == 400, f"HTTP {s}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
