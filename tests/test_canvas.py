from nicegui import ui
from nicegui.testing import User

from nicefabric import FabricCanvas


async def test_element_renders(user: User) -> None:
    @ui.page('/')
    def page() -> None:
        FabricCanvas(width=400, height=300)
    await user.open('/')
    # the custom tag is present in the page tree
    assert user.find(FabricCanvas).elements


async def test_add_rect_registers_before_init(user: User) -> None:
    canvases: list[FabricCanvas] = []

    @ui.page('/')
    def page() -> None:
        c = FabricCanvas()
        c.add_rect(left=10, top=20, width=30, height=40, fill='red')
        canvases.append(c)
    await user.open('/')
    c = canvases[0]
    assert not c.is_initialized          # user fixture never runs JS → init never fires
    (obj,) = c._objects.values()
    assert obj['type'] == 'Rect' and obj['left'] == 10 and 'id' in obj
