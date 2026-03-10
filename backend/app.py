"""
Flask Backend API — соединяет фронтенд с агентами.

Endpoints:
  POST /api/waitlist          — регистрация в waitlist
  POST /api/stripe/webhook    — Stripe events (payment success)
  GET  /api/stats             — статистика для дашборда
  GET  /api/signals           — последние крипто-сигналы
  GET  /api/results           — результаты агентов
  POST /api/run/<agent>       — ручной запуск агента (admin)
  POST /api/chat              — чат с AI (Groq)
"""
import os, json, hmac, hashlib
from flask import Flask, request, jsonify
from flask_cors import CORS
from groq import Groq

app  = Flask(__name__)
CORS(app, origins="*")

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "blomster-admin-2026")

PLAN_PRICES_NOK = {"росток": 149, "сад": 349, "полный_сад": 699}


# ── Waitlist ──────────────────────────────────────────────────
@app.route("/api/waitlist", methods=["POST"])
def waitlist():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    name  = data.get("name", "").strip()
    plan  = data.get("plan", "росток").strip()

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Invalid email"}), 400

    from backend.db import add_subscriber
    from backend.email import send_waitlist_welcome
    sub_id = add_subscriber(email, name, plan)
    send_waitlist_welcome(email, name or email, plan)

    return jsonify({
        "ok": True,
        "message": f"Välkommen {name}! Plass #{sub_id} er reservert.",
        "plan": plan,
    })


# ── Stripe Webhook ────────────────────────────────────────────
@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload   = request.get_data()
    sig       = request.headers.get("Stripe-Signature", "")

    # Verify webhook signature
    if STRIPE_WEBHOOK_SECRET:
        try:
            import stripe
            event = stripe.Webhook.construct_event(
                payload, sig, STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        try:
            event = json.loads(payload)
        except Exception:
            return jsonify({"error": "invalid json"}), 400

    event_type = event.get("type", "")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        email   = session.get("customer_email", "")
        plan    = session.get("metadata", {}).get("plan", "росток")
        amount  = session.get("amount_total", 0) / 100

        from backend.db import get_conn
        conn = get_conn()
        conn.execute(
            "UPDATE subscribers SET active=1 WHERE email=?", (email,)
        )
        conn.execute(
            "INSERT INTO payments (stripe_id,amount_nok,plan,status) VALUES (?,?,?,'paid')",
            (session.get("id"), amount, plan)
        )
        conn.commit()
        conn.close()

    elif event_type == "customer.subscription.deleted":
        customer_email = event["data"]["object"].get("customer_email", "")
        if customer_email:
            from backend.db import get_conn
            conn = get_conn()
            conn.execute(
                "UPDATE subscribers SET active=0 WHERE email=?", (customer_email,)
            )
            conn.commit()
            conn.close()

    return jsonify({"ok": True})


# ── Stats ─────────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def stats():
    from backend.db import get_stats
    return jsonify(get_stats())


# ── Signals ───────────────────────────────────────────────────
@app.route("/api/signals", methods=["GET"])
def signals():
    from backend.db import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_results WHERE agent='helianthus' ORDER BY ts DESC LIMIT 10"
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        try:
            results.append(json.loads(r["content"]))
        except Exception:
            results.append({"raw": r["content"]})
    return jsonify({"signals": results})


# ── Agent results ─────────────────────────────────────────────
@app.route("/api/results", methods=["GET"])
def results():
    agent = request.args.get("agent", "")
    from backend.db import get_conn
    conn = get_conn()
    q = "SELECT * FROM agent_results ORDER BY ts DESC LIMIT 20"
    if agent:
        q = f"SELECT * FROM agent_results WHERE agent=? ORDER BY ts DESC LIMIT 20"
        rows = conn.execute(q, (agent,)).fetchall()
    else:
        rows = conn.execute(q).fetchall()
    conn.close()
    return jsonify({"results": [dict(r) for r in rows]})


# ── Manual agent run (admin) ──────────────────────────────────
@app.route("/api/run/<agent_name>", methods=["POST"])
def run_agent(agent_name: str):
    if request.headers.get("X-Admin-Key") != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 403

    AGENTS = {
        "rosa":        "agents.rosa.RosaDamascena",
        "helianthus":  "agents.helianthus.Helianthus",
        "poppy":       "agents.poppy.PoppySales",
    }
    if agent_name not in AGENTS:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 400

    try:
        module_path, class_name = AGENTS[agent_name].rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        agent = getattr(mod, class_name)()
        result = agent.run()
        return jsonify({"ok": True, "result": str(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── AI Chat ───────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    data    = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "No message"}), 400

    messages = [
        {"role": "system", "content": """Du er en hjelpsom AI-assistent fra Blomster Hage.
Du hjelper brukere med AI-automatisering, innholdsskaping, kryptosignaler og freelancing i Norge.
Svar kort, konkret og profesjonelt på norsk eller russisk avhengig av hva brukeren skriver.
Fremhev tjenestene til Blomster Hage når det er naturlig."""}
    ] + history[-6:] + [{"role": "user", "content": message}]

    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=500,
        )
        reply = resp.choices[0].message.content
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    from backend.db import init_db
    init_db()
    app.run(host="0.0.0.0", port=8000, debug=False)
