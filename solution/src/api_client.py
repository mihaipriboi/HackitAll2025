import requests
import logging
from typing import List, Dict, Optional
from config import API_URL

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ApiClient:
    def __init__(self, api_key: str, base_url: str = API_URL):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self.session_id = None
        self.timeout = 5 # Seconds

    def start_session(self) -> bool:
        """
        Starts the game session and captures the SESSION-ID.
        """
        url = f"{self.base_url}/api/v1/session/start"
        
        try:
            # Added timeout
            response = self.session.post(url, timeout=self.timeout)
            
            # --- HANDLE 409 CONFLICT ---
            if response.status_code == 409:
                logger.warning("⚠️ Active session found (409). Restarting session...")
                self.stop_session() 
                try:
                    response = self.session.post(url, timeout=self.timeout)
                    response.raise_for_status()
                except Exception as retry_e:
                    logger.error(f"❌ Failed to restart session: {retry_e}")
                    return False

            response.raise_for_status()
            
            # --- CAPTURE SESSION-ID ---
            self.session_id = response.text.strip().replace('"', '')
            
            if not self.session_id:
                logger.error("❌ Server returned empty Session ID!")
                return False
                
            self.session.headers.update({"SESSION-ID": self.session_id})
            logger.info(f"✅ Session started successfully. ID: {self.session_id}")
            return True
            
        except requests.exceptions.ConnectionError:
            logger.error(f"❌ Connection Refused: Could not connect to {self.base_url}")
            logger.error("   -> Is the Java Server running?")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to start session: {e}")
            if e.response is not None:
                logger.error(f"Server response: {e.response.text}")
            return False

    def play_round(self, day: int, hour: int, 
                   flight_loads: List[Dict], 
                   kit_orders: Dict[str, int] = None) -> Optional[Dict]:
        """Submits decisions for the current hour."""
        
        if not self.session_id:
            logger.error("❌ Cannot play round: No Session ID")
            return None

        if kit_orders is None:
            kit_orders = create_per_class_amount(0, 0, 0, 0)

        payload = {
            "day": day,
            "hour": hour,
            "flightLoads": flight_loads,
            "kitPurchasingOrders": kit_orders
        }

        url = f"{self.base_url}/api/v1/play/round"
        
        try:
            # Added timeout
            response = self.session.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code == 400:
                logger.error(f"⚠️ Validation Error (400) at Day {day} Hour {hour}: {response.text}")
                return None
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Connection Error playing round {day}:{hour} - {e}")
            return None

    def stop_session(self):
        """Stops the session."""
        try:
            url = f"{self.base_url}/api/v1/session/end"
            # Added timeout so it doesn't hang if server is down
            self.session.post(url, timeout=2) 
            logger.warning("🛑 Session stopped.")
        except requests.exceptions.ConnectionError:
            # We don't crash here, but we warn the user
            logger.warning("⚠️ Could not stop session: Server unreachable.")
        except Exception as e:
            logger.warning(f"⚠️ Error stopping session: {e}")

# --- Helper Functions ---

def create_per_class_amount(first=0, business=0, premium=0, economy=0):
    return {
        "first": int(first),
        "business": int(business),
        "premiumEconomy": int(premium),
        "economy": int(economy)
    }

def create_flight_load(flight_id: str, first=0, business=0, premium=0, economy=0):
    return {
        "flightId": str(flight_id),
        "loadedKits": create_per_class_amount(first, business, premium, economy)
    }