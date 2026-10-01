def success(data=None, message="OK"):
    return {"success": True, "message": message, "data": data}

def paginated(items, total, page, page_size):
    return success({"items": items, "total": total, "page": page, "page_size": page_size})