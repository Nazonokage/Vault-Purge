from collections import defaultdict
from image_dedup.core.resolver import recommend


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
            exact[record.md5].append(record)
    groups = []
    for digest, members in sorted(exact.items()):
        if len(members) > 1:
            groups.append(dict(id=f"exact-{digest}", kind="exact", members=members, recommendation=recommend(members)))
    # Anchor groups: every member is within threshold of its anchor. No transitive chains.
    tree = BKTree()
    near = {}
    for record in records:
        if not record.phash:
            continue
        value = int(record.phash, 16)
        candidates = list(tree.find(value, threshold))
        if candidates:
            anchor = min(candidates, key=lambda a: ((value ^ int(a.phash, 16)).bit_count(), a.path))
            near[anchor.id].append(record)
        else:
            tree.add(value, record)
            near[record.id] = [record]
    for anchor_id, members in near.items():
        if len(members) > 1 and len({r.md5 or r.path for r in members}) > 1:
            groups.append(dict(id=f"near-{anchor_id}", kind="near", anchor_id=anchor_id, members=members, recommendation=recommend(members)))
    return groups
