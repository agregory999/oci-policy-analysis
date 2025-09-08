import configparser

import flet as ft
from utils import list_caches, list_oci_profiles, log_handler, save_config, set_logging_level


class IAMUI:
    def __init__(self, page: ft.Page, service: 'IAMService', config: configparser.ConfigParser, on_load_callback):  # noqa: F821
        self.page = page
        self.service = service
        self.config = config
        self.ai_insights_content = None
        self.selected_row = None
        self.sort_column = None
        self.sort_ascending = True
        self.ai_insights_enabled = False
        self.console_log_enabled = False
        self.on_load_callback = on_load_callback
        self.setup_ui()

    def setup_ui(self):
        """Set up the UI with a tabbed interface and orderly layout."""
        self.page.title = 'OCI IAM Explorer'
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.bgcolor = ft.Colors.BLUE_GREY_50
        self.page.padding = 20
        self.page.horizontal_alignment = ft.CrossAxisAlignment.START

        self.load_mode_dropdown = ft.Dropdown(
            label='Load Mode',
            options=[
                ft.dropdown.Option('instance_principal'),
                ft.dropdown.Option('profile'),
                ft.dropdown.Option('cache'),
            ],
            value=self.config['General'].get('load_mode', 'profile'),
            width=300,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            on_change=self.on_load_mode_change,
        )
        self.second_dropdown = ft.Dropdown(
            label='Profile / Cache',
            options=[],
            value=self.config['OCI'].get('config_profile')
            if self.load_mode_dropdown.value == 'profile'
            else self.config['OCI'].get('cache_name', ''),
            width=300,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            on_change=self.on_config_change,
            visible=self.load_mode_dropdown.value in ['profile', 'cache'],
        )
        self.load_button = ft.ElevatedButton(
            'Load',
            on_click=self.on_load_data,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.INDIGO_500, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)
            ),
        )
        self.ai_endpoint_input = ft.TextField(
            label='AI Endpoint',
            value=self.config['OCI'].get('ai_endpoint', ''),
            width=500,
            border_radius=10,
            on_change=self.on_config_change,
        )
        self.model_ocid_input = ft.TextField(
            label='Model OCID',
            value=self.config['OCI'].get('model_ocid', ''),
            width=500,
            border_radius=10,
            on_change=self.on_config_change,
        )
        self.verb_filter = ft.TextField(
            label='Policy Text Filter',
            width=300,
            border_radius=10,
            on_change=self.on_filter_change,
        )
        self.name_filter = ft.TextField(
            label='Filter by Name',
            width=300,
            border_radius=10,
            on_change=self.on_filter_change,
        )
        self.test_ai_input = ft.TextField(
            label='Test AI Input',
            width=300,
            border_radius=10,
            disabled=not self.ai_insights_enabled,
            on_change=self.on_test_ai_input_change,
        )
        self.test_ai_button = ft.ElevatedButton(
            'Test AI',
            on_click=self.on_test_ai,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.GREY_400, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)
            ),
            disabled=not (self.ai_insights_enabled and self.test_ai_input.value.strip()),
        )
        self.ai_insights_check = ft.Checkbox(
            label='AI Insights', value=self.ai_insights_enabled, on_change=self.on_panel_toggle
        )
        self.console_log_check = ft.Checkbox(
            label='Console Log', value=self.console_log_enabled, on_change=self.on_panel_toggle
        )
        self.log_level_dropdown = ft.Dropdown(
            label='Log Level',
            options=[ft.dropdown.Option('INFO'), ft.dropdown.Option('DEBUG')],
            value=self.config['General'].get('log_level', 'INFO'),
            width=150,
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            on_change=self.on_log_level_change,
        )
        self.clear_button = ft.ElevatedButton(
            'Clear Logs',
            on_click=self.on_clear_logs,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.INDIGO_500, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)
            ),
        )
        self.refresh_button = ft.ElevatedButton(
            'Refresh Data',
            on_click=self.on_refresh_data,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.INDIGO_500, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)
            ),
        )
        self.get_insights_button = ft.ElevatedButton(
            'Get AI Insights',
            on_click=self.on_get_insights,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.GREY_400, color=ft.Colors.WHITE, shape=ft.RoundedRectangleBorder(radius=10)
            ),
            disabled=not self.ai_insights_enabled,
            visible=True,  # Keep permanently visible for testing
        )
        self.policy_statement_input = ft.TextField(
            label='Policy Statement Analysis',
            width=500,
            border_radius=10,
            read_only=True,
            visible=True,  # Keep permanently visible for testing
        )
        self.statements_table = ft.DataTable(
            columns=[
                ft.DataColumn(
                    ft.Text('Policy Name', weight=ft.FontWeight.BOLD), on_sort=lambda e: self.on_sort_column(0)
                ),
                ft.DataColumn(
                    ft.Text('Compartment OCID', weight=ft.FontWeight.BOLD), on_sort=lambda e: self.on_sort_column(1)
                ),
                ft.DataColumn(
                    ft.Text('Creation Date', weight=ft.FontWeight.BOLD), on_sort=lambda e: self.on_sort_column(2)
                ),
                ft.DataColumn(
                    ft.Text('Statement', weight=ft.FontWeight.BOLD), on_sort=lambda e: self.on_sort_column(3)
                ),
            ],
            rows=[],
            border=ft.border.all(width=1, color=ft.Colors.GREY_300),
            bgcolor=ft.Colors.WHITE,
        )
        self.users_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text('Domain Name', weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('User Name', weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('ID', weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            border=ft.border.all(width=1, color=ft.Colors.GREY_300),
            bgcolor=ft.Colors.WHITE,
        )
        self.groups_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text('Domain Name', weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('Group Name', weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('ID', weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('Matching Rule', weight=ft.FontWeight.BOLD)),
            ],
            rows=[],
            border=ft.border.all(width=1, color=ft.Colors.GREY_300),
            bgcolor=ft.Colors.WHITE,
        )
        self.bottom_panel = ft.Container(
            content=ft.Row([], spacing=10), padding=10, border_radius=10, bgcolor=ft.Colors.WHITE, visible=False
        )
        self.help_panel = ft.Container(
            content=ft.Text('', size=14, color=ft.Colors.GREY_800, italic=True),
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.GREY_200,
            alignment=ft.alignment.center,
        )

        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            on_change=self.on_tab_change,
            tabs=[
                ft.Tab(
                    text='Config & Load',
                    content=ft.Column(
                        [
                            ft.Text('Loading', size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO_500),
                            ft.Row(
                                [self.load_mode_dropdown, self.second_dropdown, self.load_button],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=20,
                            ),
                            ft.Row([self.refresh_button], alignment=ft.MainAxisAlignment.START, spacing=20),
                            ft.Text('AI', size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO_500),
                            ft.Row(
                                [self.ai_endpoint_input, self.model_ocid_input],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=20,
                            ),
                            ft.Row(
                                [self.test_ai_input, self.test_ai_button],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=20,
                            ),
                            ft.Text('Display', size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO_500),
                            ft.Row(
                                [
                                    self.ai_insights_check,
                                    self.console_log_check,
                                    self.log_level_dropdown,
                                    self.clear_button,
                                ],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=20,
                            ),
                        ],
                        spacing=20,
                        alignment=ft.MainAxisAlignment.START,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                    ),
                ),
                ft.Tab(
                    text='Policies',
                    content=ft.Column(
                        [
                            ft.Row([self.verb_filter], alignment=ft.MainAxisAlignment.START, spacing=20),
                            ft.Container(
                                content=ft.ListView(
                                    controls=[self.statements_table],
                                    height=300,  # Reduced height to ensure AI controls are visible
                                    auto_scroll=False,
                                    spacing=0,
                                    padding=10,
                                ),
                                bgcolor=ft.Colors.WHITE,
                                border_radius=10,
                                padding=10,
                            ),
                            ft.Row(
                                [self.policy_statement_input, self.get_insights_button],
                                alignment=ft.MainAxisAlignment.START,
                                spacing=20,
                                visible=True,  # Keep permanently visible for testing
                            ),
                        ],
                        spacing=20,
                        alignment=ft.MainAxisAlignment.START,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        expand=True,
                    ),
                ),
                ft.Tab(
                    text='Users & Groups',
                    content=ft.Column(
                        [
                            ft.Row([self.name_filter], alignment=ft.MainAxisAlignment.START, spacing=20),
                            ft.Text('Users', size=18, weight=ft.FontWeight.BOLD),
                            ft.Container(self.users_table, padding=10, border_radius=10, bgcolor=ft.Colors.WHITE),
                            ft.Text('Groups', size=18, weight=ft.FontWeight.BOLD),
                            ft.Container(self.groups_table, padding=10, border_radius=10, bgcolor=ft.Colors.WHITE),
                        ],
                        spacing=20,
                        alignment=ft.MainAxisAlignment.START,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        expand=True,
                    ),
                ),
            ],
            expand=1,
        )

        self.page.add(
            ft.Column(
                [
                    ft.Text('OCI IAM Explorer', size=30, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO_500),
                    self.tabs,
                    self.bottom_panel,
                    self.help_panel,
                ],
                spacing=20,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.START,
                expand=True,
            )
        )
        self.on_load_mode_change(None)

    def on_tab_change(self, e):
        """Handle tab change to update the tables."""
        self.update_table()

    def on_sort_column(self, column_index):
        """Handle manual column sorting for policies table."""
        if self.tabs.selected_index == 1:
            if column_index is not None:
                self.sort_column = column_index
                self.sort_ascending = not self.sort_ascending
                self.update_table()
        self.page.update()

    def on_load_mode_change(self, e):
        """Handle load mode change."""
        mode = self.load_mode_dropdown.value
        self.config['General']['load_mode'] = mode
        self.second_dropdown.visible = mode in ['profile', 'cache']
        if mode == 'profile':
            self.second_dropdown.options = [ft.dropdown.Option(p) for p in list_oci_profiles()]
            self.second_dropdown.label = 'Profile'
            self.second_dropdown.value = self.config['OCI'].get('config_profile', 'DEFAULT')
        elif mode == 'cache':
            self.second_dropdown.options = [ft.dropdown.Option(c) for c in list_caches()]
            self.second_dropdown.label = 'Cache'
            self.second_dropdown.value = self.config['OCI'].get('cache_name', '')
        save_config(self.config)
        self.page.update()

    def on_load_data(self, e):
        """Load data based on mode only when triggered by user."""
        mode = self.load_mode_dropdown.value
        profile = self.second_dropdown.value if mode == 'profile' else 'DEFAULT'
        cache_name = self.second_dropdown.value if mode == 'cache' else None
        ai_endpoint = self.ai_endpoint_input.value.strip()
        model_ocid = self.model_ocid_input.value.strip()
        if ai_endpoint:
            self.config['OCI']['ai_endpoint'] = ai_endpoint
        if model_ocid:
            self.config['OCI']['model_ocid'] = model_ocid
        save_config(self.config)
        new_service = self.on_load_callback(mode, profile, cache_name)
        self.service = new_service
        self.service.update_ai_config(ai_endpoint, model_ocid)
        self.update_table()
        self.get_insights_button.disabled = not self.ai_insights_enabled
        self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
        self.selected_row = None
        self.policy_statement_input.value = ''
        self.page.update()

    async def show_ai_insights(self, policy_name):
        """Show AI insights for a selected policy with loading indicator."""
        if not self.ai_insights_enabled:
            return
        self.ai_insights_content = ft.Markdown('**Loading AI Insights...**', selectable=True)
        self.update_bottom_panel()
        self.page.update()
        insights = await self.service.get_ai_insights(policy_name)
        self.ai_insights_content = ft.Markdown(insights, selectable=True, extension_set='gitHubWeb')
        self.update_bottom_panel()
        self.page.update()

    def on_get_insights(self, e):
        """Handle AI Insights button click to display details for the selected policy."""
        if not self.ai_insights_enabled:
            self.ai_insights_content = ft.Markdown('**AI Insights must be enabled**', selectable=True)
            self.update_bottom_panel()
            self.page.update()
            return
        if self.selected_row:
            policy_name = self.selected_row['policy_name']
            self.page.run_task(self.show_ai_insights, policy_name)
        else:
            self.ai_insights_content = ft.Markdown('**Please select a policy to view AI insights**', selectable=True)
            self.update_bottom_panel()
            self.page.update()

    def on_test_ai(self, e):
        """Handle Test AI button click to test the AI endpoint with input text."""
        if self.ai_insights_enabled and self.test_ai_input.value.strip():
            prompt = self.test_ai_input.value.strip()
            result = self.service.query_genai(prompt, cache_type='test', cache_query=prompt)
            self.ai_insights_content = ft.Markdown(
                f'**Test Result**: {result}', selectable=True, extension_set='gitHubWeb'
            )
            self.update_bottom_panel()
            self.page.update()
        else:
            self.ai_insights_content = ft.Markdown(
                '**Please enter a valid prompt and ensure AI Insights is enabled**', selectable=True
            )
            self.update_bottom_panel()
            self.page.update()

    def on_test_ai_input_change(self, e):
        """Handle changes to Test AI input to update button state."""
        self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
        self.page.update()

    def update_table(self):
        """Update tables based on selected tab and filters."""
        current_tab = self.tabs.selected_index
        verb_filter = self.verb_filter.value.strip() if current_tab == 1 else ''
        name_filter = self.name_filter.value.strip() if current_tab == 2 else ''

        if current_tab == 1:
            data = []
            for policy in self.service.cache.get('policies', []):
                for stmt in policy.get('statements', []):
                    if not verb_filter or verb_filter.lower() in stmt.lower():
                        data.append(
                            {
                                'policy_name': policy['name'],
                                'compartment_id': policy['compartment_id'],
                                'creation_date': policy.get('creation_date', 'N/A'),
                                'statement': stmt,
                            }
                        )
            if self.sort_column is not None:
                key = ['policy_name', 'compartment_id', 'creation_date', 'statement'][self.sort_column]
                data.sort(key=lambda x: str(x.get(key, '')).lower(), reverse=not self.sort_ascending)
            self.statements_table.rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.GestureDetector(
                                content=ft.Text(row['policy_name']), on_tap=lambda e, r=row: self.on_row_select(r)
                            )
                        ),
                        ft.DataCell(ft.Text(row['compartment_id'])),
                        ft.DataCell(ft.Text(row['creation_date'])),
                        ft.DataCell(ft.Text(row['statement'], max_lines=5, overflow=ft.TextOverflow.ELLIPSIS)),
                    ],
                    on_select_changed=lambda e, r=row: self.on_row_select(r),
                )
                for row in data
            ]
            self.get_insights_button.disabled = not self.ai_insights_enabled
            self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
            self.policy_statement_input.value = (
                self.selected_row['statement'] if self.selected_row and self.ai_insights_enabled else ''
            )
        elif current_tab == 2:
            users_data = self.service.get_entities_for_table('Users', name_filter)
            self.users_table.rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(u.get('domain_name', 'N/A'))),
                        ft.DataCell(ft.Text(u['name'])),
                        ft.DataCell(ft.Text(u['id'])),
                    ]
                )
                for u in users_data
            ]
            groups_data = self.service.get_entities_for_table(
                'Groups', name_filter
            ) + self.service.get_entities_for_table('Dynamic Groups', name_filter)
            self.groups_table.rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(g.get('domain_name', 'N/A'))),
                        ft.DataCell(ft.Text(g['name'])),
                        ft.DataCell(ft.Text(g['id'])),
                        ft.DataCell(ft.Text(g.get('matching_rule', 'N/A'))),
                    ]
                )
                for g in groups_data
            ]
        self.update_bottom_panel()
        self.page.update()

    def on_row_select(self, row_data):
        """Handle row selection to enable/disable the AI Insights button and populate statement."""
        self.selected_row = row_data
        self.get_insights_button.disabled = not self.ai_insights_enabled
        self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
        self.policy_statement_input.value = row_data['statement'] if row_data and self.ai_insights_enabled else ''
        self.page.update()

    def update_bottom_panel(self):
        """Update the bottom panel based on global checkbox states."""
        ai_enabled = self.ai_insights_enabled
        log_enabled = self.console_log_enabled
        row_controls = []

        if ai_enabled:
            self.ai_insights_content = self.ai_insights_content or ft.Markdown(
                '**Click a policy name to view AI insights**', selectable=True, extension_set='gitHubWeb'
            )
            row_controls.append(
                ft.Container(
                    content=ft.ListView(
                        controls=[self.ai_insights_content], height=200, auto_scroll=True, spacing=0, padding=10
                    ),
                    bgcolor=ft.Colors.GREY_100,
                    border_radius=5,
                    expand=1 if log_enabled else True,
                )
            )

        if log_enabled:
            log_level = self.log_level_dropdown.value
            logs = log_handler.short_logs[-10:] if log_level == 'INFO' else log_handler.logs[-10:]
            row_controls.append(
                ft.Container(
                    content=ft.Text('\n'.join(logs), size=14, color=ft.Colors.BLACK, selectable=True),
                    padding=10,
                    bgcolor=ft.Colors.GREY_100,
                    border_radius=5,
                    expand=1 if ai_enabled else True,
                )
            )

        self.bottom_panel.content = ft.Row(row_controls, spacing=10, tight=True, alignment=ft.MainAxisAlignment.START)
        self.bottom_panel.visible = ai_enabled or log_enabled
        if self.bottom_panel.visible:
            self.bottom_panel.height = 200
        self.page.update()

    def on_filter_change(self, e):
        """Handle filter input changes."""
        self.update_table()

    def on_panel_toggle(self, e):
        """Handle checkbox toggle for AI Insights or Console Log globally."""
        if e.control == self.ai_insights_check:
            self.ai_insights_enabled = e.control.value
            self.test_ai_input.disabled = not self.ai_insights_enabled
            self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
            self.get_insights_button.disabled = not self.ai_insights_enabled
            self.policy_statement_input.value = (
                self.selected_row['statement'] if self.selected_row and self.ai_insights_enabled else ''
            )
        elif e.control == self.console_log_check:
            self.console_log_enabled = e.control.value
        self.update_bottom_panel()
        self.update_table()
        self.page.update()

    def on_log_level_change(self, e):
        """Handle log level change, updating app-wide logging and UI display."""
        log_level = self.log_level_dropdown.value
        set_logging_level(log_level)
        self.config['General']['log_level'] = log_level
        save_config(self.config)
        self.update_bottom_panel()
        self.page.update()

    def on_clear_logs(self, e):
        """Clear logs in the Console Log panel."""
        log_handler.clear()
        self.update_bottom_panel()
        self.page.update()

    def on_config_change(self, e):
        """Handle changes to config fields."""
        self.config['OCI']['config_profile'] = (
            self.second_dropdown.value
            if self.load_mode_dropdown.value == 'profile'
            else self.config['OCI']['config_profile']
        )
        self.config['OCI']['cache_name'] = (
            self.second_dropdown.value if self.load_mode_dropdown.value == 'cache' else self.config['OCI']['cache_name']
        )
        ai_endpoint = self.ai_endpoint_input.value.strip()
        model_ocid = self.model_ocid_input.value.strip()
        if ai_endpoint:
            self.config['OCI']['ai_endpoint'] = ai_endpoint
        if model_ocid:
            self.config['OCI']['model_ocid'] = model_ocid
        self.service.update_ai_config(ai_endpoint, model_ocid)
        self.test_ai_button.disabled = not (self.ai_insights_enabled and self.test_ai_input.value.strip())
        self.get_insights_button.disabled = not self.ai_insights_enabled
        save_config(self.config)
        self.page.update()

    def on_refresh_data(self, e):
        """Force refresh data from OCI and update cache."""
        self.on_load_data(e)
