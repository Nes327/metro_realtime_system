# app.py
from flask import Flask, render_template
from routes import api_bp
from realtime import init_realtime
from database import init_db

def create_app():
    app = Flask(__name__)
    app.config["DB_PATH"] = "metro.db"
    app.config["DATA_DIR"] = "data"

    # 注册 REST API
    app.register_blueprint(api_bp, url_prefix="/")

    # 首页：渲染 templates/index.html
    @app.route("/")
    def index():
        return render_template("index.html")

    # （可选）安静掉浏览器请求的 service worker
    @app.route("/service-worker.js")
    def sw():
        # 如果你以后真的要用 SW，把一个同名文件放到 static/ 下即可
        return ("", 204, {"Content-Type": "application/javascript"})

    # 初始化 DB & WebSocket
    init_db(app.config["DB_PATH"], app.config["DATA_DIR"])
    init_realtime(app)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
