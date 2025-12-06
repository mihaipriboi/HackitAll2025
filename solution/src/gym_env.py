import gymnasium as gym
from gymnasium import spaces
import numpy as np
import time

class RotablesEnv(gym.Env):
    def __init__(self, api_client, strategy, total_hours=720):
        super(RotablesEnv, self).__init__()
        self.api = api_client
        self.strategy = strategy
        self.total_hours = total_hours
        self.current_step = 0
        self.day = 0
        self.hour = 0
        
        # --- OBSERVATION SPACE ---
        # 0: Time Left (normalized)
        # 1: Hub Stock Ratio (normalized avg across classes)
        # 2: Outstation Stock Ratio (normalized avg)
        self.observation_space = spaces.Box(low=0, high=1, shape=(3,), dtype=np.float32)
        
        # --- ACTION SPACE ---
        # 0: Buffer Factor (0.0 to 1.0)
        # 1: Purchase Threshold (Days) (0.0 to 5.0)
        # 2: Force Endgame (0.0 to 1.0, >0.5 is True)
        self.action_space = spaces.Box(low=np.array([0, 0, 0]), high=np.array([1.0, 5.0, 1.0]), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        # Restart Session
        print("\n🔄 RL: Resetting Environment...")
        self.api.stop_session()
        time.sleep(1) # Wait for cleanup
        if not self.api.start_session():
            raise RuntimeError("Failed to start API session during reset")
            
        # Reset Internal State
        self.current_step = 0
        self.day = 0
        self.hour = 0
        
        # Re-sync Strategy from static
        self.strategy.sync_inventory_static()
        
        return self._get_obs(), {}

    def step(self, action):
        # 1. Apply Action to Strategy
        buffer_factor = action[0]
        purch_threshold = action[1]
        force_endgame = action[2]
        
        self.strategy.set_ai_params(buffer_factor, purch_threshold, force_endgame)
        
        # 2. Run Strategy Logic
        flight_loads = self.strategy.decide_kit_loads(self.day, self.hour)
        purch_orders = self.strategy.decide_purchases(self.day, self.hour)
        
        # 3. Call API
        response = self.api.play_round(self.day, self.hour, flight_loads, purch_orders)
        
        reward = 0
        terminated = False
        
        if response:
            self.strategy.update_state(self.day, self.hour, response)
            
            # --- REWARD CALCULATION ---
            # Penalize penalties heavily
            penalties_count = len(response.get('penalties', []))
            penalty_cost = sum(p.get('penalty', 0) for p in response.get('penalties', []))
            
            # Reward is negative cost. 
            # We want to minimize cost, so maximize negative cost.
            # Scale it down so numbers aren't huge (e.g., millions).
            reward = - (penalty_cost / 1000.0) 
            
            if penalties_count > 0:
                reward -= 100 # Extra penalty for just having an error
                
        else:
            # API Fail -> Big penalty and terminate
            reward = -10000
            terminated = True

        # 4. Advance Time
        self.hour += 1
        if self.hour >= 24:
            self.hour = 0
            self.day += 1
        
        self.current_step += 1
        if self.current_step >= self.total_hours:
            terminated = True
            
        return self._get_obs(), reward, terminated, False, {}

    def _get_obs(self):
        # Simplified observation
        time_norm = 1.0 - (self.current_step / self.total_hours)
        
        # Hub Stock Avg (Normalized roughly)
        hub_total = sum(self.strategy.get_real_stock(self.strategy.hub_code, c) for c in self.strategy.classes)
        hub_norm = min(1.0, hub_total / 20000.0)
        
        # Outstation Stock approximation
        # (This is costly to compute exactly every step, so we assume strategy handles it, 
        # but for RL we pass a dummy or a sampled value. Using dummy 0.5 for speed now)
        out_norm = 0.5 
        
        return np.array([time_norm, hub_norm, out_norm], dtype=np.float32)