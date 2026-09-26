def recommend(records):
    winner = min(records, key=lambda r: (-(r.width * r.height), -r.size, r.mtime_ns, r.path.casefold(), r.path))
    return {"id": winner.id, "reason": "Highest resolution; ties use file size, oldest modification time, then path."}
