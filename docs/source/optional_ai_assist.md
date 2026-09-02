# Optional AI Assist

OCI Policy Analysis can use OCI Generative AI (GenAI) to help explain policy context. This is a desktop-only preview feature. It is disabled by default, is not required for any policy-analysis workflow, and is not available from the web, CLI, or MCP interfaces.

The feature is deliberately gated so a normal desktop launch does not display AI controls or submit GenAI requests. Enable it only when you want to evaluate AI assistance with an OCI model that your selected credentials can use.

## Enable the preview

Start the desktop application with the optional flag:

```bash
oci-policy-analysis-ui --enable-genai
```

The flag applies only to that application launch. It does not change saved settings or enable AI Assist in the web application, command-line interface, or MCP server. Launching without the flag keeps the OCI GenAI settings panel, the AI Assist buttons, and the query pane unavailable.

## Configure OCI GenAI

Before testing the feature, make sure the OCI profile or instance-principal authentication selected in the desktop **Settings** tab can use the GenAI model and compartment you intend to test. Model availability depends on the OCI region, deployment or endpoint, compartment authorization, and authentication mode.

With the preview enabled:

1. Open the desktop **Settings** tab and select the OCI profile or authentication mode to use.
2. In the **OCI GenAI** section, select **Refresh Models (using selected profile)**. Optionally use **Load Regions** and select a subscribed region first.
3. Select a model from the list. The application fills the model identifier; review the regional endpoint and GenAI compartment if needed.
4. Select **Apply and Test GenAI Settings**. The application sends a test request to the configured model.

After a successful test, the desktop enables the AI pane toggle and the available AI Assist buttons. The **Tested** value in the model table applies only to the current application session. It does not guarantee that the same model will work in another region, compartment, or authentication configuration.

## Use AI Assist

Once the model test succeeds, AI Assist is available in these desktop tabs:

- Policy Inventory
- Policy Analysis
- Groups / Users
- Dynamic Groups
- Workload Principals

Use **AI Assist** to open the query pane. The pane lets you submit the selected policy context or a question for OCI GenAI. The Workload Principals tab supplies workload-principal and dynamic-group context when its AI Assist control is used.

AI Assist is supplementary: validate its output against the underlying OCI policies, statements, and permissions shown elsewhere in the application. Review the data included in a query according to your organization's OCI and data-handling policies.

## Troubleshooting

**The OCI GenAI section or AI Assist buttons are missing.** Restart the desktop application with `--enable-genai`. The flag must be supplied for each launch.

**No models or regions are available.** Confirm that the selected profile or instance principal is valid for the tenancy, then refresh models or load subscribed regions again. A model must be available to the selected OCI region and credentials.

**The model test fails.** Check the selected model identifier, regional endpoint, GenAI compartment, OCI region, and the selected authentication method. The test result shown in the application is the relevant result for the current session.

**The preview is enabled but AI Assist is disabled.** Apply and test the GenAI settings successfully first. The controls remain disabled until the application receives a successful test response.

## Related documentation

- [Set up the desktop application](setup.md#desktop-application)
- [Desktop usage guide](usage.md)
