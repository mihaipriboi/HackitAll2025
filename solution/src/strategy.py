from collections import defaultdict
from copy import deepcopy

from api_client import create_flight_load
from config import TOTAL_GAME_HOURS


class Strategy:
    """
    Hybrid strategy with RL hooks:
    - Tracks inventory and kit processing locally to avoid negative stock penalties.
    - Loads kits based on passengers and destination buffer needs.
    - Reorders to HUB1 with thresholds tunable via set_ai_params (used by RL env).
    """

    def __init__(self, world_state):
        self.world = world_state
        self.hub_code = "HUB1"
        self.classes = ["FIRST", "BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"]

        # Live flight events indexed by (day, hour) -> flightId -> event
        self.departures = defaultdict(dict)

        # Inventory and processing
        self.inventory = {}
        self.processing_queue = []  # list of {"airport": str, "cls": str, "qty": int, "ready_time": int}

        # Base buffers (scaled by RL)
        self.base_dest_min_stock = {
            "FIRST": 0,
            "BUSINESS": 2,
            "PREMIUM_ECONOMY": 3,
            "ECONOMY": 10,
        }
        self.dest_min_stock = deepcopy(self.base_dest_min_stock)

        self.base_hub_reorder_threshold = {
            "FIRST": 80,
            "BUSINESS": 180,
            "PREMIUM_ECONOMY": 320,
            "ECONOMY": 1200,
        }
        self.hub_reorder_threshold = deepcopy(self.base_hub_reorder_threshold)
        self.hub_reorder_amount = {
            "FIRST": 50,
            "BUSINESS": 120,
            "PREMIUM_ECONOMY": 180,
            "ECONOMY": 600,
        }

        # Lead times (hours) when purchasing kits
        self.purchase_lead_time = {
            "FIRST": 48,
            "BUSINESS": 36,
            "PREMIUM_ECONOMY": 24,
            "ECONOMY": 12,
        }

        # AI parameters (can be tuned by RL)
        self.ai_buffer_factor = 0.15
        self.ai_purchase_threshold_days = 0.6
        self.ai_endgame_mode = False

        # Safety reserve at origin (to avoid negative inventory mismatch)
        self.origin_reserve = {
            "FIRST": 1,
            "BUSINESS": 3,
            "PREMIUM_ECONOMY": 5,
            "ECONOMY": 20,
        }

        self.sync_inventory_static()

    # --- Time helpers ---
    def _time_to_int(self, day, hour):
        return day * 24 + hour

    def _int_to_time(self, total_hours):
        return total_hours // 24, total_hours % 24

    def _add_hours(self, day, hour, delta):
        return self._int_to_time(self._time_to_int(day, hour) + delta)

    # --- Inventory helpers ---
    def _available_inventory(self, airport_code, cls):
        return int(self.inventory.get(airport_code, {}).get(cls, 0))

    def _consume_inventory(self, airport_code, cls, qty):
        if qty <= 0:
            return
        self.inventory.setdefault(airport_code, {})
        self.inventory[airport_code][cls] = self.inventory[airport_code].get(cls, 0) - qty

    def _release_processed_kits(self, current_day, current_hour):
        """Move kits from processing/purchase queues into available inventory."""
        now = self._time_to_int(current_day, current_hour)
        remaining = []
        for item in self.processing_queue:
            if item["ready_time"] <= now:
                self.inventory.setdefault(item["airport"], {})
                self.inventory[item["airport"]][item["cls"]] = self.inventory[item["airport"]].get(item["cls"], 0) + item["qty"]
            else:
                remaining.append(item)
        self.processing_queue = remaining

    def _schedule_processing_return(self, dest, cls, qty, arrival_day, arrival_hour):
        """After arrival, kits re-enter inventory post-processing."""
        if qty <= 0 or not dest:
            return
        airport = self.world.airports.get(dest)
        if not airport:
            return
        processing_hours = int(airport.processing_time.get(cls, 4))
        ready_day, ready_hour = self._add_hours(arrival_day, arrival_hour, processing_hours)
        ready_time = self._time_to_int(ready_day, ready_hour)
        self.processing_queue.append({"airport": dest, "cls": cls, "qty": qty, "ready_time": ready_time})

    def _schedule_purchase_arrival(self, current_day, current_hour, orders):
        """Track incoming purchases to keep local inventory in sync with backend deliveries."""
        for cls_key, qty in orders.items():
            if qty <= 0:
                continue
            # Map API field names to internal cls
            if cls_key == "first":
                cls = "FIRST"
            elif cls_key == "business":
                cls = "BUSINESS"
            elif cls_key == "premiumEconomy":
                cls = "PREMIUM_ECONOMY"
            elif cls_key == "economy":
                cls = "ECONOMY"
            else:
                continue

            lead = self.purchase_lead_time.get(cls, 12)
            ready_day, ready_hour = self._add_hours(current_day, current_hour, lead)
            ready_time = self._time_to_int(ready_day, ready_hour)
            self.processing_queue.append({"airport": self.hub_code, "cls": cls, "qty": int(qty), "ready_time": ready_time})

    # --- RL hooks ---
    def set_ai_params(self, buffer_factor: float, purch_threshold_days: float, force_endgame: float):
        """
        Allow RL/heuristics to scale buffers and reorder aggressiveness.
        buffer_factor: scales destination min stock (0.2 - 2.0).
        purch_threshold_days: hub stock target in 'days' of burn (0 - 5).
        force_endgame: if >0.5 we suppress late-game buying.
        """
        buffer_factor = max(0.05, min(1.0, float(buffer_factor)))
        purch_threshold_days = max(0.0, min(2.0, float(purch_threshold_days)))
        force_endgame = float(force_endgame)

        self.ai_buffer_factor = buffer_factor
        self.ai_purchase_threshold_days = purch_threshold_days
        self.ai_endgame_mode = force_endgame > 0.5 or self.ai_endgame_mode

        # Scale destination buffers
        self.dest_min_stock = {k: int(v * buffer_factor) for k, v in self.base_dest_min_stock.items()}

        # Hub thresholds proportional to desired days of coverage (rough heuristic)
        burn_rates = {"FIRST": 8, "BUSINESS": 30, "PREMIUM_ECONOMY": 60, "ECONOMY": 300}
        for cls in self.classes:
            target = burn_rates[cls] * 24 * purch_threshold_days
            self.hub_reorder_threshold[cls] = max(0, int(target))
            self.hub_reorder_amount[cls] = max(0, int(target * 0.6))

        if self.ai_endgame_mode:
            self.hub_reorder_amount = {k: 0 for k in self.hub_reorder_amount}

    def sync_inventory_static(self):
        """Reset inventory/queues based on CSV initial stock."""
        self.departures = defaultdict(dict)
        self.inventory = {
            code: {cls: int(stock) for cls, stock in airport.stock.items()}
            for code, airport in self.world.airports.items()
        }
        self.processing_queue = []

    def get_real_stock(self, airport_code, cls):
        return self._available_inventory(airport_code, cls)

    # --- Main game loop hooks ---
    def update_state(self, current_day, current_hour, api_response):
        """
        Update flight calendar with latest events.
        """
        if not api_response or "flightUpdates" not in api_response:
            return

        for event in api_response["flightUpdates"]:
            dep = event.get("departure") or {}
            dep_day = int(dep.get("day", current_day))
            dep_hour = int(dep.get("hour", current_hour))
            flight_id = event.get("flightId")
            if not flight_id:
                continue

            if event["eventType"] in ("SCHEDULED", "CHECKED_IN"):
                self.departures[(dep_day, dep_hour)][flight_id] = event
            elif event["eventType"] == "LANDED":
                self.departures[(dep_day, dep_hour)].pop(flight_id, None)

    def decide_kit_loads(self, current_day, current_hour):
        # Release processed kits and purchases into inventory
        self._release_processed_kits(current_day, current_hour)

        flights_leaving = list(self.departures.get((current_day, current_hour), {}).values())
        loads = []

        def passenger_count(passengers, *keys):
            for key in keys:
                val = passengers.get(key)
                if val is not None:
                    return int(val)
            return 0

        for event in flights_leaving:
            flight_id = event.get("flightId")
            plane_type = event.get("aircraftType")
            passengers = event.get("passengers", {}) or {}
            origin = event.get("originAirport")
            destination = event.get("destinationAirport")
            arrival_info = event.get("arrival", {}) or {}
            arrival_day = int(arrival_info.get("day", current_day))
            arrival_hour = int(arrival_info.get("hour", current_hour))

            plane_info = self.world.aircraft_types.get(plane_type)
            if not plane_info or not origin or not destination:
                continue

            # Available inventory at origin
            avail = {cls: self._available_inventory(origin, cls) for cls in self.classes}
            dest_stock = {cls: self._available_inventory(destination, cls) for cls in self.classes}

            # Requests per class
            requests = {
                "FIRST": passenger_count(passengers, "first", "firstClass"),
                "BUSINESS": passenger_count(passengers, "business", "businessClass"),
                "PREMIUM_ECONOMY": passenger_count(passengers, "premiumEconomy", "premiumEconomyClass", "premium"),
                "ECONOMY": passenger_count(passengers, "economy", "economyClass"),
            }

            # Capacity limits
            caps = plane_info.kit_capacity

            # Compute desired load with buffer to raise dest stock toward target
            loads_per_class = {}
            for cls in self.classes:
                buffer_need = max(0, self.dest_min_stock[cls] - dest_stock[cls])
                desired = requests[cls] + int(buffer_need * self.ai_buffer_factor)
                # Clamp to capacity and available origin stock
                safe_avail = max(0, avail[cls] - self.origin_reserve.get(cls, 0))
                desired = min(desired, caps[cls], safe_avail)
                loads_per_class[cls] = max(0, desired)

            # Reduce origin inventory
            for cls in self.classes:
                self._consume_inventory(origin, cls, loads_per_class[cls])

            # Schedule kits to return into destination inventory after processing time
            for cls in self.classes:
                self._schedule_processing_return(destination, cls, loads_per_class[cls], arrival_day, arrival_hour)

            load_cmd = create_flight_load(
                flight_id=str(flight_id),
                first=loads_per_class["FIRST"],
                business=loads_per_class["BUSINESS"],
                premium=loads_per_class["PREMIUM_ECONOMY"],
                economy=loads_per_class["ECONOMY"],
            )
            loads.append(load_cmd)

        # cleanup
        if (current_day, current_hour) in self.departures:
            self.departures.pop((current_day, current_hour), None)

        return loads

    def decide_purchases(self, current_day, current_hour):
        """
        Reorder to HUB1 when stock drops below thresholds.
        """
        # Auto endgame safety after day 24
        if current_day >= 22:
            self.ai_endgame_mode = True

        orders = {
            "first": 0,
            "business": 0,
            "premiumEconomy": 0,
            "economy": 0,
        }

        current_abs = self._time_to_int(current_day, current_hour)
        hours_left = TOTAL_GAME_HOURS - current_abs

        # Burn rates used to size thresholds
        burn_rates = {"FIRST": 8, "BUSINESS": 30, "PREMIUM_ECONOMY": 60, "ECONOMY": 300}

        for cls in self.classes:
            hub_stock = self._available_inventory(self.hub_code, cls)
            threshold = self.hub_reorder_threshold[cls]
            amount = self.hub_reorder_amount[cls]

            # Skip if endgame or not enough time for delivery
            lead = self.purchase_lead_time.get(cls, 12)
            if self.ai_endgame_mode or hours_left <= lead + 6:
                continue

            # Safety: avoid exceeding capacity
            cap = self.world.airports[self.hub_code].capacity.get(cls, threshold + amount + 1000)
            if hub_stock < threshold:
                order_qty = min(amount, max(0, cap - hub_stock))
                if order_qty > 0:
                    api_key = self._cls_key(cls)
                    orders[api_key] = int(order_qty)

            # Track expected arrivals so our local inventory stays closer to backend state
        self._schedule_purchase_arrival(current_day, current_hour, orders)

        return orders

    # --- Utility ---
    def _cls_key(self, cls):
        return {
            "FIRST": "first",
            "BUSINESS": "business",
            "PREMIUM_ECONOMY": "premiumEconomy",
            "ECONOMY": "economy",
        }.get(cls, "economy")
