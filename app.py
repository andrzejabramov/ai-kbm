import os
import json
import time
import re
import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# === КОНСТАНТЫ ===
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

if OPENROUTER_API_KEY:
    print(f"🔑 КЛЮЧ ЗАГРУЖЕН: {OPENROUTER_API_KEY[:15]}...")
else:
    print("❌ OPENROUTER_API_KEY не найден!")

# === ЗАГРУЗКА БАЗЫ ЗНАНИЙ ===
with open("knowledge_base.json", "r", encoding="utf-8") as f:
    KB = json.load(f)

COMPANY = KB["company_info"]
PRODUCTS = {p["code"]: p for p in COMPANY["products"]}
COST_TABLE = KB["cost_table"]
INTENTS = KB["intents"]
RESPONSES = KB["responses"]

# === СИСТЕМНЫЙ ПРОМПТ ===
SYSTEM_PROMPT = f"""Ты — AI-ассистент менеджера по продажам {COMPANY['name']}.
Твоя задача — помогать менеджеру обрабатывать заявки клиентов на буровые наконечники.

ПРАВИЛА:
1. Отвечай ТОЛЬКО на русском языке, кратко (2-4 предложения).
2. Используй эмодзи ⚡ для быстрых ответов и 📊 для расчётов.
3. Если пользователь просит расчёт, но не указал товар/количество — ЗАДАЙ уточняющий вопрос.
4. НИКОГДА не возвращай технические сообщения типа "Safety: safe" или системные логи.
5. Если не понимаешь запрос — вежливо попроси уточнить.

КОНТЕКСТ:
- Продукция: буровые наконечники (НБ-120, НБ-150, НБ-200, КБ-50).
- Ты работаешь с технологом и главным инженером для расчёта себестоимости.
- Всегда подтверждай ключевые цифры перед отправкой документа.

ПРИМЕРЫ ПРАВИЛЬНЫХ ОТВЕТОВ:
✅ "⚡ Для расчёта укажите товар и количество. Например: НБ-120, 100 шт."
✅ "📊 Заявка принята. Товар: НБ-120, количество: 100 шт. Подтверждаете?"
❌ "User Safety: safe" — ТАК НЕ ПИСАТЬ!
"""

# === КЭШ МОДЕЛЕЙ ===
FREE_MODELS_CACHE = []
LAST_MODEL_FETCH = 0


def get_available_free_models():
    global FREE_MODELS_CACHE, LAST_MODEL_FETCH
    if time.time() - LAST_MODEL_FETCH < 3600 and FREE_MODELS_CACHE:
        return FREE_MODELS_CACHE

    try:
        headers = {}
        if OPENROUTER_API_KEY:
            headers["Authorization"] = f"Bearer {OPENROUTER_API_KEY}"
        response = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=15)
        models_data = response.json().get("data", [])

        free_models = []
        for m in models_data:
            model_id = m.get("id", "")
            pricing = m.get("pricing", {})
            is_free = model_id.endswith(":free") or (
                pricing.get("prompt") == "0" and pricing.get("completion") == "0"
            )
            if is_free and m.get("context_length", 0) > 0:
                free_models.append(model_id)

        FREE_MODELS_CACHE = free_models[:10]
        LAST_MODEL_FETCH = time.time()
        return FREE_MODELS_CACHE
    except Exception as e:
        print(f"⚠️ Ошибка загрузки моделей: {e}")
        return [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-7b-instruct:free",
            "google/gemma-3-1b-it:free",
        ]


# === РАСПОЗНАВАНИЕ НАМЕРЕНИЙ ===
def detect_intent(text):
    text_lower = text.lower()

    # 🔥 ВАЖНО: Проверяем бизнес-инты ПЕРВЫМИ (высший приоритет)
    # 1. Новая заявка (самый важный интент)
    if any(kw in text_lower for kw in INTENTS["new_request"]):
        return "new_request"

    # 2. Расчёт себестоимости
    if any(kw in text_lower for kw in INTENTS["cost_calc"]):
        return "cost_calc"

    # 3. Статус заказа
    if any(kw in text_lower for kw in INTENTS["status"]):
        return "status"

    # 4. Помощь
    if any(kw in text_lower for kw in INTENTS["help"]):
        return "help"

    # 5. Приветствие (САМЫЙ НИЗКИЙ приоритет)
    if any(kw in text_lower for kw in INTENTS["greeting"]):
        return "greeting"

    return "unknown"


