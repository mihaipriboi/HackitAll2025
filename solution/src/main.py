import os
import sys
import subprocess
import time
import numpy as np
import pandas as pd
from datetime import datetime

# Safe Imports
from config import DATA_DIR, FILE_TEAMS, TOTAL_GAME_HOURS, LOOP_SLEEP_SECONDS
from domain import NetworkState, Airport

# --- 1. LAUNCHER LOGIC ---
if __name__ == "__main__" and not os.environ.get("STREAMLIT_RUN_CTX"):
    print("🚀 Initializing DevCode Command Center...")
    current_file = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file)
    env = os.environ.copy()
    env["STREAMLIT_RUN_CTX"] = "true"
    cmd = [sys.executable, "-m", "streamlit", "run", current_file]
    try:
        subprocess.run(cmd, cwd=current_dir, env=env, check=True)
    except KeyboardInterrupt: pass
    sys.exit(0)

# ==============================================================================
#  STREAMLIT APP LOGIC
# ==============================================================================
import streamlit as st
from api_client import ApiClient
from strategy import Strategy
from gui import LogisticsDashboard

RL_AVAILABLE = False
try:
    from stable_baselines3 import PPO
    RL_AVAILABLE = True
    print("🔍 DEBUG: Reinforcement Learning libraries found.", flush=True)
except ImportError:
    print("⚠️ WARNING: Stable Baselines3 not found. Running in Heuristic Mode.", flush=True)
except Exception as e:
    print(f"⚠️ WARNING: Error importing RL libraries: {e}", flush=True)

MAX_LOG_HISTORY = 5000  # Enough for full 30-day simulation history

def get_api_key():
    try:
        path = os.path.join(DATA_DIR, FILE_TEAMS)
        if os.path.exists(path):
            return pd.read_csv(path, sep=';').iloc[0]['api_key']
    except: pass
    return "TEST_KEY"

# --- HTML LOG GENERATOR ---
def add_log_entry(day, hour, cost, penalties, departing_flights, loads, ai_params=None):
    """
    Creates a robust HTML block for the current hour.
    """
    time_str = f"Day {day} : {hour:02d}"
    
    # 1. Header Line
    html = f"""
    <div class="log-entry">
        <div class="log-header">
            <span>[{time_str}] Cost: ${cost:,.0f}</span>
            <span class="{'log-err' if penalties else 'dim'}">Pens: {len(penalties)}</span>
        </div>
        <div class="log-body">
    """
    
    # 2. Penalties (if any)
    if penalties:
        # Show first penalty detail, count rest
        first_pen = penalties[0]
        reason = first_pen.get('reason', 'Unknown reason')
        html += f"""<div class="log-err">⚠️ {len(penalties)} Penalties: {reason} ...</div>"""

    # 3. Departing Flights
    if departing_flights:
        count = len(departing_flights)
        html += f"""<div class="highlight">🛫 {count} Flights Departing:</div>
        """

        for flight in departing_flights:
            f_id = flight['flightId']
            my_load = next((l for l in loads if l['flightId'] == f_id), None)
            
            pax = flight['passengers']
            load = my_load['loadedKits'] if my_load else {'first':0,'business':0,'premiumEconomy':0,'economy':0}
            
            # Helper to format "Load/Pax"
            def fmt(l, p):
                color = "#FF4B4B" if l < p else "#888" # Red if understocked
                return f"<span style='color:{color}'>{l}/{p}</span>"
            
            f_str = fmt(load['first'], pax['first'])
            b_str = fmt(load['business'], pax['business'])
            p_str = fmt(load['premiumEconomy'], pax['premiumEconomy'])
            e_str = fmt(load['economy'], pax['economy'])
            
            html += f"""<div class="flight-row">
                <span class="highlight">{flight['flightNumber']}</span> 
                <span class="dim">({flight['originAirport']}➔{flight['destinationAirport']})</span><br/>
                <div class="dim" style="font-family:monospace">F:{f_str} B:{b_str} P:{p_str} E:{e_str}</div>
            </div>
            """

            
    html += """</div></div>""" # Close body and entry divs
    
    # 4. AI Params
    if ai_params is not None:
        buf, buy, end = ai_params
        end_icon = "🏁" if end > 0.5 else "🟢"
        ai_str = f" | 🤖 AI: Buf={buf:.2f} Buy={buy:.1f}d {end_icon}"
        html += f"""<div class="dim" style="font-size:0.9em">{ai_str}</div>"""

    st.session_state.logs.insert(0, html)
    if len(st.session_state.logs) > MAX_LOG_HISTORY:
        st.session_state.logs.pop()

def prepare_airport_data(world):
    """
    Prepares DataFrame with Stock AND Capacity for styling logic.
    """
    data = []
    for code, ap in world.airports.items():
        if code == 'HUB1': continue
        
        s = ap.stock
        c = ap.capacity
        
        # Determine Status
        status = "🟢 OK"
        if any(s[k] < 0 for k in s): status = "🔴 NEGATIVE"
        elif any(s[k] > c[k] for k in s): status = "🔴 OVERFLOW"
        elif s['ECONOMY'] < 20: status = "🟡 LOW"
        elif c['ECONOMY'] - s['ECONOMY'] < 20: status = "🟡 NEAR CAP"
            
        data.append({
            "Code": code,
            "Status": status,
            # Data Columns (Visible)
            "FC": s['FIRST'], 
            "BC": s['BUSINESS'], 
            "PE": s['PREMIUM_ECONOMY'], 
            "EC": s['ECONOMY'],
            # Capacity Columns (Hidden, used for calculation)
            "Cap_FC": c['FIRST'], 
            "Cap_BC": c['BUSINESS'], 
            "Cap_PE": c['PREMIUM_ECONOMY'], 
            "Cap_EC": c['ECONOMY']
        })
    
    df = pd.DataFrame(data)
    if not df.empty:
        # Sort by Status for visibility
        df = df.sort_values(by="Status", ascending=True)
    return df

