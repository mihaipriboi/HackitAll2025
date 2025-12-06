import time
import pandas as pd
import os
import sys

# Import our modular components
from config import DATA_DIR, FILE_TEAMS, TOTAL_GAME_HOURS
from domain import NetworkState
from api_client import ApiClient
from strategy import Strategy

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

def main():
    print("🚀 Initializing Rotables Solution...")

    # 1. Load Data
    world = NetworkState()
    world.load_data()

    # 2. Connect API
    key = get_api_key()
    client = ApiClient(api_key=key)

    # 3. Initialize Strategy
    brain = Strategy(world_state=world)

    # Flag to track if we finished the full 720 hours
    simulation_completed_successfully = False

    # --- WRAPPER FOR CLEANUP ---
    try:
        # START SESSION
        if not client.start_session():
            print("❌ Could not start session. Exiting.")
            sys.exit(1)

        # 4. Game Loop
        current_day = 0
        current_hour = 0
        final_cost = 0.0
        
        print("\n🎮 Starting Simulation Loop...")
        
        while (current_day * 24 + current_hour) < TOTAL_GAME_HOURS:
            print(f"\r[Day {current_day} : {current_hour:02d}] Processing...", end='')

            # Decide
            flight_loads = brain.decide_kit_loads(current_day, current_hour)
            purchase_orders = brain.decide_purchases(current_day, current_hour)

            # Act
            response = client.play_round(current_day, current_hour, flight_loads, purchase_orders)

            if response:
                # Update
                brain.update_state(current_day, current_hour, response)
                final_cost = response['totalCost']
                
                # Report
                if current_hour == 0:
                    print(f"\n   💰 Daily Cost Report: {final_cost:.2f}")
                    if response['penalties']:
                        print(f"   ⚠️ Active Penalties: {len(response['penalties'])}")
            else:
                print(f"\n❌ Round failed at {current_day}:{current_hour}")
                # We do NOT set success flag here, so finally block will clean up
                raise Exception("Server communication failed")

            # Advance
            current_hour += 1
            if current_hour >= 24:
                current_hour = 0
                current_day += 1
                
            time.sleep(0.05) 

        # --- SUCCESSFUL COMPLETION ---
        simulation_completed_successfully = True
        print(f"\n\n🏁 Simulation Complete.")
        print(f"🏆 Final Total Cost: {final_cost:,.2f}")

    except KeyboardInterrupt:
        print("\n\n🛑 Simulation stopped by user (Ctrl+C).")
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
    finally:
        # --- CONDITIONAL CLEANUP ---
        # Only manually stop the session if we crashed or were interrupted.
        # If we finished successfully, the backend automatically ends the session.
        if not simulation_completed_successfully:
            print("\n🧹 Cleanup: Stopping interrupted session...")
            client.stop_session()
            print("✅ Session closed forcefully.")
        else:
            print("\n✅ Session finished naturally.")

if __name__ == "__main__":
    main()