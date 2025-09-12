from flask import Flask, render_template
from routes import api_bp
from realtime import init_realtime
from database import init_db

def create_app():
    # Create the Flask app instance
    app = Flask(__name__)
    app.config["DB_PATH"] = "metro.db"
    app.config["DATA_DIR"] = "data"

    app.register_blueprint(api_bp, url_prefix="/")

    # Home page
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/service-worker.js")
    def sw():
        return ("", 204, {"Content-Type": "application/javascript"})

    # Initialize SQLite database, create tables, import data
    init_db(app.config["DB_PATH"], app.config["DATA_DIR"])
    # Initialize WebSocket server for real-time updates
    init_realtime(app)

    return app

# Entry point
if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
