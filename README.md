# OCI Policy Analysis

Analyze Oracle Cloud IAM policies and identity data.

📘 **Full documentation:**  
👉 [https://agregory999.github.io/oci-policy-analysis](https://agregory999.github.io/oci-policy-analysis)

## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m oci_policy_analysis.main
```
Or run a packaged release right feom your desktop:
```bash
oci-policy-analysis.exe   # Windows
oci-policy-analysis.app   # macOS
```

For the executables, disable the OS Security for the application so it can run.  
- MAC: Settings -> Privacy & Security - Open Anyway
- Windows: Double-click EXE -> More Info - Run Anyway

![Mac](/images/mac_security_bypass.png)
![Windows](/images/windows_security_bypass.png)
