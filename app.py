import gradio as gr
import math
import random
import os
import json
from collections import Counter
from google import genai

HOME_ADVANTAGE_FACTOR = 1.15
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

def get_team_stats_gemini(home_team, away_team):
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        prompt = f"""
Busca en internet las estadísticas recientes de estos dos equipos de fútbol.
Para cada equipo necesito los últimos 5 partidos y calcular:
- Promedio de goles marcados por partido
- Promedio de goles recibidos por partido

Equipos: {home_team} (local) y {away_team} (visitante)

Responde SOLO con este JSON exacto sin texto adicional ni markdown:
{{
  "home_avg_scored": 1.5,
  "home_avg_conceded": 1.0,
  "away_avg_scored": 1.2,
  "away_avg_conceded": 1.3
}}
"""
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return (
            float(data["home_avg_scored"]),
            float(data["home_avg_conceded"]),
            float(data["away_avg_scored"]),
            float(data["away_avg_conceded"]),
        )
    except Exception as e:
        return None, None, None, None

def poisson_random(lam):
    L = math.exp(-max(lam, 0.1))
    p, k = 1.0, 0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1

def monte_carlo(home_exp, away_exp, iterations=10000):
    return [(poisson_random(home_exp), poisson_random(away_exp)) for _ in range(iterations)]

def analyze(home_team, away_team, odd_home, odd_draw, odd_away, odd_over25, odd_btts):
    if not home_team or not away_team:
        return "⚠️ Ingresa los nombres de los equipos."

    home_avg, home_def, away_avg, away_def = get_team_stats_gemini(home_team, away_team)

    if home_avg is None:
        return "⚠️ No se pudieron obtener datos. Intenta de nuevo."

    league_avg = 1.4
    home_exp = max((home_avg / league_avg) * (away_def / league_avg) * league_avg * HOME_ADVANTAGE_FACTOR, 0.3)
    away_exp = max((away_avg / league_avg) * (home_def / league_avg) * league_avg, 0.3)

    results = monte_carlo(home_exp, away_exp)
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
⚽ {home_team} vs {away_team}
{'='*40}

📊 DATOS (vía Gemini AI)
  {home_team}: {home_avg} goles/partido (permite {home_def})
  {away_team}: {away_avg} goles/partido (permite {away_def})

📈 GOLES ESPERADOS
  Local:     {home_exp:.2f}
  Visitante: {away_exp:.2f}
  Total:     {home_exp+away_exp:.2f}

🎯 PROBABILIDADES 1X2
  {home_team}: {p_home:.1%}
  Empate:      {p_draw:.1%}
  {away_team}: {p_away:.1%}

⚽ OVER/UNDER
  Over 1.5: {p_o15:.1%}
  Over 2.5: {p_o25:.1%}
  Over 3.5: {p_o35:.1%}

🔥 BTTS (Ambos anotan)
  Sí: {p_btts:.1%} | No: {1-p_btts:.1%}

🏆 MARCADORES MÁS PROBABLES
{"".join(f"  {h}-{a}: {c/n:.1%}\n" for (h,a),c in top)}
💰 ANÁLISIS DE VALOR
{"".join(f"  {v}\n" for v in value_lines)}
🚦 {signal}
"""

demo = gr.Interface(
    fn=analyze,
    inputs=[
        gr.Textbox(label="Equipo Local", placeholder="Ej: Barcelona"),
        gr.Textbox(label="Equipo Visitante", placeholder="Ej: Real Madrid"),
        gr.Number(label="Cuota Victoria Local", value=2.10),
        gr.Number(label="Cuota Empate", value=3.40),
        gr.Number(label="Cuota Victoria Visitante", value=3.20),
        gr.Number(label="Cuota Over 2.5", value=1.85),
        gr.Number(label="Cuota BTTS Sí", value=1.75),
    ],
    outputs=gr.Textbox(label="Análisis Completo", lines=35),
    title="⚽ Analizador de Fútbol para Apuestas",
    description="Escribe los equipos y las cuotas — Gemini AI busca los datos automáticamente.",
)

demo.launch(server_name="0.0.0.0", server_port=10000)
