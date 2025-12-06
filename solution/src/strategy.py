from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from api_client import create_flight_load, create_per_class_amount

CLASS_ORDER = ["FIRST", "BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"]
EVENT_CLASS_KEYS = {
    "FIRST": "first",
    "BUSINESS": "business",
    "PREMIUM_ECONOMY": "premiumEconomy",
    "ECONOMY": "economy",
}


@dataclass
class FlightInfo:
    flight_id: str
    origin: str
    destination: str
    departure: Tuple[int, int]
    arrival: Tuple[int, int]
    passengers: Dict[str, int]
    aircraft_type: str


@dataclass
class ProcessingJob:
    ready_time: Tuple[int, int]
    airport: str
    kit_class: str
    quantity: int


class Strategy:
    def __init__(self, world_state):
        """
        Initialize the strategy.
        Args:
            world_state (NetworkState): Static data loaded from CSVs.
        """
        self.world = world_state

        # Flights indexed by id and by departure time
        self.flights: Dict[str, FlightInfo] = {}
        self.departures: defaultdict[Tuple[int, int], List[str]] = defaultdict(list)

        # Inventory tracking (best effort mirror of server state)
        self.inventory: Dict[str, Dict[str, int]] = {
            code: airport.stock.copy() for code, airport in self.world.airports.items()
        }
        self.processing_queue: List[ProcessingJob] = []

    def update_state(self, current_day, current_hour, api_response):
        """
        Ingests the 'flightUpdates' from the API.
        """
        if not api_response or 'flightUpdates' not in api_response:
            return

        for event in api_response['flightUpdates']:
            # Handle both SCHEDULED and CHECKED_IN to ensure we have the latest passenger data (demand 1h ago)
            if event['eventType'] in ('SCHEDULED', 'CHECKED_IN'):
                f_id = event['flightId']

                dep_day = event['departure']['day']
                dep_hour = event['departure']['hour']
                arr_day = event['arrival']['day']
                arr_hour = event['arrival']['hour']

                passengers = event.get('passengers', {}) or {}
                aircraft_type = event.get('aircraftType')

                info = FlightInfo(
                    flight_id=f_id,
                    origin=event['originAirport'],
                    destination=event['destinationAirport'],
                    departure=(dep_day, dep_hour),
                    arrival=(arr_day, arr_hour),
                    passengers={
                        "FIRST": int(passengers.get('first', 0)),
                        "BUSINESS": int(passengers.get('business', 0)),
                        "PREMIUM_ECONOMY": int(passengers.get('premiumEconomy', 0)),
                        "ECONOMY": int(passengers.get('economy', 0)),
                    },
                    aircraft_type=aircraft_type,
                )

                # Keep latest passenger counts (CHECKED_IN overrides SCHEDULED)
                self.flights[f_id] = info
                if f_id not in self.departures[(dep_day, dep_hour)]:
                    self.departures[(dep_day, dep_hour)].append(f_id)

    def decide_kit_loads(self, current_day, current_hour):
        """
        Decide loads for flights departing now, based on tracked inventory.
        Capped at actual passenger demand (from 1h ago).
        """
        self._release_completed_processing(current_day, current_hour)

        loads = []
        flights_leaving_now = self.departures.get((current_day, current_hour), [])

        for flight_id in flights_leaving_now:
            info = self.flights.get(flight_id)
            if not info:
                continue

            origin_inv = self.inventory.get(info.origin, {})
            aircraft = self.world.aircraft_types.get(info.aircraft_type)
            if not aircraft:
                # If we don't know the aircraft, skip loading to avoid penalties
                load_cmd = create_flight_load(flight_id, 0, 0, 0, 0)
                loads.append(load_cmd)
                continue

            load_per_class: Dict[str, int] = {}

            if info.origin == "HUB1":
                # Plan shipments based on known demand, BUT CAP AT CURRENT PASSENGERS
                dest_airport = self.world.airports.get(info.destination)
                dest_inv = self.inventory.get(info.destination, {cls: 0 for cls in CLASS_ORDER})
                dest_cap = dest_airport.capacity if dest_airport else {cls: 0 for cls in CLASS_ORDER}
                arrival_time = info.arrival
                window_hours = 36
                dest_future_need = self._future_demand_for_airport(info.destination, arrival_time, window_hours)

                for cls in CLASS_ORDER:
                    pax_now = info.passengers.get(cls, 0)
                    cap = aircraft.kit_capacity.get(cls, 0)
                    hub_stock = origin_inv.get(cls, 0)
                    dest_stock = dest_inv.get(cls, 0)
                    
                    need = dest_future_need.get(cls, 0)
                    dest_remaining_cap = max(0, dest_cap.get(cls, 0) - dest_stock)
                    
                    # Original logic calculated desired extra:
                    # desired = min(dest_remaining_cap, pax_now + max(0, need - dest_stock))
                    
                    # NEW LOGIC: We calculate desired buffer, but strictly cap at pax_now
                    # This ensures we never load more than the demand 1h ago.
                    calculated_need = pax_now + max(0, need - dest_stock)
                    
                    # Apply constraints: 
                    # 1. Aircraft Capacity
                    # 2. Hub Stock
                    # 3. Destination Capacity
                    # 4. Pax Demand (The new strict cap)
                    qty = min(cap, hub_stock, dest_remaining_cap, calculated_need, pax_now)
                    
                    load_per_class[cls] = qty
                    origin_inv[cls] = hub_stock - qty
            else:
                # Outstation: load passengers only (already capped by definition)
                for cls in CLASS_ORDER:
                    pax = info.passengers.get(cls, 0)
                    cap = aircraft.kit_capacity.get(cls, 0)
                    available = origin_inv.get(cls, 0)
                    qty = min(pax, cap, max(0, available))
                    load_per_class[cls] = qty
                    origin_inv[cls] = available - qty

            # Schedule processed kits to return at destination after processing time
            dest = self.world.airports.get(info.destination)
            if dest:
                for cls in CLASS_ORDER:
                    qty = load_per_class.get(cls, 0)
                    if qty <= 0:
                        continue
                    proc_time = dest.processing_time[cls]
                    ready_day, ready_hour = self._add_hours(info.arrival, proc_time)
                    self.processing_queue.append(
                        ProcessingJob(
                            ready_time=(ready_day, ready_hour),
                            airport=info.destination,
                            kit_class=cls,
                            quantity=qty,
                        )
                    )

            load_cmd = create_flight_load(
                flight_id=flight_id,
                first=load_per_class.get("FIRST", 0),
                business=load_per_class.get("BUSINESS", 0),
                premium=load_per_class.get("PREMIUM_ECONOMY", 0),
                economy=load_per_class.get("ECONOMY", 0),
            )
            loads.append(load_cmd)

        if (current_day, current_hour) in self.departures:
            del self.departures[(current_day, current_hour)]

        return loads

    def decide_purchases(self, current_day, current_hour):
        """
        Decide if we need to buy more kits at HUB1.
        """
        hub_stock = self.inventory.get("HUB1", {cls: 0 for cls in CLASS_ORDER})
        hub = self.world.airports.get("HUB1")
        if not hub:
            return create_per_class_amount(0, 0, 0, 0)

        horizon = 48  # hours ahead
        demand = self._future_demand_from_hub((current_day, current_hour), horizon)
        incoming = self._incoming_kits("HUB1", (current_day, current_hour), horizon)

        orders = {cls: 0 for cls in CLASS_ORDER}
        for cls in CLASS_ORDER:
            projected = hub_stock.get(cls, 0) + incoming.get(cls, 0)
            needed = int(demand.get(cls, 0) * 1.05)  # small buffer
            if projected < needed:
                shortfall = needed - projected
                # keep under capacity
                orders[cls] = min(shortfall, max(0, hub.capacity[cls] - hub_stock.get(cls, 0)))
            else:
                orders[cls] = 0

        # Apply purchase to inventory as soon as it will arrive
        if any(v > 0 for v in orders.values()):
            self._schedule_purchase_delivery(current_day, current_hour, orders)

        return create_per_class_amount(
            orders["FIRST"], orders["BUSINESS"], orders["PREMIUM_ECONOMY"], orders["ECONOMY"]
        )

    # --- Internal helpers ---
    def _release_completed_processing(self, current_day: int, current_hour: int):
        """
        Move kits that finished processing into available stock.
        """
        ready: List[ProcessingJob] = []
        pending: List[ProcessingJob] = []
        for job in self.processing_queue:
            if self._time_leq(job.ready_time, (current_day, current_hour)):
                ready.append(job)
            else:
                pending.append(job)

        for job in ready:
            airport_inv = self.inventory.setdefault(job.airport, {cls: 0 for cls in CLASS_ORDER})
            airport_inv[job.kit_class] = airport_inv.get(job.kit_class, 0) + job.quantity

        self.processing_queue = pending

    def _schedule_purchase_delivery(self, current_day: int, current_hour: int, orders: Dict[str, int]):
        """
        Add purchase arrivals into processing queue (fulfilled at HUB).
        """
        lead_times = {
            "FIRST": 48,
            "BUSINESS": 36,
            "PREMIUM_ECONOMY": 24,
            "ECONOMY": 12,
        }
        for cls, qty in orders.items():
            if qty <= 0:
                continue
            ready_day, ready_hour = self._add_hours((current_day, current_hour), lead_times[cls])
            self.processing_queue.append(
                ProcessingJob(
                    ready_time=(ready_day, ready_hour),
                    airport="HUB1",
                    kit_class=cls,
                    quantity=qty,
                )
            )

    def _future_demand_for_airport(self, airport_code: str, start_time: Tuple[int, int], window_hours: int) -> Dict[str, int]:
        """
        Sum passenger demand for flights originating from airport within window.
        """
        start_int = self._time_to_int(start_time)
        end_int = start_int + window_hours
        demand = {cls: 0 for cls in CLASS_ORDER}
        for f in self.flights.values():
            if f.origin != airport_code:
                continue
            dep_int = self._time_to_int(f.departure)
            if start_int < dep_int <= end_int:
                for cls in CLASS_ORDER:
                    demand[cls] += f.passengers.get(cls, 0)
        return demand

    def _future_demand_from_hub(self, current_time: Tuple[int, int], window_hours: int) -> Dict[str, int]:
        """
        Sum passenger demand for flights departing from HUB1 in horizon.
        """
        start_int = self._time_to_int(current_time)
        end_int = start_int + window_hours
        demand = {cls: 0 for cls in CLASS_ORDER}
        for f in self.flights.values():
            if f.origin != "HUB1":
                continue
            dep_int = self._time_to_int(f.departure)
            if start_int <= dep_int <= end_int:
                for cls in CLASS_ORDER:
                    demand[cls] += f.passengers.get(cls, 0)
        return demand

    def _incoming_kits(self, airport_code: str, current_time: Tuple[int, int], window_hours: int) -> Dict[str, int]:
        """
        Kits scheduled to arrive (processing queue) at airport within window.
        """
        start_int = self._time_to_int(current_time)
        end_int = start_int + window_hours
        incoming = {cls: 0 for cls in CLASS_ORDER}
        for job in self.processing_queue:
            if job.airport != airport_code:
                continue
            t_int = self._time_to_int(job.ready_time)
            if start_int <= t_int <= end_int:
                incoming[job.kit_class] += job.quantity
        return incoming

    @staticmethod
    def _time_to_int(reference: Tuple[int, int]) -> int:
        return reference[0] * 24 + reference[1]

    @staticmethod
    def _add_hours(reference: Tuple[int, int], delta_hours: int) -> Tuple[int, int]:
        """
        Adds hours to a (day, hour) tuple and returns the normalized result.
        """
        day, hour = reference
        total_hours = day * 24 + hour + delta_hours
        return divmod(total_hours, 24)

    @staticmethod
    def _time_leq(left: Tuple[int, int], right: Tuple[int, int]) -> bool:
        """
        Compare two (day, hour) tuples.
        """
        return left[0] < right[0] or (left[0] == right[0] and left[1] <= right[1])