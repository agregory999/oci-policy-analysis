import tkinter as tk
from tkinter import ttk

from logic.data_repo import PolicyCompartmentAnalysis
from logic.logger import get_logger
from ui.data_table import DataTable

logger = get_logger()

# Column data for Custom Data Table
ALL_POLICY_COLUMNS = [
    'Policy Name',
    'Policy OCID',
    'Compartment OCID',
    'Policy Compartment',
    'Statement Text',
    'Valid',
    'Invalid Reason',
    'Subject Type',
    'Subject',
    'Verb',
    'Resource',
    'Permission',
    'Location Type',
    'Location',
    'Effective Path',
    'Conditions',
    'Comments',
    'Parsing Notes',
    'Creation Time',
    'Parsed',
]
BASIC_POLICY_COLUMNS = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Effective Path', 'Valid']
BASIC_INVALID_POLICY_COLUMNS = ['Policy Name', 'Policy Compartment', 'Statement Text', 'Valid', 'Invalid Reason']
POLICY_COLUMN_WIDTHS = {
    'Policy Name': 250,
    'Policy OCID': 450,
    'Compartment OCID': 450,
    'Policy Compartment': 250,
    'Statement Text': 700,
    'Valid': 80,
    'Invalid Reason': 200,
    'Effective Path': 200,
    'Subject Type': 120,
    'Subject': 200,
    'Verb': 100,
    'Resource': 150,
    'Permission': 150,
    'Location Type': 120,
    'Location': 200,
    'Conditions': 200,
    'Comments': 200,
    'Parsing Notes': 250,
    'Creation Time': 150,
    'Parsed': 80,
}


