def recommend(records):
    if all(r.media_type == "audio" for r in records):
        winner = min(records, key=lambda r: (r.mtime_ns, r.path.casefold(), r.path))
        return {"id": winner.id, "reason": "Oldest modification time, then path. Listen before choosing; encoding metadata does not prove audio quality."}
    winner = min(records, key=lambda r: (-(r.width * r.height), -r.size, r.mtime_ns, r.path.casefold(), r.path))
    return {"id": winner.id, "reason": "Highest resolution; ties use file size, oldest modification time, then path."}
