import flet as ft
from data import OCIDataService
from service import IAMService
from ui import IAMUI
from utils import load_config, logger, set_logging_level


def main(page: ft.Page):
    try:
        # Set initial window size to a larger value and enforce it
        page.window_width = 1800
        page.window_height = 1200
        page.update()

        def on_window_event(e):
            if e.data == 'resize':
                page.window_width = 1800
                page.window_height = 1200
                page.update()

        page.on_window_event = on_window_event

        # Load configuration
        config = load_config()
        set_logging_level(config['General'].get('log_level', 'INFO'))

        # Initialize data service with dynamic profile
        def create_data_service(profile, auth_mode):  # Modified to accept auth_mode
            return OCIDataService(config_file='~/.oci/config', profile=profile, auth_mode=auth_mode)

        # Initialize service layer
        service = IAMService(
            create_data_service(
                config['OCI'].get('config_profile', 'DEFAULT'), config['General'].get('load_mode', 'profile')
            )
        )

        # Initialize UI with callback to update data service
        def on_load_callback(mode, profile, cache_name):
            if mode != 'cache':  # Only create new data service for profile or instance_principal
                data_service = create_data_service(profile, mode)
                new_service = IAMService(data_service)
                new_service.load_data(data_service.compartment_id, auth_mode=mode, cache_name=cache_name)
                logger.info('Data loaded with profile: %s, auth_mode: %s', profile, mode)
                return new_service
            else:
                # For cache mode, use default profile but don't reload auth
                data_service = create_data_service('DEFAULT', 'profile')
                new_service = IAMService(data_service)
                new_service.load_data(data_service.compartment_id, auth_mode=mode, cache_name=cache_name)
                logger.info('Data loaded from cache: %s', cache_name)
                return new_service

        IAMUI(page, service, config, on_load_callback)
        logger.info('Application started successfully.')
    except Exception as e:
        logger.error(f'Application error: {e}')
        page.add(ft.Text(f'Error: {e}', color=ft.Colors.RED))


ft.app(target=main)
