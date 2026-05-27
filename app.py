import gradio as gr
import math
import random
import os
import requests
from collections import Counter

HOME_ADVANTAGE_FACTOR = 1.15
FD_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")

COMPETITIONS = {
    "Premier League": "PL",
    "La Liga": "PD", 
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "Ligue 1": "FL1",
    "Champions League": "CL",
    "Eredivisie": "DED",
}

def get_team_id(team_name):
    headers = {"X-Auth-Token": FD_KEY}
    for comp_id in COMPETITIONS.values():
        try:
            r = requests.get(
                f"https://api.football-data.org/v4/competitions/{comp_id}/teams",
                headers=headers, timeout=10
            )
            teams = r.json().get("teams", [])
            for t in teams:
                if team_name.lower() in t["name"].lower() or team_name.lower() in t.get("shortName","").lower():
                    return t["id"]
        except:
            continue
    return None

def get_team_stats(team_id):
    headers = {"X-Auth-Token": FD_KEY}
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/teams/{team_id}/matches",
            headers=headers,
            params={"status": "FINISHED", "limit": 10},
            timeout=10
        )
        matches = r.json().get("matches", [])
        if not matches:
            return None, None
        goals_for, goals_against = [], []
        for m in matches:
            home_id = m["homeTeam"]["id"]
            gh = m["score"]["fullTime"]["home"]
            ga = m["score"]["fullTime"]["away"]
            if gh is None or ga is None:
                continue
            if home_id == team_id:
                goals_for.append(gh)
                goals_against.append(ga)
            else:
                goals_for.append(ga)
                goals_against.append(gh)
        if not goals_for:
            return None, None
        return round(sum(goals_for)/len(goals_for), 2), round(sum(goals_against)/len(goals_against), 2)
    except:
        return None, None

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

    home_id = get_team_id(home_team)
    away_id = get_team_id(away_team)

    if not home_id or not away_id:
        return f"⚠️ No se encontró: {''+home_team if not home_id else away_team}. Intenta con el nombre en inglés."

    home_avg, home_def = get_team_stats(home_id)
    away_avg, away_def = get_team_stats(away_id)

    if home_avg is None or away_avg is None:
        return "⚠️ No se pudieron obtener estadísticas. Intenta de nuevo."

    league_avg = 1.4
    home_exp = max((home_avg/league_avg)*(away_def/league_avg)*league_avg*HOME_ADVANTAGE_FACTOR, 0.3)
    away_exp = max((away_avg/league_avg)*(home_def/league_avg)*league_avg, 0.3)

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

📊 DATOS REALES (football-data.org)
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
        gr.Textbox(label="Equipo Visitante", placeholder="Ej: Arsenal"),
        gr.Number(label="Cuota Victoria Local", value=2.10),
        gr.Number(label="Cuota Empate", value=3.40),
        gr.Number(label="Cuota Victoria Visitante", value=3.20),
        gr.Number(label="Cuota Over 2.5", value=1.85),
        gr.Number(label="Cuota BTTS Sí", value=1.75),
    ],
    outputs=gr.Textbox(label="Análisis Completo", lines=35),
    title="⚽ Analizador de Fútbol para Apuestas",
    description="Escribe los equipos y las cuotas — los datos se obtienen automáticamente.",
)

demo.launch()
