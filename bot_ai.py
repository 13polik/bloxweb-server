"""Bounded A* navigation and readable, finite-ammunition cooperative opponents."""
import heapq
import math
import random

ROLES = ("Szturmowiec", "Zwiadowca", "Strzelec")


class Navigation:
    step = 4
    size = 44

    def __init__(self, boxes):
        self.boxes = [b for b in boxes if b[4] > 1]
        self.walkable = {(x, z) for x in range(self.size) for z in range(self.size)
                         if self.free(*self.point((x, z)))}

    def point(self, cell):
        return (-86 + cell[0]*self.step, -86 + cell[1]*self.step)

    def free(self, x, z):
        return abs(x) <= 88 and abs(z) <= 88 and not any(
            abs(x-b[0]) < b[3]/2+1.05 and abs(z-b[2]) < b[5]/2+1.05 for b in self.boxes)

    def clear(self, a, b):
        distance = math.dist(a, b)
        steps = max(1, math.ceil(distance/1.2))
        return all(self.free(a[0]+(b[0]-a[0])*i/steps, a[1]+(b[1]-a[1])*i/steps)
                   for i in range(steps+1))

    def anchor(self, p, connect=True):
        x, z = (round((v+86)/self.step) for v in p)
        candidates = [(x+dx, z+dz) for dx in range(-3, 4) for dz in range(-3, 4)]
        return min((c for c in candidates if c in self.walkable and (not connect or self.clear(p, self.point(c)))),
                   key=lambda c: math.dist(p, self.point(c)), default=None)

    def route(self, a, b):
        if self.clear(a, b):
            return [b]
        start, end = self.anchor(a), self.anchor(b)
        if start is None or end is None:
            return []
        frontier = [(0, start)]
        costs, previous = {start: 0}, {}
        visits = 0
        while frontier and visits < 2000:
            _, current = heapq.heappop(frontier)
            visits += 1
            if current == end:
                cells = [current]
                while current in previous:
                    current = previous[current]
                    cells.append(current)
                path = [self.point(c) for c in reversed(cells)]
                if self.clear(path[-1], b):
                    path.append(b)
                # Remove redundant grid corners without cutting through walls.
                smooth, origin, index = [], a, 0
                while index < len(path):
                    best = index
                    for candidate in range(index+1, min(index+12, len(path))):
                        if self.clear(origin, path[candidate]):
                            best = candidate
                    smooth.append(path[best])
                    origin = path[best]
                    index = best+1
                return smooth
            for dx, dz in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nxt = (current[0]+dx, current[1]+dz)
                if nxt not in self.walkable:
                    continue
                if dx and dz and ((current[0]+dx,current[1]) not in self.walkable or
                                  (current[0],current[1]+dz) not in self.walkable):
                    continue
                cost = costs[current]+math.hypot(dx,dz)
                if cost < costs.get(nxt, math.inf):
                    costs[nxt], previous[nxt] = cost, current
                    heapq.heappush(frontier, (cost+math.dist(nxt,end), nxt))
        return []


