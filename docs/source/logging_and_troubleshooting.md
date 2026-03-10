# Logging and Troubleshooting

This page provides guidance on logging configuration, debugging, and troubleshooting for the application.

## 1. Global Logging by Component

You can enable or adjust logging granularity across different components within the system. Logging levels can typically be set (ERROR, WARNING, INFO, DEBUG) to control verbosity.

- Each major code component/module supports logging, allowing for tracking of operations and detection of issues.
- Logs may be viewed on the console shell or UI Console tab if started via command line 
- If started via an executable, there is not a shell, so the Console UI tab provides logs

The Console UI has a tab, available via Settings -> Show Console/Debugger Tab, which shows all logs depending on configured level for each component.

There is a single Global Logger dropdown, which if set, will change the log level for all componenets to the configured level.

Additionally, there is a "Show Loggers" checkbox, which allows inidividual override per component.  For example, set the global level to WARNING, and then override a compoment to INFO.  Doing this will allow you to see additional details for that component.

### 1a. Debugging to Command Line

Due to the volume of logging, DEBUG output, if set, is only available on the shell.  Therefore debug logging is not really available via executable.   There are 2 ways to enable debug

- Enable DEBUG-level log output using the UI to see detailed processing information in the command line.
- Launch the application with an explicit `--verbose` parameter to force global DEBUG 
  ```bash
  python -m oci_policy_analysis.main --verbose
  ```

**NOTE:** Global DEBUG is very noisy, so only do this if you really need to.

### 1b. API and Timing Logging Options

In addition to standard component-based logging levels, the application offers dedicated logging for specific events such as API calls (external integrations, requests to OCI, etc.) and timing/performance data.

- **API Logging:**  
  - API-related logs can be configured to output at higher levels (such as `CRITICAL`), allowing you to always see important API activity or errors even if the global logger is set to `WARNING` or above.
  - This ensures that key API successes, failures, or latencies are always visible for troubleshooting, regardless of the overall log verbosity.
  - Some API and external integration logs may include timing or performance diagnostics for requests and responses.

- **Timing Logging:**  
  - Timing/performance logs (operation durations, critical-path timings, long-running queries) can also be emitted at high log levels (`CRITICAL` or `ERROR`) so they're never missed, regardless of global settings.
  - Useful for investigating slowness or identifying bottlenecks without increasing general log noise.

- **How Levels Affect Visibility:**  
  - When a message is logged at a high level like `CRITICAL`, it is always output unless logging is globally silenced.
  - This approach makes sure operationally significant API/timing events get through, even if most components are set to `WARNING` or lower.

**Example:**  
If the global logger is set to `WARNING`, but API logger is emitting certain messages at `CRITICAL`, those API log entries will still appear in your logs/Console.

*To configure more granular logging for API and timing, use either the UI log level overrides (via the "Show Loggers" checkbox) or set log levels programmatically in your environment/setup scripts.*

## 2. JSON Debugger Tab

- The *JSON Debugger* tab in the UI allows you to inspect structured data that flows through the application.
- Use it to:
  - Review raw input/output for policy analysis steps
  - Trace errors back to their source with contextual JSON data
- More internal objects will be added as needed.  

## 3. Troubleshooting Topics

- **Common Errors:** Review logs for full error traces or use the Console and JSON Debugger for more details.
- **No Output or Silent Failure:**  
  - Ensure logging is not set to ERROR-only for all components.
  - Check that the appropriate components are enabled.
- **Unexpected Behavior:**  
  - Use DEBUG level for the affected component(s), repeat the action, and consult logs/Console output.
- **UI Not Responding:**  
  - Open developer tools (F12), check for browser console errors.
  - Check backend logs for exceptions.

*If you need more detailed guidance, refer to the main documentation or contact the maintainers.*

---

## Further Reading

For deep technical details—covering logging architecture, log-level wiring, log persistence, per-component overrides, and programmatic/debug workflows—consult:

- [Logging Context/Deep Dive](context/project/CONTEXT_logging.md)

_(Additional 3rd-party or advanced troubleshooting links may be added here in future updates. For a reference of architecture, simulation, and usage topics, see also: [Recommendations](recommendations.md) and the context section of the docs.)_
