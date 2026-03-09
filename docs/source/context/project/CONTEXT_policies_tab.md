# Context: Policies Tab

The Policies tab presents all Oracle Cloud Infrastructure (OCI) policy statements relevant to the analyzed tenancy. This tab is designed to facilitate exploration, sorting, and filtering of policies for governance, audit, and troubleshooting purposes.

---

## 1. Display

- Policies are shown in a tabular format, with each row representing an individual policy statement.
- Columns typically include: Policy Name, Compartment, Description, Statements/Rules, Created/Modified dates, and Status.
- Statements are often highlighted or expandable to reveal underlying rules or parsed details.

---

## 2. Sorting

- Users can sort policies by any visible column (e.g., Policy Name, Compartment, Date).
- Clicking a column header toggles ascending/descending order.
- Default sort is commonly by Policy Name or Compartment (configurable as needed).

---

## 3. Filtering

- The tab supports quick filtering via:
  - Search keyword (matches policy names, statements, descriptions)
  - Compartment selector (limits results to a specific compartment/subtree)
  - Status filter (Enabled/Disabled if available)
- Advanced filters may include policy creation/modification date ranges or text pattern filters for statement content.
- Multiple filters can be combined for precise results.

---

## 4. Additional UX Notes

- Sticky headers support scrolling through long lists.
- Statement formatting highlights risky or unusual patterns when identified.
- Export or copy actions may be included for selected sets.

---

## 5. Code Location

Implementation: [`src/oci_policy_analysis/ui/policies_tab.py`](../../../src/oci_policy_analysis/ui/policies_tab.py)

---

## 6. Reload Policy Data

The "Reload Policy Data" button is provided in the Filter Actions panel for advanced usage. 

- **Effect:** Reloads policies, compartments, and statements directly from the currently connected tenancy (using the original authentication and recursion settings).
- **When enabled:** Only available if your current data was loaded from tenancy (not cache or compliance). 
- **IAM Data:** Group, Dynamic Group, and User data are *not* reloaded; those are refreshed only on initial load or a full cache update.
- **Dual timestamps:** After a reload, the Settings tab will display both the original "Data as of" (the cache/IAM snapshot date) and a new "Policy data reloaded" date. This clarifies exactly which data is from which analysis point in time.
- **UI:** Hover over the reload button for a full explanation of what is and isn't reloaded and which timestamps to expect in the Settings tab.

---

This context file will be updated as advanced features (such as saved views or policy diffing) are added to the Policies tab.
