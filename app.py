from flask import Flask, render_template
from routes import api_bp
from realtime import init_realtime
from database import init_db

def create_app():
    app = Flask(__name__)
    # 配置：数据库路径 & CSV 路径（后续 database.py 会用到）
    app.config["DB_PATH"] = "metro.db"
    app.config["DATA_DIR"] = "data"  # 你的 CSV 文件夹，如 data/Fare.csv

    init_db(app.config["DB_PATH"], app.config["DATA_DIR"])

    # 注册 REST API
    app.register_blueprint(api_bp, url_prefix="/")

    # 初始化 WebSocket（/ws）
    init_realtime(app)

    @app.route("/")
    def index():
        return render_template("index.html")
    
    return app

if __name__ == "__main__":
    app = create_app()
    # 开发模式运行
    app.run(host="127.0.0.1", port=5000, debug=True)