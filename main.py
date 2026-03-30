import json
import os
from datetime import datetime

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

MAX_TOKEN = os.getenv("MAX_BOT_TOKEN", "f9LHodD0cOJPSEslDXyuwyYeVsMfK_IJS22nsR7E2g1OpCeOy2Y1rNZIsloOLwRlkGEtczbLCbmi1_SGB6xJ")
MAX_WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET", "mrcmb_feedback_2026")
MAX_API_BASE = "https://platform-api.max.ru"

user_state = {}

with open("config.json", "r", encoding="utf-8") as f:
    DEPARTMENTS = json.load(f)


def normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def find_department_by_text(text: str):
    normalized = normalize_text(text)

    if normalized.startswith("dept:"):
        dept_key = normalized.replace("dept:", "", 1).strip()
        if dept_key in DEPARTMENTS:
            return dept_key

    for dept_key, dept_data in DEPARTMENTS.items():
        if normalize_text(dept_data["name"]) == normalized:
            return dept_key

    return None


def build_inline_keyboard(button_rows):
    rows = []
    for row in button_rows:
        buttons = []
        for item in row:
            text, btn_type, payload = item
            if btn_type == "message":
                buttons.append({
                    "type": "message",
                    "text": text,
                    "message": payload
                })
            elif btn_type == "callback":
                buttons.append({
                    "type": "callback",
                    "text": text,
                    "payload": payload
                })
        if buttons:
            rows.append(buttons)

    return [{
        "type": "inline_keyboard",
        "payload": {
            "buttons": rows
        }
    }]


def send_message(chat_id: str, text: str, attachments=None):
    if not MAX_TOKEN:
        print(f"[DEBUG] Нет токена. Сообщение не отправлено в chat_id={chat_id}")
        print(text)
        if attachments:
            print("[DEBUG] attachments =", json.dumps(attachments, ensure_ascii=False))
        return

    chat_id_str = str(chat_id).strip()
    if not chat_id_str.lstrip("-").isdigit():
        print(f"[ERROR] Некорректный chat_id: {chat_id}")
        return

    url = f"{MAX_API_BASE}/messages?chat_id={chat_id_str}"
    headers = {
        "Authorization": MAX_TOKEN,
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "text": text
    }

    if attachments:
        payload["attachments"] = attachments

    try:
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=15
        )
        print("SEND STATUS:", response.status_code, response.text)
    except Exception as e:
        print("SEND ERROR:", e)


def send_choose_kind_message(chat_id: str):
    attachments = build_inline_keyboard([
        [("Жалоба", "message", "Жалоба"), ("Предложение", "message", "Предложение")]
    ])
    send_message(
        chat_id,
        "Добрый день!\nВыберите тип обращения:",
        attachments=attachments
    )


def send_choose_department_message(chat_id: str):
    dept_items = list(DEPARTMENTS.items())

    rows = []
    current_row = []

    for dept_key, dept_data in dept_items:
        # Кнопка показывает и отправляет название отделения
        current_row.append((dept_data["name"], "message", dept_data["name"]))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []

    if current_row:
        rows.append(current_row)

    attachments = build_inline_keyboard(rows)

    send_message(
        chat_id,
        "Выберите отделение:",
        attachments=attachments
    )


def standard_reply(kind: str):
    if kind == "complaint":
        return (
            "Ваша жалоба принята в обработку и будет обработана "
            "в самое ближайшее время. По результатам вы получите ответ."
        )
    return (
        "Спасибо за предложение. Мы учтём его в работе и постараемся "
        "исполнить в кратчайшие сроки."
    )


def format_admin_message(dept_key: str, kind: str, text: str, user_id: str):
    dept = DEPARTMENTS[dept_key]
    kind_label = "Жалоба" if kind == "complaint" else "Предложение"
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    return (
        f"📍 Отдел: {dept['name']} ({dept['short']})\n"
        f"📌 Тип: {kind_label}\n\n"
        f"📝 Текст:\n{text}\n\n"
        f"🆔 Пользователь: {user_id}\n"
        f"📅 Дата: {now_str}"
    )


