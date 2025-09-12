from flask import Flask, render_template
from routes import api_bp
from realtime import init_realtime
from database import init_db

def create_app():
    app = Flask(__name__)
    app.config["DB_PATH"] = "metro.db"
    app.config["DATA_DIR"] = "data"

    app.register_blueprint(api_bp, url_prefix="/")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/service-worker.js")
    def sw():
        return ("", 204, {"Content-Type": "application/javascript"})

    init_db(app.config["DB_PATH"], app.config["DATA_DIR"])
    init_realtime(app)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
