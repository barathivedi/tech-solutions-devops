from flask import Flask, jsonify
from datetime import datetime, timezone

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({
        "application": "Tech Solutions Backend",
        "status": "running",
        "message": "Backend API is working"
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy"
    })


@app.route("/api/info")
def info():
    return jsonify({
        "project": "Containerized Application Deployment",
        "frontend": "Nginx",
        "backend": "Python Flask",
        "deployment": "Docker",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
