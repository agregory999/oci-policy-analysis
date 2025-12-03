OCI Policy Analysis Main Entry Points
=====================================

.. automodule:: oci_policy_analysis
   :no-members:

.. currentmodule:: oci_policy_analysis.main

User Interface application
--------------------------

The Tkinter UI can be launched directly by executing the module as a script.
The entrypoint is defined using the standard Python ``if __name__ == "__main__":`` pattern:

.. code-block:: python

    if __name__ == "__main__":
        app = App()
        app.mainloop()

You can run the UI directly:

.. code-block:: bash

    python -m oci_policy_analysis.main

.. autoclass:: App
   :members:
   :undoc-members:
   :show-inheritance:

   .. automethod:: _import_cache_from_json
   .. automethod:: _export_cache_to_json

Command Line Interface
----------------------

The command line interface can be launched directly by executing the module as a script.
The entrypoint is defined using the standard Python ``if __name__ == "__main__":`` pattern:

.. code-block:: python

    if __name__ == "__main__":
        app = App()
        app.mainloop()

You can run the CLI directly:

.. code-block:: bash

    python -m oci_policy_analysis.cli

Parameters can be passed to the CLI as arguments. Documented below.

.. automodule:: oci_policy_analysis.cli
   :no-members:

.. currentmodule:: oci_policy_analysis.cli

.. autofunction:: main

Standalone MCP Server
----------------------
The standalone MCP server can be launched directly by executing the module as a script.
The entrypoint is defined using the standard Python ``if __name__ == "__main__":`` pattern:

.. code-block:: python

    if __name__ == "__main__":
        main()

You can run the MCP server directly:

.. code-block:: bash

    python -m oci_policy_analysis.mcp_server

Parameters can be passed to the MCP server as arguments as part of the command line. Examples:

To use STDIO and starting as a sub-process from Claude, you must edit the `claude_desktop_config.json`` file.  
Parameters such as loading from cache can be passed as arguments.  The following config:
* runs python from a virtual environment
* runs the mcp_server.py module
* uses the --use-cache argument with a specified cache name to load from cache
* sets the MCP_STDIO_MODE environment variable to enable STDIO mode


.. code-block:: json

   {
      "mcpServers": {
         "oci-policy-stdio": {
            "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
            "log_level": "debug",
            "args": [
               "/Users/agregory/oci-policy-analysis/src/oci_policy_analysis/mcp_server.py",
               "--use-cache",
               "mmytenancy_2025-10-29-16-52-22-UTC"
            ],
            "env": {
               "MCP_STDIO_MODE": "1"
            },
            "type": "stdio"
         }
      }
   }

Another example to run the MCP server in normal STDIO mode from the command line, loading from the tenancy directly:

.. code-block:: json

   {
      "mcpServers": {
         "oci-policy-stdio": {
            "command": "/Users/agregory/oci-policy-analysis/.venv/bin/python",
            "log_level": "debug",
            "args": [
               "-m",
               "oci_policy_analysis.mcp_server",
               "--profile",
               "DEFAULT"
            ],
            "env": {
               "MCP_STDIO_MODE": "1"
            },
            "type": "stdio"
         }
      }
   }

Connecting to the MCP server from Claude Desktop directly to HTTP requires the use of `mcp-proxy` to bridge between Claude Desktop and the MCP server.   
This is separately documented in the `mcp-proxy` documentation.

Example configuration, if using the embedded MCP server running on localhost port 8765 with streamablehttp transport:

.. code-block:: json

   {
      "mcpServers": {
         "oci-policy-http": {
            "command": "mcp-proxy",
            "args": [
               "http://127.0.0.1:8765/mcp",
               "--transport",
               "streamablehttp"
            ]
         }
      }
   }
.. automodule:: oci_policy_analysis.mcp_server
   :no-members:

.. currentmodule:: oci_policy_analysis.mcp_server

.. autofunction:: main