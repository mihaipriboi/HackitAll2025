import sys
import os
import time
import numpy as np
import pandas as pd
import traceback

# --- DEBUG & IMPORTS ---
print("🔍 DEBUG: Script started. Loading system libraries...", flush=True)

try:
    # Încercăm importurile locale cu protecție
    from config import DATA_DIR, FILE_TEAMS, TOTAL_GAME_HOURS
    from domain import NetworkState
    from api_client import ApiClient
    from strategy import Strategy
    print("🔍 DEBUG: Project modules loaded.", flush=True)
except Exception as e:
    print(f"❌ CRITICAL ERROR importing project modules: {e}")
    traceback.print_exc()
    sys.exit(1)

# Încercăm importurile RL
RL_AVAILABLE = False
try:
    from stable_baselines3 import PPO
    RL_AVAILABLE = True
    print("🔍 DEBUG: Reinforcement Learning libraries found.", flush=True)
except ImportError:
    print("⚠️ WARNING: Stable Baselines3 not found. Running in Heuristic Mode.", flush=True)
except Exception as e:
    print(f"⚠️ WARNING: Error importing RL libraries: {e}", flush=True)

# --- HELPER FUNCTIONS ---

def get_api_key():
    """Helper to read API Key"""
    try:
        path = os.path.join(DATA_DIR, FILE_TEAMS)
        if not os.path.exists(path):
            return "TEST_KEY"
        df = pd.read_csv(path, sep=';')
        return df.iloc[0]['api_key']
    except Exception as e:
        print(f"⚠️ Error reading API Key: {e}")
        return "TEST_KEY"

def print_status_bar(day, hour, cost, penalties, ai_params=None):
    """Afișează o bară de stare dinamică."""
    
    # Formatare AI Params
    ai_str = ""
    # FIX CRITIC: Verificare explicită None pentru a evita eroarea NumPy
    if ai_params is not None:
        buf, buy, end = ai_params
        end_icon = "🏁" if end > 0.5 else "🟢"
        ai_str = f" | 🤖 AI: Buf={buf:.2f} Buy={buy:.1f}d {end_icon}"

    # Status icon
    status_icon = "✅"
    if penalties > 0: status_icon = "⚠️"
    if penalties > 5: status_icon = "🚨"

    # Bara de progres vizuală
    progress = (day * 24 + hour) / TOTAL_GAME_HOURS
    bar_len = 20
    filled = int(bar_len * progress)
    bar = "█" * filled + "░" * (bar_len - filled)

    sys.stdout.write(f"\r{status_icon} [D{day:02d}:H{hour:02d}] {bar} {int(progress*100)}% | 💰 {cost:,.0f}{ai_str}")
    sys.stdout.flush()

def print_daily_map_status(brain, day):
    """Generează un raport detaliat despre starea rețelei."""
    # Afișăm pe o linie nouă pentru a nu strica bara de progres
    sys.stdout.write("\n") 
    print(f"\n📊 --- NETWORK HEALTH REPORT: DAY {day} ---")
    
    hub_stock = {}
    out_stats = {c: {'total': 0, 'min': 999999, 'zeros': 0} for c in brain.classes}
    outstation_count = 0

    for code in brain.inventory:
        is_hub = (code == brain.hub_code)
        if not is_hub: outstation_count += 1
        
        for cls in brain.classes:
            qty = brain.get_real_stock(code, cls)
            
            if is_hub:
                hub_stock[cls] = qty
            else:
                stats = out_stats[cls]
                stats['total'] += qty
                if qty < stats['min']: stats['min'] = qty
                if qty <= 0: stats['zeros'] += 1

    print(f"🏭 HUB1 STOCK:")
    print(f"   {'CLASS':<16} {'QTY':<10} {'STATUS'}")
    for cls in brain.classes:
        qty = hub_stock.get(cls, 0)
        status = "🟢 OK" if qty > 100 else "🔴 LOW"
        if qty == 0: status = "💀 EMPTY"
        print(f"   {cls:<16} {qty:<10} {status}")

    print(f"\n🌍 OUTSTATIONS ({outstation_count} airports):")
    print(f"   {'CLASS':<16} {'AVG/AIRPORT':<12} {'LOWEST':<10} {'DANGER (0 STOCK)'}")
    print("-" * 65)
    
    for cls in brain.classes:
        stats = out_stats[cls]
        avg = stats['total'] / max(1, outstation_count)
        zeros = stats['zeros']
        
        danger_lvl = ""
        if zeros > 0: danger_lvl = f"⚠️ {zeros} airports"
        if zeros > 10: danger_lvl = f"🚨 {zeros} airports!"
        if zeros == 0: danger_lvl = "✅ All stocked"

        print(f"   {cls:<16} {avg:<12.1f} {stats['min']:<10} {danger_lvl}")
    print("-----------------------------------------------------------------\n")

