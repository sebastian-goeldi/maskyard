import oassembly as oas
from oassembly import engine, kdb
from oassembly.models.enclosure import EnclosureDefinition

pdk = oas.PDK(name="TEST")

session = engine.get_session()


layers = [oas.Layer(layer=number, datatype=0) for number in range(5)]
[session.add(layer) for layer in layers]
session.commit()

definition: EnclosureDefinition = {
    "bands": [
        {"layer": 3, "datatype": 0, "d_min": 100, "d_max": 400},
        {"layer": 2, "datatype": 0, "d_min": None, "d_max": 500},
    ],
    "bboxes": [{"layer": 4, "datatype": 0, "offset": 200}],
}

enc = oas.models.enclosure.get_or_create_enclosure(
    session=session, main_layer=layers[0], definition=definition
)

session.add(enc)

xs = oas.models.cross_section.SymmetricCrossSection(
    name="WG", canonical_name="WG", width=1000, layer=layers[0], enclosure=enc
)
session.add(xs)
session.commit()


@pdk.pcell
def straight() -> oas.Cell:
    c = pdk.create_cell("straight")
    c.shapes(kdb.LayerInfo(1, 0)).insert(kdb.Box(10_000, 1000))
    c.create_port(name="o1", cross_section=xs, trans=kdb.Trans(x=-5000, y=0))
    c.create_port(name="o2", cross_section=xs, trans=kdb.Trans(rot=2, x=5000, y=0))
    return c


@pdk.pcell
def long_straight() -> oas.Cell:
    s = straight()
    c = pdk.create_cell("long_straight")
    s1 = c.insert(s)
    s2 = c.insert(s)
    s2.connect("o1", s1.get_port("o2"))

    return c


long_straight().write("test.gds")
