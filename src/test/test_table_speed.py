import logging
import random
import string
import time
import tkinter as tk

import pytest
from oci_policy_analysis.ui.data_table import CheckboxTable, DataTable

# Ensure logs are output (they already log elapsed timings at INFO)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('oci-policy-analysis').setLevel(logging.INFO)
logging.getLogger('data_table').setLevel(logging.INFO)

# Representative protection/candidate table columns
UI_COLUMNS = ['Policy Name', 'Statement Text', 'Location', 'Compartment', 'Principal', 'Internal ID', '☑']
UI_DISPLAY_COLUMNS = ['☑', 'Policy Name', 'Statement Text', 'Location', 'Compartment', 'Principal']
UI_COLUMN_WIDTHS = {
    'Policy Name': 180,
    'Statement Text': 320,
    'Location': 120,
    'Compartment': 120,
    'Principal': 120,
    'Internal ID': 90,
    '☑': 34,
}


def random_row(columns, checked=True):
    d = {}
    for col in columns:
        if col == 'Internal ID':
            d[col] = random.randint(10000, 99999)
        elif col == 'Policy Name':
            d[col] = random.choice(['NetworkPolicy', 'DBAccess', 'Consolidation', 'TestPolicy'])
        elif col == 'Statement Text':
            d[col] = (
                'Allow '
                + random.choice(['Admins', 'Users', 'DevOps', 'Guests'])
                + ' to '
                + random.choice(['read', 'manage', 'inspect'])
            )
        elif col == 'Location':
            d[col] = random.choice(['root', 'EU/Compartment', 'APP', 'DEFAULT'])
        elif col == 'Compartment':
            d[col] = random.choice(['Finance', 'Dev', 'Ops', 'Security'])
        elif col == 'Principal':
            d[col] = random.choice(['group', 'user', 'dynamic-group'])
        else:
            d[col] = ''.join(random.choices(string.ascii_letters, k=6))
    d['checked'] = checked
    return d


def random_checked_list(columns, n, p_checked=0.5):
    # Return list of n dicts with random checked state
    return [random_row(columns, checked=random.random() < p_checked) for _ in range(n)]


@pytest.mark.parametrize('table_class', [DataTable, CheckboxTable])
@pytest.mark.parametrize('num_rows', [10, 100, 500, 1000, 2500])
def test_table_loading_and_productionlike_ops(table_class, num_rows, caplog):
    """
    Improved realistic speed test for DataTable/CheckboxTable, mimicking UI patterns (filter/search/updates).
    For CheckboxTable: tests select/deselect all, updates after various simulated UI changes.
    """
    columns = list(UI_COLUMNS)

    # -- Data for test
    data = random_checked_list(columns, num_rows)

    root = tk.Tk()
    root.withdraw()
    try:
        # --- Initial load: simulate full UI load of data
        t0 = time.perf_counter()
        if table_class is DataTable:
            # DataTable doesn't use "☑" column or checked
            dt = DataTable(
                root,
                columns=columns,
                display_columns=[c for c in columns if c != 'Internal ID'],
                data=[{k: v for k, v in row.items() if k in columns} for row in data],
                column_widths=UI_COLUMN_WIDTHS,
                sortable=True,
            )
        else:
            # Typical display_columns includes ☑
            dt = CheckboxTable(
                root,
                columns=columns,
                data=data,
                display_columns=UI_DISPLAY_COLUMNS,
                column_widths=UI_COLUMN_WIDTHS,
                sortable=True,
                checked_by_default=False,
            )
        root.update_idletasks()
        t1 = time.perf_counter()
        logging.info('[%s, %d rows] Instantiation/initial load: %.3f s', table_class.__name__, num_rows, t1 - t0)
        print(f'[{table_class.__name__}, {num_rows} rows] Initial load: {t1-t0:.3f}s')

        # --- Simulate search/filter change: partial update_data with filtered/changed checked state
        search_filter_data = [row for i, row in enumerate(data) if i % 10 != 0]
        for row in search_filter_data:
            # flip checked state for 25%
            if random.random() < 0.25:
                row['checked'] = not row['checked']
        t2 = time.perf_counter()
        dt.update_data(search_filter_data)
        root.update_idletasks()
        t3 = time.perf_counter()
        logging.info(
            '[%s, %d rows] Simulated search/filter + update_data: %.3f s',
            table_class.__name__,
            len(search_filter_data),
            t3 - t2,
        )
        print(f'[{table_class.__name__}, {len(search_filter_data)} rows] Search update: {t3-t2:.3f}s')

        if table_class is CheckboxTable:
            # --- Simulate select-all (all rows checked)
            all_checked = [dict(row, checked=True) for row in data]
            t4 = time.perf_counter()
            dt.update_data(all_checked)
            root.update_idletasks()
            t5 = time.perf_counter()
            logging.info('[%s, %d rows] Select-all update_data: %.3f s', table_class.__name__, num_rows, t5 - t4)
            print(f'[{table_class.__name__}, {num_rows} rows] Select-all: {t5-t4:.3f}s')

            # --- Simulate unselect-all (all rows unchecked)
            all_unchecked = [dict(row, checked=False) for row in data]
            t6 = time.perf_counter()
            dt.update_data(all_unchecked)
            root.update_idletasks()
            t7 = time.perf_counter()
            logging.info('[%s, %d rows] Unselect-all update_data: %.3f s', table_class.__name__, num_rows, t7 - t6)
            print(f'[{table_class.__name__}, {num_rows} rows] Unselect-all: {t7-t6:.3f}s')

            # --- Simulate toggling a single row (check first row, uncheck second, etc.)
            toggled_data = data[:]
            if toggled_data:
                toggled_data[0]['checked'] = not toggled_data[0]['checked']
                if len(toggled_data) > 1:
                    toggled_data[1]['checked'] = not toggled_data[1]['checked']
            t8 = time.perf_counter()
            dt.update_data(toggled_data)
            root.update_idletasks()
            t9 = time.perf_counter()
            logging.info('[%s, %d rows] Single-row toggle update_data: %.3f s', table_class.__name__, num_rows, t9 - t8)
            print(f'[{table_class.__name__}, {num_rows} rows] Single-row toggle: {t9-t8:.3f}s')

        # --- Change displayed columns (simulate show/hide column)
        if hasattr(dt, 'set_display_columns'):
            # remove a middle column, e.g. "Compartment"
            reduced_display = [
                c for c in (UI_DISPLAY_COLUMNS if table_class is CheckboxTable else columns) if c != 'Compartment'
            ]
            t10 = time.perf_counter()
            dt.set_display_columns(reduced_display)
            root.update_idletasks()
            t11 = time.perf_counter()
            logging.info(
                '[%s, %d rows] Hide one column/set_display_columns: %.3f s', table_class.__name__, num_rows, t11 - t10
            )
            print(f'[{table_class.__name__}, {num_rows} rows] Hide column: {t11-t10:.3f}s')

    finally:
        root.destroy()
