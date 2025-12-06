from collections import defaultdict
from api_client import create_flight_load, create_per_class_amount

class Strategy:
    def __init__(self, world_state):
        """
        Initialize the strategy.
        Args:
            world_state (NetworkState): Static data loaded from CSVs.
        """
        self.world = world_state
        
        # TIMING MAP:
        # Maps (day, hour) -> List of [flight_id]
        # This acts as our "Calendar" of when to act.
        self.departures = defaultdict(list)

    def update_state(self, current_day, current_hour, api_response):
        """
        Ingests the 'flightUpdates' from the API.
        This is where we find out about new flights and their UUIDs.
        """
        if not api_response or 'flightUpdates' not in api_response:
            return

        for event in api_response['flightUpdates']:
            # We look for SCHEDULED events to know about future flights.
            # These usually arrive ~24h before departure.
            if event['eventType'] == 'SCHEDULED':
                
                f_id = event['flightId']
                
                # Extract departure time from the event
                # The API structure is: event['departure']['day'], event['departure']['hour']
                dep_day = event['departure']['day']
                dep_hour = event['departure']['hour']
                
                # Store this ID in our calendar so we remember to load it when that hour comes
                self.departures[(dep_day, dep_hour)].append(f_id)
                
                # Optional debug
                # print(f"   [Strategy] Noted flight {event['flightNumber']} departing Day {dep_day} Hour {dep_hour}")

    def decide_kit_loads(self, current_day, current_hour):
        """
        Checks the calendar for flights departing NOW.
        Returns 0-loads for all of them.
        """
        loads = []
        
        # 1. Check our calendar for flights departing at this exact (day, hour)
        flights_leaving_now = self.departures.get((current_day, current_hour), [])
        
        # 2. Generate a "Load 0" command for each
        for flight_id in flights_leaving_now:
            # Create a payload with 0 kits for every class
            load_cmd = create_flight_load(
                flight_id=flight_id,
                first=0, 
                business=0, 
                premium=0, 
                economy=0
            )
            loads.append(load_cmd)
            
        # 3. Cleanup (Optional): Remove past entries to save memory
        if (current_day, current_hour) in self.departures:
            del self.departures[(current_day, current_hour)]
            
        return loads

    def decide_purchases(self, current_day, current_hour):
        """
        Decide if we need to buy more kits at HUB1.
        Returns 0 for now.
        """
        return create_per_class_amount(0, 0, 0, 0)