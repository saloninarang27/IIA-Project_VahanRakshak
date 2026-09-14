"""
Frontend Presentation Server (Port 3000).
Serves the HTML pages and static assets (CSS, JS, images).
Communicates with the Mediator Backend on Port 5000 via REST.
"""
import os
from flask import Flask, send_from_directory, render_template_string
from flask_cors import CORS

FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR = os.path.join(FRONTEND_DIR, "pages")
ASSETS_DIR = os.path.join(FRONTEND_DIR, "assets")

app = Flask(__name__, static_folder=ASSETS_DIR, static_url_path="/assets")
CORS(app)

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/pages/<path:filename>")
def pages(filename):
    return send_from_directory(PAGES_DIR, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT_FRONTEND", 3000))
    print(f"[*] Starting Frontend Server on http://localhost:{port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
