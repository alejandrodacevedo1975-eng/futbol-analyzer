import os
import math
import random
import json
import requests
from collections import Counter
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
HOME_ADVANTAGE_FACTOR = 1.15

def get_team_stats(home_team, away_team):
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_KEY)
        prompt = f"""
Busca en internet estadísticas reales de fútbol de {home_team} y {away_team}.
Encuentra sus últimos 5-10 partidos y calcula promedio de goles marcados y recibidos.
Responde SOLO con JSON sin markdown:
{{"home_avg_scored":1.5,"home_avg_conceded":1.0,"away_avg_scored":1.2,"away_avg_conceded":1.3}}
"""
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )
        text = response.text.strip().replace("```json","").replace("```","").strip()
        data = json.loads(text)
        return float(data["home_avg_scored"]), float(data["home_avg_conceded"]), float(data["away_avg_scored"]), float(data["away_avg_conceded"])
    except:
        return None, None, None, None

def poisson_random(lam):
    L = math.exp(-max(lam, 0.1))
    p, k = 1.0, 0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1

def analizar(home_team, away_team, odd_home, odd_draw, odd_away, odd_over25, odd_btts):
    home_avg, home_def, away_avg, away_def = get_team_stats(home_team, away_team)
    if home_avg is None:
        return "⚠️ No se pudieron obtener datos. Intenta de nuevo."

    league_avg = 1.4
    home_exp = max((home_avg/league_avg)*(away_def/league_avg)*league_avg*HOME_ADVANTAGE_FACTOR, 0.3)
    away_exp = max((away_avg/league_avg)*(home_def/league_avg)*league_avg, 0.3)

    results = [(poisson_random(home_exp), poisson_random(away_exp)) for _ in range(10000)]
    n = len(results)

    p_home = sum(1 for h,a in results if h > a) / n
    p_draw = sum(1 for h,a in results if h == a) / n
    p_away = sum(1 for h,a in results if h < a) / n
    p_o15  = sum(1 for h,a in results if h+a > 1.5) / n
    p_o25  = sum(1 for h,a in results if h+a > 2.5) / n
    p_o35  = sum(1 for h,a in results if h+a > 3.5) / n
    p_btts = sum(1 for h,a in results if h > 0 and a > 0) / n
    top = Counter(results).most_common(5)

    markets = {
        "Victoria Local": (p_home, odd_home),
        "Empate":         (p_draw, odd_draw),
        "Victoria Visit": (p_away, odd_away),
        "Over 2.5":       (p_o25,  odd_over25),
        "BTTS Sí":        (p_btts, odd_btts),
    }
    value_lines = []
    for market, (prob, odd) in markets.items():
        if odd and odd > 1:
            ev = (prob * odd) - 1
            icon = "✅" if ev > 0.05 else "❌"
            value_lines.append(f"{icon} {market}: EV {ev:+.2%} | Cuota {odd}")

    max_prob = max(p_home, p_draw, p_away)
    has_value = any("✅" in v for v in value_lines)
    if max_prob >= 0.55 and has_value:
        signal = "🟢 ALTA CONFIANZA"
    elif max_prob >= 0.45:
        signal = "🟡 CONFIANZA MEDIA"
    else:
        signal = "🔴 BAJA CONFIANZA"

    return f"""
⚽ *{home_team} vs {away_team}*

📊 *Datos automáticos*
{home_team}: {home_avg} goles/p (permite {home_def})
{away_team}: {away_avg} goles/p (permite {away_def})

📈 *Goles esperados*
Local: {home_exp:.2f} | Visit: {away_exp:.2f} | Total: {home_exp+away_exp:.2f}

🎯 *Probabilidades 1X2*
{home_team}: {p_home:.1%}
Empate: {p_draw:.1%}
{away_team}: {p_away:.1%}

⚽ *Over/Under*
Over 1.5: {p_o15:.1%} | Over 2.5: {p_o25:.1%} | Over 3.5: {p_o35:.1%}

🔥 *BTTS*
Sí: {p_btts:.1%} | No: {1-p_btts:.1%}

🏆 *Marcadores probables*
{"".join(f"{h}-{a}: {c/n:.1%}\n" for (h,a),c in top)}
💰 *Valor de apuesta*
{"".join(f"{v}\n" for v in value_lines)}
🚦 *{signal}*
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ *Analizador de Fútbol para Apuestas*\n\n"
        "Envía el análisis así:\n"
        "`/analizar Barcelona Real Madrid 2.10 3.40 3.20 1.85 1.75`\n\n"
        "Orden: Local Visitante CuotaLocal CuotaEmpate CuotaVisit CuotaOver25 CuotaBTTS",
        parse_mode="Markdown"
    )

async def analizar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 7:
        await update.message.reply_text(
            "⚠️ Uso correcto:\n`/analizar Barcelona RealMadrid 2.10 3.40 3.20 1.85 1.75`",
            parse_mode="Markdown"
        )
        return
    home = args[0]
    away = args[1]
    try:
        odds = [float(x) for x in args[2:7]]
    except:
        await update.message.reply_text("⚠️ Las cuotas deben ser números. Ej: 2.10")
        return

    await update.message.reply_text("🔍 Analizando... espera unos segundos.")
    resultado = analizar(home, away, *odds)
    await update.message.reply_text(resultado, parse_mode="Markdown")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analizar", analizar_cmd))
    app.run_polling()
