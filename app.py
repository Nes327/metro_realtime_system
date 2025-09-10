# app.py
from flask import Flask, render_template
from routes import api_bp
from realtime import init_realtime
from database import init_db

def create_app():
    app = Flask(__name__)
    # 配置
    app.config["DB_PATH"] = "metro.db"
    app.config["DATA_DIR"] = "data"

    # API 路由
    app.register_blueprint(api_bp, url_prefix="/")

    # 主页（前端）
    @app.route("/")
    def index():
        return render_template("index.html")

    # 初始化数据库（只在启动时做一次）
    init_db(app.config["DB_PATH"], app.config["DATA_DIR"])

    return app

if __name__ == "__main__":
    app = create_app()
    # 初始化 Socket.IO（确保 realtime.init_realtime 返回 socketio 实例）
    socketio = init_realtime(app)
    # 用 socketio.run 运行（不要再用 app.run）
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
