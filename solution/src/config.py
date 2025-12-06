import os

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')

# API Settings
API_URL = "http://localhost:8080"
TOTAL_GAME_HOURS = 720  # 30 days * 24 hours

# CSV Filenames
FILE_AIRPORTS = 'airports_with_stocks.csv'
FILE_AIRCRAFT = 'aircraft_types.csv'
FILE_SCHEDULE = 'flight_plan.csv'
FILE_TEAMS = 'teams.csv'

# Simulation Settings
LOOP_SLEEP_SECONDS = 0.01  # Time to wait between "hours"