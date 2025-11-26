# permission_ui.py

import json
import tkinter as tk
from tkinter import messagebox, ttk

from oci_policy_analysis.logic.reference_data_repo import ReferenceDataRepo

repo = ReferenceDataRepo()


def display_json():
    json_str = json.dumps(repo.data, indent=2)
    json_text.delete(1.0, tk.END)
    json_text.insert(tk.END, json_str)


def get_permission():
    sel = resource_combo.get()
    verb = verb_combo.get()
    result_label.config(text='')
    if sel and verb:
        is_family = sel.startswith('Family: ')
        entity = sel.replace('Family: ', '') if is_family else sel
        perms = repo.get_permissions(entity, verb)
        label = f'Family: {entity}' if is_family else entity
        if perms is None:
            result_label.config(text='Invalid selection.')
        else:
            source = repo.get_source(entity)
            source_text = f'\nSource URL: {source}' if source else ''
            if perms:
                result_label.config(text=f"{label} | {verb}: {', '.join(perms)}{source_text}")
            else:
                result_label.config(text=f'{label} | {verb}: (no permissions){source_text}')
    else:
        result_label.config(text='Select resource/family and verb.')


def check_overlap_action():
    sel1 = res1_combo.get()
    verb1 = verb1_combo.get()
    sel2 = res2_combo.get()
    verb2 = verb2_combo.get()
    overlap_text.delete(1.0, tk.END)
    if not (sel1 and verb1 and sel2 and verb2):
        overlap_text.insert(tk.END, 'Select both statements.')
        return
    is_family1 = sel1.startswith('Family: ')
    name1 = sel1.replace('Family: ', '') if is_family1 else sel1
    perms1 = repo.get_permissions(name1, verb1)
    is_family2 = sel2.startswith('Family: ')
    name2 = sel2.replace('Family: ', '') if is_family2 else sel2
    perms2 = repo.get_permissions(name2, verb2)
    if perms1 is None or perms2 is None:
        overlap_text.insert(tk.END, 'Invalid selection.')
        return
    overlap = repo.check_overlap(perms1, perms2)
    output = f'Overlap between:\n  {sel1} | {verb1}\n  {sel2} | {verb2}\n\n'
    output += f"Common permissions: {', '.join(overlap) if overlap else '(none)'}"
    overlap_text.insert(tk.END, output)


def update_resources(event=None):
    all_items = sorted(repo.data['resources'].keys()) + [f'Family: {f}' for f in sorted(repo.data['families'].keys())]
    resource_combo['values'] = all_items
    res1_combo['values'] = all_items
    res2_combo['values'] = all_items
    if all_items:
        resource_combo.current(0)
        res1_combo.current(0)
        res2_combo.current(0)


def save_json():
    try:
        repo.save_data()
        messagebox.showinfo('Saved', 'permissions.json saved.')
    except Exception as e:
        messagebox.showerror('Error', f'Save failed: {e}')


# UI
root = tk.Tk()
root.title('OCI Permission Overlap Analyzer')
root.geometry('800x900')

# JSON View
tk.Label(root, text='permissions.json:').pack(pady=5)
json_text = tk.Text(root, height=10, width=90, wrap=tk.WORD)
json_text.pack(pady=5)
display_json()
tk.Button(root, text='Save JSON', command=save_json).pack(pady=2)

# Query by Resource/Family + Verb
tk.Label(root, text='Query by Resource/Family + Verb:').pack(pady=5)
frame1 = tk.Frame(root)
frame1.pack(pady=5)
tk.Label(frame1, text='Resource/Family:').grid(row=0, column=0)
resource_combo = ttk.Combobox(frame1)
resource_combo.grid(row=0, column=1)

tk.Label(frame1, text='Verb:').grid(row=1, column=0)
verb_combo = ttk.Combobox(frame1, values=['inspect', 'read', 'use', 'manage'])
verb_combo.grid(row=1, column=1)

tk.Button(frame1, text='Get Permissions', command=get_permission).grid(row=2, column=1, pady=5)
result_label = tk.Label(root, text='', wraplength=700, justify='left')
result_label.pack(pady=5)

# Overlap Check
tk.Label(root, text='Overlap Check (Resource/Family + Verb vs Resource/Family + Verb):').pack(pady=10)
overlap_frame = tk.Frame(root)
overlap_frame.pack(pady=5)

tk.Label(overlap_frame, text='Statement 1:').grid(row=0, column=0, columnspan=2)
tk.Label(overlap_frame, text='Resource/Family:').grid(row=1, column=0)
res1_combo = ttk.Combobox(overlap_frame)
res1_combo.grid(row=1, column=1)
tk.Label(overlap_frame, text='Verb:').grid(row=2, column=0)
verb1_combo = ttk.Combobox(overlap_frame, values=['inspect', 'read', 'use', 'manage'])
verb1_combo.grid(row=2, column=1)

tk.Label(overlap_frame, text='Statement 2:').grid(row=0, column=2, columnspan=2)
tk.Label(overlap_frame, text='Resource/Family:').grid(row=1, column=2)
res2_combo = ttk.Combobox(overlap_frame)
res2_combo.grid(row=1, column=3)
tk.Label(overlap_frame, text='Verb:').grid(row=2, column=2)
verb2_combo = ttk.Combobox(overlap_frame, values=['inspect', 'read', 'use', 'manage'])
verb2_combo.grid(row=2, column=3)

tk.Button(overlap_frame, text='Check Overlap', command=check_overlap_action).grid(row=3, column=1, columnspan=2, pady=5)
overlap_text = tk.Text(root, height=8, width=90, wrap=tk.WORD)
overlap_text.pack(pady=5)

# Init
update_resources()

root.mainloop()
