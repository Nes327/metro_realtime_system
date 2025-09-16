# Metro Realtime System 🚇
- A real-time metro routing and fare web application built with Flask (Python), SQLite, and WebSockets.
- It allows users to plan routes (fewest stops / shortest time), check fares, and even watch live train simulations on an interactive map.

## ✨ Features
### Route Planning: 
Find the optimal route by either fewest stops or shortest travel time.
### Fare Lookup: 
Instantly calculate the fare between two stations.
### Realtime Simulation: 
Watch animated trains move in real-time via WebSockets.
### Interactive Frontend: 
Simple kiosk-like interface built with HTML + JavaScript (Leaflet for maps).

## 📦 Prerequisites
### Windows
1. Install Python 3.10+
2. Allow PowerShell to run virtual environment activation
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
### macOS / Linux
1. Install Python 3.10+
```bash
brew install python
```

## 📥 Get the Code
Clone the repo:
```bash
git clone <https://github.com/Nes327/metro_realtime_system>
cd metro_realtime_system
```

## 🛠️ Setup Virtual Environment
### Windows (PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
### macOS / Linux
```bash
python3 -m venv venv
source venv/bin/activate
```

## 📚 Install Dependencies
### With the venv active:
```bash
pip install -r requirements.txt
```
### Or manually:
```bash
pip install Flask==2.3.3 Flask-Sock==0.7.0 simple-websocket==0.10.1 pandas openpyxl
```

## 🗂️ Data Files
The app loads data from these files (included in the repo):
- Fare.csv
- Route.csv
- Time.csv
- stations_coords.csv
If metro.db doesn’t exist, it will be created and populated automatically on first run.

## 🚀 Run the Server
### Default (port 5000)
```bash
python app.py
```
Open: http://127.0.0.1:5000
- If port 5000 is blocked
```bash
python -c "from app import create_app; app=create_app(); app.run(host='127.0.0.1', port=5050, debug=True, use_reloader=False)"
```
Open: http://127.0.0.1:5050

## 🖥️ Using the App
Choose From and To stations.
Select mode: stops (fewest stops) or time (shortest time).
Click Plan Route → displays path + fare.
Click Start Simulation → watch trains animate in real-time.
Realtime logs will show WebSocket updates.

## 🔄 Optional: External Realtime Generator
Run in a separate terminal:
```bash
python data_generator.py
```

## 🌐 Example API Endpoints
- List stations:
```bash
GET /stations
```
- Fare lookup:
```bash
GET /fare_by_name?from=KLCC&to=Kajang
```
- Route lookup:
```bash
GET /route_by_name?from=KLCC&to=Kajang&mode=time
```

## 🛑 Troubleshooting
PowerShell: “source not recognized” → use:
```powershell
.\venv\Scripts\Activate.ps1
```
Permission error on venv activation → run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 📁 Project Structure
```text
metro_realtime_system/
├── app.py              # Flask entry point
├── database.py         # SQLite connection & setup
├── routes.py           # HTTP API endpoints
├── realtime.py         # WebSocket (Flask-Sock) logic
├── data_generator.py   # Simulates train movement
├── index.html          # Frontend interface
├── requirements.txt    # Python dependencies
├── Fare.csv
├── Route.csv
├── Time.csv
├── stations_coords.csv
└── metro.db            # Auto-generated database
```