class PoliciesTab(ttk.Frame):
    """Policy UI:
    - document here
    """

    def __init__(self, parent, app, policy_repo: PolicyCompartmentAnalysis, settings):  # noqa: C901
        super().__init__(parent)
        self.app = app
        self.settings = settings
        self.policy_repo = policy_repo

        # Configure tab
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Filter options (LabelFrame)
        label_frm = ttk.LabelFrame(self, text='Policy Filters')
        label_frm.pack(fill='both', padx=10, pady=10)

        # Create the policy filter frame
        frm_policy_filter = ttk.Frame(label_frm)
        frm_policy_filter.grid(row=0, column=0, sticky='w', padx=10, pady=10)
        frm_policy_filter.columnconfigure([0, 5], weight=1)
        ttk.Label(frm_policy_filter, text='Filters - use | in fields for OR)').grid(
            row=0, column=0, columnspan=6, pady=2, sticky='w'
        )

        # Variables for policy and output filters
        self.subject_filter_var = tk.StringVar()
        self.use_subject_any = tk.BooleanVar()
        self.verb_filter_var = tk.StringVar()
        self.location_filter_var = tk.StringVar()
        self.resource_filter_var = tk.StringVar()
        self.hierarchy_filter_var = tk.StringVar()
        self.condition_filter_var = tk.StringVar()
        self.text_filter_var = tk.StringVar()
        self.effective_path_var = tk.StringVar()
        self.policy_filter_var = tk.StringVar()
        self.hierarchy_filter_root = tk.BooleanVar()
        self.location_filter_tenancy = tk.BooleanVar()
        self.chk_show_service = tk.BooleanVar()
        self.chk_show_dynamic = tk.BooleanVar()
        self.chk_show_resource = tk.BooleanVar()
        self.chk_show_invalid = tk.BooleanVar()
        self.chk_show_regular = tk.BooleanVar(value=True)
        self.chk_show_expanded = tk.BooleanVar()

        def toggle_any_subject():
            if self.use_subject_any.get():
                self.subject_filter_var.set('any-user|any-group')
            else:
                self.subject_filter_var.set('')

            # Update the Output
            self.update_policy_output()

        def toggle_location_tenancy():
            if self.location_filter_tenancy.get():
                self.location_filter_var.set('tenancy')
            else:
                self.location_filter_var.set('')

            # Update the output
            self.update_policy_output()

        def toggle_hierarchy_root():
            if self.hierarchy_filter_root.get():
                self.hierarchy_filter_var.set('ROOTONLY')
            else:
                self.hierarchy_filter_var.set('')

            # Update the Output
            self.update_policy_output()

        def clear_policy_filters():
            # Clear all filters
            for entry in [
                self.subject_filter_var,
                self.verb_filter_var,
                self.resource_filter_var,
                self.location_filter_var,
                self.hierarchy_filter_var,
                self.condition_filter_var,
                self.text_filter_var,
                self.policy_filter_var,
            ]:
                entry.set('')
            self.use_subject_any.set(False)
            self.location_filter_tenancy.set(False)
            self.hierarchy_filter_root.set(False)
            self.update_policy_output()

        # Within the policy filter frame, create the filter fields and buttons
        ttk.Label(frm_policy_filter, text='Subject').grid(row=1, column=0, padx=5, pady=2, sticky='w')
        ttk.Entry(frm_policy_filter, textvariable=self.subject_filter_var, width=20).grid(
            row=1, column=1, padx=2, sticky='ew'
        )
        ttk.Checkbutton(
            frm_policy_filter, text='Any-User/Group', variable=self.use_subject_any, command=toggle_any_subject
        ).grid(row=1, column=2, padx=2)

        # Verb
        ttk.Label(frm_policy_filter, text='Verb').grid(row=1, column=3, padx=5, pady=2, sticky='w')
        tk.Entry(frm_policy_filter, textvariable=self.verb_filter_var, width=30).grid(
            row=1, column=4, columnspan=2, padx=5, pady=2, sticky='ew'
        )

        # Resource
        ttk.Label(frm_policy_filter, text='Resource').grid(row=2, column=0, padx=5, pady=2, sticky='w')
        tk.Entry(frm_policy_filter, textvariable=self.resource_filter_var, width=30).grid(
            row=2, column=1, columnspan=2, padx=5, pady=2, sticky='ew'
        )

        # Location
        ttk.Label(frm_policy_filter, text='Location').grid(row=2, column=3, padx=5, pady=2, sticky='w')
        entry_loc = tk.Entry(frm_policy_filter, width=20, textvariable=self.location_filter_var)
        entry_loc.grid(row=2, column=4, padx=2, sticky='w')
        ttk.Checkbutton(
            frm_policy_filter,
            text='in tenancy?',
            variable=self.location_filter_tenancy,
            command=toggle_location_tenancy,
        ).grid(row=2, column=5, padx=2)

        # Hierarchy

        ttk.Label(frm_policy_filter, text='Hierarchy').grid(row=3, column=0, padx=5, pady=2, sticky='w')
        entry_hierarchy = tk.Entry(frm_policy_filter, width=30, textvariable=self.hierarchy_filter_var)
        entry_hierarchy.grid(row=3, column=1, padx=5, pady=2, sticky='w')
        ttk.Checkbutton(
            frm_policy_filter,
            text='Tenancy Root Only',
            variable=self.hierarchy_filter_root,
            command=toggle_hierarchy_root,
        ).grid(row=3, column=2, padx=5, pady=2)

        # Condition
        ttk.Label(frm_policy_filter, text='Condition').grid(row=3, column=3, padx=5, pady=2, sticky='w')
        entry_condition = tk.Entry(frm_policy_filter, width=30, textvariable=self.condition_filter_var)
        entry_condition.grid(row=3, column=4, columnspan=2, padx=5, pady=2, sticky='ew')

        # Text
        ttk.Label(frm_policy_filter, text='Text').grid(row=4, column=0, padx=5, pady=2, sticky='w')
        entry_text = tk.Entry(frm_policy_filter, width=30, textvariable=self.text_filter_var)
        entry_text.grid(row=4, column=1, columnspan=2, padx=5, pady=2, sticky='ew')

        # Policy Name
        ttk.Label(frm_policy_filter, text='Policy Name').grid(row=4, column=3, padx=5, pady=2, sticky='w')
        entry_policy = tk.Entry(frm_policy_filter, textvariable=self.policy_filter_var, width=30)
        entry_policy.grid(row=4, column=4, columnspan=2, padx=5, pady=2, sticky='ew')

        # Effective Path
        ttk.Label(frm_policy_filter, text='Effective Path (Shows any policy that affects this compartment)').grid(
            row=5, column=0, columnspan=2, padx=5, pady=2, sticky='w'
        )
        effective_path_text = tk.Entry(frm_policy_filter, width=30, textvariable=self.effective_path_var)
        effective_path_text.grid(row=5, column=3, columnspan=4, padx=5, pady=2, sticky='ew')

        # Clear Button
        self.btn_clear = ttk.Button(label_frm, text='Clear', state=tk.DISABLED, command=clear_policy_filters)
        self.btn_clear.grid(row=0, column=1, padx=5, pady=2, sticky='e')

        # Output Filter options (LabelFrame)
        label_frm2 = ttk.LabelFrame(self, text='Output Filters')
        label_frm2.pack(fill='both', padx=10, pady=10)

        # Show Tenancy Name and Statements count
        self.tenancy_name_var = tk.StringVar()
        ttk.Label(label_frm2, textvariable=self.tenancy_name_var).grid(row=0, column=0, padx=5, pady=3)
        ttk.Separator(label_frm2, orient=tk.VERTICAL).grid(row=0, column=1, padx=5, pady=3)
        self.label_policy_count = ttk.Label(label_frm2, text='Statements (Filtered): 0')
        self.label_policy_count.grid(row=0, column=2, padx=5, pady=3, sticky='w')

        ttk.Separator(label_frm2, orient=tk.VERTICAL).grid(row=0, column=3, padx=5, pady=3)
        # Display Output Selection
        ttk.Label(label_frm2, text='Statement Type\nto display:').grid(row=0, column=4, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Service', variable=self.chk_show_service, command=self.update_policy_output
        ).grid(row=0, column=5, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Dynamic Group', variable=self.chk_show_dynamic, command=self.update_policy_output
        ).grid(row=0, column=6, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Resource', variable=self.chk_show_resource, command=self.update_policy_output
        ).grid(row=0, column=7, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Regular', variable=self.chk_show_regular, command=self.update_policy_output
        ).grid(row=0, column=8, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Invalid Only', variable=self.chk_show_invalid, command=self.update_policy_output
        ).grid(row=0, column=9, padx=5, pady=3)
        ttk.Checkbutton(
            label_frm2, text='Parsed Output', variable=self.chk_show_expanded, command=self.update_policy_output
        ).grid(row=0, column=10, padx=5, pady=3)

        def selection_callback(selected_rows: list[dict]) -> None:
            for row in selected_rows:
                logger.info(f"Selected policy statement: {row.get('Statement Text')}")
                # Update the policy box
                self.app.policy_query_var.set(row.get('Statement Text'))
                # self.policy_analyze_statement_var.set(row.get('Statement Text'))

        # Use the Data Table here with fields
        self.policy_table = DataTable(
            self,
            columns=ALL_POLICY_COLUMNS,
            display_columns=BASIC_POLICY_COLUMNS,
            data=[],
            column_widths=POLICY_COLUMN_WIDTHS,
            selection_callback=selection_callback,
            multi_select=True,
        )
        # self.policy_table.grid(row=0, column=0, sticky="nsew")
        self.policy_table.pack(fill='both', expand=True)

        # Trace to update the output when any filter changes
        self.verb_filter_var.trace_add('write', self.update_policy_output)
        self.subject_filter_var.trace_add('write', self.update_policy_output)
        self.resource_filter_var.trace_add('write', self.update_policy_output)
        self.location_filter_var.trace_add('write', self.update_policy_output)
        self.hierarchy_filter_var.trace_add('write', self.update_policy_output)
        self.condition_filter_var.trace_add('write', self.update_policy_output)
        self.text_filter_var.trace_add('write', self.update_policy_output)
        self.policy_filter_var.trace_add('write', self.update_policy_output)
        self.effective_path_var.trace_add('write', self.update_policy_output)

    def update_policy_output(self, *args):  # noqa: C901
        # Tenancy Display
        if self.policy_repo and self.policy_repo.tenancy_name:
            self.tenancy_name_var.set(f'Tenancy:\n{self.policy_repo.tenancy_name}')
        else:
            self.tenancy_name_var.set('Please Load a Tenancy')

        # Build filter dict for new call to filter
        filters = {}
        if self.subject_filter_var.get():
            filters['subject'] = self.subject_filter_var.get().split('|') or None
        if self.verb_filter_var.get():
            filters['verb'] = self.verb_filter_var.get().split('|') or None
        if self.resource_filter_var.get():
            filters['resource'] = self.resource_filter_var.get().split('|') or None
        if self.location_filter_var.get():
            filters['location'] = self.location_filter_var.get().split('|') or None
        if self.hierarchy_filter_var.get():
            filters['hierarchy'] = (
                'ROOTONLY' if self.hierarchy_filter_root.get() else self.hierarchy_filter_var.get().split('|')
            )
        if self.condition_filter_var.get():
            filters['condition'] = self.condition_filter_var.get().split('|') or None
        if self.text_filter_var.get():
            filters['statement_text'] = self.text_filter_var.get().split('|') or None
        if self.policy_filter_var.get():
            filters['policy_name'] = self.policy_filter_var.get().split('|') or None
        if self.effective_path_var.get():
            filters['effective_path'] = [self.effective_path_var.get()]

        logger.info(f'Applying policy filters: {filters}')
        filtered_statements = self.policy_repo.filter_policy_statements_json(filters=filters)
        logger.info(f'Filtered statements via JSON filter: {len(filtered_statements)}')
        # Apply additional filters for output

        # Determine which rows to show based on checkboxes
        rows_to_show: list = [
            st
            for st in filtered_statements
            if (
                self.chk_show_service.get()
                and st.get('Subject Type') == 'service'
                or self.chk_show_dynamic.get()
                and st.get('Subject Type') == 'dynamic-group'
                or self.chk_show_resource.get()
                and st.get('Subject Type') == 'resource'
                or self.chk_show_regular.get()
                and st.get('Subject Type') in ['group', 'any-user', 'any-group']
                or self.chk_show_invalid.get()
                and (not st.get('Valid') or not st.get('Parsed'))
            )
        ]
        self.label_policy_count.config(
            text=f'Statements (Filtered): {len(filtered_statements)}\nStatements (Shown): {len(rows_to_show)}'
        )
        # Populate Data Table
        logger.debug(rows_to_show)
        self.policy_table.update_data(rows_to_show)
        logger.info(f'Populating policy data table with {len(rows_to_show)} statements')

        # Open up all columns if expanded is checked
        if self.chk_show_expanded.get():
            self.policy_table.set_display_columns(ALL_POLICY_COLUMNS)
            logger.debug('Setting policy table to expanded view with all columns')
        elif self.chk_show_invalid.get():
            self.policy_table.set_display_columns(BASIC_INVALID_POLICY_COLUMNS)
            logger.debug('Setting policy table to expanded view with invalid columns')
        else:
            self.policy_table.set_display_columns(BASIC_POLICY_COLUMNS)
            logger.debug('Setting policy table to expanded view with basic columns')
