# Python Project

## File Structure
```
project_root/
│
├── data/                 <-- CSV Files
│
└── src/
    ├── __init__.py       <-- Empty file (Package marker)
    ├── config.py         <-- Configuration & Constants
    ├── domain.py         <-- Data Classes (Airport, Aircraft)
    ├── api_client.py     <-- API Communication
    ├── strategy.py       <-- THE BRAIN: Your algorithm lives here
    └── main.py           <-- THE RUNNER: Connects everything
```

## Setup & Installation

Open your terminal in the `solution` directory.

### 1. Create the Virtual Environment
```bash
python -m venv venv
```

### 2. Activate the Environment
```bash
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install pandas requests
```

## How to Run
Once the environment is active (you see `(venv)` in your terminal), run the main script from the root directory:

```bash
python src/main.py
```