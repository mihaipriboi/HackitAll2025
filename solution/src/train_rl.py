import os
from stable_baselines3 import PPO
from gym_env import RotablesEnv
from domain import NetworkState
from api_client import ApiClient
from strategy import Strategy
import pandas as pd
from config import DATA_DIR, FILE_TEAMS

def get_api_key():
    try:
        path = os.path.join(DATA_DIR, FILE_TEAMS)
        df = pd.read_csv(path, sep=';')
        return df.iloc[0]['api_key']
    except:
        return "TEST_KEY"

def train():
    # 1. Init Dependencies
    world = NetworkState()
    world.load_data()
    key = get_api_key()
    client = ApiClient(api_key=key)
    strategy = Strategy(world_state=world)
    
    # 2. Init Environment
    env = RotablesEnv(client, strategy)
    
    # 3. Define Model (PPO is great for continuous actions)
    model = PPO("MlpPolicy", env, verbose=1, learning_rate=0.0003)
    
    print("🧠 Starting RL Training...")
    # Din cauza vitezei, antrenăm puține episoade, dar e un PoC funcțional
    # 720 steps = 1 episod (joc complet)
    # 7200 steps = 10 jocuri
    model.learn(total_timesteps=3600) 
    
    print("💾 Saving model...")
    model.save("rotables_ppo_model")
    print("✅ Done!")

if __name__ == "__main__":
    train()