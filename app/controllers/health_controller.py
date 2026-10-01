from app.utils.response import success

def check_health():
    return success({"status": "running"})