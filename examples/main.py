"""NiceFabric demo — run with: python examples/main.py"""
import base64
import random

from nicegui import app, ui

from nicefabric import FabricCanvas


@ui.page('/')  # per-visit page: module-level canvases would be shared by ALL tabs/users
def index() -> None:
    ui.label('NiceFabric demo').classes('text-2xl')

    with ui.row().classes('items-center gap-2'):
        color = ui.color_input(value='#3b82f6').props('dense')

        def rand_pos() -> dict:
            return {'left': random.randint(0, 500), 'top': random.randint(0, 300)}

        ui.button('Rect', on_click=lambda: canvas.add_rect(
            width=80, height=60, fill=color.value, **rand_pos()))
        ui.button('Circle', on_click=lambda: canvas.add_circle(
            radius=40, fill=color.value, **rand_pos()))
        ui.button('Text', on_click=lambda: canvas.add_text(
            'edit me', fontSize=24, fill=color.value, **rand_pos()))

        ui.switch('draw', on_change=lambda e:
                  canvas.enable_drawing(color.value, 3) if e.value else canvas.disable_drawing())
        ui.button('Delete sel.', on_click=lambda: canvas.remove_selected())
        ui.button('Clear', on_click=lambda: canvas.clear_objects())

        async def export_png() -> None:
            data_url = await canvas.to_data_url()
            ui.download(base64.b64decode(data_url.split(',', 1)[1]), 'canvas.png')
        ui.button('Export PNG', on_click=export_png)

        def save() -> None:
            app.storage.general['nicefabric-demo'] = canvas.to_dict()
            ui.notify('saved')

        def load() -> None:
            data = app.storage.general.get('nicefabric-demo')
            if data is None:
                ui.notify('nothing saved yet')
                return
            try:
                canvas.load_json(data)
            except ValueError as e:
                # to_dict()/to_json() are uncapped, but load_json refuses payloads over 1 MB —
                # a canvas full of free-drawn paths can be saved and then rejected on load.
                ui.notify(f'load failed: {e}', type='negative')
        ui.button('Save', on_click=save)
        ui.button('Load', on_click=load)

    canvas = FabricCanvas(width=800, height=450, background='#f8fafc', keyboard_delete=True,
                          on_selection=lambda e: log.push(f'selection: {e.args}'),
                          on_modified=lambda e: log.push(f'modified: {e.args["id"][:8]}'),
                          on_added=lambda e: log.push(f'drawn: {e.args["id"][:8]}'),
                          on_error=lambda e: log.push(f'ERROR: {e.args}'))
    log = ui.log(max_lines=20).classes('w-full h-40')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(show=False)