# --- MAIN LOOP ---

def main():
    print("🚀 Initializing Rotables Solution (Dashboard Mode)...", flush=True)

    try:
        # 1. Load Data
        world = NetworkState()
        world.load_data()

        # 2. Connect API
        key = get_api_key()
        client = ApiClient(api_key=key)

        # 3. Initialize Strategy
        brain = Strategy(world_state=world)

        # 4. Load AI Model
        rl_model = None
        model_path = "rotables_ppo_model.zip"
        if RL_AVAILABLE and os.path.exists(model_path):
            print(f"🧠 AI Model found ({model_path}). Loading Brain...", flush=True)
            try:
                rl_model = PPO.load("rotables_ppo_model")
                print("✅ AI Brain loaded successfully!", flush=True)
            except Exception as e:
                print(f"⚠️ Failed to load AI model: {e}. Running heuristics.", flush=True)
        else:
            print("ℹ️ Running in Algorithmic Mode (No RL model found).", flush=True)

        simulation_completed_successfully = False

        print(f"🔌 Connecting to server at {client.base_url}...", flush=True)
        if not client.start_session():
            print("❌ Could not start session. Check server.")
            sys.exit(1)

        current_day = 0
        current_hour = 0
        final_cost = 0.0
        active_penalties = 0
        
        print("\n🎮 Simulation Started. Monitoring active...\n")
        print(f"{'TIME':<10} {'EVENT':<15} {'DETAILS'}")
        print("-" * 60)
        
        while (current_day * 24 + current_hour) < TOTAL_GAME_HOURS:
            
            # --- RAPORT ZILNIC ---
            if current_hour == 0 and current_day > 0:
                print_daily_map_status(brain, current_day)

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

            # --- STRATEGY ---
            flight_loads = brain.decide_kit_loads(current_day, current_hour)
            purchase_orders = brain.decide_purchases(current_day, current_hour)

            # --- API CALL ---
            response = client.play_round(current_day, current_hour, flight_loads, purchase_orders)

            if response:
                brain.update_state(current_day, current_hour, response)
                final_cost = response.get('totalCost', 0.0)
                
                # --- LOGGING ---
                # Log Achiziții
                if any(v > 0 for v in purchase_orders.values()):
                    total_items = sum(purchase_orders.values())
                    sys.stdout.write("\r" + " " * 100 + "\r") 
                    print(f"D{current_day:02d}:H{current_hour:02d}  🛒 BUY           Bought {total_items} kits")

                # Log Penalități
                new_penalties = response.get('penalties', [])
                if new_penalties:
                    active_penalties = len(new_penalties)
                    sys.stdout.write("\r" + " " * 100 + "\r")
                    first_code = new_penalties[0]['code']
                    print(f"D{current_day:02d}:H{current_hour:02d}  🚨 PENALTY       {first_code} ({len(new_penalties)} active)")
                else:
                    active_penalties = 0

                # Update Status Bar
                print_status_bar(current_day, current_hour, final_cost, active_penalties, current_ai_params)
                
            else:
                print(f"\n❌ Round failed at {current_day}:{current_hour}")
                raise Exception("Server communication failed")

            current_hour += 1
            if current_hour >= 24:
                current_hour = 0
                current_day += 1

        simulation_completed_successfully = True
        print(f"\n\n🏁 Simulation Complete.")
        print(f"🏆 Final Total Cost: {final_cost:,.2f}")

    except KeyboardInterrupt:
        print("\n\n🛑 Simulation stopped by user.")
    except Exception as e:
        print(f"\n❌ Unexpected Error in Main Loop: {e}")
        traceback.print_exc()
    finally:
        if not simulation_completed_successfully:
            print("\n🧹 Cleanup: Stopping session...")
            try:
                client.stop_session()
            except:
                pass
        else:
            print("\n✅ Session finished naturally.")

if __name__ == "__main__":
    main()