# === ИЗВЛЕЧЕНИЕ СУЩНОСТЕЙ ===
def extract_entities(text):
    entities = {"client": None, "product": None, "quantity": None, "deadline": None}

    # Клиент
    client_match = re.search(r'(ООО|ЗАО|АО|ИП|ОАО)\s+[«"]?([^«"\s,]+)[»"]?', text)
    if client_match:
        entities["client"] = f"{client_match.group(1)} {client_match.group(2)}"

    # Товар
    for code in PRODUCTS.keys():
        if code.lower() in text.lower():
            entities["product"] = code
            break

    # Количество
    qty_match = re.search(r"(\d+)\s*(шт|штук|единиц)?", text)
    if qty_match:
        entities["quantity"] = int(qty_match.group(1))

    # 🔥 ИСПРАВЛЕНИЕ: Дата в формате "15 июля" или "15.07.2026"
    # Сначала ищем числовой формат
    deadline_match = re.search(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", text)
    if deadline_match:
        entities["deadline"] = deadline_match.group(1)
    else:
        # Ищем текстовый формат "15 июля", "20 августа" и т.д.
        months = {
            "январ": "01",
            "феврал": "02",
            "март": "03",
            "апрел": "04",
            "ма": "05",
            "июн": "06",
            "июл": "07",
            "август": "08",
            "сентябр": "09",
            "октябр": "10",
            "ноябр": "11",
            "декабр": "12",
        }
        for month_name, month_num in months.items():
            if month_name in text.lower():
                day_match = re.search(r"(\d{1,2})\s+" + month_name, text.lower())
                if day_match:
                    day = day_match.group(1).zfill(2)
                    year = "2026"  # По умолчанию текущий год
                    entities["deadline"] = f"{day}.{month_num}.{year}"
                    break

    return entities


# === МАРШРУТЫ ===


@app.route("/")
def index():
    return render_template("index.html", company=COMPANY)


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    history = data.get("history", [])
    user_message = history[-1]["content"] if history else ""
    stage = data.get("stage", "idle")

    intent = detect_intent(user_message)
    entities = extract_entities(user_message)

    print(f"\n📩 ЗАПРОС: {user_message}")
    print(f"🎯 INTENT: {intent} | ENTITIES: {entities} | STAGE: {stage}")

    # === ПРИВЕТСТВИЕ (если нет сущностей) ===
    if intent == "greeting" and not (entities["product"] and entities["quantity"]):
        return jsonify(
            {
                "reply": RESPONSES["greeting"],
                "source": "local",
                "stage": "idle",
                "form_data": None,
            }
        )

    # === ПОМОЩЬ ===
    if intent == "help":
        return jsonify(
            {
                "reply": RESPONSES["help"],
                "source": "local",
                "stage": "idle",
                "form_data": None,
            }
        )

    # 🔥 ИСПРАВЛЕНИЕ 1: Сначала проверяем ПОДТВЕРЖДЕНИЕ (если stage == awaiting_confirmation)
    if stage == "awaiting_confirmation":
        confirm_words = [
            "да",
            "подтверждаю",
            "ок",
            "верно",
            "отправь",
            "ага",
            "угу",
            "yes",
        ]
        if any(w in user_message.lower() for w in confirm_words):
            # Пользователь подтвердил → запрашиваем себестоимость
            product_code = data.get("product_code")
            quantity = data.get("quantity", 0)

            if product_code and product_code in COST_TABLE:
                cost = COST_TABLE[product_code]
                total_cost = cost["total"] * quantity

                form_data = {
                    "type": "cost_calc",
                    "product_code": product_code,
                    "quantity": quantity,
                    "materials": cost["materials"] * quantity,
                    "labor": cost["labor"] * quantity,
                    "overhead": cost["overhead"] * quantity,
                    "total_cost": total_cost,
                    "engineer": KB["fake_engineers"]["technologist"]["name"],
                }

                reply = (
                    f"📬 Запрос отправлен технологу {form_data['engineer']}.\n"
                    f"⏱ Получен расчёт себестоимости:\n"
                    f"• Материалы: {form_data['materials']:,.0f} ₽\n"
                    f"• Труд: {form_data['labor']:,.0f} ₽\n"
                    f"• Накладные: {form_data['overhead']:,.0f} ₽\n"
                    f"• Итого себестоимость: {total_cost:,.0f} ₽\n\n"
                    f"Готово к расчёту маржи. Показать итог?"
                )

                return jsonify(
                    {
                        "reply": reply,
                        "source": "local",
                        "stage": "cost_ready",
                        "form_data": form_data,
                    }
                )

        # Если пользователь отменил
        cancel_words = ["нет", "отмена", "отменить", "stop", "стоп"]
        if any(w in user_message.lower() for w in cancel_words):
            return jsonify(
                {
                    "reply": "⚡ Заявка отменена. Готов к новой!",
                    "source": "local",
                    "stage": "idle",
                    "form_data": None,
                }
            )

        # Если непонятно — уточняем
        return jsonify(
            {
                "reply": "⚠️ Пожалуйста, подтвердите заявку (напишите «Да») или отмените (напишите «Нет»).",
                "source": "local",
                "stage": "awaiting_confirmation",
                "form_data": data.get("form_data"),
            }
        )

    # 🔥 ИСПРАВЛЕНИЕ 2: Теперь проверяем НОВУЮ ЗАЯВКУ
    if intent == "new_request":
        if entities["product"] and entities["quantity"]:
            product = PRODUCTS[entities["product"]]
            total_base = product["base_price"] * entities["quantity"]

            form_data = {
                "type": "request_form",
                "client": entities["client"] or "Не указан",
                "product_code": entities["product"],
                "product_name": product["name"],
                "quantity": entities["quantity"],
                "deadline": entities["deadline"] or "Не указан",
                "base_price": product["base_price"],
                "total_base": total_base,
            }

            reply = (
                f"📊 Заявка распознана:\n"
                f"• Клиент: {form_data['client']}\n"
                f"• Товар: {product['name']} ({entities['product']})\n"
                f"• Количество: {entities['quantity']} шт\n"
                f"• Срок: {form_data['deadline']}\n\n"
                f"Базовая цена: {total_base:,.0f} ₽\n\n"
                f"Подтвердите заявку, чтобы запросить себестоимость у технолога."
            )

            return jsonify(
                {
                    "reply": reply,
                    "source": "local",
                    "stage": "awaiting_confirmation",
                    "form_data": form_data,
                }
            )
        else:
            return jsonify(
                {
                    "reply": "⚠️ Не удалось распознать товар или количество. Укажите, например: «Новая заявка от ООО Горняк на 100 шт НБ-120 до 15.07.2026»",
                    "source": "local",
                    "stage": "idle",
                    "form_data": None,
                }
            )

    # === РАСЧЁТ МАРЖИ ===
    if stage == "cost_ready" or intent == "cost_calc":
        product_code = data.get("product_code")
        quantity = data.get("quantity", 0)
        base_price_total = data.get("total_base", 0)

        if product_code and product_code in COST_TABLE:
            cost = COST_TABLE[product_code]
            total_cost = cost["total"] * quantity
            profit = base_price_total - total_cost
            margin = (profit / base_price_total * 100) if base_price_total > 0 else 0

            form_data = {
                "type": "final_result",
                "product_code": product_code,
                "quantity": quantity,
                "revenue": base_price_total,
                "cost": total_cost,
                "profit": profit,
                "margin": round(margin, 1),
                "status": "approved" if margin > 30 else "review",
            }

            emoji = "🟢" if margin > 30 else "🟡" if margin > 15 else "🔴"
            reply = (
                f"{emoji} ИТОГОВЫЙ РАСЧЁТ:\n"
                f"• Выручка: {base_price_total:,.0f} ₽\n"
                f"• Себестоимость: {total_cost:,.0f} ₽\n"
                f"• Прибыль: {profit:,.0f} ₽\n"
                f"• Маржинальность: {margin:.1f}%\n\n"
                f"{'✅ Заказ можно отправлять в производство!' if margin > 30 else '⚠️ Маржа ниже нормы (30%). Требуется согласование с руководителем.'}"
            )

            return jsonify(
                {
                    "reply": reply,
                    "source": "local",
                    "stage": "final",
                    "form_data": form_data,
                }
            )

    # === FALLBACK: ИДЁМ В AI ===
    print("🤖 ИДЁМ В AI...")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "KBM Sales Agent",
        "Content-Type": "application/json",
    }

    models_to_try = get_available_free_models()
    for model in models_to_try:
        print(f"🔄 Пробуем: {model}")
        payload = {"model": model, "messages": messages, "max_tokens": 300}
        try:
            response = requests.post(
                OPENROUTER_URL, json=payload, headers=headers, timeout=20
            )
            if response.status_code in [429, 404]:
                continue
            if response.status_code != 200:
                continue
            result = response.json()
            reply = result["choices"][0]["message"]["content"]

            # Валидация ответа
            if "safety" in reply.lower() or len(reply) < 10:
                print(f"⚠️ Подозрительный ответ от AI: {reply}")
                reply = "⚠️ Извините, возникла техническая ошибка. Попробуйте переформулировать запрос или используйте кнопки быстрых команд."

            print(f"✅ УСПЕХ! Ответ от {model}")
            return jsonify(
                {"reply": reply, "source": "ai", "stage": stage, "form_data": None}
            )
        except Exception as e:
            print(f"💥 Ошибка: {e}")
            continue

    return (
        jsonify(
            {
                "reply": "⚠️ Все бесплатные модели перегружены. Попробуйте использовать кнопки быстрых команд.",
                "source": "error",
                "stage": stage,
                "form_data": None,
            }
        ),
        200,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("✅ AI-АГЕНТ ОТДЕЛА ПРОДАЖ КБМ ЗАПУЩЕН!")
    print("🌐 ОТКРОЙ: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
