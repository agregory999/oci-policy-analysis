import flet as ft


def main(page: ft.Page):
    # Set the initial window size
    page.window_width = 1400
    page.window_height = 900
    page.window_min_width = 1400
    # Optional: Make the window non-resizable by the user
    # page.window_resizable = False

    page.add(ft.Text('Hello, Flet! This is a resizable window example.'))

    page.update()


# Run the Flet application
ft.app(target=main)