class BotDirector:
    def __init__(self, boxes):
        self.navigation = Navigation(boxes)
        self.brains = {}

    def update(self, enemies, players, dt, clock, visible, fire):
        live = {e["id"] for e in enemies}
        for key in list(self.brains):
            if key not in live:
                del self.brains[key]
        if not players:
            return
        for e in enemies:
            b = self.brains.setdefault(e["id"], dict(path=[], plan=0, reaction=0, seen=-100,
                target=None, memory=(-60,-58), ammo=8, reload=0, burst=0, hold=0))
            role = e["id"] % 3
            e["role"] = ROLES[role]
            origin = (e["x"], e["z"])
            candidates = sorted(players, key=lambda p: math.hypot(p["x"]-e["x"],p["z"]-e["z"]))
            sight = [p for p in candidates if math.hypot(p["x"]-e["x"],p["z"]-e["z"]) < 65 and visible(e,p)]
            target = sight[0] if sight else next((p for p in candidates if p["id"] == b["target"]), candidates[0])
            can_see = target in sight
            distance = math.hypot(target["x"]-e["x"],target["z"]-e["z"]) or 1
            dx, dz = (target["x"]-e["x"])/distance, (target["z"]-e["z"])/distance
            if can_see:
                if clock-b["seen"] > .35 or b["target"] != target["id"]:
                    b["reaction"] = .45 + role*.12
                b["seen"], b["target"], b["memory"] = clock, target["id"], (target["x"],target["z"])
            b["reaction"] = max(0,b["reaction"]-dt)
            b["plan"] -= dt
            b["hold"] -= dt
            e["cooldown"] = e.get("cooldown", 0)-dt
            goal, state = b["memory"], "szukanie"
            if clock-b["seen"] > 4:
                patrol = [(-62,-56),(-30,12),(16,-18),(-10,50),(52,4)]
                if math.dist(origin,goal) < 5:
                    goal = patrol[(int(clock/9)+e["id"]) % len(patrol)]
                    b["memory"] = goal
                else:
                    goal = b["memory"]
            if can_see and distance < 48:
                state = "walka"
                side = -1 if e["id"] % 2 else 1
                if distance < 11:
                    goal = (e["x"]-dx*7,e["z"]-dz*7)
                    state = "odwrot"
                elif role == 1 and distance > 16:
                    goal = (target["x"]-dx*18-dz*side*10,target["z"]-dz*18+dx*side*10)
                    state = "flanka"
                elif distance < 29:
                    sway = side*(1 if int(clock/2)%2 else -1)
                    goal = (e["x"]-dz*sway*4,e["z"]+dx*sway*4)
            if e["hp"] < 36 and distance < 45 and (clock+e["id"]) % 7 < 3.3:
                if b["hold"] <= 0:
                    covers = []
                    for box in self.navigation.boxes:
                        if max(box[3],box[5]) > 40:
                            continue
                        vx,vz = box[0]-target["x"],box[2]-target["z"]
                        length = math.hypot(vx,vz) or 1
                        c = (box[0]+vx/length*(box[3]/2+2),box[2]+vz/length*(box[5]/2+2))
                        if self.navigation.free(*c):
                            covers.append(c)
                    b["cover"] = min(covers,key=lambda c:math.dist(c,origin),default=goal)
                    b["hold"] = 2.8
                goal, state = b.get("cover",goal), "oslona"
            if not self.navigation.free(*goal):
                anchor = self.navigation.anchor(goal, connect=False)
                goal = self.navigation.point(anchor) if anchor else origin
            if b["plan"] <= 0 or (not b["path"] and math.dist(origin,goal) > 2):
                b["path"] = self.navigation.route(origin,goal)
                b["plan"] = 1 + e["id"]%3*.15
            if b["path"] and math.dist(origin,b["path"][0]) < .8:
                b["path"].pop(0)
            moving = False
            if b["path"]:
                gx,gz = b["path"][0]
                mx,mz = gx-e["x"],gz-e["z"]
                length = math.hypot(mx,mz) or 1
                speed = 5.2 + role*.45
                nx,nz = e["x"]+mx/length*speed*dt,e["z"]+mz/length*speed*dt
                # Soft separation avoids a single stacked enemy silhouette.
                for other in enemies:
                    if other is e:
                        continue
                    sx,sz = e["x"]-other["x"],e["z"]-other["z"]
                    gap = math.hypot(sx,sz)
                    if .01 < gap < 2.3:
                        nx += sx/gap*(2.3-gap)*dt
                        nz += sz/gap*(2.3-gap)*dt
                if self.navigation.clear(origin,(nx,nz)):
                    e["x"],e["z"],moving = nx,nz,True
                else:
                    b["plan"] = 0
            e.update(moving=moving,state=state,rot=math.atan2(dx,dz)+math.pi,ammo=b["ammo"],reloading=b["reload"]>0)
            if b["reload"] > 0:
                b["reload"] -= dt
                if b["reload"] <= 0:
                    b["ammo"] = 8
                continue
            if can_see and distance < 55 and b["reaction"] <= 0 and e["cooldown"] <= 0 and state != "oslona":
                if b["ammo"] <= 0:
                    b["reload"] = 1.8
                    continue
                # Check visibility again after moving; never fire through cover.
                if visible(e,target):
                    chance = max(.12,.65-distance/95)
                    fire(e,target,random.random()<chance)
                    b["ammo"] -= 1
                    b["burst"] += 1
                    e["cooldown"] = .3 if b["burst"] < 3 else 1.3+role*.15
                    if b["burst"] >= 3:
                        b["burst"] = 0
                    e["ammo"] = b["ammo"]
