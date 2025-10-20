import os, json, time, threading
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from web3 import Web3
from dotenv import load_dotenv
from oracle_automation import process_and_anchor

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PANELS_DIR = os.path.join(BASE_DIR, "panels")

INFURA_WS = "wss://sepolia.infura.io/ws/v3/57ea67cde27f45f9af5a69bdc5c92332"
INFURA_HTTP = "https://sepolia.infura.io/v3/57ea67cde27f45f9af5a69bdc5c92332"
CONTRACT_ADDRESS = Web3.to_checksum_address("0x59B649856d8c5Fb6991d30a345f0b923eA91a3f7")
WALLET_ADDRESS = "0xb8935eBEb1dA663C187fc9090b77E1972A909e12"

web3_ws = Web3(Web3.LegacyWebSocketProvider(INFURA_WS, websocket_timeout=30))
web3_http = Web3(Web3.HTTPProvider(INFURA_HTTP))

with open("contract_abi.json", "r", encoding="utf-8") as f:
    contract_abi = json.load(f)

contract_ws = web3_ws.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)
contract_http = web3_http.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return "✅ Oracle Backend is running and serving API routes!"

@app.route("/health")
def health():
    try:
        return {"ok": True, "latest_block": web3_http.eth.block_number, "wallet": WALLET_ADDRESS}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/api/hash/<panel_id>")
def get_hash(panel_id):
    file_path = os.path.join(PANELS_DIR, f"{panel_id}.json")
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    with open(file_path, "rb") as f:
        h = web3_http.keccak(f.read()).hex()
    return jsonify({"panel_id": panel_id, "sha3_hash": h})

@app.route("/panels/<path:filename>")
def serve_panel(filename):
    return send_from_directory(PANELS_DIR, filename)

def listen_for_events():
    print("👂 Worker listening for PanelEventAdded events in real time...")
    try:
        event_filter = contract_ws.events.PanelEventAdded.create_filter(from_block=web3_ws.eth.block_number - 10)
        print("Event filter created.")
    except Exception as e:
        print("Failed to create filter:", e)
        return

    while True:
        try:
            for event in event_filter.get_new_entries():
                args = event["args"]
                panel_id = args["panelId"]
                event_type = args["eventType"]
                fault_type = args["faultType"]
                fault_severity = args["faultSeverity"]
                action_taken = args["actionTaken"]
                event_hash = args["eventHash"].hex() if hasattr(args["eventHash"], "hex") else str(args["eventHash"])
                validated_by = args.get("validatedBy", "")
                timestamp = args["timestamp"]

                print(f"🔹 New Event → {panel_id} | {event_type} | {fault_type} | "
                      f"{fault_severity} | {action_taken} | {validated_by} | {timestamp}")

                process_and_anchor(
                    panel_id=panel_id,
                    event_type=event_type,
                    fault_type=fault_type,
                    fault_severity=fault_severity,
                    action_taken=action_taken,
                    event_hash=event_hash,
                    validated_by=validated_by,
                    timestamp=timestamp
                )

        except Exception as e:
            print(f"⚠️ Worker error: {type(e).__name__}: {e}")
            time.sleep(5)
        time.sleep(2)

def start_worker_thread():
    t = threading.Thread(target=listen_for_events, daemon=True)
    t.start()

if __name__ == "__main__":
    start_worker_thread()
    app.run(host="0.0.0.0", port=5000)
