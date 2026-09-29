from collections import defaultdict
from bisect import bisect_left
from vault_purge.core.resolver import recommend
from vault_purge.core.audio import music_similarity


class BKTree:
    """Hamming-distance index; avoids enumerating all pairs for typical data."""
    def __init__(self):
        self.root = None

    def add(self, value, record):
        node = (value, record, {})
        if self.root is None:
            self.root = node
            return
        current = self.root
        while True:
            distance = (value ^ current[0]).bit_count()
            if distance not in current[2]:
                current[2][distance] = node
                return
            current = current[2][distance]

    def find(self, value, threshold):
        stack = [self.root] if self.root else []
        while stack:
            node = stack.pop()
            distance = (value ^ node[0]).bit_count()
            if distance <= threshold:
                yield node[1]
            stack.extend(child for edge, child in node[2].items() if distance - threshold <= edge <= distance + threshold)


def group_images(records, threshold=10):
    records = sorted((r for r in records if r.status == "active"), key=lambda r: r.path)
    exact = defaultdict(list)
    for record in records:
        if record.md5:
            exact[(record.media_type, record.md5)].append(record)
    groups = []
    for (media_type, digest), members in sorted(exact.items()):
        if len(members) > 1:
            groups.append(dict(id=f"exact-{media_type}-{digest}", kind="exact", members=members, recommendation=recommend(members)))
    # Anchor groups: every member is within threshold of its anchor. No transitive chains.
    trees = {"image": BKTree(), "video": BKTree()}
    near = {}
    for record in records:
        if record.media_type == "audio" or not record.phash:
            continue
        value = int(record.phash, 16)
        tree = trees[record.media_type]
        candidates = [candidate for candidate in tree.find(value, threshold)
                      if record.media_type != "video" or videos_match(record, candidate, threshold)]
        if candidates:
            anchor = min(candidates, key=lambda a: ((value ^ int(a.phash, 16)).bit_count(), a.path))
            near[anchor.id].append(record)
        else:
            tree.add(value, record)
            near[record.id] = [record]
    for anchor_id, members in near.items():
        if len(members) > 1 and len({r.md5 or r.path for r in members}) > 1:
            groups.append(dict(id=f"near-{anchor_id}", kind="near", anchor_id=anchor_id, members=members, recommendation=recommend(members)))
    audio_anchors = []
    anchor_durations = []
    for record in sorted((r for r in records if r.media_type == "audio" and r.audio_fingerprint), key=lambda r: (r.duration or 0, r.path)):
        lower = bisect_left(anchor_durations, (record.duration or 0) - max(2, (record.duration or 0) * .02))
        match = next(((anchor, members, evidence, score) for anchor, members, evidence in reversed(audio_anchors[lower:])
                      if (score := music_similarity(anchor, record)) is not None), None)
        if match:
            anchor, members, evidence, score = match
            members.append(record)
            evidence[str(record.id)] = score
        else:
            audio_anchors.append((record, [record], {}))
            anchor_durations.append(record.duration or 0)
    for anchor, members, evidence in audio_anchors:
        if len(members) > 1 and len({r.md5 or r.path for r in members}) > 1:
            groups.append(dict(id=f"music-{anchor.id}", kind="near", anchor_id=anchor.id, members=members,
                               evidence=evidence, recommendation=recommend(members)))
    return groups


def videos_match(left, right, threshold):
    if not left.duration or not right.duration or not left.frame_hashes or not right.frame_hashes:
        return False
    if abs(left.duration - right.duration) > max(.25, min(left.duration, right.duration) * .01):
        return False
    a, b = left.frame_hashes.split(","), right.frame_hashes.split(",")
    return len(a) == len(b) == 3 and all((int(x, 16) ^ int(y, 16)).bit_count() <= threshold for x, y in zip(a, b))
