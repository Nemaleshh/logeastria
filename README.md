# Logeastria 🏢🤝📦

Logeastria is an AI-powered Supply Chain and Logistics Orchestrator Platform built with Flask and intelligent autonomous agents. It manages and orchestrates different areas of the supply chain through isolated modules, facilitating seamless communication between various stages of inventory, production, procurement, warehouse management, and overall logistics.

## 🚀 Features

- **Agent-Based Architecture**: Powered by intelligent agents that seamlessly interact to orchestrate supply chain decisions and actions:
  - 🧠 **Central Orchestrator Agent**: Manages and coordinates cross-domain operations.
  - 🏭 **Supplier & Procurement Agent**: Handles purchasing, supplier communication, and stock replenishment.
  - 🏢 **Warehouse Agent**: Monitors capacity and oversees internal storage limits and configurations.
  - 🚚 **Logistics Agent**: Controls dispatching, transportation routes, and delivery status.
  - 📦 **Inventory Agent**: Tracks current stock levels, safety stocks, and alerts on low inventory.
- **RESTful API via Flask modules/blueprints**:
  - `/inventory`
  - `/production`
  - `/procurement`
  - `/logistics`
  - `/warehouse`
  - `/orchestrator`
- **Dynamic Database adapters**: Connects to domain-specific datasets (like `inventory.csv`) and scales to handle multiple databases effectively.

## 📁 Project Structure

```
.
├── app.py                     # Main Flask Application Entry Point
├── agents/                    # AI Agent Logic (Inventory, Warehouse, Logistics, Orchestrator)
├── routes/                    # API Endpoints / Flask Blueprints
├── services/                  # Business Logic and integration points
├── data_base/                 # Database connection and adapters
├── adapter/                   # External format/data adapters
├── execution/                 # Action execution flows for agents
├── new_front/                 # Frontend assets / UI Logic
├── templates/                 # UI HTML templates (Flask rendering)
├── test.py / test.ipynb       # Unit Tests and Data Modeling Notebooks
└── inventory.csv              # Seed / Local testing inventory data
```

## 🛠️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Nemaleshh/logeastria.git
   cd logeastria
   ```

2. **Set up a Virtual Environment**:
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   Ensure you have your `requirements.txt` installed.
   ```bash
   pip install flask
   # Install any other required agent/AI libraries...
   ```

4. **Run the Application**:
   ```bash
   python app.py
   ```
   The server will start on `http://0.0.0.0:5000/`.

## 📌 Extending Modules

Each blueprint in `routes/` corresponds to a domain in the supply chain. Expanding the logic requires adding standard routes or dispatching tasks to the existing agents in the `agents/` directory logic.

## 📝 License

This project is open-source. Feel free to use or modify it.
