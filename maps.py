"""Shared arena geometry. All maps retain the safe southwest buy-zone spawn."""
import json
from pathlib import Path

ORIGINAL = json.loads((Path(__file__).parent / "arena.json").read_text())
BOUNDARY = ORIGINAL[:17]
BUY_ZONE = ORIGINAL[-1:]


def arena(name, description, color, boxes):
    return dict(name=name, description=description, color=color,
                boxes=BOUNDARY + boxes + BUY_ZONE)


MAPS = {
    "dust": arena("Dust Yard", "Piaskowy dziedziniec i krzyżowe osłony.", "#d6ac76", ORIGINAL[17:-1]),
    "depot": arena("Depot", "Kontenery, trzy przejścia i długie linie strzału.", "#6d9fad", [
        [x, 3, z, 12, 6, 24] for x, z in
        [(-35, -32), (0, -12), (35, -32), (-35, 28), (0, 48), (35, 28)]
    ] + [[-62, 2, 8, 8, 4, 8], [62, 2, -4, 8, 4, 8]]),
    "temple": arena("Temple", "Kamienne kolumny i otwarty środek świątyni.", "#8eac87", [
        [x, 4, z, 6, 8, 6] for x in (-36, 0, 36) for z in (-36, 0, 36)
    ] + [[-55, 2, 32, 22, 4, 4], [55, 2, -32, 22, 4, 4]]),
    "citadel": arena("Citadel", "Dwie fortyfikacje, boczne trasy i osłony dla snajperów.", "#aa92b9", [
        [-26, 3, -24, 4, 6, 40], [26, 3, 24, 4, 6, 40],
        [-8, 3, -42, 40, 6, 4], [8, 3, 42, 40, 6, 4],
        [48, 2, -28, 12, 4, 12], [-48, 2, 28, 12, 4, 12],
        [0, 2, 0, 10, 4, 10]
    ]),
}
