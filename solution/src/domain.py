import pandas as pd
import os
import sys
from config import DATA_DIR, FILE_AIRPORTS, FILE_AIRCRAFT, FILE_SCHEDULE

# --- Entities ---

class Airport:
    def __init__(self, data):
        self.id = data['id']
        self.code = data['code']
        self.name = data['name']
        
        # Processing Times (Hours)
        self.processing_time = {
            'FIRST': data['first_processing_time'],
            'BUSINESS': data['business_processing_time'],
            'PREMIUM_ECONOMY': data['premium_economy_processing_time'],
            'ECONOMY': data['economy_processing_time']
        }
        
        # Costs
        self.processing_cost = {
            'FIRST': data['first_processing_cost'],
            'BUSINESS': data['business_processing_cost'],
            'PREMIUM_ECONOMY': data['premium_economy_processing_cost'],
            'ECONOMY': data['economy_processing_cost']
        }
        self.loading_cost = {
            'FIRST': data['first_loading_cost'],
            'BUSINESS': data['business_loading_cost'],
            'PREMIUM_ECONOMY': data['premium_economy_loading_cost'],
            'ECONOMY': data['economy_loading_cost']
        }
        
        # Initial Stock
        self.stock = {
            'FIRST': data['initial_fc_stock'],
            'BUSINESS': data['initial_bc_stock'],
            'PREMIUM_ECONOMY': data['initial_pe_stock'],
            'ECONOMY': data['initial_ec_stock']
        }
        
        self.capacity = {
            'FIRST': data['capacity_fc'],
            'BUSINESS': data['capacity_bc'],
            'PREMIUM_ECONOMY': data['capacity_pe'],
            'ECONOMY': data['capacity_ec']
        }

    def __repr__(self):
        return f"Airport({self.code})"

class AircraftType:
    def __init__(self, data):
        self.id = data['id']
        self.type_code = data['type_code']
        self.cost_per_kg_per_km = data['cost_per_kg_per_km']
        
        self.seats = {
            'FIRST': data['first_class_seats'],
            'BUSINESS': data['business_seats'],
            'PREMIUM_ECONOMY': data['premium_economy_seats'],
            'ECONOMY': data['economy_seats']
        }
        
        self.kit_capacity = {
            'FIRST': data['first_class_kits_capacity'],
            'BUSINESS': data['business_kits_capacity'],
            'PREMIUM_ECONOMY': data['premium_economy_kits_capacity'],
            'ECONOMY': data['economy_kits_capacity']
        }

class FlightSchedule:
    def __init__(self, data):
        self.origin = data['depart_code']
        self.destination = data['arrival_code']
        self.departure_hour = data['scheduled_hour']
        self.arrival_hour = data['scheduled_arrival_hour']
        self.arrival_next_day = data['arrival_next_day'] == 1
        self.distance_km = data['distance_km']
        
        # Schedule Active Days (0=Mon, 6=Sun based on columns)
        self.days_active = {
            0: data['Mon'] == 1,
            1: data['Tue'] == 1,
            2: data['Wed'] == 1,
            3: data['Thu'] == 1,
            4: data['Fri'] == 1,
            5: data['Sat'] == 1,
            6: data['Sun'] == 1
        }

    def __repr__(self):
        return f"Flight({self.origin}->{self.destination} @ {self.departure_hour}:00)"

# --- State Manager ---

class NetworkState:
    def __init__(self):
        self.airports = {} 
        self.aircraft_types = {} 
        self.flight_schedule = [] 

    def load_data(self):
        """Loads CSVs using paths from config.py"""
        print(f"📂 Loading data from: {DATA_DIR}")

        try:
            # 1. Airports
            path = os.path.join(DATA_DIR, FILE_AIRPORTS)
            df_airports = pd.read_csv(path, sep=';')
            for _, row in df_airports.iterrows():
                airport = Airport(row)
                self.airports[airport.code] = airport
                
            # 2. Aircraft
            path = os.path.join(DATA_DIR, FILE_AIRCRAFT)
            df_aircraft = pd.read_csv(path, sep=';')
            for _, row in df_aircraft.iterrows():
                ac = AircraftType(row)
                self.aircraft_types[ac.type_code] = ac
                
            # 3. Schedule
            path = os.path.join(DATA_DIR, FILE_SCHEDULE)
            df_schedule = pd.read_csv(path, sep=';')
            for _, row in df_schedule.iterrows():
                flight = FlightSchedule(row)
                self.flight_schedule.append(flight)
                
            print(f"✅ Loaded: {len(self.airports)} Airports, {len(self.aircraft_types)} Aircraft, {len(self.flight_schedule)} Routes.")
            
        except FileNotFoundError as e:
            print(f"❌ Error: Could not find file. {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected Error during loading: {e}")
            sys.exit(1)