def extract_max_message(data: dict):
    message = data.get("message", {})
    body = message.get("body", {})
    recipient = message.get("recipient", {})
    sender = message.get("sender", {})

    text = (body.get("text") or "").strip()
    chat_id = recipient.get("chat_id")
    user_id = sender.get("user_id")

    return (
        str(chat_id) if chat_id is not None else "",
        str(user_id) if user_id is not None else "",
        text,
    )


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    incoming_secret = request.headers.get("X-Max-Bot-Api-Secret", "")
    if incoming_secret != MAX_WEBHOOK_SECRET:
        print("[WARN] Неверный secret в webhook:", incoming_secret)
        return JSONResponse({"ok": False, "error": "invalid secret"}, status_code=403)

    data = await request.json()
    print("INCOMING:", json.dumps(data, ensure_ascii=False))

    update_type = data.get("update_type")

    if update_type == "bot_started":
        chat_id = str(data.get("chat_id", ""))
        user = data.get("user", {})
        user_id = str(data.get("user_id") or user.get("user_id") or chat_id)
        payload = data.get("payload")

        user_state[user_id] = {
            "chat_id": chat_id,
            "step": "choose_kind",
            "dept_from_link": payload if payload in DEPARTMENTS else None
        }

        send_choose_kind_message(chat_id)
        return JSONResponse({"ok": True})

    if update_type == "message_created":
        chat_id, user_id, text = extract_max_message(data)

        if not text or not chat_id or not user_id:
            return JSONResponse({"ok": True})

        state = user_state.get(user_id)

        if not state:
            user_state[user_id] = {
                "chat_id": chat_id,
                "step": "choose_kind",
                "dept_from_link": None
            }
            send_choose_kind_message(chat_id)
            return JSONResponse({"ok": True})

        step = state.get("step")
        normalized = normalize_text(text)

        if step == "choose_kind":
            if normalized == "жалоба":
                state["kind"] = "complaint"
            elif normalized == "предложение":
                state["kind"] = "suggestion"
            else:
                send_choose_kind_message(chat_id)
                return JSONResponse({"ok": True})

            dept_from_link = state.get("dept_from_link")
            if dept_from_link in DEPARTMENTS:
                state["dept"] = dept_from_link
                state["step"] = "wait_text"
                send_message(chat_id, "Пожалуйста, опишите ситуацию одним сообщением.")
            else:
                state["step"] = "choose_department"
                send_choose_department_message(chat_id)

            return JSONResponse({"ok": True})

        if step == "choose_department":
            dept_key = find_department_by_text(text)

            if not dept_key:
                send_choose_department_message(chat_id)
                return JSONResponse({"ok": True})

            state["dept"] = dept_key
            state["step"] = "wait_text"
            send_message(chat_id, "Пожалуйста, опишите ситуацию одним сообщением.")
            return JSONResponse({"ok": True})

        if step == "wait_text":
            dept_key = state.get("dept")
            kind = state.get("kind")

            if dept_key not in DEPARTMENTS or kind not in ("complaint", "suggestion"):
                user_state[user_id] = {
                    "chat_id": chat_id,
                    "step": "choose_kind",
                    "dept_from_link": None
                }
                send_choose_kind_message(chat_id)
                return JSONResponse({"ok": True})

            admin_text = format_admin_message(
                dept_key=dept_key,
                kind=kind,
                text=text,
                user_id=user_id
            )

            dept_chat_id = DEPARTMENTS[dept_key]["chat_id"]
            send_message(dept_chat_id, admin_text)
            send_message(chat_id, standard_reply(kind))

            user_state[user_id] = {
                "chat_id": chat_id,
                "step": "choose_kind",
                "dept_from_link": state.get("dept_from_link")
            }
            return JSONResponse({"ok": True})

        user_state[user_id] = {
            "chat_id": chat_id,
            "step": "choose_kind",
            "dept_from_link": None
        }
        send_choose_kind_message(chat_id)
        return JSONResponse({"ok": True})

    return JSONResponse({"ok": True})