def main_app():
    if 'world' not in st.session_state:
        st.session_state.world = NetworkState()
        st.session_state.world.load_data()
        st.session_state.client = ApiClient(api_key=get_api_key())
        st.session_state.brain = Strategy(st.session_state.world)
        st.session_state.running = False
        st.session_state.finished = False
        st.session_state.logs = []        
        st.session_state.cost_history = []
        st.session_state.penalty_count = 0
        st.session_state.last_view_data = None
        st.session_state.rl_mode = None


    dashboard = LogisticsDashboard()
    
    if dashboard.render_controls(st.session_state.running):
        st.session_state.running = True
        st.session_state.finished = False
        st.session_state.logs = [] 
        st.session_state.cost_history = []
        st.session_state.penalty_count = 0
        run_simulation(dashboard)

    # Static View
    if not st.session_state.running:
        if st.session_state.last_view_data:
            dashboard.render_update(st.session_state.last_view_data)
            if st.session_state.finished:
                st.success("Simulation Run Complete.")
        else:
            # Initial State
            hub = st.session_state.world.airports['HUB1']
            empty_data = {
                'day': 0, 'hour': 0, 'total_cost': 0.0, 'penalty_count': 0,
                'hub_stock': hub.stock,
                'cost_history': pd.DataFrame(),
                'logs': [],
                'airports_df': prepare_airport_data(st.session_state.world)
            }
            dashboard.render_update(empty_data)
    
    if st.session_state.rl_model == None:
        model_path = "rotables_ppo_model.zip"
        if RL_AVAILABLE and os.path.exists(model_path):
            print(f"🧠 AI Model found ({model_path}). Loading Brain...", flush=True)
            try:
                st.session_state.rl_model = PPO.load("rotables_ppo_model")
                print("✅ AI Brain loaded successfully!", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to load AI model: {e}. Running heuristics.", flush=True)
        else:
            print("ℹ️ Running in Algorithmic Mode (No RL model found).", flush=True)


def run_simulation(dashboard):
    client = st.session_state.client
    brain = st.session_state.brain
    world = st.session_state.world
    rl_model = st.session_state.rl_model
    
    st.session_state.logs.insert(0, "<div class='log-entry'>🔌 Connecting...</div>")
    client.stop_session()
    time.sleep(0.5)
    
    if not client.start_session():
        st.session_state.logs.insert(0, "<div class='log-entry log-err'>❌ Connection Failed.</div>")
        st.session_state.running = False
        st.rerun()
        return

    placeholder = st.empty()
    current_day = 0
    current_hour = 0

    last_total_cost = 0.0
    
    try:
        while (current_day * 24 + current_hour) < TOTAL_GAME_HOURS:
            # --- AI DECISION ---
            current_ai_params = None
            if rl_model:
                # Observație simplificată pentru AI
                time_norm = 1.0 - ((current_day * 24 + current_hour) / TOTAL_GAME_HOURS)
                hub_total = sum(brain.get_real_stock(brain.hub_code, c) for c in brain.classes)
                hub_norm = min(1.0, hub_total / 20000.0)
                obs = np.array([time_norm, hub_norm, 0.5], dtype=np.float32)
                
                # Predicție
                action, _ = rl_model.predict(obs)
                brain.set_ai_params(action[0], action[1], action[2])
                current_ai_params = action
            
            # Logic
            loads = brain.decide_kit_loads(current_day, current_hour)
            orders = brain.decide_purchases(current_day, current_hour)
            resp = client.play_round(current_day, current_hour, loads, orders)
            
            if resp:
                brain.update_state(current_day, current_hour, resp)
                total_cost = resp['totalCost']
                
                hour_cost = total_cost - last_total_cost
                last_total_cost = total_cost
                
                # Filter departing flights
                departing_now = []
                for update in resp.get('flightUpdates', []):
                    dep = update['departure']
                    if dep['day'] == current_day and dep['hour'] == current_hour:
                        departing_now.append(update)

                if resp.get('penalties'):
                    st.session_state.penalty_count += len(resp['penalties'])

                # Log
                add_log_entry(current_day, current_hour, hour_cost, resp.get('penalties', []), departing_now, loads, current_ai_params)

                st.session_state.cost_history.append({
                    'time': current_day * 24 + current_hour,
                    'cost': hour_cost
                })
                
                # Update View Data (Saved to State)
                view_data = {
                    'day': current_day,
                    'hour': current_hour,
                    'total_cost': total_cost,
                    'penalty_count': st.session_state.penalty_count,
                    'hub_stock': world.airports['HUB1'].stock,
                    'cost_history': pd.DataFrame(st.session_state.cost_history),
                    'logs': st.session_state.logs,
                    'airports_df': prepare_airport_data(world)
                }
                st.session_state.last_view_data = view_data
                
                with placeholder.container():
                    dashboard.render_update(view_data)
            else:
                st.session_state.logs.insert(0, "<div class='log-entry log-err'>❌ Server Error</div>")
                break
                
            current_hour += 1
            if current_hour >= 24:
                current_hour = 0
                current_day += 1
            
            time.sleep(LOOP_SLEEP_SECONDS)
            
        st.session_state.finished = True
            
    except Exception as e:
        st.session_state.logs.insert(0, f"<div class='log-entry log-err'>Error: {e}</div>")
    finally:
        client.stop_session()
        st.session_state.running = False
        st.rerun()

if __name__ == "__main__":
    main_app()
